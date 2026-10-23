import asyncio

from database.db import get_db
from database.return_service import log_event, utc_now
from agent.recovery_service import get_credit_verification_provider, _validate_provider_confirmation


async def run_demo_workflow(
    return_id: str,
    delay_seconds: float = 1.5,
):
    """
    Simulate pickup and refund progression for an approved return.

    Progression:
    1. Courier collection: SCHEDULED -> PICKED_UP
    2. Warehouse receipt: PICKED_UP -> RECEIVED
    3. Refund initiation: PENDING -> INITIATED
    4. Trustworthy credit verification check:
       - If a trusted verification provider is configured and confirms credit,
         the refund is marked CREDITED and the return is marked COMPLETED.
       - If no trusted verification provider is configured, the refund remains
         INITIATED (REFUND_IN_PROGRESS) and the return remains APPROVED.
         Time passing alone never creates unverified credit.
    """

    # Step 1: Find the pickup and refund records.
    with get_db() as connection:
        return_row = connection.execute(
            """
            SELECT return_id, status
            FROM returns
            WHERE return_id = ?
            """,
            (return_id,),
        ).fetchone()

        if return_row is None:
            raise ValueError(f"Return not found: {return_id}")

        if return_row["status"] != "APPROVED":
            raise ValueError(
                f"Return must be APPROVED, not {return_row['status']}"
            )

        pickup = connection.execute(
            """
            SELECT pickup_id, status
            FROM pickups
            WHERE return_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (return_id,),
        ).fetchone()

        refund = connection.execute(
            """
            SELECT refund_id, status
            FROM refunds
            WHERE return_id = ?
            """,
            (return_id,),
        ).fetchone()

        if pickup is None or refund is None:
            raise ValueError(
                "Approved return is missing its pickup or refund record"
            )

        if pickup["status"] != "SCHEDULED":
            raise ValueError(
                f"Pickup must be SCHEDULED, not {pickup['status']}"
            )

        if refund["status"] != "PENDING":
            raise ValueError(
                f"Refund must be PENDING, not {refund['status']}"
            )

        pickup_id = pickup["pickup_id"]
        refund_id = refund["refund_id"]

    # Step 2: Simulate the courier collecting the item.
    await asyncio.sleep(delay_seconds)

    with get_db() as connection:
        now = utc_now()
        connection.execute(
            """
            UPDATE pickups
            SET status = 'PICKED_UP', picked_up_at = ?
            WHERE pickup_id = ? AND status = 'SCHEDULED'
            """,
            (now, pickup_id),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Pickup was no longer SCHEDULED")

        log_event(
            connection,
            return_id,
            "PICKUP",
            "Courier collected the item",
            from_status="SCHEDULED",
            to_status="PICKED_UP",
        )

    # Step 3: Simulate the returned item reaching the warehouse.
    await asyncio.sleep(delay_seconds)

    with get_db() as connection:
        now = utc_now()
        connection.execute(
            """
            UPDATE pickups
            SET status = 'RECEIVED', received_at = ?
            WHERE pickup_id = ? AND status = 'PICKED_UP'
            """,
            (now, pickup_id),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Pickup was no longer PICKED_UP")

        log_event(
            connection,
            return_id,
            "PICKUP",
            "Returned item received at the warehouse",
            from_status="PICKED_UP",
            to_status="RECEIVED",
        )

    # Step 4: Initiate the refund.
    await asyncio.sleep(delay_seconds)

    with get_db() as connection:
        now = utc_now()
        connection.execute(
            """
            UPDATE refunds
            SET status = 'INITIATED', initiated_at = ?
            WHERE refund_id = ? AND status = 'PENDING'
            """,
            (now, refund_id),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Refund was no longer PENDING")

        log_event(
            connection,
            return_id,
            "REFUND",
            "Refund initiated to the original payment method",
            from_status="PENDING",
            to_status="INITIATED",
        )

    # Step 5: Check trustworthy credit verification
    provider = get_credit_verification_provider()
    credit_verified = False
    provider_ext_ref = None

    if provider is not None:
        try:
            raw_res = provider(return_id, refund_id)
            credit_verified, provider_ext_ref = _validate_provider_confirmation(raw_res)
        except Exception:
            credit_verified = False

    if not credit_verified:
        # Time passing alone does NOT turn INITIATED into CREDITED without verification.
        return {
            "return_id": return_id,
            "pickup_id": pickup_id,
            "refund_id": refund_id,
            "status": "APPROVED",
            "refund_status": "INITIATED",
            "message": "Refund initiated; awaiting trustworthy external credit confirmation.",
        }

    # Step 6: External verification confirmed — mark CREDITED and COMPLETED
    await asyncio.sleep(delay_seconds)

    with get_db() as connection:
        now = utc_now()
        connection.execute(
            """
            UPDATE refunds
            SET status = 'CREDITED', credited_at = ?
            WHERE refund_id = ? AND status = 'INITIATED'
            """,
            (now, refund_id),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Refund was no longer INITIATED")

        event_msg = "Refund credited successfully following verification"
        if provider_ext_ref:
            event_msg += f" (Ref: {provider_ext_ref})"

        log_event(
            connection,
            return_id,
            "REFUND",
            event_msg,
            from_status="INITIATED",
            to_status="CREDITED",
        )

        connection.execute(
            """
            UPDATE returns
            SET status = 'COMPLETED', completed_at = ?
            WHERE return_id = ? AND status = 'APPROVED'
            """,
            (now, return_id),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Return was no longer APPROVED")

        log_event(
            connection,
            return_id,
            "RETURN",
            "Return workflow completed successfully",
            from_status="APPROVED",
            to_status="COMPLETED",
        )

    return {
        "return_id": return_id,
        "pickup_id": pickup_id,
        "refund_id": refund_id,
        "status": "COMPLETED",
        "message": "Demo refund credited successfully",
    }


def run_full_demo_workflow(return_id: str) -> dict:
    """Synchronous convenience wrapper around run_demo_workflow with 0 delay."""
    return asyncio.run(run_demo_workflow(return_id=return_id, delay_seconds=0.0))


if __name__ == "__main__":
    print(
        "This module is intended to be called by the API after "
        "a return is explicitly approved."
    )
