"""
Official Hackathon Scenarios Test Suite (TC1 - TC4).

Covers:
- TC1: Eligible return (end-to-end API approval, pickup scheduling, refund creation, record persistence).
- TC2: Expired return window (eligibility rejection, return creation rejection, absence of unintended records, alternative recommendation gap).
- TC3: Wrong item selected (ownership validation rejection for other customer vs same customer order/item validation gap, absence of unintended records).
- TC4: Refund initiated is not credited (assessment as REFUND_IN_PROGRESS, MONITOR_REFUND_CREDIT action, safety verification, preserving known defect test).
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from database import db
from agent.post_approval_agent import assess_return_status, inspect_return
from database.return_service import create_return

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


# ==============================================================================
# TC1: ELIGIBLE RETURN
# ==============================================================================

def test_tc1_eligible_return_creation_and_action_flow(test_db_env):
    """
    [TC1 - Eligible Return]
    Input and Initial State:
      - Customer 'CUS-001' with delivered order 'ORD-001' containing item 'ITEM-001'
        ('Test Running Shoes', return window 30 days, delivered 2 days ago).
    Expected Outcome:
      - /returns/check-eligibility returns eligible=True.
      - /returns with approval_confirmed=True creates an APPROVED return.
      - Pickup is scheduled and refund is created in PENDING state.
      - Persistence verified in returns, pickups, refunds, and return_events tables.
      - Response provides return_id and pickup identifier (pickup_id).
    Evidence:
      - Verified against API endpoints POST /returns/check-eligibility, POST /returns,
        and GET /returns/{return_id}.
    Mismatch / Finding:
      - The API contract returns 'pickup_id' (e.g. 'PICKUP-XXXX') under details/return object;
        no external third-party 'pickup_reference' or carrier tracking number is generated
        as external courier integration is not implemented.
    """
    client = test_db_env["client"]
    customer_id = test_db_env["customer_id"]
    order_item_id = test_db_env["order_item_id"]

    # 1. Check eligibility
    elig_resp = client.post(
        "/returns/check-eligibility",
        json={
            "customer_id": customer_id,
            "order_item_id": order_item_id,
            "quantity": 1,
        },
    )
    assert elig_resp.status_code == 200
    elig_data = elig_resp.json()
    assert elig_data["eligible"] is True
    assert elig_data["details"]["product_name"] == "Test Running Shoes"

    # 2. Submit return with human approval confirmed
    create_resp = client.post(
        "/returns",
        json={
            "customer_id": customer_id,
            "order_item_id": order_item_id,
            "quantity": 1,
            "reason": "DEFECTIVE",
            "approval_confirmed": True,
        },
    )
    assert create_resp.status_code == 200
    create_data = create_resp.json()
    assert create_data["success"] is True
    ret_info = create_data["return"]
    assert ret_info["status"] == "APPROVED"
    assert ret_info["pickup_id"] is not None
    assert ret_info["pickup_id"].startswith("PICKUP-")
    assert ret_info["refund_id"] is not None
    assert ret_info["refund_id"].startswith("REFUND-")
    return_id = ret_info["return_id"]

    # 3. Verify persistence and details via GET /returns/{return_id}
    detail_resp = client.get(f"/returns/{return_id}")
    assert detail_resp.status_code == 200
    details = detail_resp.json()
    assert details["return_id"] == return_id
    assert details["status"] == "APPROVED"
    assert details["pickup"]["pickup_id"] == ret_info["pickup_id"]
    assert details["pickup"]["status"] == "SCHEDULED"
    assert details["refund"]["refund_id"] == ret_info["refund_id"]
    assert details["refund"]["status"] == "PENDING"

    # 4. Direct DB verification
    with db.get_db() as conn:
        ret_row = conn.execute("SELECT * FROM returns WHERE return_id = ?", (return_id,)).fetchone()
        assert ret_row is not None
        assert ret_row["status"] == "APPROVED"

        pk_row = conn.execute("SELECT * FROM pickups WHERE return_id = ?", (return_id,)).fetchone()
        assert pk_row is not None
        assert pk_row["status"] == "SCHEDULED"

        rf_row = conn.execute("SELECT * FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
        assert rf_row is not None
        assert rf_row["status"] == "PENDING"

        events = conn.execute("SELECT * FROM return_events WHERE return_id = ?", (return_id,)).fetchall()
        event_types = {e["event_type"] for e in events}
        assert "RETURN" in event_types
        assert "PICKUP" in event_types
        assert "REFUND" in event_types


# ==============================================================================
# TC2: EXPIRED RETURN WINDOW
# ==============================================================================

def test_tc2_expired_return_window_rejected(test_db_env):
    """
    [TC2 - Expired Return Window]
    Input and Initial State:
      - Order delivered 45 days ago for a product with a 30-day return window.
    Expected Outcome:
      - Eligibility check returns eligible=False with clear policy expiration message.
      - Attempting to POST /returns results in HTTP 400 Bad Request.
      - Zero records are created in returns, pickups, or refunds tables.
    Evidence:
      - Verified against POST /returns/check-eligibility and POST /returns.
    Mismatch / Finding:
      - The official hackathon scenario notes: "Checks return window and policy... shows alternatives".
        The existing backend API provides no alternative product suggestions or alternative resolution
        endpoint when the return window has expired.
    """
    client = test_db_env["client"]
    customer_id = test_db_env["customer_id"]

    # Seed an order delivered 45 days ago (return window is 30 days)
    delivered_past = (date.today() - timedelta(days=45)).isoformat()
    with db.get_db() as conn:
        conn.execute(
            """
            INSERT INTO orders (order_id, customer_id, order_date, delivery_date, status, payment_method, created_at)
            VALUES ('ORD-EXPIRED', ?, '2026-01-01T00:00:00+00:00', ?, 'DELIVERED', 'UPI', '2026-01-01T00:00:00+00:00')
            """,
            (customer_id, delivered_past),
        )
        conn.execute(
            """
            INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price_paise)
            VALUES ('ITEM-EXPIRED', 'ORD-EXPIRED', 'PROD-001', 1, 500000)
            """
        )

    # 1. Eligibility check must be False
    elig_resp = client.post(
        "/returns/check-eligibility",
        json={
            "customer_id": customer_id,
            "order_item_id": "ITEM-EXPIRED",
            "quantity": 1,
        },
    )
    assert elig_resp.status_code == 200
    elig_data = elig_resp.json()
    assert elig_data["eligible"] is False
    assert "expired" in elig_data["message"].lower()

    # 2. Return creation must be rejected
    create_resp = client.post(
        "/returns",
        json={
            "customer_id": customer_id,
            "order_item_id": "ITEM-EXPIRED",
            "quantity": 1,
            "reason": "NO_LONGER_NEEDED",
            "approval_confirmed": True,
        },
    )
    assert create_resp.status_code == 400
    assert "expired" in create_resp.json()["detail"].lower()

    # 3. Confirm no unintended database entries
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM returns WHERE order_item_id = 'ITEM-EXPIRED'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM pickups WHERE return_id NOT IN (SELECT return_id FROM returns)").fetchone()[0] == 0


# ==============================================================================
# TC3: WRONG ITEM SELECTED
# ==============================================================================

def test_tc3_wrong_item_selected_ownership_and_validation(test_db_env):
    """
    [TC3 - Wrong Item Selected]
    Input and Initial State:
      - Item 'ITEM-OTHER' belonging to customer 'CUS-OTHER'.
      - Customer 'CUS-001' attempts to check eligibility and return 'ITEM-OTHER'.
    Expected Outcome:
      - Backend detects customer/item ownership mismatch and rejects.
      - /returns/check-eligibility returns eligible=False.
      - /returns rejects with HTTP 400.
      - No return, pickup, or refund records are created.
    Evidence:
      - POST /returns/check-eligibility and POST /returns response status and body.
    Mismatch / Finding:
      - The backend successfully validates ownership via (order_items -> orders.customer_id).
        However, if customer 'CUS-001' bought two different items in the same or different orders
        and accidentally selected Item B instead of Item A (e.g., wrong shoes or shirts), the API
        validates Item B strictly by its own policy rules; the current API has no natural language
        or semantic cross-check to detect user intent mismatches ("I meant the red shoes") prior to submission.
    """
    client = test_db_env["client"]
    customer_id = test_db_env["customer_id"]

    # Create another customer and order item
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO customers (customer_id, name, created_at) VALUES ('CUS-OTHER', 'Other User', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO orders (order_id, customer_id, order_date, delivery_date, status, payment_method, created_at) "
            "VALUES ('ORD-OTHER', 'CUS-OTHER', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', 'DELIVERED', 'UPI', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price_paise) "
            "VALUES ('ITEM-OTHER', 'ORD-OTHER', 'PROD-001', 1, 1000)"
        )

    # 1. Eligibility check with wrong customer must fail
    elig_resp = client.post(
        "/returns/check-eligibility",
        json={
            "customer_id": customer_id,
            "order_item_id": "ITEM-OTHER",
            "quantity": 1,
        },
    )
    assert elig_resp.status_code == 200
    assert elig_resp.json()["eligible"] is False
    assert "not belong" in elig_resp.json()["message"].lower()

    # 2. Return submission with wrong customer must be rejected
    create_resp = client.post(
        "/returns",
        json={
            "customer_id": customer_id,
            "order_item_id": "ITEM-OTHER",
            "quantity": 1,
            "reason": "WRONG_ITEM",
            "approval_confirmed": True,
        },
    )
    assert create_resp.status_code == 400
    assert "not belong" in create_resp.json()["detail"].lower()

    # 3. Nonexistent item identifier must also be rejected
    bad_item_resp = client.post(
        "/returns",
        json={
            "customer_id": customer_id,
            "order_item_id": "ITEM-DOES-NOT-EXIST",
            "quantity": 1,
            "reason": "WRONG_ITEM",
            "approval_confirmed": True,
        },
    )
    assert bad_item_resp.status_code == 400
    assert "not found" in bad_item_resp.json()["detail"].lower()

    # 4. Verify no orphan records created
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM returns WHERE order_item_id = 'ITEM-OTHER'").fetchone()[0] == 0


# ==============================================================================
# TC4: REFUND INITIATED IS NOT CREDITED
# ==============================================================================

def test_tc4_refund_initiated_assessed_as_in_progress(test_db_env):
    """
    [TC4 - Refund Initiated Is Not Credited]
    Input and Initial State:
      - Return with pickup status 'RECEIVED' and refund status 'INITIATED'.
    Expected Outcome:
      - Agent assesses stage as 'REFUND_IN_PROGRESS'.
      - Next recommended action is 'MONITOR_REFUND_CREDIT'.
      - Assessment does NOT claim the refund is credited or return completed.
      - requires_attention is False (within normal SLA).
    Evidence:
      - Output of assess_return_status() on actual return state.
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
        conn.execute(
            "UPDATE pickups SET status = 'RECEIVED', received_at = ? WHERE return_id = ?",
            (now_iso, return_id),
        )
        conn.execute(
            "UPDATE refunds SET status = 'INITIATED', initiated_at = ? WHERE return_id = ?",
            (now_iso, return_id),
        )

    state = inspect_return(return_id)
    assessment = assess_return_status(state)

    assert assessment["stage"] == "REFUND_IN_PROGRESS"
    assert assessment["next_action"] == "MONITOR_REFUND_CREDIT"
    assert assessment["requires_attention"] is False
    assert "initiated" in assessment["reason"].lower()
    assert assessment["stage"] != "COMPLETED"


def test_tc4_demo_workflow_unverified_credit_defect(test_db_env):
    """
    [TC4 - Verified Fix: Demo Workflow Without Provider Does Not Auto-Credit]
    Verifies that run_full_demo_workflow in database/demo_workflow.py refrains
    from auto-advancing refund from INITIATED to CREDITED without external confirmation.
    Without an authorized credit verification provider, refund stays INITIATED.
    """
    from database.demo_workflow import run_full_demo_workflow
    from agent.recovery_service import set_credit_verification_provider

    set_credit_verification_provider(None)
    try:
        ret = create_return(
            customer_id=test_db_env["customer_id"],
            order_item_id=test_db_env["order_item_id"],
            quantity=1,
            reason="DEFECTIVE",
            approval_confirmed=True,
        )
        return_id = ret["return_id"]

        run_full_demo_workflow(return_id)

        with db.get_db() as conn:
            refund_row = conn.execute("SELECT status FROM refunds WHERE return_id = ?", (return_id,)).fetchone()
            assert refund_row["status"] == "INITIATED", (
                "Workflow must not auto-credit refund without external confirmation"
            )
    finally:
        set_credit_verification_provider(None)
