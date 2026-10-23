

from agent.post_approval_agent import (
    assess_return_status,
    assess_stage_delay,
    explain_assessment,
)


def make_return_state(
    return_status: str = "APPROVED",
    pickup_status: str | None = "SCHEDULED",
    refund_status: str | None = "PENDING",
) -> dict:
    """Build a return state without accessing the database."""

    return {
        "return": {
            "return_id": "RET-TEST-001",
            "return_status": return_status,
        },
        "pickup": (
            {"status": pickup_status}
            if pickup_status is not None
            else None
        ),
        "refund": (
            {"status": refund_status}
            if refund_status is not None
            else None
        ),
    }


def test_scheduled_pickup_requires_monitoring():
    state = make_return_state()

    result = assess_return_status(state)

    assert result["stage"] == "PICKUP_PENDING"
    assert result["next_action"] == "MONITOR_PICKUP"
    assert result["requires_attention"] is False


def test_picked_up_item_requires_warehouse_receipt():
    state = make_return_state(
        pickup_status="PICKED_UP",
        refund_status="PENDING",
    )

    result = assess_return_status(state)

    assert result["stage"] == "AWAITING_WAREHOUSE_RECEIPT"
    assert result["next_action"] == "MONITOR_WAREHOUSE_RECEIPT"


def test_received_item_with_pending_refund_is_ready_for_refund():
    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="PENDING",
    )

    result = assess_return_status(state)

    assert result["stage"] == "REFUND_READY"
    assert result["next_action"] == "INITIATE_REFUND"


def test_initiated_refund_is_not_treated_as_credited():
    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="INITIATED",
    )

    result = assess_return_status(state)

    assert result["stage"] == "REFUND_IN_PROGRESS"
    assert result["next_action"] == "MONITOR_REFUND_CREDIT"
    assert result["stage"] != "COMPLETED"
    assert result["requires_attention"] is False


def test_failed_pickup_requires_attention():
    state = make_return_state(
        pickup_status="FAILED",
        refund_status="PENDING",
    )

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "INVESTIGATE_PICKUP"
    assert result["requires_attention"] is True


def test_cancelled_pickup_requires_attention():
    state = make_return_state(
        pickup_status="CANCELLED",
        refund_status="PENDING",
    )

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "INVESTIGATE_PICKUP"


def test_failed_refund_requires_attention():
    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="FAILED",
    )

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "INVESTIGATE_REFUND"
    assert result["requires_attention"] is True


def test_missing_pickup_record_requires_attention():
    state = make_return_state(pickup_status=None)

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "REVIEW_MISSING_RECORDS"


def test_missing_refund_record_requires_attention():
    state = make_return_state(refund_status=None)

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "REVIEW_MISSING_RECORDS"


def test_completed_return_requires_consistent_final_statuses():
    state = make_return_state(
        return_status="COMPLETED",
        pickup_status="RECEIVED",
        refund_status="CREDITED",
    )

    result = assess_return_status(state)

    assert result["stage"] == "COMPLETED"
    assert result["next_action"] == "NONE"
    assert result["requires_attention"] is False


def test_completed_return_with_inconsistent_status_requires_attention():
    state = make_return_state(
        return_status="COMPLETED",
        pickup_status="RECEIVED",
        refund_status="INITIATED",
    )

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "REVIEW_INCONSISTENT_COMPLETED_RETURN"
    assert result["requires_attention"] is True


def test_unapproved_return_is_not_ready():
    state = make_return_state(
        return_status="REQUESTED",
    )

    result = assess_return_status(state)

    assert result["stage"] == "NOT_READY"
    assert result["next_action"] == "WAIT_FOR_RETURN_APPROVAL"


def test_unknown_status_combination_requires_attention():
    state = make_return_state(
        pickup_status="SCHEDULED",
        refund_status="INITIATED",
    )

    result = assess_return_status(state)

    assert result["stage"] == "NEEDS_ATTENTION"
    assert result["next_action"] == "REVIEW_INCONSISTENT_STATUSES"


from datetime import datetime, timedelta, timezone


def test_overdue_pickup_requires_attention():
    now = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)

    state = make_return_state()
    state["pickup"]["scheduled_at"] = (
        now - timedelta(seconds=61)
    ).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "PICKUP_PENDING"
    assert result["delayed"] is True
    assert result["requires_attention"] is True


def test_pickup_within_time_limit_does_not_require_attention():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    state = make_return_state()
    state["pickup"]["scheduled_at"] = (
        now - timedelta(seconds=30)
    ).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "PICKUP_PENDING"
    assert result["delayed"] is False
    assert result["requires_attention"] is False


def test_initiated_refund_is_not_reported_as_credited():
    now = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)

    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="INITIATED",
    )

    state["pickup"]["received_at"] = (
        now - timedelta(seconds=120)
    ).isoformat()

    state["refund"]["initiated_at"] = (
        now - timedelta(seconds=120)
    ).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "REFUND_CREDIT_PENDING"
    assert result["delayed"] is False
    assert result["requires_attention"] is False

def test_overdue_warehouse_receipt_requires_attention():
    now = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)

    state = make_return_state(
        pickup_status="PICKED_UP",
        refund_status="PENDING",
    )

    state["pickup"]["picked_up_at"] = (
        now - timedelta(seconds=121)
    ).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "WAREHOUSE_RECEIPT_PENDING"
    assert result["delayed"] is True
    assert result["requires_attention"] is True


def test_overdue_refund_initiation_requires_attention():
    now = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)

    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="PENDING",
    )

    state["pickup"]["received_at"] = (
        now - timedelta(seconds=61)
    ).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "REFUND_INITIATION_PENDING"
    assert result["delayed"] is True
    assert result["requires_attention"] is True


def test_overdue_refund_credit_requires_attention():
    now = datetime(2026, 1, 1, 12, 6, tzinfo=timezone.utc)

    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="INITIATED",
    )

    state["refund"]["initiated_at"] = (
        now - timedelta(seconds=301)
    ).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "REFUND_CREDIT_PENDING"
    assert result["delayed"] is True
    assert result["requires_attention"] is True

def test_explanation_rejects_unsupported_refund_promises(monkeypatch):
    # Simulate an LLM response containing unsupported promises.
    def fake_chat(prompt):
        return (
            "Your refund will arrive soon, by tomorrow, "
            "and no further action is required."
        )

    monkeypatch.setattr(
        "agent.post_approval_agent.chat",
        fake_chat,
    )

    state = make_return_state(
        pickup_status="RECEIVED",
        refund_status="INITIATED",
    )

    assessment = assess_return_status(state)

    explanation = explain_assessment(state, assessment)

    assert isinstance(explanation, str)

    explanation_lower = explanation.lower()

    assert "soon" not in explanation_lower
    assert "by tomorrow" not in explanation_lower
    assert "no further action is required" not in explanation_lower


# --- Phase 1 Regression Tests ---

def test_missing_timestamp_uncertainty():
    """Missing timestamp should yield explicit uncertainty and investigation action."""
    state = make_return_state(pickup_status="SCHEDULED", refund_status="PENDING")
    state["pickup"]["scheduled_at"] = None

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
    )

    assert result["requires_attention"] is True
    assert result["delayed"] is False
    assert result.get("timestamp_uncertain") is True
    assert result.get("next_action") == "INVESTIGATE_MISSING_TIMESTAMP"
    assert "missing" in result["reason"].lower()


def test_malformed_timestamp_uncertainty():
    """Malformed timestamp should not be parsed as delayed or completed, but as uncertain."""
    state = make_return_state(pickup_status="SCHEDULED", refund_status="PENDING")
    state["pickup"]["scheduled_at"] = "not-a-valid-iso-timestamp"

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
    )

    assert result["requires_attention"] is True
    assert result["delayed"] is False
    assert result.get("timestamp_uncertain") is True
    assert result.get("next_action") == "INVESTIGATE_INVALID_TIMESTAMP"
    assert "invalid" in result["reason"].lower()


def test_valid_timestamp_within_sla():
    """Valid timestamp within SLA must not be delayed or require attention."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    state = make_return_state(pickup_status="PICKED_UP", refund_status="PENDING")
    state["pickup"]["picked_up_at"] = (now - timedelta(seconds=30)).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "WAREHOUSE_RECEIPT_PENDING"
    assert result["delayed"] is False
    assert result["requires_attention"] is False
    assert result.get("timestamp_uncertain") is not True


def test_valid_timestamp_exceeding_sla():
    """Valid timestamp exceeding SLA must be marked delayed and require attention."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    state = make_return_state(pickup_status="PICKED_UP", refund_status="PENDING")
    state["pickup"]["picked_up_at"] = (now - timedelta(seconds=125)).isoformat()

    result = assess_stage_delay(
        state,
        pickup_sla_seconds=60,
        warehouse_sla_seconds=120,
        refund_initiation_sla_seconds=60,
        refund_credit_sla_seconds=300,
        now=now,
    )

    assert result["stage"] == "WAREHOUSE_RECEIPT_PENDING"
    assert result["delayed"] is True
    assert result["requires_attention"] is True
    assert result.get("timestamp_uncertain") is not True
