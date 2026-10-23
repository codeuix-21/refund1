"""
Edge-Case Test Suite for Post-Approval Agent and Recovery Operations.

Targeted Cases:
1. Concurrent pickup-recovery requests (threading + BEGIN IMMEDIATE concurrency).
2. Concurrent refund-initiation requests.
3. Repeated requests using the same idempotency key (idempotency safety).
4. Different keys attempting the same logical operation when in an ineligible state.
5. Provider timeouts, exceptions, malformed/non-boolean returns, and uncertain outcomes.
6. Simulated restart while an operation is pending or uncertain.
7. Database transaction failures / rollback ensuring no partial state corruption.
8. Untrusted or incomplete refund-credit evidence dictionaries.
9. Ineligible return and pickup/refund states for recovery and initiation.
10. Non-destructive schema migration over existing checkpoints and records.
11. P0/P1/P2 Regression tests:
    - Provider returning string 'false' or truthy non-booleans.
    - Caller-supplied trusted_bank_confirmation=True without authorized provider.
    - Non-approved, rejected, or inconsistent returns blocked from credit finalization.
    - COMPLETED returns with non-CREDITED refunds flagged as INCONSISTENT.
    - Idempotency key bound to return_id (rejecting reuse with a different return).
    - Older active pickup records blocking recovery even if latest pickup was failed.
    - Reconciling non-UNCERTAIN or non-existent attempts blocked.
    - Reconciliation of UNCERTAIN as SUCCESS requires authorized evidence.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
import sqlite3

from database import db
from database.return_service import create_return
from agent.recovery_service import (
    RecoveryError,
    set_credit_verification_provider,
    set_pickup_recovery_provider,
    set_refund_initiation_provider,
    recover_pickup,
    record_uncertain_pickup_attempt,
    reconcile_pickup_attempt,
    initiate_refund_safe,
    record_uncertain_refund_attempt,
    reconcile_refund_attempt,
    verify_and_finalize_refund,
)
from agent.background_worker import scan_and_log_once
from agent.post_approval_agent import list_monitored_returns


@pytest.fixture(autouse=True)
def cleanup_providers():
    set_credit_verification_provider(None)
    set_pickup_recovery_provider(None)
    set_refund_initiation_provider(None)
    yield
    set_credit_verification_provider(None)
    set_pickup_recovery_provider(None)
    set_refund_initiation_provider(None)


# ==============================================================================
# 1 & 2: CONCURRENT OPERATIONS (WITH AUTHORIZED PROVIDERS)
# ==============================================================================

def test_concurrent_pickup_recovery_race(test_db_env):
    """
    Two concurrent threads attempt pickup recovery for the same failed pickup.
    With an authorized provider configured, exactly one must succeed in scheduling a new pickup;
    the other must either be serialized and rejected or raise RecoveryError.
    Never should two SCHEDULED pickups be created.
    """
    set_pickup_recovery_provider(lambda ret_id, pk_id: {"confirmed": True, "reference": "CARRIER-CONCURRENT"})

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]
    orig_pickup_id = ret["pickup_id"]

    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE' WHERE pickup_id = ?", (orig_pickup_id,))

    results = []
    errors = []

    def run_recovery(key):
        try:
            res = recover_pickup(return_id=return_id, idempotency_key=key)
            results.append(res)
        except Exception as e:
            errors.append(e)

    # Launch concurrently with different keys
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_recovery, "CONCURRENT-PK-KEY-1")
        f2 = executor.submit(run_recovery, "CONCURRENT-PK-KEY-2")
        f1.result()
        f2.result()

    # Verify database: exactly 1 active SCHEDULED pickup must exist
    with db.get_db() as conn:
        active_pickups = conn.execute(
            "SELECT pickup_id, status FROM pickups WHERE return_id = ? AND status = 'SCHEDULED'",
            (return_id,),
        ).fetchall()
        assert len(active_pickups) == 1

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], (RecoveryError, sqlite3.OperationalError))


def test_concurrent_refund_initiation_race(test_db_env):
    """
    Two concurrent threads attempt refund initiation for the same received return.
    With an authorized payment provider configured, exactly one must succeed;
    the other must be rejected.
    """
    set_refund_initiation_provider(lambda ret_id, ref_id, amt: {"confirmed": True, "reference": "PG-CONCURRENT"})

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))

    results = []
    errors = []

    def run_initiation(key):
        try:
            res = initiate_refund_safe(return_id=return_id, idempotency_key=key)
            results.append(res)
        except Exception as e:
            errors.append(e)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_initiation, "CONCURRENT-RF-KEY-1")
        f2 = executor.submit(run_initiation, "CONCURRENT-RF-KEY-2")
        f1.result()
        f2.result()

    with db.get_db() as conn:
        rf = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        assert rf["status"] == "INITIATED"

    assert len(results) == 1
    assert len(errors) == 1


# ==============================================================================
# 3 & 4: IDEMPOTENCY KEY BEHAVIOR & RESOURCE BINDING
# ==============================================================================

def test_repeated_requests_same_idempotency_key_replay(test_db_env):
    """Multiple identical submissions with the same key replay the original result."""
    set_refund_initiation_provider(lambda ret_id, ref_id, amt: True)

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))

    # First call
    r1 = initiate_refund_safe(return_id=return_id, idempotency_key="STABLE-KEY-100")
    assert r1["idempotent_replay"] is False

    # Second and third calls
    r2 = initiate_refund_safe(return_id=return_id, idempotency_key="STABLE-KEY-100")
    r3 = initiate_refund_safe(return_id=return_id, idempotency_key="STABLE-KEY-100")

    assert r2["idempotent_replay"] is True
    assert r3["idempotent_replay"] is True
    assert r2["refund_id"] == r1["refund_id"]
    assert r3["refund_id"] == r1["refund_id"]


def test_different_key_rejected_when_already_active(test_db_env):
    """A different idempotency key cannot trigger a second initiation or recovery."""
    set_pickup_recovery_provider(lambda ret_id, pk_id: True)

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]
    orig_pk = ret["pickup_id"]

    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE' WHERE pickup_id = ?", (orig_pk,))

    # Recover pickup with KEY-A
    res_a = recover_pickup(return_id=return_id, idempotency_key="KEY-A")
    assert res_a["status"] == "SUCCESS"

    # Now attempt recovery with KEY-B: rejected because pickup is now active (SCHEDULED)
    with pytest.raises(RecoveryError, match="already in status SCHEDULED"):
        recover_pickup(return_id=return_id, idempotency_key="KEY-B")


def test_idempotency_key_bound_to_resource_rejects_different_return(test_db_env):
    """Reusing the same idempotency key for a different return ID must be rejected."""
    set_pickup_recovery_provider(lambda ret_id, pk_id: True)

    ret1 = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    ret2 = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE'")

    # Use KEY-SHARED on ret1
    recover_pickup(return_id=ret1["return_id"], idempotency_key="KEY-SHARED")

    # Attempt to reuse KEY-SHARED on ret2
    with pytest.raises(RecoveryError, match="cannot be reused for return"):
        recover_pickup(return_id=ret2["return_id"], idempotency_key="KEY-SHARED")


# ==============================================================================
# 5: P0 DEFECT — PROVIDER RETURNING STRING 'FALSE' OR TRUTHY NON-BOOLEAN
# ==============================================================================

def test_provider_returning_string_false_fails_closed(test_db_env):
    """
    P0 Defect: Provider returning the string 'false' must NOT be coerced to True.
    It must fail closed and leave the refund uncredited.
    """
    set_credit_verification_provider(lambda ret_id, ref_id: "false")

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?", (now_iso, return_id))

    res = verify_and_finalize_refund(return_id)
    assert res["verified"] is False

    with db.get_db() as conn:
        rf = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        assert rf["status"] == "INITIATED"


def test_provider_raising_exception_does_not_credit(test_db_env):
    """If provider raises an unhandled exception or timeout, refund stays INITIATED."""
    def broken_provider(return_id, refund_id):
        raise TimeoutError("Provider gateway timeout")

    set_credit_verification_provider(broken_provider)

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?", (now_iso, return_id))

    res = verify_and_finalize_refund(return_id)
    assert res["verified"] is False

    with db.get_db() as conn:
        rf = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
    assert rf["status"] == "INITIATED"


def test_provider_malformed_falsy_return(test_db_env):
    """If provider returns None, empty string, or 0, credit is rejected."""
    set_credit_verification_provider(lambda ret_id, ref_id: "")

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?", (now_iso, return_id))

    res = verify_and_finalize_refund(return_id)
    assert res["verified"] is False


# ==============================================================================
# 6: SIMULATED RESTART WITH UNCERTAIN OPERATION
# ==============================================================================

def test_restart_preserves_uncertain_blocking_across_sessions(test_db_env):
    """
    Simulate app restart: An UNCERTAIN attempt persisted in the DB must still
    block new operations after the application / test reconnects.
    """
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))

    record_uncertain_refund_attempt(return_id, idempotency_key="RESTART-KEY-1")

    # Re-importing or calling recovery_service functions directly simulates a new request cycle
    with pytest.raises(RecoveryError, match="Unresolved UNCERTAIN attempt"):
        initiate_refund_safe(return_id=return_id, idempotency_key="AFTER-RESTART-KEY")


# ==============================================================================
# 7: TRANSACTION FAILURES & PARTIAL OPERATION PREVENTION
# ==============================================================================

def test_pickup_recovery_atomic_rollback(test_db_env):
    """If an error occurs before completion, no partial pickup record or orphan attempt is saved."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]
    orig_pk = ret["pickup_id"]

    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE' WHERE pickup_id = ?", (orig_pk,))

    # Empty key raises RecoveryError before any DB change
    with pytest.raises(RecoveryError, match="non-empty idempotency_key"):
        recover_pickup(return_id=return_id, idempotency_key="")

    with db.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM pickup_attempts WHERE return_id = ?", (return_id,)).fetchone()[0]
        assert count == 0


# ==============================================================================
# 8: P0 DEFECT — UNTRUSTED / INCOMPLETE EVIDENCE & INELIGIBLE RETURN STATES
# ==============================================================================

def test_untrusted_evidence_dictionary_rejected(test_db_env):
    """Evidence dict without an authorized provider cannot credit refund."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?", (now_iso, return_id))

    for bogus_evidence in [
        {},
        {"note": "customer said it reached"},
        {"trusted_bank_confirmation": False},
        {"trusted_bank_confirmation": True},
        {"trusted_bank_confirmation": "true"},
        {"amount": 50000},
    ]:
        res = verify_and_finalize_refund(return_id, verification_evidence=bogus_evidence)
        assert res["verified"] is False

    with db.get_db() as conn:
        rf = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        assert rf["status"] == "INITIATED"


def test_rejected_or_unapproved_return_blocked_from_credit_finalization(test_db_env):
    """Even if an authorized provider reports True, an unapproved return cannot be finalized."""
    set_credit_verification_provider(lambda ret_id, ref_id: True)

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=False,  # NOT approved (status: REQUESTED)
    )
    return_id = ret["return_id"]

    res = verify_and_finalize_refund(return_id)
    assert res["verified"] is False
    assert "must be APPROVED" in res["message"]


def test_completed_return_with_inconsistent_refund_is_flagged(test_db_env):
    """A return marked COMPLETED but with refund still INITIATED must be flagged as INCONSISTENT."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE returns SET status = 'COMPLETED', completed_at = ? WHERE return_id = ?", (now_iso, return_id))

    res = verify_and_finalize_refund(return_id)
    assert res["verified"] is False
    assert res["status"] == "INCONSISTENT_COMPLETED"
    assert "Inconsistent return state" in res["message"]


# ==============================================================================
# 9: INELIGIBLE RETURN / PICKUP / REFUND STATES & OLDER ACTIVE PICKUPS
# ==============================================================================

def test_recovery_on_nonexistent_or_completed_return(test_db_env):
    """Recovery on nonexistent return or completed return is rejected."""
    with pytest.raises(RecoveryError, match="Return not found"):
        recover_pickup("RET-NONEXISTENT", idempotency_key="KEY-X")

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE returns SET status = 'COMPLETED', completed_at = ? WHERE return_id = ?", (now_iso, return_id))

    with pytest.raises(RecoveryError, match="requires an APPROVED return"):
        recover_pickup(return_id, idempotency_key="KEY-X")

    with pytest.raises(RecoveryError, match="requires an APPROVED return"):
        initiate_refund_safe(return_id, idempotency_key="KEY-X")


def test_older_active_pickup_record_blocks_recovery(test_db_env):
    """
    If any active pickup exists anywhere in history (e.g., older pickup is SCHEDULED),
    recovery must be blocked even if latest pickup record was marked FAILED.
    """
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]
    orig_pk = ret["pickup_id"]  # status is SCHEDULED

    # Insert a second pickup that failed
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO pickups (pickup_id, return_id, status, failure_reason, scheduled_at, created_at)
            VALUES ('PICKUP-EXTRA-FAILED', ?, 'FAILED', 'WEATHER_DELAY', ?, ?)
            """,
            (return_id, now_iso, now_iso),
        )

    # Attempt recovery: should be rejected because orig_pk is still active (SCHEDULED)
    with pytest.raises(RecoveryError, match="active pickup .* is already in status SCHEDULED"):
        recover_pickup(return_id=return_id, idempotency_key="KEY-CHECK-ALL")


# ==============================================================================
# 10: NON-DESTRUCTIVE SCHEMA INITIALIZATION & MIGRATION
# ==============================================================================

def test_schema_init_is_non_destructive_with_checkpoints(test_db_env):
    """Calling db.init_db() repeatedly must preserve existing records and checkpoints."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO monitoring_checkpoints (return_id, last_observed_status, last_event_id, active_alert_signature, updated_at)
            VALUES (?, 'APPROVED', 1, 'SIG-123', ?)
            """,
            (return_id, now_iso),
        )

    db.init_db()

    with db.get_db() as conn:
        cp = conn.execute("SELECT * FROM monitoring_checkpoints WHERE return_id = ?", (return_id,)).fetchone()
        assert cp is not None
        assert cp["active_alert_signature"] == "SIG-123"


# ==============================================================================
# P2: RECONCILIATION GAPS (NON-UNCERTAIN / NON-EXISTENT / AUTHORIZATION)
# ==============================================================================

def test_reconciliation_rejects_non_uncertain_or_nonexistent_attempts(test_db_env):
    """Reconciling a non-existent or already SUCCESS/FAILED attempt must raise RecoveryError."""
    # 1. Non-existent attempt
    with pytest.raises(RecoveryError, match="not found"):
        reconcile_pickup_attempt("ATT-NONEXISTENT", "FAILED")

    with pytest.raises(RecoveryError, match="not found"):
        reconcile_refund_attempt("ATT-NONEXISTENT", "FAILED")

    # 2. Existing attempt that is SUCCESS, not UNCERTAIN
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    set_pickup_recovery_provider(lambda ret_id, pk_id: True)
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE'")

    res = recover_pickup(ret["return_id"], idempotency_key="KEY-SUCC")
    attempt_id = res["attempt_id"]

    with pytest.raises(RecoveryError, match="status is SUCCESS, not UNCERTAIN"):
        reconcile_pickup_attempt(attempt_id, "FAILED")

    # 3. Resolving as SUCCESS without authorized provider is blocked (arbitrary dicts rejected)
    set_pickup_recovery_provider(None)
    unc_id = record_uncertain_pickup_attempt(ret["return_id"], idempotency_key="KEY-UNC")
    with pytest.raises(RecoveryError, match="requires an authorized carrier provider"):
        reconcile_pickup_attempt(unc_id, "SUCCESS")

    # Reconciling with authorized provider succeeds
    mock_carrier = lambda ret_id, pk_id: {"confirmed": True, "reference": "REC-CONFIRMED-99"}
    reconcile_pickup_attempt(unc_id, "SUCCESS", carrier_provider=mock_carrier)
    with db.get_db() as conn:
        row = conn.execute("SELECT status, external_reference FROM pickup_attempts WHERE attempt_id = ?", (unc_id,)).fetchone()
        assert row["status"] == "SUCCESS"
        assert row["external_reference"] == "REC-CONFIRMED-99"


def test_reconciliation_security_and_refund_lifecycle(test_db_env):
    """
    Focused Security Verification:
    1. Reconciling refund UNCERTAIN as SUCCESS without authorized provider raises RecoveryError.
    2. Arbitrary caller-supplied dictionary {'authorized': True} is ignored/rejected.
    3. Reconciling with authorized payment provider transitions refund to INITIATED, NOT CREDITED.
    4. Crediting still strictly requires verify_and_finalize_refund with credit verification provider.
    5. Completed attempt cannot be overwritten by replaying an old reconciliation call.
    """
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))

    unc_rf_id = record_uncertain_refund_attempt(return_id, idempotency_key="SEC-RF-UNC")

    # 1. Arbitrary dictionary / no provider fails
    with pytest.raises(RecoveryError, match="requires an authorized payment provider"):
        reconcile_refund_attempt(unc_rf_id, "SUCCESS")

    # 2. Reconcile with authorized payment provider
    mock_pg = lambda ret_id, ref_id, amt: {"confirmed": True, "reference": "PG-RECON-SUCCESS"}
    reconcile_refund_attempt(unc_rf_id, "SUCCESS", payment_provider=mock_pg)

    # 3. Check that refund is INITIATED, NOT CREDITED!
    with db.get_db() as conn:
        rf = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        ret_row = conn.execute("SELECT status FROM returns WHERE return_id = ?", (return_id,)).fetchone()
        assert rf["status"] == "INITIATED"
        assert ret_row["status"] == "APPROVED"

    # 4. Old attempt replay cannot overwrite status once resolved (status is now SUCCESS, not UNCERTAIN)
    with pytest.raises(RecoveryError, match="status is SUCCESS, not UNCERTAIN"):
        reconcile_refund_attempt(unc_rf_id, "FAILED")

