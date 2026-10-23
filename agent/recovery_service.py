"""
Safe Post-Approval Recovery and Operations Service.

Provides:
- Safe pickup rescheduling / recovery with idempotency, state checking, and carrier provider gating.
- Safe refund initiation with warehouse-receipt verification, idempotency, and payment provider gating.
- Strict refund credit verification checking without fake provider invention or insecure boolean coercion.
"""

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from database.db import get_db
from database.return_service import log_event, utc_now


class RecoveryError(Exception):
    """Business rule violation or invalid state during recovery."""


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


# Explicit provider hooks
_CREDIT_VERIFICATION_PROVIDER: Callable[..., Any] | None = None
_PICKUP_RECOVERY_PROVIDER: Callable[..., Any] | None = None
_REFUND_INITIATION_PROVIDER: Callable[..., Any] | None = None


def set_credit_verification_provider(provider_callable: Callable[..., Any] | None) -> None:
    """Set or unset a trusted external credit-verification provider."""
    global _CREDIT_VERIFICATION_PROVIDER
    _CREDIT_VERIFICATION_PROVIDER = provider_callable


def get_credit_verification_provider() -> Callable[..., Any] | None:
    return _CREDIT_VERIFICATION_PROVIDER


def set_pickup_recovery_provider(provider_callable: Callable[..., Any] | None) -> None:
    """Set or unset an authorized carrier/courier provider for pickup recovery."""
    global _PICKUP_RECOVERY_PROVIDER
    _PICKUP_RECOVERY_PROVIDER = provider_callable


def get_pickup_recovery_provider() -> Callable[..., Any] | None:
    return _PICKUP_RECOVERY_PROVIDER


def set_refund_initiation_provider(provider_callable: Callable[..., Any] | None) -> None:
    """Set or unset an authorized payment gateway provider for refund initiation."""
    global _REFUND_INITIATION_PROVIDER
    _REFUND_INITIATION_PROVIDER = provider_callable


def get_refund_initiation_provider() -> Callable[..., Any] | None:
    return _REFUND_INITIATION_PROVIDER


def _validate_provider_confirmation(result: Any) -> tuple[bool, str | None]:
    """
    Strictly validate provider confirmation.
    Fails closed on string 'false', non-boolean types, or exceptions.
    Returns (confirmed: bool, external_reference: str | None).
    """
    if result is True:
        return True, None
    if isinstance(result, dict):
        if result.get("confirmed") is True:
            ref = result.get("external_reference") or result.get("reference")
            return True, str(ref) if ref else None
    return False, None


def recover_pickup(
    return_id: str,
    idempotency_key: str,
    carrier_provider: str = "DEFAULT",
) -> dict:
    """
    Safely reschedule or recover a pickup for an approved return.

    Rules:
    - Return must exist and have status 'APPROVED'.
    - Existing pickups: ALL pickup records for this return must NOT be active
      ('SCHEDULED', 'PICKED_UP', 'RECEIVED'). If any active pickup exists, reject.
    - At least one pickup must exist and the latest must be in an eligible state ('FAILED' or 'CANCELLED').
    - Idempotency: Bound to the (return_id, "PICKUP_RECOVERY"). Reusing the key for a different
      return or resource is strictly rejected. Replaying returns the original attempt result.
    - Reconciliation requirement: If an unresolved UNCERTAIN attempt exists for this return, block retry.
    - Provider integration:
        * If an authorized pickup provider is configured, invoke it.
        * If no provider is configured, do not claim external success or invent fake references;
          return an UNAVAILABLE result while recording the attempt cleanly.
    - Durable tracking in pickup_attempts and return_events tables.
    """
    if not idempotency_key or not str(idempotency_key).strip():
        raise RecoveryError("A non-empty idempotency_key is required.")

    idempotency_key = str(idempotency_key).strip()

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        # 1. Check existing attempt by idempotency_key
        existing_attempt = conn.execute(
            """
            SELECT attempt_id, pickup_id, return_id, attempt_number, idempotency_key,
                   status, external_reference, error_details, created_at, completed_at
            FROM pickup_attempts
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if existing_attempt:
            att = dict(existing_attempt)
            if att["return_id"] != return_id:
                raise RecoveryError(
                    f"Idempotency key {idempotency_key} was previously used for return "
                    f"{att['return_id']}, cannot be reused for return {return_id}."
                )
            if att["status"] == "UNCERTAIN":
                raise RecoveryError(
                    f"Previous pickup attempt {att['attempt_id']} has an UNCERTAIN outcome. "
                    "Reconciliation is required before retrying."
                )
            return {
                "idempotent_replay": True,
                "attempt": att,
                "status": att["status"],
                "return_id": att["return_id"],
                "pickup_id": att["pickup_id"],
                "external_reference": att["external_reference"],
            }

        # 2. Check return status
        ret = conn.execute(
            "SELECT return_id, status FROM returns WHERE return_id = ?",
            (return_id,),
        ).fetchone()

        if not ret:
            raise RecoveryError(f"Return not found: {return_id}")

        if ret["status"] != "APPROVED":
            raise RecoveryError(
                f"Pickup recovery requires an APPROVED return, but return is {ret['status']}."
            )

        # 3. Check existing pickup records: ensure NO active pickup exists anywhere in history
        all_pickups = conn.execute(
            """
            SELECT pickup_id, status
            FROM pickups
            WHERE return_id = ?
            ORDER BY created_at DESC
            """,
            (return_id,),
        ).fetchall()

        if not all_pickups:
            raise RecoveryError(f"No pickup record found for return {return_id}.")

        for pk in all_pickups:
            if pk["status"] in ("SCHEDULED", "PICKED_UP", "RECEIVED"):
                raise RecoveryError(
                    f"Cannot recover pickup: active pickup {pk['pickup_id']} is already in status {pk['status']}."
                )

        latest_pickup = all_pickups[0]
        if latest_pickup["status"] not in ("FAILED", "CANCELLED"):
            raise RecoveryError(
                f"Pickup status {latest_pickup['status']} is not eligible for recovery."
            )

        # Check if there is an unresolved UNCERTAIN attempt for this return
        uncertain_attempt = conn.execute(
            """
            SELECT attempt_id FROM pickup_attempts
            WHERE return_id = ? AND status = 'UNCERTAIN'
            """,
            (return_id,),
        ).fetchone()
        if uncertain_attempt:
            raise RecoveryError(
                f"Unresolved UNCERTAIN attempt {uncertain_attempt['attempt_id']} exists for return {return_id}. "
                "Reconciliation is required before attempting another action."
            )

        # Count prior attempts
        prior_count = conn.execute(
            "SELECT COUNT(*) FROM pickup_attempts WHERE return_id = ?",
            (return_id,),
        ).fetchone()[0]
        attempt_number = prior_count + 1

        attempt_id = new_id("ATT-PK")
        now = utc_now()

        # Check provider availability
        provider = get_pickup_recovery_provider()
        if provider is None:
            # Record attempt as FAILED / UNAVAILABLE without fabricating success
            conn.execute(
                """
                INSERT INTO pickup_attempts (
                    attempt_id, pickup_id, return_id, attempt_number,
                    idempotency_key, status, error_details, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, 'FAILED', 'No authorized carrier provider configured', ?, ?)
                """,
                (attempt_id, latest_pickup["pickup_id"], return_id, attempt_number, idempotency_key, now, now),
            )
            return {
                "idempotent_replay": False,
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "return_id": return_id,
                "previous_pickup_id": latest_pickup["pickup_id"],
                "status": "PROVIDER_UNAVAILABLE",
                "message": "Pickup recovery provider is unavailable or not configured. No external booking created.",
            }

        # Invoke authorized provider
        try:
            provider_res = provider(return_id, latest_pickup["pickup_id"])
            confirmed, ext_ref = _validate_provider_confirmation(provider_res)
        except Exception as e:
            conn.execute(
                """
                INSERT INTO pickup_attempts (
                    attempt_id, pickup_id, return_id, attempt_number,
                    idempotency_key, status, error_details, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, 'UNCERTAIN', ?, ?, ?)
                """,
                (attempt_id, latest_pickup["pickup_id"], return_id, attempt_number, idempotency_key, str(e), now, utc_now()),
            )
            raise RecoveryError(f"Pickup provider encountered an uncertain error: {e}")

        if not confirmed:
            conn.execute(
                """
                INSERT INTO pickup_attempts (
                    attempt_id, pickup_id, return_id, attempt_number,
                    idempotency_key, status, error_details, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, 'FAILED', 'Carrier rejected pickup request', ?, ?)
                """,
                (attempt_id, latest_pickup["pickup_id"], return_id, attempt_number, idempotency_key, now, utc_now()),
            )
            return {
                "idempotent_replay": False,
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "return_id": return_id,
                "status": "FAILED",
                "message": "Carrier provider rejected the pickup recovery request.",
            }

        # Confirmed by external provider: schedule new pickup record
        new_pickup_id = new_id("PICKUP")
        conn.execute(
            """
            INSERT INTO pickups (
                pickup_id, return_id, status, scheduled_at, created_at
            )
            VALUES (?, ?, 'SCHEDULED', ?, ?)
            """,
            (new_pickup_id, return_id, now, now),
        )

        log_event(
            conn,
            return_id,
            "PICKUP",
            f"Pickup recovered and rescheduled via attempt {attempt_id}.",
            from_status=latest_pickup["status"],
            to_status="SCHEDULED",
        )

        completed_at = utc_now()
        conn.execute(
            """
            INSERT INTO pickup_attempts (
                attempt_id, pickup_id, return_id, attempt_number,
                idempotency_key, status, external_reference, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, 'SUCCESS', ?, ?, ?)
            """,
            (attempt_id, new_pickup_id, return_id, attempt_number, idempotency_key, ext_ref, now, completed_at),
        )

        return {
            "idempotent_replay": False,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "return_id": return_id,
            "previous_pickup_id": latest_pickup["pickup_id"],
            "new_pickup_id": new_pickup_id,
            "status": "SUCCESS",
            "external_reference": ext_ref,
        }


def record_uncertain_pickup_attempt(
    return_id: str,
    idempotency_key: str,
    error_details: str = "Network timeout to carrier service",
) -> str:
    """Helper to record an uncertain pickup attempt for testing reconciliation rules."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ret = conn.execute("SELECT return_id FROM returns WHERE return_id = ?", (return_id,)).fetchone()
        if not ret:
            raise RecoveryError(f"Return not found: {return_id}")

        pickup = conn.execute(
            "SELECT pickup_id FROM pickups WHERE return_id = ? ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        ).fetchone()
        pickup_id = pickup["pickup_id"] if pickup else "UNKNOWN"

        prior_count = conn.execute(
            "SELECT COUNT(*) FROM pickup_attempts WHERE return_id = ?",
            (return_id,),
        ).fetchone()[0]

        attempt_id = new_id("ATT-PK")
        now = utc_now()
        conn.execute(
            """
            INSERT INTO pickup_attempts (
                attempt_id, pickup_id, return_id, attempt_number,
                idempotency_key, status, error_details, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, 'UNCERTAIN', ?, ?, ?)
            """,
            (attempt_id, pickup_id, return_id, prior_count + 1, idempotency_key, error_details, now, now),
        )
        return attempt_id


def reconcile_pickup_attempt(
    attempt_id: str,
    resolved_status: str,
    carrier_provider: Callable[..., Any] | None = None,
) -> None:
    """
    Resolve an UNCERTAIN pickup attempt.
    Requires that the attempt exists and is currently in status 'UNCERTAIN'.
    Resolving as SUCCESS requires verification from an authorized carrier provider
    (passed explicitly or configured globally). An arbitrary evidence dictionary is not accepted.
    """
    if resolved_status not in ("SUCCESS", "FAILED"):
        raise RecoveryError("Resolved status must be SUCCESS or FAILED.")

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        att = conn.execute(
            """
            SELECT attempt_id, pickup_id, return_id, status
            FROM pickup_attempts
            WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()

        if not att:
            raise RecoveryError(f"Pickup attempt not found: {attempt_id}")

        if att["status"] != "UNCERTAIN":
            raise RecoveryError(
                f"Cannot reconcile pickup attempt {attempt_id}: status is {att['status']}, not UNCERTAIN."
            )

        ext_ref = None
        if resolved_status == "SUCCESS":
            provider = carrier_provider or get_pickup_recovery_provider()
            if provider is None:
                raise RecoveryError(
                    "Resolving an UNCERTAIN pickup attempt as SUCCESS requires an authorized carrier provider."
                )
            try:
                res = provider(att["return_id"], att["pickup_id"])
                confirmed, ext_ref = _validate_provider_confirmation(res)
            except Exception as e:
                raise RecoveryError(f"Carrier provider verification failed during reconciliation: {e}")

            if not confirmed:
                raise RecoveryError("Carrier provider did not confirm successful pickup execution.")

        conn.execute(
            "UPDATE pickup_attempts SET status = ?, external_reference = COALESCE(?, external_reference), completed_at = ? WHERE attempt_id = ?",
            (resolved_status, ext_ref, utc_now(), attempt_id),
        )


def initiate_refund_safe(
    return_id: str,
    idempotency_key: str,
) -> dict:
    """
    Safely initiate a refund for an approved return whose item has reached the warehouse.

    Rules:
    - Return must exist and have status 'APPROVED'.
    - Item pickup must have status 'RECEIVED' (warehouse receipt confirmed).
    - Refund record must be 'PENDING' (or previous failed attempt being safely retried).
    - If refund is already 'INITIATED' or 'CREDITED', reject duplicate initiation.
    - If idempotency_key was already used, verify resource binding and replay attempt.
    - If an unresolved UNCERTAIN attempt exists for this refund, require reconciliation.
    - Provider integration:
        * If an authorized refund initiation provider is configured, invoke it.
        * If no provider is configured, report PROVIDER_UNAVAILABLE without claiming success or inventing references.
    """
    if not idempotency_key or not str(idempotency_key).strip():
        raise RecoveryError("A non-empty idempotency_key is required.")

    idempotency_key = str(idempotency_key).strip()

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        # 1. Check existing attempt by idempotency_key
        existing_attempt = conn.execute(
            """
            SELECT attempt_id, refund_id, return_id, attempt_number, idempotency_key,
                   status, external_reference, error_details, created_at, completed_at
            FROM refund_attempts
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if existing_attempt:
            att = dict(existing_attempt)
            if att["return_id"] != return_id:
                raise RecoveryError(
                    f"Idempotency key {idempotency_key} was previously used for return "
                    f"{att['return_id']}, cannot be reused for return {return_id}."
                )
            if att["status"] == "UNCERTAIN":
                raise RecoveryError(
                    f"Previous refund attempt {att['attempt_id']} has an UNCERTAIN outcome. "
                    "Reconciliation is required before retrying."
                )
            return {
                "idempotent_replay": True,
                "attempt": att,
                "status": att["status"],
                "return_id": att["return_id"],
                "refund_id": att["refund_id"],
                "external_reference": att["external_reference"],
            }

        # 2. Check return status
        ret = conn.execute(
            "SELECT return_id, status FROM returns WHERE return_id = ?",
            (return_id,),
        ).fetchone()

        if not ret:
            raise RecoveryError(f"Return not found: {return_id}")

        if ret["status"] != "APPROVED":
            raise RecoveryError(
                f"Refund initiation requires an APPROVED return, but return is {ret['status']}."
            )

        # 3. Check warehouse receipt confirmation
        pickup = conn.execute(
            """
            SELECT pickup_id, status, received_at
            FROM pickups
            WHERE return_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (return_id,),
        ).fetchone()

        if not pickup or pickup["status"] != "RECEIVED":
            raise RecoveryError(
                f"Refund initiation blocked: item has not been received at warehouse. "
                f"Current pickup status: {pickup['status'] if pickup else 'NONE'}."
            )

        # 4. Check refund record
        refund = conn.execute(
            """
            SELECT refund_id, status, amount_paise, method
            FROM refunds
            WHERE return_id = ?
            """,
            (return_id,),
        ).fetchone()

        if not refund:
            raise RecoveryError(f"No refund record found for return {return_id}.")

        if refund["status"] in ("INITIATED", "CREDITED"):
            raise RecoveryError(
                f"Refund {refund['refund_id']} is already {refund['status']}; duplicate initiation prohibited."
            )

        # 5. Check for any unresolved UNCERTAIN attempt for this refund
        uncertain = conn.execute(
            """
            SELECT attempt_id FROM refund_attempts
            WHERE refund_id = ? AND status = 'UNCERTAIN'
            """,
            (refund["refund_id"],),
        ).fetchone()
        if uncertain:
            raise RecoveryError(
                f"Unresolved UNCERTAIN attempt {uncertain['attempt_id']} exists for refund {refund['refund_id']}. "
                "Reconciliation is required before retrying."
            )

        # 6. Record attempt
        prior_count = conn.execute(
            "SELECT COUNT(*) FROM refund_attempts WHERE refund_id = ?",
            (refund["refund_id"],),
        ).fetchone()[0]
        attempt_number = prior_count + 1

        attempt_id = new_id("ATT-RF")
        now = utc_now()

        # Check provider availability
        provider = get_refund_initiation_provider()
        if provider is None:
            conn.execute(
                """
                INSERT INTO refund_attempts (
                    attempt_id, refund_id, return_id, attempt_number,
                    idempotency_key, status, error_details, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, 'FAILED', 'No authorized payment provider configured', ?, ?)
                """,
                (attempt_id, refund["refund_id"], return_id, attempt_number, idempotency_key, now, now),
            )
            return {
                "idempotent_replay": False,
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "return_id": return_id,
                "refund_id": refund["refund_id"],
                "status": "PROVIDER_UNAVAILABLE",
                "message": "Payment initiation provider is unavailable or not configured. No external submission created.",
            }

        # Invoke authorized payment provider
        try:
            provider_res = provider(return_id, refund["refund_id"], refund["amount_paise"])
            confirmed, ext_ref = _validate_provider_confirmation(provider_res)
        except Exception as e:
            conn.execute(
                """
                INSERT INTO refund_attempts (
                    attempt_id, refund_id, return_id, attempt_number,
                    idempotency_key, status, error_details, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, 'UNCERTAIN', ?, ?, ?)
                """,
                (attempt_id, refund["refund_id"], return_id, attempt_number, idempotency_key, str(e), now, utc_now()),
            )
            raise RecoveryError(f"Refund payment provider encountered an uncertain error: {e}")

        if not confirmed:
            conn.execute(
                """
                INSERT INTO refund_attempts (
                    attempt_id, refund_id, return_id, attempt_number,
                    idempotency_key, status, error_details, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, 'FAILED', 'Payment gateway rejected refund request', ?, ?)
                """,
                (attempt_id, refund["refund_id"], return_id, attempt_number, idempotency_key, now, utc_now()),
            )
            return {
                "idempotent_replay": False,
                "attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "return_id": return_id,
                "refund_id": refund["refund_id"],
                "status": "FAILED",
                "message": "Payment gateway rejected the refund initiation request.",
            }

        # Confirmed initiation: update refund status to INITIATED
        conn.execute(
            """
            UPDATE refunds
            SET status = 'INITIATED', initiated_at = ?
            WHERE refund_id = ? AND status IN ('PENDING', 'FAILED')
            """,
            (now, refund["refund_id"]),
        )

        log_event(
            conn,
            return_id,
            "REFUND",
            f"Refund initiated via attempt {attempt_id} (idempotency key {idempotency_key}).",
            from_status=refund["status"],
            to_status="INITIATED",
        )

        completed_at = utc_now()
        conn.execute(
            """
            INSERT INTO refund_attempts (
                attempt_id, refund_id, return_id, attempt_number,
                idempotency_key, status, external_reference, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, 'SUCCESS', ?, ?, ?)
            """,
            (attempt_id, refund["refund_id"], return_id, attempt_number, idempotency_key, ext_ref, now, completed_at),
        )

        return {
            "idempotent_replay": False,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "return_id": return_id,
            "refund_id": refund["refund_id"],
            "status": "SUCCESS",
            "external_reference": ext_ref,
        }


def record_failed_refund_attempt(
    return_id: str,
    idempotency_key: str,
    error_details: str,
) -> str:
    """Record a failed refund attempt durably in refund_attempts."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        refund = conn.execute("SELECT refund_id FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        refund_id = refund["refund_id"] if refund else "UNKNOWN"

        prior_count = conn.execute(
            "SELECT COUNT(*) FROM refund_attempts WHERE refund_id = ?",
            (refund_id,),
        ).fetchone()[0]

        attempt_id = new_id("ATT-RF")
        now = utc_now()
        conn.execute(
            """
            INSERT INTO refund_attempts (
                attempt_id, refund_id, return_id, attempt_number,
                idempotency_key, status, error_details, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, 'FAILED', ?, ?, ?)
            """,
            (attempt_id, refund_id, return_id, prior_count + 1, idempotency_key, error_details, now, now),
        )
        return attempt_id


def record_uncertain_refund_attempt(
    return_id: str,
    idempotency_key: str,
    error_details: str = "Gateway connection timeout",
) -> str:
    """Record an uncertain refund attempt durably for testing reconciliation."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        refund = conn.execute("SELECT refund_id FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        refund_id = refund["refund_id"] if refund else "UNKNOWN"

        prior_count = conn.execute(
            "SELECT COUNT(*) FROM refund_attempts WHERE refund_id = ?",
            (refund_id,),
        ).fetchone()[0]

        attempt_id = new_id("ATT-RF")
        now = utc_now()
        conn.execute(
            """
            INSERT INTO refund_attempts (
                attempt_id, refund_id, return_id, attempt_number,
                idempotency_key, status, error_details, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, 'UNCERTAIN', ?, ?, ?)
            """,
            (attempt_id, refund_id, return_id, prior_count + 1, idempotency_key, error_details, now, now),
        )
        return attempt_id


def reconcile_refund_attempt(
    attempt_id: str,
    resolved_status: str,
    payment_provider: Callable[..., Any] | None = None,
) -> None:
    """
    Reconcile an UNCERTAIN refund attempt.
    Requires attempt to exist in status 'UNCERTAIN'.
    Resolving as SUCCESS requires verification from an authorized payment provider
    (passed explicitly or configured globally). An arbitrary evidence dictionary is not accepted.
    If resolved as SUCCESS, also transitions the refund record to INITIATED if not already.
    """
    if resolved_status not in ("SUCCESS", "FAILED"):
        raise RecoveryError("Resolved status must be SUCCESS or FAILED.")

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        att = conn.execute(
            """
            SELECT attempt_id, refund_id, return_id, status
            FROM refund_attempts
            WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()

        if not att:
            raise RecoveryError(f"Refund attempt not found: {attempt_id}")

        if att["status"] != "UNCERTAIN":
            raise RecoveryError(
                f"Cannot reconcile refund attempt {attempt_id}: status is {att['status']}, not UNCERTAIN."
            )

        ext_ref = None
        if resolved_status == "SUCCESS":
            provider = payment_provider or get_refund_initiation_provider()
            if provider is None:
                raise RecoveryError(
                    "Resolving an UNCERTAIN refund attempt as SUCCESS requires an authorized payment provider."
                )
            try:
                # Query refund details
                rf = conn.execute("SELECT amount_paise FROM refunds WHERE refund_id = ?", (att["refund_id"],)).fetchone()
                amt = rf["amount_paise"] if rf else 0
                res = provider(att["return_id"], att["refund_id"], amt)
                confirmed, ext_ref = _validate_provider_confirmation(res)
            except Exception as e:
                raise RecoveryError(f"Payment provider verification failed during reconciliation: {e}")

            if not confirmed:
                raise RecoveryError("Payment provider did not confirm successful refund initiation.")

            now = utc_now()
            conn.execute(
                """
                UPDATE refunds
                SET status = 'INITIATED', initiated_at = COALESCE(initiated_at, ?)
                WHERE refund_id = ? AND status IN ('PENDING', 'FAILED')
                """,
                (now, att["refund_id"]),
            )

        conn.execute(
            "UPDATE refund_attempts SET status = ?, external_reference = COALESCE(?, external_reference), completed_at = ? WHERE attempt_id = ?",
            (resolved_status, ext_ref, utc_now(), attempt_id),
        )


def verify_and_finalize_refund(
    return_id: str,
    verification_evidence: dict | None = None,
) -> dict:
    """
    Verify refund credit and complete the return ONLY when trustworthy external proof exists.

    Rules:
    - Only an authorized credit verification provider (configured via set_credit_verification_provider)
      can establish refund credit. Caller-supplied dictionaries without a configured provider are NOT trusted.
    - Provider return value must be strictly True or a dict with confirmed=True (not coerced string "false").
    - Return must exist, be in APPROVED status (or COMPLETED if already verified), item received, and refund INITIATED.
    - If return is already marked COMPLETED:
        * Checks whether refund status is CREDITED. If not, flags inconsistent record rather than trusting the label.
    - Persists verification source and external evidence reference when available. Never invents references.
    """
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        ret = conn.execute(
            "SELECT return_id, status FROM returns WHERE return_id = ?",
            (return_id,),
        ).fetchone()
        if not ret:
            raise RecoveryError(f"Return not found: {return_id}")

        # Check return status eligibility before expecting child records
        if ret["status"] not in ("APPROVED", "COMPLETED"):
            return {
                "verified": False,
                "return_status": ret["status"],
                "message": f"Return {return_id} has status {ret['status']} (must be APPROVED to finalize).",
            }

        refund = conn.execute(
            "SELECT refund_id, status, amount_paise FROM refunds WHERE return_id = ?",
            (return_id,),
        ).fetchone()

        if not refund:
            raise RecoveryError(f"No refund record for return {return_id}")

        # Check existing COMPLETED return for consistency
        if ret["status"] == "COMPLETED":
            if refund["status"] != "CREDITED":
                return {
                    "verified": False,
                    "status": "INCONSISTENT_COMPLETED",
                    "refund_status": refund["status"],
                    "return_status": ret["status"],
                    "message": f"Inconsistent return state: return is COMPLETED but refund is {refund['status']} (not CREDITED).",
                }
            return {
                "verified": True,
                "status": "COMPLETED",
                "refund_status": "CREDITED",
                "message": "Return was already completed with verified credited refund.",
            }

        # For uncompleted returns: must be APPROVED
        if ret["status"] != "APPROVED":
            return {
                "verified": False,
                "refund_status": refund["status"],
                "return_status": ret["status"],
                "message": f"Return {return_id} has status {ret['status']} (must be APPROVED to finalize).",
            }

        # Pickup warehouse receipt check
        pickup = conn.execute(
            "SELECT status FROM pickups WHERE return_id = ? ORDER BY created_at DESC LIMIT 1",
            (return_id,),
        ).fetchone()
        if not pickup or pickup["status"] != "RECEIVED":
            return {
                "verified": False,
                "refund_status": refund["status"],
                "return_status": ret["status"],
                "message": f"Item has not been received at warehouse (pickup status: {pickup['status'] if pickup else 'NONE'}).",
            }

        # Refund must be INITIATED
        if refund["status"] != "INITIATED":
            return {
                "verified": False,
                "refund_status": refund["status"],
                "return_status": ret["status"],
                "message": f"Refund status is {refund['status']}, not INITIATED. Cannot finalize credit.",
            }

        # Check authorized credit verification provider ONLY
        provider = get_credit_verification_provider()
        provider_confirmed = False
        ext_ref = None

        if provider is not None:
            try:
                raw_res = provider(return_id, refund["refund_id"])
                provider_confirmed, ext_ref = _validate_provider_confirmation(raw_res)
            except Exception:
                provider_confirmed = False

        if not provider_confirmed:
            return {
                "verified": False,
                "refund_status": refund["status"],
                "return_status": ret["status"],
                "message": "Credit verification unavailable or pending confirmation. Refund remains uncredited.",
            }

        # Trustworthy external confirmation established
        now = utc_now()
        conn.execute(
            """
            UPDATE refunds
            SET status = 'CREDITED', credited_at = ?
            WHERE refund_id = ?
            """,
            (now, refund["refund_id"]),
        )

        audit_msg = "Refund confirmed and credited via authorized credit verification provider."
        if ext_ref:
            audit_msg += f" (Ref: {ext_ref})"

        log_event(
            conn,
            return_id,
            "REFUND",
            audit_msg,
            from_status=refund["status"],
            to_status="CREDITED",
        )

        conn.execute(
            """
            UPDATE returns
            SET status = 'COMPLETED', completed_at = ?
            WHERE return_id = ?
            """,
            (now, return_id),
        )
        log_event(
            conn,
            return_id,
            "RETURN",
            "Return completed following verified refund credit.",
            from_status=ret["status"],
            to_status="COMPLETED",
        )

        return {
            "verified": True,
            "refund_status": "CREDITED",
            "return_status": "COMPLETED",
            "credited_at": now,
            "external_reference": ext_ref,
            "message": "Refund credit verified and return marked COMPLETED.",
        }
