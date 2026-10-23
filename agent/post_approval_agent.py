import json

from database.db import get_db
from .llm_client import chat

import asyncio
import time

from datetime import datetime, timezone

def inspect_return(return_id: str) -> dict:
    """
    Read the current state of an approved return.

    This function does not modify the database or initiate
    any pickup or refund operations.
    """

    if not isinstance(return_id, str) or not return_id.strip():
        raise ValueError("A valid return ID is required.")

    with get_db() as connection:

        # Retrieve the return and its associated order item.
        return_row = connection.execute(
            """
            SELECT
                r.return_id,
                r.status AS return_status,
                r.requested_at,
                r.approved_at,
                r.completed_at,
                r.quantity AS return_quantity,
                r.reason,
                oi.order_item_id,
                o.customer_id,
                p.name AS product_name
            FROM returns r
            JOIN order_items oi
                ON oi.order_item_id = r.order_item_id
            JOIN orders o
                ON o.order_id = oi.order_id
            JOIN products p
                ON p.product_id = oi.product_id
            WHERE r.return_id = ?
            """,
            (return_id,),
        ).fetchone()

        if return_row is None:
            raise ValueError(f"Return not found: {return_id}")

        # Retrieve the latest pickup record.
        pickup_row = connection.execute(
            """
            SELECT
                pickup_id,
                status,
                scheduled_at,
                picked_up_at,
                received_at,
                failure_reason
            FROM pickups
            WHERE return_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (return_id,),
        ).fetchone()

        # Retrieve the associated refund record.
        refund_row = connection.execute(
            """
            SELECT
                refund_id,
                amount_paise,
                method,
                status,
                initiated_at,
                credited_at,
                failure_reason
            FROM refunds
            WHERE return_id = ?
            LIMIT 1
            """,
            (return_id,),
        ).fetchone()

        # Retrieve recent events for context.
        event_rows = connection.execute(
            """
            SELECT
                event_type,
                from_status,
                to_status,
                description,
                created_at
            FROM return_events
            WHERE return_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (return_id,),
        ).fetchall()

        return {
            "return": dict(return_row),
            "pickup": dict(pickup_row) if pickup_row else None,
            "refund": dict(refund_row) if refund_row else None,
            "recent_events": [
                dict(event) for event in event_rows
            ],
        }

def assess_return_status(return_state: object) -> dict:
    """
    Assess a return's current workflow state and recommend
    the next permitted action.

    This function is read-only. It does not change statuses,
    initiate refunds, or claim that external actions occurred.
    """

    if not isinstance(return_state, dict):
        raise ValueError("Return state must be a dictionary.")

    return_info = return_state.get("return")
    pickup = return_state.get("pickup")
    refund = return_state.get("refund")

    if not isinstance(return_info, dict):
        raise ValueError("Return information is missing.")

    return_status = return_info.get("return_status")

    if not return_status:
        raise ValueError("Return status is missing.")

    def assessment(stage, next_action, reason, attention=False):
        return {
            "return_id": return_info.get("return_id"),
            "stage": stage,
            "next_action": next_action,
            "requires_attention": attention,
            "reason": reason,
        }

    # This component only handles returns after approval.
    if return_status not in {"APPROVED", "COMPLETED"}:
        return assessment(
            "NOT_READY",
            "WAIT_FOR_RETURN_APPROVAL",
            f"Return status is {return_status}; approval is required.",
        )

    # A completed return must have consistent final statuses.
    if return_status == "COMPLETED":
        if (
            isinstance(pickup, dict)
            and pickup.get("status") == "RECEIVED"
            and isinstance(refund, dict)
            and refund.get("status") == "CREDITED"
        ):
            return assessment(
                "COMPLETED",
                "NONE",
                "The database records the item as received and "
                "the refund as credited. No further workflow "
                "action is required.",
            )

        return assessment(
            "NEEDS_ATTENTION",
            "REVIEW_INCONSISTENT_COMPLETED_RETURN",
            "The return is marked COMPLETED, but the pickup or "
            "refund status does not match the expected final state.",
            attention=True,
        )

    # An approved return must have pickup and refund records.
    if not isinstance(pickup, dict) or not isinstance(refund, dict):
        return assessment(
            "NEEDS_ATTENTION",
            "REVIEW_MISSING_RECORDS",
            "The approved return is missing its pickup or refund record.",
            attention=True,
        )

    pickup_status = pickup.get("status")
    refund_status = refund.get("status")

    # Failures require investigation instead of automatic progression.
    if pickup_status in {"FAILED", "CANCELLED"}:
        return assessment(
            "NEEDS_ATTENTION",
            "INVESTIGATE_PICKUP",
            f"Pickup status is {pickup_status}.",
            attention=True,
        )

    if refund_status == "FAILED":
        return assessment(
            "NEEDS_ATTENTION",
            "INVESTIGATE_REFUND",
            "The refund is marked FAILED.",
            attention=True,
        )

    # Pickup has not yet occurred.
    if pickup_status == "SCHEDULED":
        if refund_status != "PENDING":
            return assessment(
                "NEEDS_ATTENTION",
                "REVIEW_INCONSISTENT_STATUSES",
                "The refund status is inconsistent with a pickup "
                "that has not occurred.",
                attention=True,
            )

        return assessment(
            "PICKUP_PENDING",
            "MONITOR_PICKUP",
            "The pickup is scheduled. Check for a subsequent "
            "pickup status update.",
        )

    # The item was collected but has not reached the warehouse.
    if pickup_status == "PICKED_UP":
        if refund_status != "PENDING":
            return assessment(
                "NEEDS_ATTENTION",
                "REVIEW_INCONSISTENT_STATUSES",
                "The refund progressed before the item was recorded "
                "as received at the warehouse.",
                attention=True,
            )

        return assessment(
            "AWAITING_WAREHOUSE_RECEIPT",
            "MONITOR_WAREHOUSE_RECEIPT",
            "The item was picked up. Wait for warehouse receipt.",
        )

    # The warehouse has received the item.
    if pickup_status == "RECEIVED":
        if refund_status == "PENDING":
            return assessment(
                "REFUND_READY",
                "INITIATE_REFUND",
                "The item is recorded as received, and the refund "
                "is still pending.",
            )

        if refund_status == "INITIATED":
            return assessment(
                "REFUND_IN_PROGRESS",
                "MONITOR_REFUND_CREDIT",
                "The refund has been initiated. Wait for reliable "
                "confirmation of credit.",
            )

        if refund_status == "CREDITED":
            return assessment(
                "READY_TO_FINALIZE",
                "REVIEW_RETURN_COMPLETION",
                "The refund is recorded as credited, but the return "
                "has not yet been marked COMPLETED.",
            )

    return assessment(
        "NEEDS_ATTENTION",
        "INVESTIGATE_UNKNOWN_STATE",
        f"Unexpected pickup/refund status combination: "
        f"{pickup_status}/{refund_status}.",
        attention=True,
    )

def assess_stage_delay(
    return_state: object,
    *,
    pickup_sla_seconds: float,
    warehouse_sla_seconds: float,
    refund_initiation_sla_seconds: float,
    refund_credit_sla_seconds: float,
    now: datetime | None = None,
) -> dict:
    """
    Check whether the current post-approval stage has exceeded
    its configured time limit.

    This function is read-only. It does not change statuses,
    initiate refunds, or contact external providers.
    """

    if not isinstance(return_state, dict):
        raise ValueError("Return state must be a dictionary.")

    thresholds = {
        "pickup": pickup_sla_seconds,
        "warehouse": warehouse_sla_seconds,
        "refund initiation": refund_initiation_sla_seconds,
        "refund credit": refund_credit_sla_seconds,
    }

    for name, value in thresholds.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value <= 0
        ):
            raise ValueError(
                f"The {name} time limit must be a positive number."
            )

    return_info = return_state.get("return")
    pickup = return_state.get("pickup")
    refund = return_state.get("refund")

    if not isinstance(return_info, dict):
        raise ValueError("Return information is missing.")

    return_id = return_info.get("return_id")
    return_status = return_info.get("return_status")

    if return_status == "COMPLETED":
        return {
            "return_id": return_id,
            "stage": "COMPLETED",
            "delayed": False,
            "requires_attention": False,
            "reason": "The return is already completed.",
        }

    if return_status != "APPROVED":
        return {
            "return_id": return_id,
            "stage": "NOT_READY",
            "delayed": False,
            "requires_attention": False,
            "reason": "The return has not been approved.",
        }

    if not isinstance(pickup, dict) or not isinstance(refund, dict):
        return {
            "return_id": return_id,
            "stage": "NEEDS_ATTENTION",
            "delayed": False,
            "requires_attention": True,
            "reason": "The approved return is missing pickup or refund data.",
        }

    pickup_status = pickup.get("status")
    refund_status = refund.get("status")

    # Select the timestamp and threshold for the current stage.
    if pickup_status == "SCHEDULED" and refund_status == "PENDING":
        stage = "PICKUP_PENDING"
        timestamp = pickup.get("scheduled_at")
        threshold = pickup_sla_seconds
        label = "Pickup"

    elif pickup_status == "PICKED_UP" and refund_status == "PENDING":
        stage = "WAREHOUSE_RECEIPT_PENDING"
        timestamp = pickup.get("picked_up_at")
        threshold = warehouse_sla_seconds
        label = "Warehouse receipt"

    elif pickup_status == "RECEIVED" and refund_status == "PENDING":
        stage = "REFUND_INITIATION_PENDING"
        timestamp = pickup.get("received_at")
        threshold = refund_initiation_sla_seconds
        label = "Refund initiation"

    elif pickup_status == "RECEIVED" and refund_status == "INITIATED":
        stage = "REFUND_CREDIT_PENDING"
        timestamp = refund.get("initiated_at")
        threshold = refund_credit_sla_seconds
        label = "Refund credit"

    elif pickup_status == "RECEIVED" and refund_status == "CREDITED":
        return {
            "return_id": return_id,
            "stage": "READY_TO_FINALIZE",
            "delayed": False,
            "requires_attention": True,
            "reason": (
                "The refund is recorded as credited, but the return "
                "is still APPROVED. Review return completion."
            ),
        }

    elif pickup_status in {"FAILED", "CANCELLED"}:
        return {
            "return_id": return_id,
            "stage": "NEEDS_ATTENTION",
            "delayed": False,
            "requires_attention": True,
            "reason": f"Pickup status is {pickup_status}.",
        }

    elif refund_status == "FAILED":
        return {
            "return_id": return_id,
            "stage": "NEEDS_ATTENTION",
            "delayed": False,
            "requires_attention": True,
            "reason": "The refund is marked FAILED.",
        }

    else:
        return {
            "return_id": return_id,
            "stage": "NEEDS_ATTENTION",
            "delayed": False,
            "requires_attention": True,
            "reason": (
                f"Unexpected status combination: "
                f"{pickup_status}/{refund_status}."
            ),
        }

    # A timestamp is required to calculate how long the stage has lasted.
    if not timestamp:
        return {
            "return_id": return_id,
            "stage": stage,
            "delayed": False,
            "requires_attention": True,
            "reason": f"The timestamp for {label.lower()} is missing.",
            "timestamp_uncertain": True,
            "next_action": "INVESTIGATE_MISSING_TIMESTAMP",
        }

    try:
        started_at = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return {
            "return_id": return_id,
            "stage": stage,
            "delayed": False,
            "requires_attention": True,
            "reason": f"The timestamp for {label.lower()} is invalid.",
            "timestamp_uncertain": True,
            "next_action": "INVESTIGATE_INVALID_TIMESTAMP",
        }

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    current_time = now or datetime.now(timezone.utc)

    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    elapsed_seconds = max(
        0.0,
        (current_time - started_at).total_seconds(),
    )

    delayed = elapsed_seconds > threshold

    return {
        "return_id": return_id,
        "stage": stage,
        "delayed": delayed,
        "requires_attention": delayed,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "threshold_seconds": threshold,
        "reason": (
            f"{label} has exceeded its configured time limit."
            if delayed
            else f"{label} is within its configured time limit."
        ),
    }

def explain_assessment(return_state: object, assessment: object) -> str:
    """
    Use Qwen to explain the current post-approval situation.

    Python's assessment remains authoritative.
    The LLM cannot modify database records or choose a
    different workflow action.
    """

    if not isinstance(return_state, dict):
        raise ValueError("Return state must be a dictionary.")

    if not isinstance(assessment, dict):
        raise ValueError("Assessment must be a dictionary.")

    return_info = return_state.get("return", {})
    pickup = return_state.get("pickup") or {}
    refund = return_state.get("refund") or {}

    # Pass only the information needed to explain the situation.
    facts = {
        "return_id": return_info.get("return_id"),
        "return_status": return_info.get("return_status"),
        "pickup_status": pickup.get("status"),
        "pickup_failure_reason": pickup.get("failure_reason"),
        "refund_status": refund.get("status"),
        "refund_failure_reason": refund.get("failure_reason"),
        "assessment": assessment,
    }

    prompt = f"""
You are an operations assistant for a return and refund
tracking system.

Your task is to explain the current operational situation
using the supplied facts.

FACTS:
{json.dumps(facts, ensure_ascii=False)}

RULES:

1. Treat the supplied Python assessment as authoritative.
   Do not change its stage, next_action, or attention flag.

2. Use only the supplied facts. Do not invent events, causes,
   evidence, or expected completion times.

3. A refund with status INITIATED is not necessarily credited.

4. A refund with status CREDITED is recorded as credited in
   this system. Do not claim that you independently verified
   a bank transaction or contacted a payment provider.

5. If the refund or pickup has FAILED, explain that the
   problem requires investigation. Do not invent a cause,
   retry the operation, or promise a resolution time.

6. If the workflow is already completed, explain that no
   further workflow action is required.

7. Keep the explanation concise: 1 to 3 sentences.

8. Return plain text only. Do not return JSON or Markdown.
"""

    explanation = chat(prompt).strip()
    explanation_lower = explanation.casefold()
    next_action = assessment.get("next_action")
    stage = assessment.get("stage")

    # Flag unsupported timing predictions.
    unsupported_timing_phrases = (
        "shortly",
        "soon",
        "expect confirmation",
        "within an hour",
        "within a day",
        "by tomorrow",
        "in a few minutes",
    )

    has_unsupported_timing = any(
        phrase in explanation_lower
        for phrase in unsupported_timing_phrases
    )

    # An explanation must not claim no action is needed when
    # Python has recommended a further action.
    no_action_phrases = (
        "no further action is required",
        "no further action is needed",
        "no action is required",
        "no action is needed",
        "nothing else is needed",
    )

    contradicts_next_action = (
        next_action != "NONE"
        and any(
            phrase in explanation_lower
            for phrase in no_action_phrases
        )
    )

    # Use a deterministic explanation if the model makes
    # either of these unsupported claims.
    if has_unsupported_timing or contradicts_next_action:
        safe_explanations = {
            "PICKUP_PENDING": (
                "The pickup is scheduled. Its completion has not "
                "yet been recorded. The next action is to monitor "
                "pickup status."
            ),
            "AWAITING_WAREHOUSE_RECEIPT": (
                "The item is recorded as picked up. Warehouse "
                "receipt has not yet been recorded. The next action "
                "is to monitor warehouse receipt."
            ),
            "REFUND_READY": (
                "The item is recorded as received, and the refund "
                "is pending. The next action is to initiate the refund."
            ),
            "REFUND_IN_PROGRESS": (
                "The refund is recorded as initiated, but credit "
                "has not yet been recorded. The next action is to "
                "monitor for a status update."
            ),
            "COMPLETED": (
                "The database records the return as completed and "
                "the refund as credited. No further workflow action "
                "is required."
            ),
            "NEEDS_ATTENTION": (
                f"The return requires attention. {assessment.get('reason')} "
                f"Next action: {next_action}."
            ),
            "READY_TO_FINALIZE": (
                "The refund is recorded as credited, but the return "
                "is not yet completed. The next action is to review "
                "return completion."
            ),
        }

        explanation = safe_explanations.get(
            stage,
            f"{assessment.get('reason')} Next action: {next_action}.",
        )
    if not explanation:
        raise RuntimeError(
            "The AI model returned an empty explanation."
        )

    return explanation

async def monitor_return(
    return_id: str,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: float = 30.0,
    pickup_sla_seconds: float = 60.0,
    warehouse_sla_seconds: float = 120.0,
    refund_initiation_sla_seconds: float = 60.0,
    refund_credit_sla_seconds: float = 300.0,
) -> dict:
    """
    Monitor an approved return by periodically checking the database.

    Stops when the return is completed, the assessment requires
    attention, or the monitoring timeout is reached.

    This function observes status changes but does not modify
    database records or initiate external operations.
    """

    if not isinstance(return_id, str) or not return_id.strip():
        raise ValueError("A valid return ID is required.")

    if poll_interval_seconds <= 0:
        raise ValueError("Polling interval must be positive.")

    if timeout_seconds <= 0:
        raise ValueError("Monitoring timeout must be positive.")

    deadline = time.monotonic() + timeout_seconds

    observations = []
    explanation_jobs = []
    detected_events = []
    last_event_id = 0
    previous_snapshot = None
    previous_delay_snapshot = None
    timed_out = False

    while True:
        # Read the latest state from the database.
        state = inspect_return(return_id)
        # Collect persisted events, including transitions that
        # occurred between polling cycles.
        new_events = get_return_events(
            return_id,
            after_event_id=last_event_id,
        )

        if new_events:
            detected_events.extend(new_events)
            last_event_id = new_events[-1]["event_id"]
        return_info = state["return"]
        return_status = return_info["return_status"]

        # This agent handles only approved or completed returns.
        if return_status not in {"APPROVED", "COMPLETED"}:
            raise ValueError(
                "Monitoring requires an APPROVED or COMPLETED return; "
                f"current status is {return_status}."
            )

        # Python determines the permitted next action.
        assessment = assess_return_status(state)

        delay_assessment = assess_stage_delay(
            state,
            pickup_sla_seconds=pickup_sla_seconds,
            warehouse_sla_seconds=warehouse_sla_seconds,
            refund_initiation_sla_seconds=refund_initiation_sla_seconds,
            refund_credit_sla_seconds=refund_credit_sla_seconds,
        )

        final_delay_assessment = delay_assessment

        # If a stage has exceeded its time limit or has an uncertain timestamp,
        # reflect that in the main assessment as well.
        if delay_assessment["delayed"]:
            assessment = {
                **assessment,
                "stage": "NEEDS_ATTENTION",
                "next_action": "ESCALATE_STAGE_DELAY",
                "requires_attention": True,
                "reason": delay_assessment["reason"],
            }
        elif delay_assessment.get("timestamp_uncertain"):
            assessment = {
                **assessment,
                "stage": "NEEDS_ATTENTION",
                "next_action": delay_assessment.get("next_action", "REVIEW_POST_APPROVAL_STATE"),
                "requires_attention": True,
                "reason": delay_assessment["reason"],
            }
        elif delay_assessment["requires_attention"]:
            assessment = {
                **assessment,
                "stage": "NEEDS_ATTENTION",
                "next_action": "REVIEW_POST_APPROVAL_STATE",
                "requires_attention": True,
                "reason": delay_assessment["reason"],
            }

        final_assessment = assessment

        pickup = state.get("pickup") or {}
        refund = state.get("refund") or {}

        # Track meaningful status changes, not every polling cycle.
        snapshot = (
            return_status,
            pickup.get("status"),
            refund.get("status"),
        )
        delay_snapshot = (
            delay_assessment["stage"],
            delay_assessment["delayed"],
            delay_assessment["requires_attention"],
        )
        if (
                snapshot != previous_snapshot
                or delay_snapshot != previous_delay_snapshot
        ):
            observation = {
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "return_status": return_status,
                "pickup_status": pickup.get("status"),
                "refund_status": refund.get("status"),
                "assessment": assessment,
                "stage_delay": delay_assessment,
                "explanation": None,
            }

            # Record the observation immediately.
            # Do not wait for Qwen to finish.
            observations.append(observation)

            # Save the state for explanation after monitoring.
            explanation_jobs.append(
                (observation, state, assessment)
            )

            previous_snapshot = snapshot
            previous_delay_snapshot = delay_snapshot
        # Stop when the workflow is complete or needs attention.
        if (
                assessment["stage"] == "COMPLETED"
                or assessment["requires_attention"]
                or delay_assessment["requires_attention"]
        ):
            break

        remaining = deadline - time.monotonic()

        if remaining <= 0:
            timed_out = True
            break

        await asyncio.sleep(
            min(poll_interval_seconds, remaining)
        )
    # Generate explanations after monitoring has stopped.
    for observation, observed_state, observed_assessment in explanation_jobs:
        stage_delay = observation["stage_delay"]

        # Explain delay alerts deterministically rather than allowing
        # the model to minimize or contradict a detected delay.
        if stage_delay["requires_attention"]:
            explanation = stage_delay["reason"]

            if stage_delay["delayed"]:
                explanation += (
                    f" Elapsed time: "
                    f"{stage_delay['elapsed_seconds']} seconds; "
                    f"configured limit: "
                    f"{stage_delay['threshold_seconds']} seconds."
                )

            observation["explanation"] = explanation
            continue

        try:
            observation["explanation"] = await asyncio.to_thread(
                explain_assessment,
                observed_state,
                observed_assessment,
            )
        except RuntimeError:
            observation["explanation"] = None

    return {
        "return_id": return_id,
        "timed_out": timed_out,
        "final_assessment": final_assessment,
        "final_delay_assessment": final_delay_assessment,
        "observations": observations,
        "events": detected_events,
        "last_event_id": last_event_id,
    }

def get_return_events(
    return_id: str,
    after_event_id: int = 0,
) -> list[dict]:
    """
    Retrieve persisted events for a return in chronological order.

    By default, return the complete event history.
    If after_event_id is supplied, return only newer events.

    This function is read-only.
    """

    if not isinstance(return_id, str) or not return_id.strip():
        raise ValueError("A valid return ID is required.")

    if (
        isinstance(after_event_id, bool)
        or not isinstance(after_event_id, int)
        or after_event_id < 0
    ):
        raise ValueError("after_event_id must be a non-negative integer.")

    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT
                event_id,
                event_type,
                from_status,
                to_status,
                description,
                created_at
            FROM return_events
            WHERE return_id = ?
              AND event_id > ?
            ORDER BY event_id ASC
            """,
            (return_id, after_event_id),
        ).fetchall()

    return [dict(row) for row in rows]

def list_monitored_returns() -> list[str]:
    """
    Return the IDs of all returns that may need post-approval monitoring.
    This includes both APPROVED returns and COMPLETED returns that may
    have inconsistent final statuses.

    This function is read-only.
    """

    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT return_id
            FROM returns
            WHERE status IN ('APPROVED', 'COMPLETED')
            ORDER BY return_id
            """
        ).fetchall()

    return [row["return_id"] for row in rows]

def list_approved_returns() -> list[str]:
    """
    Return the IDs of all returns that currently have status APPROVED.
    """

    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT return_id
            FROM returns
            WHERE status = 'APPROVED'
            ORDER BY return_id
            """
        ).fetchall()

    return [row["return_id"] for row in rows]

def scan_approved_returns(
    pickup_sla_seconds: float = 60.0,
    warehouse_sla_seconds: float = 120.0,
    refund_initiation_sla_seconds: float = 60.0,
    refund_credit_sla_seconds: float = 300.0,
) -> list[dict]:
    """
    Inspect all currently approved returns and assess their status
    and stage delays.

    This function performs one read-only scan. It does not start
    workflows, modify records, or initiate refunds.
    """

    results = []

    return_ids = list_monitored_returns()

    for return_id in return_ids:
        state = inspect_return(return_id)

        assessment = assess_return_status(state)

        delay = assess_stage_delay(
            state,
            pickup_sla_seconds=pickup_sla_seconds,
            warehouse_sla_seconds=warehouse_sla_seconds,
            refund_initiation_sla_seconds=refund_initiation_sla_seconds,
            refund_credit_sla_seconds=refund_credit_sla_seconds,
        )

        # Reflect delays or uncertain timestamps in the main assessment.
        if delay["delayed"]:
            assessment = {
                **assessment,
                "stage": "NEEDS_ATTENTION",
                "next_action": "ESCALATE_STAGE_DELAY",
                "requires_attention": True,
                "reason": delay["reason"],
            }
        elif delay.get("timestamp_uncertain"):
            assessment = {
                **assessment,
                "stage": "NEEDS_ATTENTION",
                "next_action": delay.get("next_action", "REVIEW_POST_APPROVAL_STATE"),
                "requires_attention": True,
                "reason": delay["reason"],
            }
        elif delay["requires_attention"]:
            assessment = {
                **assessment,
                "stage": "NEEDS_ATTENTION",
                "next_action": "REVIEW_POST_APPROVAL_STATE",
                "requires_attention": True,
                "reason": delay["reason"],
            }

        results.append({
            "return_id": return_id,
            "current_state": {
                "return_status": state["return"]["return_status"],
                "pickup_status": (
                    state["pickup"]["status"]
                    if state["pickup"] else None
                ),
                "refund_status": (
                    state["refund"]["status"]
                    if state["refund"] else None
                ),
            },
            "assessment": assessment,
            "stage_delay": delay,
        })

    return results