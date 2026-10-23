import asyncio
import json
import logging
from datetime import datetime, timezone

from database.db import get_db
from .post_approval_agent import scan_approved_returns


logger = logging.getLogger(__name__)


def _serialize_signature(sig: tuple | list | str | None) -> str | None:
    if sig is None:
        return None
    if isinstance(sig, str):
        return sig
    return json.dumps(list(sig))


def _deserialize_signature(sig_str: str | None) -> tuple | str | None:
    if sig_str is None:
        return None
    try:
        data = json.loads(sig_str)
        if isinstance(data, list):
            return tuple(data)
        return data
    except Exception:
        return sig_str


def load_checkpoint(return_id: str) -> dict | None:
    """Load monitoring checkpoint from DB for a given return_id."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT return_id, last_observed_status, last_event_id, active_alert_signature, updated_at
            FROM monitoring_checkpoints
            WHERE return_id = ?
            """,
            (return_id,),
        ).fetchone()
        if row:
            return dict(row)
    return None


def get_latest_event_id(return_id: str) -> int | None:
    """Retrieve the latest event_id from return_events for return_id, if any."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT MAX(event_id) AS max_id
            FROM return_events
            WHERE return_id = ?
            """,
            (return_id,),
        ).fetchone()
        if row and row["max_id"] is not None:
            return row["max_id"]
    return None


def upsert_checkpoint(
    return_id: str,
    last_observed_status: str,
    last_event_id: int | None,
    active_alert_signature: str | None,
    updated_at: str | None = None,
) -> None:
    """Upsert monitoring checkpoint in SQLite database."""
    if updated_at is None:
        updated_at = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO monitoring_checkpoints (
                return_id,
                last_observed_status,
                last_event_id,
                active_alert_signature,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(return_id) DO UPDATE SET
                last_observed_status = excluded.last_observed_status,
                last_event_id = excluded.last_event_id,
                active_alert_signature = excluded.active_alert_signature,
                updated_at = excluded.updated_at
            """,
            (
                return_id,
                last_observed_status,
                last_event_id,
                active_alert_signature,
                updated_at,
            ),
        )


async def scan_and_log_once(
    last_alert_signatures: dict | None = None,
) -> list[dict]:
    """
    Scan approved and monitored returns once and log newly detected issues.

    Persists monitoring checkpoints and alert signatures to the database
    so alert deduplication survives application restarts.
    """

    if last_alert_signatures is None:
        last_alert_signatures = {}

    # Run the synchronous database scan without blocking
    # FastAPI's asynchronous event loop.
    results = await asyncio.to_thread(scan_approved_returns)

    active_alerts = {}

    for result in results:
        return_id = result["return_id"]
        current_state = result.get("current_state", {})
        return_status = current_state.get("return_status") or "UNKNOWN"
        assessment = result["assessment"]
        requires_attention = assessment.get("requires_attention", False)

        # Retrieve checkpoint from DB if available
        db_signature_deserialized = None
        db_checkpoint = None
        try:
            db_checkpoint = await asyncio.to_thread(load_checkpoint, return_id)
            if db_checkpoint and db_checkpoint.get("active_alert_signature"):
                db_signature_deserialized = _deserialize_signature(
                    db_checkpoint["active_alert_signature"]
                )
        except Exception:
            logger.exception("Failed to load checkpoint for return %s", return_id)

        # Check in-memory first; if missing in memory, fall back to DB checkpoint
        prev_sig = last_alert_signatures.get(return_id, db_signature_deserialized)

        if requires_attention:
            signature = (
                assessment["stage"],
                assessment["next_action"],
                assessment["reason"],
            )
            active_alerts[return_id] = signature

            if prev_sig != signature:
                logger.warning(
                    "Return %s requires attention. Action: %s. Reason: %s",
                    return_id,
                    assessment["next_action"],
                    assessment["reason"],
                )

            # Persist checkpoint to database
            try:
                sig_serialized = _serialize_signature(signature)
                event_id = await asyncio.to_thread(get_latest_event_id, return_id)
                await asyncio.to_thread(
                    upsert_checkpoint,
                    return_id,
                    return_status,
                    event_id,
                    sig_serialized,
                )
            except Exception:
                logger.exception("Failed to persist checkpoint for return %s", return_id)
        else:
            # Alert cleared or not required
            # If there was a previous alert recorded in DB or memory, clear the active signature in DB
            if prev_sig is not None or (db_checkpoint and db_checkpoint.get("active_alert_signature") is not None):
                try:
                    event_id = await asyncio.to_thread(get_latest_event_id, return_id)
                    await asyncio.to_thread(
                        upsert_checkpoint,
                        return_id,
                        return_status,
                        event_id,
                        None,
                    )
                except Exception:
                    logger.exception("Failed to clear alert checkpoint for return %s", return_id)

    last_alert_signatures.clear()
    last_alert_signatures.update(active_alerts)

    return results


async def approved_return_worker(
    poll_interval_seconds: float = 15.0,
) -> None:
    """
    Repeatedly scan approved returns until the worker is cancelled.
    """

    if poll_interval_seconds <= 0:
        raise ValueError("Polling interval must be positive.")

    logger.info(
        "Approved-return background worker started. "
        "Polling interval: %s seconds.",
        poll_interval_seconds,
    )

    last_alert_signatures = {}

    while True:
        try:
            await scan_and_log_once(last_alert_signatures)

        except asyncio.CancelledError:
            logger.info("Approved-return background worker stopped.")
            raise

        except Exception:
            # A failed scan should not permanently stop the worker.
            logger.exception(
                "Background scan failed. It will retry after the next interval."
            )

        await asyncio.sleep(poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 60)
    print("  RUNNING POST-APPROVAL TRACKING & REFUND CHASER AGENT")
    print("  Scanning for SLA delays, overdue pickups, and refunds...")
    print("=" * 60)
    try:
        asyncio.run(approved_return_worker(poll_interval_seconds=5.0))
    except KeyboardInterrupt:
        print("\nChaser agent stopped gracefully.")

