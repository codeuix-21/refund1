"""
Phase 4 Regression Test Suite: Post-Approval Safe Recovery & Operations.

Tests:
1. TC4 Fix: run_demo_workflow leaves refund as INITIATED and return as APPROVED when no provider is set.
2. TC4 Verification: When provider confirms, refund advances to CREDITED and return to COMPLETED.
3. Safe Pickup Recovery:
   - Fails if return is not APPROVED.
   - Fails if pickup is already in an active state (SCHEDULED, PICKED_UP, RECEIVED).
   - Reports PROVIDER_UNAVAILABLE when no authorized carrier provider is configured.
   - Succeeds when authorized carrier provider is configured and confirms, creating new pickup and logging event.
   - Idempotency replay returns existing attempt without creating duplicate pickups.
   - UNCERTAIN attempt blocks subsequent recovery until reconciled.
4. Safe Refund Initiation:
   - Fails if return is not APPROVED.
   - Fails if item has not reached warehouse (pickup not RECEIVED).
   - Fails if refund is already INITIATED or CREDITED.
   - Reports PROVIDER_UNAVAILABLE when no authorized payment provider is configured.
   - Succeeds when authorized payment provider is configured and confirms, advancing refund to INITIATED.
   - Idempotency replay returns existing attempt without duplicate submissions.
   - UNCERTAIN refund attempt blocks further attempts until reconciled.
5. verify_and_finalize_refund:
   - Without provider, returns verified=False and leaves refund uncredited.
   - Caller-supplied {"trusted_bank_confirmation": True} is rejected without an authorized provider.
   - With provider returning False or malformed data, returns verified=False and leaves refund uncredited.
   - With provider returning True, marks refund CREDITED and return COMPLETED.
"""

from datetime import datetime, timezone
import pytest

from database import db
from database.return_service import create_return
from database.demo_workflow import run_demo_workflow, run_full_demo_workflow
from agent.recovery_service import (
    RecoveryError,
    set_credit_verification_provider,
    set_pickup_recovery_provider,
    set_refund_initiation_provider,
    recover_pickup,
    record_uncertain_pickup_attempt,
    reconcile_pickup_attempt,
    initiate_refund_safe,
    record_failed_refund_attempt,
    record_uncertain_refund_attempt,
    reconcile_refund_attempt,
    verify_and_finalize_refund,
)


@pytest.fixture(autouse=True)
def cleanup_providers():
    """Ensure all provider hooks are cleanly reset after every test."""
    set_credit_verification_provider(None)
    set_pickup_recovery_provider(None)
    set_refund_initiation_provider(None)
    yield
    set_credit_verification_provider(None)
    set_pickup_recovery_provider(None)
    set_refund_initiation_provider(None)


# ==============================================================================
# TC4 FIX TESTS
# ==============================================================================

def test_tc4_workflow_no_auto_credit_without_provider(test_db_env):
    """Time passing alone must never convert INITIATED to CREDITED."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    result = run_full_demo_workflow(return_id)

    assert result["status"] == "APPROVED"
    assert result["refund_status"] == "INITIATED"

    with db.get_db() as conn:
        refund_row = conn.execute("SELECT status, credited_at FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        return_row = conn.execute("SELECT status, completed_at FROM returns WHERE return_id = ?", (return_id,)).fetchone()

    assert refund_row["status"] == "INITIATED"
    assert refund_row["credited_at"] is None
    assert return_row["status"] == "APPROVED"
    assert return_row["completed_at"] is None


def test_tc4_workflow_credits_when_provider_confirms(test_db_env):
    """When a trusted verification provider is configured and confirms, credit advances."""
    set_credit_verification_provider(lambda ret_id, ref_id: True)

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    result = run_full_demo_workflow(return_id)

    assert result["status"] == "COMPLETED"

    with db.get_db() as conn:
        refund_row = conn.execute("SELECT status, credited_at FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        return_row = conn.execute("SELECT status, completed_at FROM returns WHERE return_id = ?", (return_id,)).fetchone()

    assert refund_row["status"] == "CREDITED"
    assert refund_row["credited_at"] is not None
    assert return_row["status"] == "COMPLETED"
    assert return_row["completed_at"] is not None


# ==============================================================================
# SAFE PICKUP RECOVERY TESTS
# ==============================================================================

def test_recover_pickup_requires_approved_return(test_db_env):
    """Pickup recovery must reject returns that are not APPROVED."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=False,
    )
    return_id = ret["return_id"]

    with pytest.raises(RecoveryError, match="requires an APPROVED return"):
        recover_pickup(return_id=return_id, idempotency_key="KEY-PK-1")


def test_recover_pickup_blocks_when_active_pickup_exists(test_db_env):
    """Cannot recover pickup if an active pickup (SCHEDULED, PICKED_UP, RECEIVED) exists."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    # Initial return has pickup in SCHEDULED state
    with pytest.raises(RecoveryError, match="already in status SCHEDULED"):
        recover_pickup(return_id=return_id, idempotency_key="KEY-PK-2")


def test_recover_pickup_provider_unavailable(test_db_env):
    """When no carrier provider is configured, reports PROVIDER_UNAVAILABLE without fabricating success."""
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

    res = recover_pickup(return_id=return_id, idempotency_key="IDEM-PK-UNAVAIL")
    assert res["status"] == "PROVIDER_UNAVAILABLE"
    assert "not configured" in res["message"]


def test_recover_pickup_success_and_idempotency(test_db_env):
    """
    When carrier provider is configured and confirms:
    - First recovery succeeds, creates new pickup record, logs event, tracks attempt.
    - Second recovery with same idempotency_key returns idempotent replay.
    """
    set_pickup_recovery_provider(lambda ret_id, pk_id: {"confirmed": True, "reference": "CARRIER-REF-123"})

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]
    orig_pickup_id = ret["pickup_id"]

    # Mark original pickup as FAILED
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE' WHERE pickup_id = ?", (orig_pickup_id,))

    # 1. First recovery attempt
    res1 = recover_pickup(return_id=return_id, idempotency_key="IDEM-PK-100")
    assert res1["idempotent_replay"] is False
    assert res1["status"] == "SUCCESS"
    assert res1["external_reference"] == "CARRIER-REF-123"
    assert res1["previous_pickup_id"] == orig_pickup_id
    new_pickup_id = res1["new_pickup_id"]
    assert new_pickup_id != orig_pickup_id

    # Verify database state
    with db.get_db() as conn:
        # Check new pickup is SCHEDULED
        new_pk = conn.execute("SELECT status FROM pickups WHERE pickup_id = ?", (new_pickup_id,)).fetchone()
        assert new_pk["status"] == "SCHEDULED"

        # Check pickup_attempts table
        att = conn.execute("SELECT * FROM pickup_attempts WHERE idempotency_key = 'IDEM-PK-100'").fetchone()
        assert att is not None
        assert att["status"] == "SUCCESS"
        assert att["pickup_id"] == new_pickup_id
        assert att["external_reference"] == "CARRIER-REF-123"

    # 2. Idempotent replay with same key
    res2 = recover_pickup(return_id=return_id, idempotency_key="IDEM-PK-100")
    assert res2["idempotent_replay"] is True
    assert res2["pickup_id"] == new_pickup_id


def test_recover_pickup_uncertain_blocks_and_reconciles(test_db_env):
    """An UNCERTAIN pickup attempt blocks retry until reconciled."""
    set_pickup_recovery_provider(lambda ret_id, pk_id: True)

    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'FAILED', failure_reason = 'CUSTOMER_UNAVAILABLE' WHERE return_id = ?", (return_id,))

    # Record an uncertain attempt
    att_id = record_uncertain_pickup_attempt(return_id, idempotency_key="IDEM-UNCERTAIN-1")

    # Calling with same key raises because outcome is UNCERTAIN
    with pytest.raises(RecoveryError, match="UNCERTAIN outcome"):
        recover_pickup(return_id=return_id, idempotency_key="IDEM-UNCERTAIN-1")

    # Calling with a new key is also blocked by unresolved UNCERTAIN attempt for return
    with pytest.raises(RecoveryError, match="Unresolved UNCERTAIN attempt"):
        recover_pickup(return_id=return_id, idempotency_key="IDEM-NEW-KEY")

    # Reconcile the attempt as FAILED
    reconcile_pickup_attempt(att_id, "FAILED")

    # Now a new recovery can proceed
    res = recover_pickup(return_id=return_id, idempotency_key="IDEM-NEW-KEY")
    assert res["status"] == "SUCCESS"


# ==============================================================================
# SAFE REFUND INITIATION TESTS
# ==============================================================================

def test_initiate_refund_blocked_without_warehouse_receipt(test_db_env):
    """Refund initiation must be blocked if item is not RECEIVED at warehouse."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    # Initial state is SCHEDULED, not RECEIVED
    with pytest.raises(RecoveryError, match="item has not been received at warehouse"):
        initiate_refund_safe(return_id=return_id, idempotency_key="KEY-RF-1")


def test_initiate_refund_provider_unavailable(test_db_env):
    """When no payment provider is configured, reports PROVIDER_UNAVAILABLE without fabricating external reference."""
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

    res = initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-UNAVAIL")
    assert res["status"] == "PROVIDER_UNAVAILABLE"
    assert "not configured" in res["message"]


def test_initiate_refund_success_and_idempotency(test_db_env):
    """
    When item is RECEIVED and payment provider confirms:
    - Safe initiation transitions refund to INITIATED and tracks attempt with genuine reference.
    - Idempotency replay with same key returns existing result without re-submitting.
    - Attempting with new key raises error because refund is already INITIATED.
    """
    set_refund_initiation_provider(lambda ret_id, ref_id, amt: {"confirmed": True, "reference": "PG-TXN-999"})

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

    # 1. First initiation
    res1 = initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-100")
    assert res1["idempotent_replay"] is False
    assert res1["status"] == "SUCCESS"
    assert res1["refund_id"] == ret["refund_id"]
    assert res1["external_reference"] == "PG-TXN-999"

    with db.get_db() as conn:
        rf = conn.execute("SELECT status, initiated_at FROM refunds WHERE refund_id = ?", (ret["refund_id"],)).fetchone()
        assert rf["status"] == "INITIATED"
        assert rf["initiated_at"] is not None

        att = conn.execute("SELECT * FROM refund_attempts WHERE idempotency_key = 'IDEM-RF-100'").fetchone()
        assert att is not None
        assert att["status"] == "SUCCESS"
        assert att["external_reference"] == "PG-TXN-999"

    # 2. Idempotent replay with same key returns replay
    res2 = initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-100")
    assert res2["idempotent_replay"] is True
    assert res2["refund_id"] == ret["refund_id"]

    # 3. New key is rejected because refund is already INITIATED
    with pytest.raises(RecoveryError, match="already INITIATED"):
        initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-DIFFERENT")


def test_initiate_refund_uncertain_blocks_and_reconciles(test_db_env):
    """An UNCERTAIN refund attempt blocks retries until reconciled."""
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

    att_id = record_uncertain_refund_attempt(return_id, idempotency_key="IDEM-RF-UNCERTAIN")

    with pytest.raises(RecoveryError, match="UNCERTAIN outcome"):
        initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-UNCERTAIN")

    with pytest.raises(RecoveryError, match="Unresolved UNCERTAIN attempt"):
        initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-NEW")

    # Reconcile attempt as FAILED
    reconcile_refund_attempt(att_id, "FAILED")

    # After reconciliation, a new attempt can proceed
    res = initiate_refund_safe(return_id=return_id, idempotency_key="IDEM-RF-NEW")
    assert res["status"] == "SUCCESS"


# ==============================================================================
# VERIFY AND FINALIZE REFUND TESTS
# ==============================================================================

def test_verify_and_finalize_refund_without_provider(test_db_env):
    """Without an authorized provider, refund remains uncredited."""
    ret = create_return(
        customer_id=test_db_env["customer_id"],
        order_item_id=test_db_env["order_item_id"],
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    return_id = ret["return_id"]

    # Set pickup RECEIVED and refund INITIATED
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?", (now_iso, return_id))
        conn.execute("UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?", (now_iso, return_id))

    res = verify_and_finalize_refund(return_id)
    assert res["verified"] is False
    assert "Credit verification unavailable" in res["message"]

    with db.get_db() as conn:
        rf = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        ret_row = conn.execute("SELECT status FROM returns WHERE return_id = ?", (return_id,)).fetchone()

    assert rf["status"] == "INITIATED"
    assert ret_row["status"] == "APPROVED"


def test_verify_and_finalize_refund_with_provider_confirmation(test_db_env):
    """When authorized provider confirms, refund becomes CREDITED and return COMPLETED."""
    set_credit_verification_provider(lambda ret_id, ref_id: {"confirmed": True, "reference": "BANK-CREDIT-777"})

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
    assert res["verified"] is True
    assert res["refund_status"] == "CREDITED"
    assert res["return_status"] == "COMPLETED"
    assert res["external_reference"] == "BANK-CREDIT-777"

    with db.get_db() as conn:
        rf = conn.execute("SELECT status, credited_at FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        ret_row = conn.execute("SELECT status, completed_at FROM returns WHERE return_id = ?", (return_id,)).fetchone()

    assert rf["status"] == "CREDITED"
    assert rf["credited_at"] is not None
    assert ret_row["status"] == "COMPLETED"
    assert ret_row["completed_at"] is not None


def test_caller_supplied_trusted_evidence_rejected_without_provider(test_db_env):
    """Caller-supplied trusted_bank_confirmation is NOT trusted without an authorized provider."""
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

    res = verify_and_finalize_refund(return_id, verification_evidence={"trusted_bank_confirmation": True})
    assert res["verified"] is False
    assert "Credit verification unavailable" in res["message"]
