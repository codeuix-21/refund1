from datetime import date
from pathlib import Path
import json
import pytest

from conversation import (
    ConversationSession,
    STATE_IDLE,
    STATE_SELECTING_ORDER,
    STATE_AWAITING_REASON,
    STATE_AWAITING_REFUND_METHOD,
    STATE_AWAITING_APPROVAL
)

SAMPLE_ORDERS = [
    {
        "order_id": "ORD-124",
        "product_name": "Adidas Sneakers",
        "brand": "Adidas",
        "aliases": ["adidas", "sneakers"],
        "price": 6499,
        "currency": "INR",
        "delivery_date": "2026-10-15",
        "policy_tag": "7_DAYS_RETURNABLE",
        "source_id": "MOCK-ORDER-124",
        "source_url": "mock://orders/ORD-124"
    },
    {
        "order_id": "ORD-125",
        "product_name": "Puma Running Shoes",
        "brand": "Puma",
        "aliases": ["puma", "running shoes"],
        "price": 5999,
        "currency": "INR",
        "delivery_date": "2026-09-01",
        "policy_tag": "14_DAYS_RETURNABLE",
        "source_id": "MOCK-ORDER-125",
        "source_url": "mock://orders/ORD-125"
    },
    {
        "order_id": "ORD-126",
        "product_name": "Sports Socks",
        "brand": "Generic",
        "aliases": ["socks"],
        "price": 499,
        "currency": "INR",
        "delivery_date": "2026-10-14",
        "policy_tag": "NON_RETURNABLE_HYGIENE",
        "source_id": "MOCK-ORDER-126",
        "source_url": "mock://orders/ORD-126"
    },
    {
        "order_id": "ORD-127",
        "product_name": "Nike Casual Shoes",
        "brand": "Nike",
        "aliases": ["nike", "casual shoes"],
        "price": 7999,
        "currency": "INR",
        "delivery_date": "2026-10-14",
        "policy_tag": "14_DAYS_RETURNABLE",
        "source_id": "MOCK-ORDER-127",
        "source_url": "mock://orders/ORD-127"
    }
]


@pytest.fixture
def session(tmp_path):
    bookings_file = tmp_path / "test_bookings.json"
    evidence_file = tmp_path / "test_evidence.jsonl"
    ref_date = date(2026, 10, 19)
    return ConversationSession(
        orders=SAMPLE_ORDERS,
        bookings_file=bookings_file,
        evidence_file=evidence_file,
        reference_date=ref_date
    )


def test_greeting(session):
    reply = session.handle_turn("hello")
    assert "How can I help you today?" in reply
    assert session.state == STATE_IDLE



def test_policy_inquiry(session):
    reply = session.handle_turn("what is your return policy?")
    assert "Store Return Policy Summary" in reply
    assert "14-day" in reply
    assert session.state == STATE_IDLE


def test_order_lookup(session):
    reply = session.handle_turn("show my recent orders")
    assert "Your Recent Orders" in reply
    assert "ORD-124" in reply
    assert "ORD-127" in reply
    assert session.state == STATE_IDLE


def test_hygiene_policy_rejection(session):
    reply = session.handle_turn("can I return the socks?")
    assert "NON_RETURNABLE_HYGIENE" in reply or "cannot be returned" in reply
    assert session.state == STATE_IDLE


def test_expired_policy_rejection(session):
    reply = session.handle_turn("return ORD-125")
    assert "Blocked: delivered" in reply
    assert "return window is 14 days" in reply
    assert session.state == STATE_IDLE


def test_full_return_workflow(session):
    # Turn 1: request return for eligible item (ORD-124 delivered Oct 15, checked Oct 19 -> 4 days <= 7 days)
    r1 = session.handle_turn("Return my Adidas sneakers")
    assert session.state == STATE_AWAITING_REASON
    assert "What is the reason for return?" in r1

    # Turn 2: provide reason
    r2 = session.handle_turn("1")
    assert session.state == STATE_AWAITING_REFUND_METHOD
    assert "Where should the refund go?" in r2

    # Turn 3: provide refund method
    r3 = session.handle_turn("2")
    assert session.state == STATE_AWAITING_APPROVAL
    assert "APPROVAL SUMMARY" in r3
    assert "STORE_CREDIT" in r3

    # Turn 4: approve
    r4 = session.handle_turn("YES")
    assert session.state == STATE_IDLE
    assert "Pickup Successfully Scheduled" in r4
    assert "PU-REF-" in r4

    # Verify booking file was created
    bookings = json.loads(session.bookings_file.read_text(encoding="utf-8"))
    assert len(bookings) == 1
    booking = list(bookings.values())[0]
    assert booking["order_id"] == "ORD-124"
    assert booking["refund_method"] == "STORE_CREDIT"
    assert booking["reason"] == "TOO_SMALL"


def test_return_cancellation(session):
    session.handle_turn("Return my Adidas sneakers")
    session.handle_turn("1")
    session.handle_turn("1")
    assert session.state == STATE_AWAITING_APPROVAL

    r4 = session.handle_turn("NO")
    assert session.state == STATE_IDLE
    assert "No booking made" in r4


def test_single_turn_with_details(session):
    reply = session.handle_turn("Return ORD-127 because they are too small and refund to bank card")
    assert session.state == STATE_AWAITING_APPROVAL
    assert "TOO_SMALL" in reply
    assert "BANK_CARD" in reply
    assert "ORD-127" in reply


def test_disambiguation_flow(session):
    # User says 'shoes', which matches multiple items in SAMPLE_ORDERS
    reply = session.handle_turn("I want to return the shoes")
    assert session.state == STATE_SELECTING_ORDER
    assert "multiple orders" in reply

    # User picks option 1
    r2 = session.handle_turn("1")
    assert session.state in {STATE_AWAITING_REASON, STATE_IDLE}
