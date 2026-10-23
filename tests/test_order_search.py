from datetime import date, timedelta
from order_search import (
    load_orders,
    find_candidates,
    get_order_by_id,
    extract_order_id_from_text,
    get_recent_orders,
    format_order_summary
)


def test_extract_order_id():
    assert extract_order_id_from_text("Please return ORD-123") == "ORD-123"
    assert extract_order_id_from_text("my order id is ord 124") == "ORD-124"
    assert extract_order_id_from_text("ORD125 refund please") == "ORD-125"
    assert extract_order_id_from_text("hello there") is None


def test_find_by_exact_order_id():
    orders = load_orders()
    results = find_candidates("Return ORD-127", orders=orders)
    assert len(results) == 1
    assert results[0]["order_id"] == "ORD-127"
    assert results[0]["product_name"] == "Nike Casual Shoes"


def test_find_by_brand():
    orders = load_orders()
    results = find_candidates("I want to return my Adidas item", orders=orders)
    assert any(o["order_id"] == "ORD-124" for o in results)


def test_find_by_category():
    orders = load_orders()
    results = find_candidates("return the shoes", orders=orders)
    # Should find Nike, Adidas, Puma shoes
    assert len(results) >= 3
    names = [o["product_name"] for o in results]
    assert any("Nike" in n for n in names)
    assert any("Adidas" in n for n in names)


def test_find_with_date_filter():
    orders = load_orders()
    # Find ORD-124's delivery date and set reference_date to the following week
    ord_124 = next(o for o in orders if o["order_id"] == "ORD-124")
    del_124 = date.fromisoformat(ord_124["delivery_date"])
    ref_date = del_124 + timedelta(days=(7 - del_124.weekday()))
    results = find_candidates(
        "return shoes from last week",
        orders=orders,
        reference_date=ref_date
    )
    order_ids = [o["order_id"] for o in results]
    assert "ORD-124" in order_ids or "ORD-127" in order_ids
    assert "ORD-123" not in order_ids


def test_get_recent_orders():
    orders = load_orders()
    recent = get_recent_orders(orders, limit=3)
    assert len(recent) == 3
    # Most recent delivery dates should be first
    assert recent[0]["delivery_date"] >= recent[1]["delivery_date"]
    assert recent[1]["delivery_date"] >= recent[2]["delivery_date"]


def test_format_order_summary():
    order = {
        "order_id": "ORD-123",
        "product_name": "Nike Running Shoes",
        "price": 8999,
        "currency": "INR",
        "delivery_date": "2026-10-10"
    }
    summary = format_order_summary(order)
    assert "ORD-123" in summary
    assert "Nike Running Shoes" in summary
    assert "8999" in summary
    assert "2026-10-10" in summary

