"""
Tests for database/date_sync.py
Verifies automatic roll-forward of delivery dates at 12 AM / new day.
"""

from datetime import date, timedelta
from database.date_sync import get_latest_recorded_date, sync_delivery_dates


def test_sync_delivery_dates_no_delta():
    # When already synced to today, delta is 0
    shifted = sync_delivery_dates()
    assert shifted == 0


def test_get_latest_recorded_date():
    recorded = get_latest_recorded_date()
    assert recorded is not None
    assert isinstance(recorded, date)
