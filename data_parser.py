"""
Date and text parsing utilities for customer order search.
Extracts relative and explicit date intervals to filter orders accurately.
"""

from datetime import date, timedelta
import calendar
import re


def normalize(text):
    """Normalize text by converting to lowercase and stripping punctuation."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def parse_requested_period(user_text, reference_date=None):
    """
    Convert relative time phrases into a (start_date, end_date) tuple.

    Handles:
    - 'last week'  -> previous calendar week (Monday through Sunday)
    - 'this week'  -> current week (Monday through reference_date)
    - 'last month' / 'previous month' -> previous calendar month
    - 'this month' -> first day of current month through reference_date
    - 'yesterday'  -> single day before reference_date
    - 'today'      -> reference_date
    - 'last N days' / 'past N days' -> rolling N-day window ending today
    - 'last year'  -> previous calendar year
    - specific month names ('september', 'october', etc.)

    Returns None if no recognizable time period was requested.
    """
    if not user_text:
        return None

    today_date = reference_date or date.today()
    text = normalize(user_text)

    # 1. 'last week' -> previous calendar week (Monday through Sunday)
    if re.search(r"\blast week\b", text):
        this_monday = today_date - timedelta(days=today_date.weekday())
        start_date = this_monday - timedelta(days=7)
        end_date = this_monday - timedelta(days=1)
        return start_date, end_date

    # 2. 'this week' -> current week (Monday through today_date)
    if re.search(r"\bthis week\b", text):
        this_monday = today_date - timedelta(days=today_date.weekday())
        return this_monday, today_date

    # 3. 'last month' or 'previous month'
    if re.search(r"\b(last|previous)\s+month\b", text):
        first_of_this_month = today_date.replace(day=1)
        last_of_previous_month = first_of_this_month - timedelta(days=1)
        first_of_previous_month = last_of_previous_month.replace(day=1)
        return first_of_previous_month, last_of_previous_month

    # 4. 'this month'
    if re.search(r"\bthis month\b", text):
        return today_date.replace(day=1), today_date

    # 5. 'yesterday'
    if re.search(r"\byesterday\b", text):
        yest = today_date - timedelta(days=1)
        return yest, yest

    # 6. 'today'
    if re.search(r"\btoday\b", text):
        return today_date, today_date

    # 7. Rolling N days: 'last 7 days', 'past 14 days', etc.
    n_days_match = re.search(r"\b(last|past)\s+(\d+)\s+days?\b", text)
    if n_days_match:
        n = int(n_days_match.group(2))
        if n > 0:
            return today_date - timedelta(days=n - 1), today_date

    if re.search(r"\bpast week\b", text):
        return today_date - timedelta(days=6), today_date

    # 8. 'last year'
    if re.search(r"\b(last|previous)\s+year\b", text):
        prev_year = today_date.year - 1
        return date(prev_year, 1, 1), date(prev_year, 12, 31)

    # 9. Explicit month names in current/reference year (e.g., 'in september')
    months = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12
    }
    for m_name, m_num in months.items():
        if re.search(rf"\b{m_name}\b", text):
            year = today_date.year
            # If the month is ahead of the reference month, it might refer to last year
            if m_num > today_date.month:
                year -= 1
            _, last_day = calendar.monthrange(year, m_num)
            return date(year, m_num, 1), date(year, m_num, last_day)

    return None