"""
Main entry point for Return & Refund Chaser Agent.
Combines deterministic policy checks, order search, and local Qwen LLM
into a smart, responsive conversational return assistant.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import itertools
import json
import re
import sys
import threading
import time
import uuid

import requests

# Expose FastAPI app so `uvicorn main:app` or `from main import app` works seamlessly
try:
    from server import app
except Exception:
    app = None

# Ensure safe console output on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from api_client import (
    OLLAMA_BASE_URL,
    DEFAULT_MODEL,
    is_ollama_available,
    chat_completion,
    chat_json
)
from data_parser import (
    normalize,
    parse_requested_period
)
from order_search import (
    load_orders as search_load_orders,
    find_candidates as search_find_candidates,
    get_order_by_id,
    get_recent_orders,
    format_order_summary,
    extract_order_id_from_text
)
from understanding import (
    classify_intent as nlu_classify_intent,
    extract_return_details,
    answer_policy_question,
    RETURN_REASONS,
    REFUND_METHODS,
    INTENT_RETURN_REQUEST,
    INTENT_GREETING,
    INTENT_POLICY,
    INTENT_ORDER_LOOKUP,
    INTENT_CHAT,
    INTENT_UNCLEAR
)

from conversation import (
    ConversationSession,
    check_eligibility as conv_check_eligibility,
    create_mock_booking as conv_create_mock_booking,
    log_event as conv_log_event,
    format_alternatives
)

# ---------- CONFIGURATION ----------

BASE_DIR = Path(__file__).resolve().parent
ORDERS_FILE = BASE_DIR / "orders.json"
BOOKINGS_FILE = BASE_DIR / "bookings.json"
EVIDENCE_FILE = BASE_DIR / "evidence.jsonl"

MODEL = DEFAULT_MODEL
OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/chat"

# Set a fixed date string (e.g. '2026-10-19') only when you want reproducible tests.
# None means use your computer's current date.
TEST_TODAY = None


# ---------- DATE AND PERSISTENCE HELPERS ----------

def today():
    if TEST_TODAY:
        return date.fromisoformat(TEST_TODAY)
    return date.today()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    p = Path(path)
    temporary = p.with_suffix(p.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    temporary.replace(p)


def log_event(event, details):
    conv_log_event(event, details, evidence_file=EVIDENCE_FILE)


def load_orders():
    return search_load_orders(ORDERS_FILE)


def load_bookings():
    return read_json(BOOKINGS_FILE, {})


# ---------- BACKWARD-COMPATIBLE WRAPPERS ----------

CHAT_HISTORY = []

def ask_qwen(user_text, system_prompt=None):
    """Chat with Qwen while retaining previous chat messages in CHAT_HISTORY."""
    global CHAT_HISTORY

    if system_prompt is None:
        system_prompt = (
            "You are a helpful, conversational AI shopping assistant.\n"
            "- Answer the user's actual question directly.\n"
            "- Solve simple arithmetic when asked; do not ask the user to calculate it.\n"
            "- Understand follow-up messages using the conversation history.\n"
            "- Remember relevant details from earlier messages in this session.\n"
            "- Help users check return rules and order details.\n"
            "- Never invent orders or claim real courier bookings occurred.\n"
            "- Return eligibility and booking authorization are decided strictly by deterministic policy tools.\n"
            "Be natural, concise, and helpful."
        )

    CHAT_HISTORY.append({"role": "user", "content": user_text})
    messages = [{"role": "system", "content": system_prompt}, *CHAT_HISTORY]

    try:
        reply = chat_completion(messages, model=MODEL, temperature=0.4, timeout=120)
        CHAT_HISTORY.append({"role": "assistant", "content": reply})
        return reply
    except Exception:
        CHAT_HISTORY.pop()
        raise


def ask_qwen_with_thinking(user_text, system_prompt=None):
    """Show a thinking animation in the CLI while Qwen generates a response."""
    result = {}
    finished = threading.Event()

    def generate():
        try:
            result["reply"] = ask_qwen(user_text, system_prompt)
        except Exception as error:
            result["error"] = error
        finally:
            finished.set()

    worker = threading.Thread(target=generate, daemon=True)
    worker.start()

    frames = itertools.cycle(["Thinking   ", "Thinking.  ", "Thinking.. ", "Thinking..."])
    while not finished.is_set():
        sys.stdout.write("\r" + next(frames))
        sys.stdout.flush()
        finished.wait(0.25)

    worker.join()
    sys.stdout.write("\r" + " " * 20 + "\r")
    sys.stdout.flush()

    if "error" in result:
        raise result["error"]

    return result["reply"]


def classify_intent(user_text):
    """Classify user intent with fast rules and LLM fallback."""
    return nlu_classify_intent(user_text)


def ask_qwen_for_product_hint(user_text):
    """Extract product hint and order ID from user text."""
    details = extract_return_details(user_text)
    return details.get("product_hint", ""), details.get("order_id")


def find_candidates(user_text, hint=None, order_id=None, orders=None):
    """Match orders by ID, name, brand, alias, category, and date range."""
    orders_list = orders if orders is not None else load_orders()
    return search_find_candidates(
        user_text=user_text,
        hint=hint,
        order_id=order_id,
        orders=orders_list,
        reference_date=today()
    )


def select_order(candidates):
    """CLI prompt for user to choose among candidates."""
    if not candidates:
        print("\nI couldn't confidently identify your product.")
        print("Please include its brand or order ID (e.g. ORD-124).")
        return None

    if len(candidates) == 1:
        return candidates[0]

    print("\nI found multiple possible orders. Which one do you mean?")
    for number, order in enumerate(candidates, start=1):
        curr = "Rs." if order.get("currency") == "INR" else f"{order.get('currency')} "
        print(
            f"{number}. {order['product_name']} | "
            f"Order: {order['order_id']} | "
            f"{curr}{order['price']} | Delivered: {order['delivery_date']}"
        )


    while True:
        choice = input("Enter the number or order ID: ").strip()
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(candidates):
                return candidates[index]

        # Allow typing order ID directly
        for o in candidates:
            if o["order_id"].upper() == choice.upper():
                return o

        print(f"Invalid choice. Enter a number from 1 to {len(candidates)}.")


def check_eligibility(order):
    """Deterministic policy check for order return eligibility."""
    return conv_check_eligibility(order, reference_date=today())


def show_alternatives(order):
    print("\n" + format_alternatives(order))


def ask_reason():
    print("\nWhat is the issue with the item?")
    for key, value in RETURN_REASONS.items():
        print(f"{key}. {value.replace('_', ' ').title()}")

    while True:
        answer = input("Choose 1-4: ").strip()
        if answer in RETURN_REASONS:
            return RETURN_REASONS[answer]
        print("Please enter a number from 1 to 4.")


def ask_refund_method():
    print("\nWhere should the refund go?")
    print("1. Bank card (original payment method)")
    print("2. Store credit (instant balance)")

    while True:
        answer = input("Choose 1 or 2: ").strip()
        if answer in REFUND_METHODS:
            return REFUND_METHODS[answer]
        print("Please enter 1 or 2.")


def create_mock_booking(order, reason, refund_method, policy_evidence):
    return conv_create_mock_booking(
        order=order,
        reason=reason,
        refund_method=refund_method,
        policy_evidence=policy_evidence,
        bookings_file=BOOKINGS_FILE
    )


def print_handoff(booking):
    handoff = {
        "order_id": booking["order_id"],
        "return_id": booking["return_id"],
        "pickup_reference": booking["pickup_reference"],
        "refund_amount": booking["refund_amount"],
        "currency": booking["currency"],
        "refund_method": booking["refund_method"],
        "return_status": booking["return_status"]
    }
    print("\n--- RETURN AUTHORIZATION & COURIER HANDOFF JSON ---")
    print(json.dumps(handoff, indent=2))
    print("Mode: MOCK — not a real courier booking.")


# ---------- MAIN CONVERSATIONAL WORKFLOW ----------

def get_customer_name(customer_id="CUS-001"):
    try:
        from database.db import get_db
        with get_db() as conn:
            row = conn.execute("SELECT name FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
            if row:
                return row["name"]
    except Exception:
        pass
    return "Valued Customer"


def main():
    import argparse
    # Ensure mock delivery dates are kept fresh relative to current date
    try:
        from database.date_sync import sync_delivery_dates
        sync_delivery_dates()
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Return & Refund Chaser - Integrated Assistant & API")
    parser.add_argument("--server", "--api", action="store_true", help="Start the FastAPI backend server")
    parser.add_argument("--host", default="0.0.0.0", help="Host for server mode (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port for server mode (default: 8000)")
    parser.add_argument("--customer", default="CUS-001", help="Customer ID for CLI mode (default: CUS-001)")
    args = parser.parse_args()

    if args.server:
        import uvicorn
        print("=" * 60)
        print("  STARTING RETURN & REFUND CHASER API SERVER")
        print(f"  Listening on http://{args.host}:{args.port}")
        print("=" * 60)
        uvicorn.run("server:app", host=args.host, port=args.port, reload=False)
        return

    print("=" * 65)
    print("  CUSTOMER RETURN & REFUND ASSISTANT")
    print("  Unified Return Intake & Automated Post-Approval Refund Tracker")
    print("  Mode: MOCK STORE DATABASE (SQLite app.db)")
    print("=" * 65)

    customer_id = args.customer
    customer_name = get_customer_name(customer_id)
    orders = search_load_orders(customer_id=customer_id)

    print(f"\nActive Customer: {customer_name} ({customer_id})")
    print(f"Loaded {len(orders)} order items from store database.")

    # Verify Ollama status
    ollama_ready = is_ollama_available()
    if ollama_ready:
        print("Connected to local Ollama (Model: qwen2.5:3b)")
    else:
        print("Notice: Ollama is currently offline. Running in deterministic rule mode.")

    session = ConversationSession(
        orders=orders,
        customer_id=customer_id,
        bookings_file=BOOKINGS_FILE,
        evidence_file=EVIDENCE_FILE,
        reference_date=today()
    )

    print("\nHello! I can help you with returns, tracking refunds, or viewing orders.")
    print("Commands:")
    print("  - Type 'show my orders' to view your purchases")
    print("  - Type 'track my return' or 'status of RET-XXXXXX' to monitor return progress")
    print("  - Type 'switch customer CUS-002' to change active customer")
    print("  - Type 'exit' to quit\n")

    while True:
        try:
            user_text = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_text:
            continue

        if user_text.lower() in {"exit", "quit"}:
            print("Goodbye! Have a great day.")
            break

        if user_text.lower().startswith("switch customer"):
            parts = user_text.split()
            if len(parts) >= 3:
                new_cust = parts[2].upper()
                session.customer_id = new_cust
                session.orders = search_load_orders(customer_id=new_cust)
                new_name = get_customer_name(new_cust)
                print(f"\n[System] Switched active customer to {new_name} ({new_cust}). Loaded {len(session.orders)} items.\n")
                continue

        # Process message through smart conversation manager
        try:
            # If input is open-ended chat, show thinking animation if Ollama is available
            intent = nlu_classify_intent(user_text)
            if intent == INTENT_CHAT and ollama_ready and session.state == "IDLE":
                try:
                    reply = ask_qwen_with_thinking(user_text)
                    print(f"\nAgent: {reply}\n")
                    continue
                except Exception:
                    pass

            reply = session.handle_turn(user_text)
            print(f"\nAgent:\n{reply}\n")

        except Exception as error:
            print(f"\nAgent encountered an error: {error}")
            print("Please try rephrasing your message.\n")


if __name__ == "__main__":
    main()
