import pytest
from unittest.mock import patch
from database import db
from database.return_service import create_return

async def _fast_run_demo_workflow(return_id: str, delay_seconds: float = 0.0):
    from database.demo_workflow import run_demo_workflow
    from agent.recovery_service import set_credit_verification_provider
    set_credit_verification_provider(lambda *a: True)
    try:
        return await run_demo_workflow(return_id=return_id, delay_seconds=0.0)
    finally:
        set_credit_verification_provider(None)

def test_database_isolation(test_db_env):
    """Ensure tests run on the temporary database, not data/app.db."""
    assert str(db.DB_PATH) == str(test_db_env["db_path"])
    assert "test_api.db" in str(db.DB_PATH)

def test_health_check(test_db_env):
    client = test_db_env["client"]
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "running" in data["message"].lower()

def test_get_customer_orders_success(test_db_env):
    client = test_db_env["client"]
    response = client.get("/customers/CUS-001/orders")
    assert response.status_code == 200
    data = response.json()
    assert data["customer"]["customer_id"] == "CUS-001"
    assert len(data["orders"]) >= 1
    assert data["orders"][0]["order_id"] in ["ORD-001", "ORD-SHIPPED"]

def test_get_customer_orders_not_found(test_db_env):
    client = test_db_env["client"]
    response = client.get("/customers/NONEXISTENT/orders")
    assert response.status_code == 404
    assert "Customer not found" in response.json()["detail"]

def test_check_eligibility_eligible(test_db_env):
    client = test_db_env["client"]
    payload = {
        "customer_id": "CUS-001",
        "order_item_id": "ITEM-001",
        "quantity": 1
    }
    response = client.post("/returns/check-eligibility", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["eligible"] is True
    assert "details" in data
    assert data["details"]["refund_amount_paise"] == 250000

def test_check_eligibility_ineligible_non_returnable(test_db_env):
    client = test_db_env["client"]
    payload = {
        "customer_id": "CUS-001",
        "order_item_id": "ITEM-NONRET",
        "quantity": 1
    }
    response = client.post("/returns/check-eligibility", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["eligible"] is False
    assert "not eligible for return" in data["message"].lower()

def test_check_eligibility_ineligible_not_delivered(test_db_env):
    client = test_db_env["client"]
    payload = {
        "customer_id": "CUS-001",
        "order_item_id": "ITEM-SHIPPED",
        "quantity": 1
    }
    response = client.post("/returns/check-eligibility", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["eligible"] is False
    assert "delivered" in data["message"].lower()

def test_create_return_unapproved(test_db_env):
    client = test_db_env["client"]
    payload = {
        "customer_id": "CUS-001",
        "order_item_id": "ITEM-001",
        "quantity": 1,
        "reason": "DEFECTIVE",
        "approval_confirmed": False
    }
    response = client.post("/returns", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["return"]["status"] == "REQUESTED"
    assert data["return"]["pickup_id"] is None
    assert data["return"]["refund_id"] is None

def test_create_return_approved(test_db_env):
    client = test_db_env["client"]
    payload = {
        "customer_id": "CUS-001",
        "order_item_id": "ITEM-001",
        "quantity": 1,
        "reason": "DEFECTIVE",
        "approval_confirmed": True
    }
    response = client.post("/returns", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["return"]["status"] == "APPROVED"
    assert data["return"]["pickup_id"] is not None
    assert data["return"]["refund_id"] is not None

def test_create_return_invalid_reason(test_db_env):
    client = test_db_env["client"]
    payload = {
        "customer_id": "CUS-001",
        "order_item_id": "ITEM-001",
        "quantity": 1,
        "reason": "INVALID_REASON",
        "approval_confirmed": True
    }
    response = client.post("/returns", json=payload)
    assert response.status_code == 400
    assert "Invalid return reason" in response.json()["detail"]

def test_get_return_details_success(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    response = client.get(f"/returns/{return_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["return_id"] == return_id
    assert data["status"] == "APPROVED"
    assert data["pickup"]["status"] == "SCHEDULED"
    assert data["refund"]["status"] == "PENDING"

def test_get_return_details_not_found(test_db_env):
    client = test_db_env["client"]
    response = client.get("/returns/RET-NONEXISTENT")
    assert response.status_code == 404
    assert "Return not found" in response.json()["detail"]

def test_assess_post_approval_return_approved(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    response = client.get(f"/agent/returns/{return_id}/assessment")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["return_id"] == return_id
    assert data["current_status"] == "APPROVED"
    assert data["assessment"]["stage"] == "PICKUP_PENDING"
    assert data["assessment"]["next_action"] == "MONITOR_PICKUP"
    assert "events" in data

def test_assess_post_approval_return_unapproved_conflict(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=False
    )
    return_id = ret["return_id"]
    response = client.get(f"/agent/returns/{return_id}/assessment")
    assert response.status_code == 409
    assert "APPROVED or COMPLETED" in response.json()["detail"]

def test_assess_post_approval_return_not_found(test_db_env):
    client = test_db_env["client"]
    response = client.get("/agent/returns/RET-NONEXISTENT/assessment")
    assert response.status_code == 404
    assert "Return not found" in response.json()["detail"]

def test_run_workflow_success(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    with patch("server.run_demo_workflow", side_effect=_fast_run_demo_workflow):
        response = client.post(f"/returns/{return_id}/run-workflow")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "completed successfully" in data["message"]

def test_run_workflow_already_completed(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    with patch("server.run_demo_workflow", side_effect=_fast_run_demo_workflow):
        res1 = client.post(f"/returns/{return_id}/run-workflow")
        assert res1.status_code == 200
        res2 = client.post(f"/returns/{return_id}/run-workflow")
        assert res2.status_code == 200
        assert "already been completed" in res2.json()["message"]

def test_run_workflow_not_found(test_db_env):
    client = test_db_env["client"]
    response = client.post("/returns/RET-NONEXISTENT/run-workflow")
    assert response.status_code == 404
    assert "Return not found" in response.json()["detail"]

def test_run_post_approval_agent_demo_success(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    with patch("server.run_demo_workflow", side_effect=_fast_run_demo_workflow):
        response = client.post(f"/agent/returns/{return_id}/run-demo")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["workflow"]["status"] == "COMPLETED"

def test_run_post_approval_agent_demo_conflict_unapproved(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=False
    )
    return_id = ret["return_id"]
    response = client.post(f"/agent/returns/{return_id}/run-demo")
    assert response.status_code == 409
    assert "requires an APPROVED return" in response.json()["detail"]

def test_run_post_approval_agent_demo_already_completed(test_db_env):
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    with patch("server.run_demo_workflow", side_effect=_fast_run_demo_workflow):
        client.post(f"/agent/returns/{return_id}/run-demo")
        response = client.post(f"/agent/returns/{return_id}/run-demo")
    assert response.status_code == 200
    assert "already completed" in response.json()["message"]

# --- TC4 REGRESSION TESTS ---

def test_tc4_assessment_reports_initiated_refund_as_refund_in_progress(test_db_env):
    """
    TC4 Part 1: Verify that when a refund is INITIATED (item RECEIVED),
    the assessment endpoint reports REFUND_IN_PROGRESS and MONITOR_REFUND_CREDIT,
    and does NOT report COMPLETED or CREDITED.
    """
    client = test_db_env["client"]
    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]
    
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE pickups
            SET status = 'RECEIVED', received_at = ?
            WHERE return_id = ?
            """,
            (now_iso, return_id)
        )
        conn.execute(
            """
            UPDATE refunds
            SET status = 'INITIATED', initiated_at = ?
            WHERE return_id = ?
            """,
            (now_iso, return_id)
        )
        
    response = client.get(f"/agent/returns/{return_id}/assessment")
    assert response.status_code == 200
    data = response.json()
    assert data["assessment"]["stage"] == "REFUND_IN_PROGRESS"
    assert data["assessment"]["next_action"] == "MONITOR_REFUND_CREDIT"
    assert data["assessment"]["stage"] != "COMPLETED"
    assert data["current_status"] != "COMPLETED"

def test_tc4_demo_workflow_does_not_auto_credit_without_external_verification(test_db_env):
    """
    TC4 Part 2 (FIXED): The demo workflow must NOT auto-credit a refund when no
    trusted credit-verification provider is configured.

    Phase 4 fix: run_demo_workflow now calls get_credit_verification_provider().
    When the _fast_run_demo_workflow helper installs a mock provider (lambda *a: True),
    credit verification succeeds and the refund is CREDITED.

    This test uses a separate call WITHOUT a provider to confirm the no-provider path
    leaves the refund at INITIATED.  A bare run_demo_workflow (no mock) is used so
    that no provider is active.
    """
    import asyncio
    from database.demo_workflow import run_demo_workflow
    from agent.recovery_service import set_credit_verification_provider

    ret = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    return_id = ret["return_id"]

    # Run with no provider configured — refund must stay INITIATED.
    set_credit_verification_provider(None)
    try:
        result = asyncio.run(
            run_demo_workflow(return_id=return_id, delay_seconds=0.0)
        )
    finally:
        set_credit_verification_provider(None)

    with db.get_db() as conn:
        refund = conn.execute(
            "SELECT status, credited_at FROM refunds WHERE return_id = ?",
            (return_id,)
        ).fetchone()

    # Official requirement: without external verification, refund must remain INITIATED.
    assert refund["status"] == "INITIATED", (
        f"Expected refund to remain INITIATED pending external confirmation, "
        f"but got {refund['status']}."
    )
    assert refund["credited_at"] is None
    assert result["status"] == "APPROVED"
    assert result["refund_status"] == "INITIATED"


# --- Phase 1 Regression Tests for Scanner & Completed Returns ---

def test_scanner_scans_approved_and_completed_returns(test_db_env):
    """
    Verify that:
    1. An APPROVED return is scanned.
    2. A consistent COMPLETED return is scanned and does NOT require attention.
    3. An inconsistent COMPLETED return (e.g. refund still INITIATED) is scanned and requires attention.
    4. A COMPLETED return with refund still INITIATED cannot be treated as successfully completed.
    """
    from agent.post_approval_agent import scan_approved_returns, list_monitored_returns
    
    # 1. Create an approved return
    ret_approved = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True
    )
    
    # 2. Create a consistent completed return (pickup RECEIVED, refund CREDITED, status COMPLETED)
    ret_consistent = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DAMAGED",
        approval_confirmed=True
    )
    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE returns SET status = 'COMPLETED', completed_at = '2026-10-22T12:00:00+00:00'
            WHERE return_id = ?
            """,
            (ret_consistent["return_id"],)
        )
        conn.execute(
            """
            UPDATE pickups SET status = 'RECEIVED', received_at = '2026-10-22T11:00:00+00:00'
            WHERE return_id = ?
            """,
            (ret_consistent["return_id"],)
        )
        conn.execute(
            """
            UPDATE refunds SET status = 'CREDITED', credited_at = '2026-10-22T11:30:00+00:00'
            WHERE return_id = ?
            """,
            (ret_consistent["return_id"],)
        )
        
    # 3. Create an inconsistent completed return (refund still INITIATED, status COMPLETED)
    ret_inconsistent = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="SIZE_ISSUE",
        approval_confirmed=True
    )
    with db.get_db() as conn:
        conn.execute(
            """
            UPDATE returns SET status = 'COMPLETED', completed_at = '2026-10-22T12:00:00+00:00'
            WHERE return_id = ?
            """,
            (ret_inconsistent["return_id"],)
        )
        conn.execute(
            """
            UPDATE pickups SET status = 'RECEIVED', received_at = '2026-10-22T11:00:00+00:00'
            WHERE return_id = ?
            """,
            (ret_inconsistent["return_id"],)
        )
        conn.execute(
            """
            UPDATE refunds SET status = 'INITIATED', initiated_at = '2026-10-22T11:30:00+00:00'
            WHERE return_id = ?
            """,
            (ret_inconsistent["return_id"],)
        )

    monitored_ids = list_monitored_returns()
    assert ret_approved["return_id"] in monitored_ids
    assert ret_consistent["return_id"] in monitored_ids
    assert ret_inconsistent["return_id"] in monitored_ids
    
    scan_results = scan_approved_returns()
    by_id = {r["return_id"]: r for r in scan_results}
    
    # 1. Approved return is scanned
    assert ret_approved["return_id"] in by_id
    assert by_id[ret_approved["return_id"]]["current_state"]["return_status"] == "APPROVED"
    
    # 2. Consistent completed return does NOT require attention
    assert ret_consistent["return_id"] in by_id
    consistent_res = by_id[ret_consistent["return_id"]]
    assert consistent_res["assessment"]["stage"] == "COMPLETED"
    assert consistent_res["assessment"]["next_action"] == "NONE"
    assert consistent_res["assessment"]["requires_attention"] is False
    
    # 3. Inconsistent completed return IS detected and requires attention
    assert ret_inconsistent["return_id"] in by_id
    inconsistent_res = by_id[ret_inconsistent["return_id"]]
    assert inconsistent_res["assessment"]["stage"] == "NEEDS_ATTENTION"
    assert inconsistent_res["assessment"]["next_action"] == "REVIEW_INCONSISTENT_COMPLETED_RETURN"
    assert inconsistent_res["assessment"]["requires_attention"] is True
    
    # 4. A COMPLETED return with refund still INITIATED cannot be treated as successfully completed
    assert inconsistent_res["assessment"]["stage"] != "COMPLETED"
    assert "not match" in inconsistent_res["assessment"]["reason"].lower() or "inconsistent" in inconsistent_res["assessment"]["reason"].lower()


def test_list_approved_returns_vs_list_monitored_returns(test_db_env):
    """
    Regression test ensuring list_approved_returns() returns ONLY APPROVED returns,
    while list_monitored_returns() returns both APPROVED and COMPLETED returns.
    """
    from agent.post_approval_agent import list_approved_returns, list_monitored_returns
    from database.return_service import create_return

    ret_approved = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="DEFECTIVE",
        approval_confirmed=True,
    )
    ret_completed = create_return(
        customer_id="CUS-001",
        order_item_id="ITEM-001",
        quantity=1,
        reason="SIZE_ISSUE",
        approval_confirmed=True,
    )

    with db.get_db() as conn:
        conn.execute(
            "UPDATE returns SET status = 'COMPLETED', completed_at = '2026-10-22T10:00:00+00:00' WHERE return_id = ?",
            (ret_completed["return_id"],)
        )

    approved_only = list_approved_returns()
    monitored_all = list_monitored_returns()

    assert ret_approved["return_id"] in approved_only
    assert ret_completed["return_id"] not in approved_only

    assert ret_approved["return_id"] in monitored_all
    assert ret_completed["return_id"] in monitored_all
