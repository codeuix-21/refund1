import asyncio
from contextlib import asynccontextmanager
from agent.background_worker import approved_return_worker
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from database.demo_workflow import run_demo_workflow
from database.db import get_db
from database.return_service import (
    check_eligibility,
    create_return,
    ReturnError,
)
from agent.post_approval_agent import (
    inspect_return,
    assess_return_status,
    assess_stage_delay,
    explain_assessment,
    get_return_events,
    monitor_return,
)

class EligibilityRequest(BaseModel):
    customer_id: str
    order_item_id: str
    quantity: int = Field(gt=0)

class CreateReturnRequest(BaseModel):
    customer_id: str
    order_item_id: str
    quantity: int = Field(gt=0)
    reason: str
    approval_confirmed: bool = False

async def midnight_date_sync_worker(poll_interval_seconds: float = 60.0):
    """
    Background worker that checks every minute if calendar day rolled over (12:00 AM).
    When a new day starts, shifts all order delivery dates forward (+1 day/day)
    so mock orders always remain fresh in active return windows.
    """
    from database.date_sync import sync_delivery_dates
    while True:
        try:
            await asyncio.sleep(poll_interval_seconds)
            sync_delivery_dates()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in midnight date sync worker: %s", e)

@asynccontextmanager
async def lifespan(_application: FastAPI):
    # Ensure delivery dates are current on startup
    try:
        from database.date_sync import sync_delivery_dates
        sync_delivery_dates()
    except Exception as e:
        logger.warning("Initial date sync failed: %s", e)

    # Start the background monitoring worker.
    worker_task = asyncio.create_task(
        approved_return_worker(poll_interval_seconds=15.0)
    )
    # Start the midnight date sync worker.
    date_sync_task = asyncio.create_task(
        midnight_date_sync_worker(poll_interval_seconds=60.0)
    )

    try:
        yield
    finally:
        # Stop the worker cleanly when FastAPI shuts down.
        worker_task.cancel()
        date_sync_task.cancel()

        try:
            await asyncio.gather(worker_task, date_sync_task, return_exceptions=True)
        except Exception:
            pass

app = FastAPI(
    title="Return & Refund Chaser API",
    description="Backend API for tracking product returns and refunds.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],

)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "message": "Return & Refund Chaser API is running",
    }


@app.get("/customers/{customer_id}/orders")
def get_customer_orders(customer_id: str):
    with get_db() as connection:
        customer = connection.execute(
            """
            SELECT customer_id, name, email
            FROM customers
            WHERE customer_id = ?
            """,
            (customer_id,),
        ).fetchone()

        if customer is None:
            raise HTTPException(
                status_code=404,
                detail="Customer not found.",
            )

        rows = connection.execute(
            """
            SELECT
                o.order_id,
                o.order_date,
                o.delivery_date,
                o.status AS order_status,
                o.payment_method,
                oi.order_item_id,
                oi.quantity,
                oi.unit_price_paise,
                p.product_id,
                p.name AS product_name,
                p.brand,
                p.category,
                p.return_window_days,
                p.is_returnable
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE o.customer_id = ?
            ORDER BY o.order_date DESC, o.order_id, oi.order_item_id
            """,
            (customer_id,),
        ).fetchall()

    orders_by_id = {}

    for row in rows:
        order_id = row["order_id"]

        if order_id not in orders_by_id:
            orders_by_id[order_id] = {
                "order_id": order_id,
                "order_date": row["order_date"],
                "delivery_date": row["delivery_date"],
                "status": row["order_status"],
                "payment_method": row["payment_method"],
                "items": [],
            }

        orders_by_id[order_id]["items"].append(
            {
                "order_item_id": row["order_item_id"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "brand": row["brand"],
                "category": row["category"],
                "quantity": row["quantity"],
                "unit_price_paise": row["unit_price_paise"],
                "return_window_days": row["return_window_days"],
                "is_returnable": bool(row["is_returnable"]),
            }
        )

    return {
        "customer": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "email": customer["email"],
        },
        "orders": list(orders_by_id.values()),
    }

@app.post("/returns/check-eligibility")
def check_return_eligibility(request: EligibilityRequest):
    try:
        with get_db() as connection:
            result = check_eligibility(
                connection=connection,
                customer_id=request.customer_id,
                order_item_id=request.order_item_id,
                quantity=request.quantity,
            )

        return {
            "eligible": True,
            "message": "This item is eligible for return.",
            "details": result,
        }

    except ReturnError as error:
        return {
            "eligible": False,
            "message": str(error),
        }

@app.post("/returns")
def request_return(request: CreateReturnRequest):
    try:
        result = create_return(
            customer_id=request.customer_id,
            order_item_id=request.order_item_id,
            quantity=request.quantity,
            reason=request.reason,
            approval_confirmed=request.approval_confirmed,
        )

        return {
            "success": True,
            "message": "Return request created successfully.",
            "return": result,
        }

    except ReturnError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

@app.get("/returns/{return_id}")
def get_return_details(return_id: str):
    with get_db() as connection:
        row = connection.execute(
            """
            SELECT
                r.return_id,
                r.quantity AS return_quantity,
                r.reason,
                r.status AS return_status,
                r.requested_at,
                r.approved_at,
                r.completed_at,
                oi.order_item_id,
                oi.order_id,
                p.product_id,
                p.name AS product_name,
                pk.pickup_id,
                pk.status AS pickup_status,
                pk.scheduled_at,
                pk.picked_up_at,
                pk.received_at,
                rf.refund_id,
                rf.amount_paise AS refund_amount_paise,
                rf.method AS refund_method,
                rf.status AS refund_status,
                rf.initiated_at AS refund_initiated_at,
                rf.credited_at AS refund_credited_at
            FROM returns r
            JOIN order_items oi
                ON oi.order_item_id = r.order_item_id
            JOIN products p
                ON p.product_id = oi.product_id
            LEFT JOIN pickups pk
                ON pk.return_id = r.return_id
            LEFT JOIN refunds rf
                ON rf.return_id = r.return_id
            WHERE r.return_id = ?
            ORDER BY pk.created_at DESC
            LIMIT 1
            """,
            (return_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Return not found.",
        )

    return {
        "return_id": row["return_id"],
        "order_id": row["order_id"],
        "order_item_id": row["order_item_id"],
        "product": {
            "product_id": row["product_id"],
            "name": row["product_name"],
        },
        "quantity": row["return_quantity"],
        "reason": row["reason"],
        "status": row["return_status"],
        "requested_at": row["requested_at"],
        "approved_at": row["approved_at"],
        "completed_at": row["completed_at"],
        "pickup": {
            "pickup_id": row["pickup_id"],
            "status": row["pickup_status"],
            "scheduled_at": row["scheduled_at"],
            "picked_up_at": row["picked_up_at"],
            "received_at": row["received_at"],
        } if row["pickup_id"] else None,
        "refund": {
            "refund_id": row["refund_id"],
            "amount_paise": row["refund_amount_paise"],
            "method": row["refund_method"],
            "status": row["refund_status"],
            "initiated_at": row["refund_initiated_at"],
            "credited_at": row["refund_credited_at"],
        } if row["refund_id"] else None,
    }
@app.get("/agent/returns/{return_id}/assessment")
def assess_post_approval_return(return_id: str):
    # Step 1: Retrieve the current database state.
    try:
        state = inspect_return(return_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )

    return_status = state["return"]["return_status"]

    # Step 2: This agent handles only approved or completed returns.
    if return_status not in {"APPROVED", "COMPLETED"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "The post-approval agent can only assess returns "
                "with APPROVED or COMPLETED status."
            ),
        )

    # Step 3: Assess the workflow using Python rules.
    assessment = assess_return_status(state)

    # Step 4: Check whether the current stage is overdue.
    stage_delay = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
    )

    # Step 5: Keep the main assessment consistent with delay detection.
    if stage_delay["delayed"]:
        assessment = {
            **assessment,
            "stage": "NEEDS_ATTENTION",
            "next_action": "ESCALATE_STAGE_DELAY",
            "requires_attention": True,
            "reason": stage_delay["reason"],
        }
    elif stage_delay["requires_attention"]:
        assessment = {
            **assessment,
            "stage": "NEEDS_ATTENTION",
            "next_action": "REVIEW_POST_APPROVAL_STATE",
            "requires_attention": True,
            "reason": stage_delay["reason"],
        }

    # Step 6: Ask Qwen to explain the authoritative assessment.
    try:
        explanation = explain_assessment(state, assessment)
    except RuntimeError:
        explanation = None

    # Step 7: Retrieve the persistent event history.
    events = get_return_events(return_id)

    return {
        "success": True,
        "return_id": return_id,
        "current_status": return_status,
        "assessment": assessment,
        "stage_delay": stage_delay,
        "explanation": explanation,
        "explanation_available": explanation is not None,
        "events": events,
        "last_event_id": events[-1]["event_id"] if events else None,
    }
@app.post("/agent/returns/{return_id}/run-demo")
async def run_post_approval_agent_demo(return_id: str):
    # Verify that the return exists and inspect its current status.
    try:
        initial_state = inspect_return(return_id)
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )

    current_status = initial_state["return"]["return_status"]

    # Never rerun a completed workflow.
    if current_status == "COMPLETED":
        return {
            "success": True,
            "message": "Return is already completed; demo was not rerun.",
            "return_id": return_id,
            "assessment": assess_return_status(initial_state),
            "events": get_return_events(return_id),
        }

    # This endpoint only starts after customer approval.
    if current_status != "APPROVED":
        raise HTTPException(
            status_code=409,
            detail=(
                "The post-approval agent requires an APPROVED return. "
                f"Current status: {current_status}."
            ),
        )

    # Start monitoring before the simulated workflow begins.
    monitor_task = asyncio.create_task(
        monitor_return(
            return_id,
            poll_interval_seconds=0.5,
            timeout_seconds=60,
        )
    )

    # Give the monitor an opportunity to record the initial state.
    await asyncio.sleep(0.1)

    try:
        # Execute the existing simulated workflow.
        workflow_result = await run_demo_workflow(
            return_id,
            delay_seconds=1.5,
        )

        # Collect observations and explanations.
        monitoring_result = await monitor_task

    except ValueError as error:
        if not monitor_task.done():
            monitor_task.cancel()

        await asyncio.gather(
            monitor_task,
            return_exceptions=True,
        )

        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    except Exception:
        if not monitor_task.done():
            monitor_task.cancel()

        await asyncio.gather(
            monitor_task,
            return_exceptions=True,
        )

        raise HTTPException(
            status_code=500,
            detail="The demo workflow or monitoring process failed.",
        )

    return {
        "success": True,
        "message": "Demo workflow and post-approval monitoring completed.",
        "workflow": workflow_result,
        "monitoring": monitoring_result,
    }
@app.post("/returns/{return_id}/run-workflow")
async def start_return_workflow(return_id: str):
    # Check the return's current status.
    with get_db() as connection:
        row = connection.execute(
            """
            SELECT status
            FROM returns
            WHERE return_id = ?
            """,
            (return_id,),
        ).fetchone()

    # Handle an unknown return ID.
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Return not found.",
        )

    # Handle an already completed return.
    if row["status"] == "COMPLETED":
        return {
            "success": True,
            "message": "This return has already been completed.",
            "return_id": return_id,
            "status": "COMPLETED",
        }

    # Run the existing workflow.
    try:
        await run_demo_workflow(return_id)

        return {
            "success": True,
            "message": "Return workflow completed successfully.",
            "return_id": return_id,
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while running the workflow.",
        )



# =====================================================================
# FULL-STACK EXTENSIONS: CHATBOT, ORDERS, REFUNDS, & AUTO-CREDIT
# =====================================================================

from conversation import ConversationSession
from order_search import load_orders
from database.return_service import utc_now, log_event

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    customer_id: str = "CUS-001"

SESSIONS: dict[str, ConversationSession] = {}

def get_or_create_session(session_id: str, customer_id: str = "CUS-001") -> ConversationSession:
    if session_id not in SESSIONS:
        orders = load_orders(customer_id=customer_id)
        SESSIONS[session_id] = ConversationSession(
            orders=orders,
            customer_id=customer_id,
        )
    return SESSIONS[session_id]

@app.post("/api/reset-all")
def reset_all_returns_and_refunds():
    """
    Cleans all returned items, pickups, refunds, and tracking checkpoints
    so starting localhost or resetting from start gives a fresh store state.
    """
    with get_db() as conn:
        for tbl in ["pickup_attempts", "refund_attempts", "return_events", "monitoring_checkpoints", "refunds", "pickups", "returns"]:
            try:
                conn.execute(f"DELETE FROM {tbl}")
            except Exception:
                pass
    try:
        Path("bookings.json").write_text("[]", encoding="utf-8")
    except Exception:
        pass
    try:
        from database.date_sync import sync_delivery_dates
        sync_delivery_dates()
    except Exception:
        pass
    SESSIONS.clear()
    return {"status": "ok", "message": "All returns, refunds, and sessions reset to clean state."}


async def schedule_refund_auto_credit(return_id: str, step_seconds: float = 5.0):
    """
    Every 5 seconds, progress through the 5 steps:
    t=0s: Step 1 (Requested / Approved)
    t=5s: Step 2 (Pickup Booked: status = 'PICKED_UP')
    t=10s: Step 3 (Quality Check: status = 'RECEIVED')
    t=15s: Step 4 (Refund Initiated: status = 'INITIATED')
    t=20s: Step 5 (Bank Credited: status = 'CREDITED', Return status = 'COMPLETED')
    Total time: 20 seconds before credit notification.
    """
    try:
        # Step 1 -> 2: Wait 5 seconds, Courier picks up item
        await asyncio.sleep(step_seconds)
        with get_db() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE pickups
                SET status = 'PICKED_UP', picked_up_at = ?
                WHERE return_id = ? AND status = 'SCHEDULED'
                """,
                (now, return_id),
            )
            log_event(conn, return_id, "PICKUP", "Courier collected package from customer", "SCHEDULED", "PICKED_UP")
        print(f"[Auto-Workflow] Return {return_id} -> Step 2: Pickup Booked / Collected (t=5s)")

        # Step 2 -> 3: Wait 5 seconds (t=10s), Warehouse receives item
        await asyncio.sleep(step_seconds)
        with get_db() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE pickups
                SET status = 'RECEIVED', received_at = ?
                WHERE return_id = ? AND status = 'PICKED_UP'
                """,
                (now, return_id),
            )
            log_event(conn, return_id, "PICKUP", "Package arrived at store warehouse and verified", "PICKED_UP", "RECEIVED")
        print(f"[Auto-Workflow] Return {return_id} -> Step 3: Quality Check / Received (t=10s)")

        # Step 3 -> 4: Wait 5 seconds (t=15s), Refund initiated
        await asyncio.sleep(step_seconds)
        with get_db() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE refunds
                SET status = 'INITIATED', initiated_at = ?
                WHERE return_id = ? AND status = 'PENDING'
                """,
                (now, return_id),
            )
            log_event(conn, return_id, "REFUND", "Refund initiated via payment gateway", "PENDING", "INITIATED")
        print(f"[Auto-Workflow] Return {return_id} -> Step 4: Refund Initiated (t=15s)")

        # Step 4 -> 5: Wait 5 seconds (t=20s), Bank credited and Return completed
        await asyncio.sleep(step_seconds)
        with get_db() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE refunds
                SET status = 'CREDITED', credited_at = ?
                WHERE return_id = ? AND status IN ('PENDING', 'INITIATED')
                """,
                (now, return_id),
            )
            log_event(conn, return_id, "REFUND", "Refund credited successfully to customer account", "INITIATED", "CREDITED")

            conn.execute(
                """
                UPDATE returns
                SET status = 'COMPLETED', completed_at = ?
                WHERE return_id = ? AND status = 'APPROVED'
                """,
                (now, return_id),
            )
            log_event(conn, return_id, "RETURN", "Return workflow fully completed and refund credited", "APPROVED", "COMPLETED")

        print(f"[Auto-Workflow] Return {return_id} -> Step 5: Bank Credited & COMPLETED at t=20s!")
    except Exception as exc:
        print(f"[Auto-Workflow Error] Error in schedule_refund_auto_credit for {return_id}: {exc}")

@app.post("/api/chat")
async def api_chat(request: ChatRequest):
    session = get_or_create_session(request.session_id, request.customer_id)
    reply_text = session.handle_turn(request.message)

    # Format visual items for the UI if currently selecting an order
    visual_items = []
    if session.state == "SELECTING_ORDER" and session.candidate_orders:
        for idx, o in enumerate(session.candidate_orders, start=1):
            visual_items.append({
                "index": idx,
                "order_id": o.get("order_id"),
                "order_item_id": o.get("order_item_id"),
                "product_name": o.get("product_name"),
                "brand": o.get("brand"),
                "category": o.get("category"),
                "price": o.get("price"),
                "delivery_date": o.get("delivery_date"),
                "policy_tag": o.get("policy_tag"),
                "return_window_days": o.get("return_window_days"),
                "is_returnable": o.get("is_returnable"),
            })

    # Options / Quick replies based on state
    options = []
    if session.state == "AWAITING_REASON":
        options = [
            {"label": "👟 Too Small / Size Issue", "value": "1"},
            {"label": "⚠️ Defective / Damaged", "value": "2"},
            {"label": "🔍 Quality Issue", "value": "3"},
            {"label": "💬 Other Reason", "value": "4"},
        ]
    elif session.state == "AWAITING_REFUND_METHOD":
        options = [
            {"label": "💳 Bank Card (Original Method)", "value": "1"},
            {"label": "🏷️ Store Credit (Instant Balance)", "value": "2"},
        ]
    elif session.state == "AWAITING_APPROVAL":
        options = [
            {"label": "✅ Confirm Return", "value": "YES"},
            {"label": "❌ Cancel", "value": "NO"},
        ]

    # Check if return was created in this turn
    return_created = getattr(session, "last_created_return", None)
    if return_created:
        session.last_created_return = None
        # Trigger 5-second-per-step auto progression (total 20s)
        asyncio.create_task(schedule_refund_auto_credit(return_created["return_id"], step_seconds=5.0))

    return {
        "text": reply_text,
        "state": session.state,
        "visual_items": visual_items,
        "options": options,
        "return_created": return_created,
        "source": "live",
    }

@app.get("/api/orders")
def get_orders_list(customer_id: str = "CUS-001"):
    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT
                o.order_id,
                o.order_date,
                o.delivery_date,
                o.status AS order_status,
                o.payment_method,
                oi.order_item_id,
                oi.quantity,
                oi.unit_price_paise,
                p.product_id,
                p.name AS product_name,
                p.brand,
                p.category,
                p.return_window_days,
                p.is_returnable,
                r.return_id,
                r.status AS return_status,
                rf.status AS refund_status
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            LEFT JOIN returns r ON r.order_item_id = oi.order_item_id
            LEFT JOIN refunds rf ON rf.return_id = r.return_id
            WHERE o.customer_id = ?
            ORDER BY o.delivery_date DESC, o.order_date DESC
            """,
            (customer_id,),
        ).fetchall()

    orders_by_id = {}
    for row in rows:
        oid = row["order_id"]
        if oid not in orders_by_id:
            orders_by_id[oid] = {
                "order_id": oid,
                "order_date": row["order_date"],
                "delivery_date": row["delivery_date"],
                "status": row["order_status"],
                "payment_method": row["payment_method"],
                "items": [],
            }
        orders_by_id[oid]["items"].append({
            "order_item_id": row["order_item_id"],
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "brand": row["brand"],
            "category": row["category"],
            "quantity": row["quantity"],
            "unit_price_paise": row["unit_price_paise"],
            "price": round((row["unit_price_paise"] or 0) / 100, 2),
            "return_window_days": row["return_window_days"],
            "is_returnable": bool(row["is_returnable"]),
            "return_id": row["return_id"],
            "return_status": row["return_status"],
            "refund_status": row["refund_status"],
        })

    return {
        "customer_id": customer_id,
        "orders": list(orders_by_id.values()),
    }

@app.get("/api/refunds")
def get_refunds_list(customer_id: str = "CUS-001"):
    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT
                r.return_id,
                r.order_item_id,
                r.quantity,
                r.reason,
                r.status AS return_status,
                r.requested_at,
                r.approved_at,
                r.completed_at,
                oi.order_id,
                p.name AS product_name,
                p.brand,
                p.category,
                pk.pickup_id,
                pk.status AS pickup_status,
                pk.scheduled_at,
                pk.picked_up_at,
                pk.received_at,
                rf.refund_id,
                rf.amount_paise,
                rf.method AS refund_method,
                rf.status AS refund_status,
                rf.initiated_at,
                rf.credited_at
            FROM returns r
            JOIN order_items oi ON oi.order_item_id = r.order_item_id
            JOIN orders o ON o.order_id = oi.order_id
            JOIN products p ON p.product_id = oi.product_id
            LEFT JOIN pickups pk ON pk.return_id = r.return_id
            LEFT JOIN refunds rf ON rf.return_id = r.return_id
            WHERE o.customer_id = ?
            ORDER BY r.requested_at DESC
            """,
            (customer_id,),
        ).fetchall()

    refunds = []
    for row in rows:
        ref_status = row["refund_status"]
        ret_status = row["return_status"]
        pk_status = row["pickup_status"]

        if ref_status == "CREDITED" or ret_status == "COMPLETED":
            step = 5
        elif ref_status == "INITIATED":
            step = 4
        elif pk_status == "RECEIVED":
            step = 3
        elif pk_status == "PICKED_UP":
            step = 2
        else:
            step = 1

        refunds.append({
            "return_id": row["return_id"],
            "order_id": row["order_id"],
            "order_item_id": row["order_item_id"],
            "product_name": row["product_name"],
            "brand": row["brand"],
            "category": row["category"],
            "quantity": row["quantity"],
            "reason": row["reason"],
            "status": ret_status,
            "requested_at": row["requested_at"],
            "approved_at": row["approved_at"],
            "completed_at": row["completed_at"],
            "pickup": {
                "pickup_id": row["pickup_id"],
                "status": pk_status,
                "scheduled_at": row["scheduled_at"],
                "picked_up_at": row["picked_up_at"],
                "received_at": row["received_at"],
            } if row["pickup_id"] else None,
            "refund": {
                "refund_id": row["refund_id"],
                "amount_paise": row["amount_paise"],
                "amount": round((row["amount_paise"] or 0) / 100, 2),
                "method": row["refund_method"],
                "status": ref_status,
                "initiated_at": row["initiated_at"],
                "credited_at": row["credited_at"],
            } if row["refund_id"] else None,
            "step": step,
        })

    return {
        "customer_id": customer_id,
        "refunds": refunds,
    }

# =====================================================================
# STATIC ASSETS & SINGLE-PAGE APPLICATION SERVING
# =====================================================================

frontend_dist = Path(__file__).resolve().parent / "frontend" / "dist"
assets_path = frontend_dist / "assets"
if assets_path.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

@app.get("/")
@app.get("/{full_path:path}")
def serve_spa(full_path: str = ""):
    if full_path.startswith("api/") or full_path in {"health", "docs", "openapi.json"}:
        raise HTTPException(status_code=404, detail="API route not found")
    target = frontend_dist / full_path
    if full_path and target.exists() and target.is_file():
        return FileResponse(target)
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "Frontend not built yet. Run npm run build in frontend directory."}
