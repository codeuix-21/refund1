"""
Module to keep mock order delivery dates fresh relative to the current date.
Every day at 12:00 AM (midnight), or on system startup when a new day arrives,
all order delivery dates and order dates are advanced by the number of elapsed days (+1 day per day).
This ensures that recent orders always remain within their active return window for evaluators.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
ORDERS_JSON_PATH = PROJECT_ROOT / "orders.json"
SYNC_FILE_PATH = DATA_DIR / "last_date_sync.txt"


def get_latest_recorded_date() -> date | None:
    """Finds the reference anchor date from sync tracking file, DB, or orders.json."""
    if SYNC_FILE_PATH.exists():
        try:
            content = SYNC_FILE_PATH.read_text(encoding="utf-8").strip()
            if content:
                return date.fromisoformat(content)
        except Exception as e:
            logger.warning("Could not read %s: %s", SYNC_FILE_PATH, e)

    # Fallback to max delivery date in DB
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("SELECT MAX(delivery_date) FROM orders WHERE delivery_date IS NOT NULL")
            row = cur.fetchone()
            con.close()
            if row and row[0]:
                return date.fromisoformat(row[0])
        except Exception as e:
            logger.warning("Could not fetch max delivery_date from DB: %s", e)

    # Fallback to orders.json
    if ORDERS_JSON_PATH.exists():
        try:
            with open(ORDERS_JSON_PATH, "r", encoding="utf-8") as f:
                orders = json.load(f)
            dates = [
                date.fromisoformat(o["delivery_date"])
                for o in orders
                if o.get("delivery_date")
            ]
            if dates:
                return max(dates)
        except Exception as e:
            logger.warning("Could not parse orders.json dates: %s", e)

    return None


def sync_delivery_dates(force_days: int | None = None) -> int:
    """
    Checks if one or more days have elapsed since the last date sync.
    If so, shifts all delivery dates and order dates forward by the elapsed days (+1 per day).
    Returns the number of days shifted (0 if already up to date).
    """
    today = date.today()

    if force_days is not None:
        delta_days = force_days
    else:
        last_date = get_latest_recorded_date()
        if last_date is None:
            # First time running: mark today as synced
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SYNC_FILE_PATH.write_text(today.isoformat(), encoding="utf-8")
            return 0

        delta_days = (today - last_date).days

    if not SYNC_FILE_PATH.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SYNC_FILE_PATH.write_text(today.isoformat(), encoding="utf-8")

    if delta_days <= 0:
        return 0

    logger.info("[DateSync] Advancing delivery dates by %d day(s) to match %s", delta_days, today)

    # 1. Update orders.json
    if ORDERS_JSON_PATH.exists():
        try:
            with open(ORDERS_JSON_PATH, "r", encoding="utf-8") as f:
                orders = json.load(f)

            for order in orders:
                if order.get("delivery_date"):
                    try:
                        cur_del = date.fromisoformat(order["delivery_date"])
                        order["delivery_date"] = (cur_del + timedelta(days=delta_days)).isoformat()
                    except ValueError:
                        pass

            with open(ORDERS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(orders, f, indent=2)
            logger.info("[DateSync] Successfully updated orders.json (+%d days)", delta_days)
        except Exception as e:
            logger.error("[DateSync] Failed to update orders.json: %s", e)

    # 2. Update data/app.db
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()

            # Fetch existing order dates
            cur.execute("SELECT order_id, order_date, delivery_date FROM orders")
            rows = cur.fetchall()

            for order_id, order_date_str, del_date_str in rows:
                new_order_date = order_date_str
                new_del_date = del_date_str

                if order_date_str:
                    try:
                        od = date.fromisoformat(order_date_str)
                        new_order_date = (od + timedelta(days=delta_days)).isoformat()
                    except ValueError:
                        pass

                if del_date_str:
                    try:
                        dd = date.fromisoformat(del_date_str)
                        new_del_date = (dd + timedelta(days=delta_days)).isoformat()
                    except ValueError:
                        pass

                cur.execute(
                    """
                    UPDATE orders
                    SET order_date = ?, delivery_date = ?
                    WHERE order_id = ?
                    """,
                    (new_order_date, new_del_date, order_id),
                )

            con.commit()
            con.close()
            logger.info("[DateSync] Successfully updated orders table in data/app.db (+%d days)", delta_days)
        except Exception as e:
            logger.error("[DateSync] Failed to update data/app.db: %s", e)

    # Record today as the latest synced date
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_FILE_PATH.write_text(today.isoformat(), encoding="utf-8")

    return delta_days
