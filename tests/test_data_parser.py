from datetime import date
from data_parser import parse_requested_period, normalize


def test_last_week_from_sunday():
    # Oct 18, 2026 was a Sunday; the previous week was Mon Oct 5 to Sun Oct 11
    start, end = parse_requested_period(
        "Return the shoes I ordered last week",
        reference_date=date(2026, 10, 18),
    )
    assert start == date(2026, 10, 5)
    assert end == date(2026, 10, 11)


def test_last_week_from_monday():
    # Oct 19, 2026 is a Monday; the previous week was Mon Oct 12 to Sun Oct 18
    start, end = parse_requested_period(
        "Return the shoes I ordered last week",
        reference_date=date(2026, 10, 19),
    )
    assert start == date(2026, 10, 12)
    assert end == date(2026, 10, 18)


def test_last_month():
    start, end = parse_requested_period(
        "Return my shoes from last month",
        reference_date=date(2026, 10, 19),
    )
    assert start == date(2026, 9, 1)
    assert end == date(2026, 9, 30)


def test_this_week():
    start, end = parse_requested_period(
        "items bought this week",
        reference_date=date(2026, 10, 21),  # Wednesday
    )
    assert start == date(2026, 10, 19)  # Monday
    assert end == date(2026, 10, 21)


def test_yesterday_and_today():
    start_y, end_y = parse_requested_period(
        "shoes delivered yesterday",
        reference_date=date(2026, 10, 19),
    )
    assert start_y == date(2026, 10, 18)
    assert end_y == date(2026, 10, 18)

    start_t, end_t = parse_requested_period(
        "bought today",
        reference_date=date(2026, 10, 19),
    )
    assert start_t == date(2026, 10, 19)
    assert end_t == date(2026, 10, 19)


def test_rolling_days():
    start, end = parse_requested_period(
        "orders in the last 7 days",
        reference_date=date(2026, 10, 19),
    )
    assert start == date(2026, 10, 13)
    assert end == date(2026, 10, 19)


def test_named_month():
    start, end = parse_requested_period(
        "bought in september",
        reference_date=date(2026, 10, 19),
    )
    assert start == date(2026, 9, 1)
    assert end == date(2026, 9, 30)


def test_normalize():
    assert normalize("Nike Running Shoes!!") == "nike running shoes"
    assert normalize("  ORD-123  ") == "ord 123"
