import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from database import db
from agent.background_worker import (
    scan_and_log_once,
    approved_return_worker,
    load_checkpoint,
    upsert_checkpoint,
)

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "schema.sql"

def _make_scan_result(return_id: str, stage: str, next_action: str, reason: str, attention: bool = True):
    return {
        "return_id": return_id,
        "current_state": {
            "return_status": "APPROVED",
            "pickup_status": "SCHEDULED",
            "refund_status": "PENDING",
        },
        "assessment": {
            "return_id": return_id,
            "stage": stage,
            "next_action": next_action,
            "requires_attention": attention,
            "reason": reason,
        },
        "stage_delay": {
            "return_id": return_id,
            "stage": stage,
            "delayed": False,
            "requires_attention": attention,
            "reason": reason,
        }
    }

@pytest.fixture(autouse=True)
def isolated_worker_db():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db_path = Path(temp_dir) / "test_worker.db"
        with patch.object(db, "DB_PATH", temp_db_path), \
             patch.object(db, "SCHEMA_PATH", SCHEMA_FILE):
            db.init_db()
            with db.get_db() as conn:
                conn.execute(
                    "INSERT INTO customers (customer_id, name, created_at) VALUES ('CUS-1', 'Cust', '2026-01-01T00:00:00Z')"
                )
                conn.execute(
                    "INSERT INTO products (product_id, name, brand, category, aliases, return_window_days, is_returnable) VALUES ('P1', 'Shoe', 'B', 'C', '[]', 30, 1)"
                )
                conn.execute(
                    "INSERT INTO orders (order_id, customer_id, order_date, delivery_date, status, payment_method, created_at) VALUES ('O1', 'CUS-1', '2026-01-01T00:00:00Z', '2026-01-01T12:00:00Z', 'DELIVERED', 'UPI', '2026-01-01T00:00:00Z')"
                )
                conn.execute(
                    "INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price_paise) VALUES ('OI-1', 'O1', 'P1', 1, 1000)"
                )
                conn.execute(
                    "INSERT INTO returns (return_id, order_item_id, status, quantity, reason, requested_at, approved_at) VALUES ('RET-1', 'OI-1', 'APPROVED', 1, 'DEFECTIVE', '2026-01-02T00:00:00Z', '2026-01-02T01:00:00Z')"
                )
                conn.execute(
                    "INSERT INTO returns (return_id, order_item_id, status, quantity, reason, requested_at, approved_at) VALUES ('RET-2', 'OI-1', 'APPROVED', 1, 'DEFECTIVE', '2026-01-02T00:00:00Z', '2026-01-02T01:00:00Z')"
                )
            yield temp_db_path

def test_scan_and_log_once_initial_alert(caplog):
    signatures = {}
    mock_results = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup status is FAILED.", attention=True)
    ]
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=mock_results):
        results = asyncio.run(scan_and_log_once(signatures))
        
    assert len(results) == 1
    assert "RET-1" in caplog.text
    assert "INVESTIGATE_PICKUP" in caplog.text
    assert "RET-1" in signatures

def test_scan_and_log_once_suppress_duplicate_alert(caplog):
    signatures = {}
    mock_results = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup status is FAILED.", attention=True)
    ]
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=mock_results):
        asyncio.run(scan_and_log_once(signatures))
        caplog.clear()
        asyncio.run(scan_and_log_once(signatures))
        
    assert caplog.text == ""

def test_scan_and_log_once_alert_changes(caplog):
    signatures = {}
    result_1 = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup status is FAILED.", attention=True)
    ]
    result_2 = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "ESCALATE_STAGE_DELAY", "Pickup has exceeded SLA.", attention=True)
    ]
    with caplog.at_level("WARNING", logger="agent.background_worker"):
        with patch("agent.background_worker.scan_approved_returns", return_value=result_1):
            asyncio.run(scan_and_log_once(signatures))
            assert "INVESTIGATE_PICKUP" in caplog.text
            
        caplog.clear()
        with patch("agent.background_worker.scan_approved_returns", return_value=result_2):
            asyncio.run(scan_and_log_once(signatures))
            assert "ESCALATE_STAGE_DELAY" in caplog.text

def test_scan_and_log_once_attention_vs_no_attention(caplog):
    signatures = {}
    mock_results = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup failed.", attention=True),
        _make_scan_result("RET-2", "PICKUP_PENDING", "MONITOR_PICKUP", "Within SLA.", attention=False),
    ]
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=mock_results):
        results = asyncio.run(scan_and_log_once(signatures))
        
    assert len(results) == 2
    assert "RET-1" in caplog.text
    assert "RET-2" not in caplog.text
    assert "RET-1" in signatures
    assert "RET-2" not in signatures

def test_checkpoint_persists_across_restart(caplog):
    mock_results = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup status is FAILED.", attention=True)
    ]
    # First run: empty memory dict
    memory_sig_1 = {}
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=mock_results):
        asyncio.run(scan_and_log_once(memory_sig_1))
        assert "INVESTIGATE_PICKUP" in caplog.text

    # Verify checkpoint saved in DB
    cp = load_checkpoint("RET-1")
    assert cp is not None
    assert cp["return_id"] == "RET-1"
    assert "INVESTIGATE_PICKUP" in cp["active_alert_signature"]

    # Restart application: new in-memory dict (empty)
    caplog.clear()
    memory_sig_2 = {}
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=mock_results):
        asyncio.run(scan_and_log_once(memory_sig_2))
        # Alert should be suppressed across restart because of persisted checkpoint!
        assert caplog.text == ""

def test_checkpoint_clears_and_relogs_on_recurrence(caplog):
    result_alert = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup status is FAILED.", attention=True)
    ]
    result_healthy = [
        _make_scan_result("RET-1", "PICKUP_COMPLETED", "MONITOR_REFUND", "Pickup healthy.", attention=False)
    ]

    memory_sig = {}
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=result_alert):
        asyncio.run(scan_and_log_once(memory_sig))
        assert "INVESTIGATE_PICKUP" in caplog.text

    # Issue resolves (healthy scan)
    caplog.clear()
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=result_healthy):
        asyncio.run(scan_and_log_once(memory_sig))
        assert caplog.text == ""

    # Checkpoint in DB has active_alert_signature cleared
    cp = load_checkpoint("RET-1")
    assert cp is not None
    assert cp["active_alert_signature"] is None

    # Simulate restart and new recurrence of the same issue
    caplog.clear()
    restarted_memory_sig = {}
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=result_alert):
        asyncio.run(scan_and_log_once(restarted_memory_sig))
        # Should re-log because alert was previously cleared
        assert "INVESTIGATE_PICKUP" in caplog.text

def sqlite3_operational_error(*args, **kwargs):
    raise sqlite3.OperationalError("Simulated disk error")

def test_checkpoint_db_failure_safety(caplog):
    mock_results = [
        _make_scan_result("RET-1", "NEEDS_ATTENTION", "INVESTIGATE_PICKUP", "Pickup status is FAILED.", attention=True)
    ]
    memory_sig = {}
    # When DB operations fail, scan should still complete without crashing
    with caplog.at_level("WARNING", logger="agent.background_worker"), \
         patch("agent.background_worker.scan_approved_returns", return_value=mock_results), \
         patch("agent.background_worker.load_checkpoint", side_effect=sqlite3_operational_error), \
         patch("agent.background_worker.upsert_checkpoint", side_effect=sqlite3_operational_error):
        results = asyncio.run(scan_and_log_once(memory_sig))
        assert len(results) == 1
        assert "INVESTIGATE_PICKUP" in caplog.text

def test_approved_return_worker_invalid_interval():
    with pytest.raises(ValueError, match="Polling interval must be positive"):
        asyncio.run(approved_return_worker(poll_interval_seconds=0))
    with pytest.raises(ValueError, match="Polling interval must be positive"):
        asyncio.run(approved_return_worker(poll_interval_seconds=-5.0))

def test_approved_return_worker_cancellation(caplog):
    async def run_and_cancel():
        with patch("agent.background_worker.scan_and_log_once", side_effect=asyncio.CancelledError):
            task = asyncio.create_task(approved_return_worker(poll_interval_seconds=0.01))
            with pytest.raises(asyncio.CancelledError):
                await task

    with caplog.at_level("INFO", logger="agent.background_worker"):
        asyncio.run(run_and_cancel())
        
    assert "started" in caplog.text.lower()
    assert "stopped" in caplog.text.lower()

def test_approved_return_worker_exception_recovery(caplog):
    call_count = [0]
    
    async def flaky_scan(sigs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Database connection glitch")
        return []

    async def run_with_error():
        with patch("agent.background_worker.scan_and_log_once", side_effect=flaky_scan):
            task = asyncio.create_task(approved_return_worker(poll_interval_seconds=0.01))
            await asyncio.sleep(0.04)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    with caplog.at_level("ERROR", logger="agent.background_worker"):
        asyncio.run(run_with_error())
        
    assert call_count[0] >= 2
    assert "Background scan failed" in caplog.text
