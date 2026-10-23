"""
Conversation and dialogue state management module.
Coordinates multi-turn dialogue, candidate disambiguation, policy checking,
approval workflows, and LLM responses.
"""

from datetime import date, datetime, timezone
from pathlib import Path
import json
import uuid
import re

from api_client import chat_completion, is_ollama_available
from data_parser import normalize
from order_search import (
    load_orders,
    find_candidates,
    get_order_by_id,
    get_recent_orders,
    format_order_summary,
    extract_order_id_from_text,
    extract_return_id_from_text
)
from understanding import (
    classify_intent,
    extract_return_details,
    answer_policy_question,
    normalize_return_reason,
    RETURN_REASONS,
    REFUND_METHODS,
    INTENT_RETURN_REQUEST,
    INTENT_GREETING,
    INTENT_POLICY,
    INTENT_ORDER_LOOKUP,
    INTENT_CONFIRMATION,
    INTENT_CANCELLATION,
    INTENT_TRACK_RETURN,
    INTENT_CHAT,
    INTENT_UNCLEAR
)


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_BOOKINGS_FILE = BASE_DIR / "bookings.json"
DEFAULT_EVIDENCE_FILE = BASE_DIR / "evidence.jsonl"

# Conversation States
STATE_IDLE = "IDLE"
STATE_SELECTING_ORDER = "SELECTING_ORDER"
STATE_AWAITING_REASON = "AWAITING_REASON"
STATE_AWAITING_REFUND_METHOD = "AWAITING_REFUND_METHOD"
STATE_AWAITING_APPROVAL = "AWAITING_APPROVAL"


def get_timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    temporary.replace(path)


def log_event(event, details, evidence_file=DEFAULT_EVIDENCE_FILE):
    record = {
        "timestamp": get_timestamp(),
        "event": event,
        "mode": "MOCK",
        "details": details
    }
    with open(evidence_file, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def check_eligibility(order, reference_date=None):
    """
    Deterministic policy check for order return eligibility.
    If the order is backed by the mock store database, validates against DB constraints.
    Otherwise, evaluates against JSON order metadata.
    Returns (eligible: bool, message: str, evidence: dict).
    """
    ref_date = reference_date or date.today()

    if order.get("order_item_id") and order.get("customer_id"):
        try:
            from database.db import get_db
            from database.return_service import check_eligibility as db_check_eligibility, ReturnError
            with get_db() as connection:
                res = db_check_eligibility(
                    connection=connection,
                    customer_id=order["customer_id"],
                    order_item_id=order["order_item_id"],
                    quantity=1
                )
                evidence = {
                    "order_id": order["order_id"],
                    "order_item_id": order["order_item_id"],
                    "product_name": order["product_name"],
                    "policy_tag": order.get("policy_tag", "UNKNOWN"),
                    "delivery_date": order.get("delivery_date"),
                    "checked_date": ref_date.isoformat(),
                    "return_window_days": res.get("return_window_days"),
                    "source_id": order.get("source_id", f"DB-{order['order_id']}"),
                    "source_url": order.get("source_url", f"mock://orders/{order['order_id']}"),
                    "retrieved_at": get_timestamp()
                }
                return True, f"Eligible for return within the {res.get('return_window_days')}-day window.", evidence
        except ReturnError as err:
            evidence = {
                "order_id": order["order_id"],
                "order_item_id": order.get("order_item_id"),
                "product_name": order["product_name"],
                "policy_tag": order.get("policy_tag", "UNKNOWN"),
                "delivery_date": order.get("delivery_date"),
                "checked_date": ref_date.isoformat(),
                "reason": str(err),
                "source_id": order.get("source_id", f"DB-{order['order_id']}"),
                "source_url": order.get("source_url", f"mock://orders/{order['order_id']}"),
                "retrieved_at": get_timestamp()
            }
            return False, f"Blocked: {err}", evidence
        except Exception:
            pass

    del_date = date.fromisoformat(order["delivery_date"])
    age_days = (ref_date - del_date).days
    tag = order.get("policy_tag", "UNKNOWN")

    evidence = {
        "order_id": order["order_id"],
        "product_name": order["product_name"],
        "policy_tag": tag,
        "delivery_date": order["delivery_date"],
        "checked_date": ref_date.isoformat(),
        "days_since_delivery": age_days,
        "source_id": order.get("source_id", f"MOCK-{order['order_id']}"),
        "source_url": order.get("source_url", f"mock://orders/{order['order_id']}"),
        "retrieved_at": get_timestamp()
    }

    if age_days < 0:
        return False, "Delivery date is in the future.", evidence

    if tag == "NON_RETURNABLE_HYGIENE":
        return (
            False,
            "Blocked: the product has the NON_RETURNABLE_HYGIENE tag. "
            "The mock hygiene policy excludes this item from returns.",
            evidence
        )

    windows = {
        "7_DAYS_RETURNABLE": 7,
        "14_DAYS_RETURNABLE": 14
    }

    if tag not in windows:
        return (
            False,
            "Blocked: unknown policy tag. Manual policy verification is required.",
            evidence
        )

    allowed_days = windows[tag]
    evidence["allowed_days"] = allowed_days

    if age_days > allowed_days:
        return (
            False,
            f"Blocked: delivered {age_days} days ago; the return window is {allowed_days} days.",
            evidence
        )

    return (
        True,
        f"Eligible under the mock {allowed_days}-day policy ({age_days} days since delivery).",
        evidence
    )


def format_alternatives(order):
    return (
        "💡 Possible next steps:\n"
        "- Check the brand's warranty, if applicable.\n"
        "- Contact customer support for a possible store-credit exception.\n"
        "- Consider resale or trade-in if appropriate.\n"
        "(These alternatives are suggestions, not confirmed offers.)"
    )


def create_mock_booking(order, reason, refund_method, policy_evidence, bookings_file=DEFAULT_BOOKINGS_FILE):
    """
    Create a simulated return booking and persist to bookings.json.
    Prevents duplicate bookings for the same order.
    """
    bookings = read_json(bookings_file, {})

    # Check for existing scheduled pickup
    for existing in bookings.values():
        if (
            existing.get("order_id") == order["order_id"]
            and existing.get("return_status") == "PICKUP_SCHEDULED"
        ):
            return existing, False

    next_number = len(bookings) + 1001
    return_id = "RET-" + uuid.uuid4().hex[:8].upper()
    pickup_ref = f"PU-REF-{next_number}"

    handoff = {
        "order_id": order["order_id"],
        "return_id": return_id,
        "pickup_reference": pickup_ref,
        "refund_amount": order["price"],
        "currency": order["currency"],
        "refund_method": refund_method,
        "return_status": "PICKUP_SCHEDULED"
    }

    booking = {
        **handoff,
        "product_name": order["product_name"],
        "reason": reason,
        "policy_evidence": policy_evidence,
        "booking_mode": "MOCK",
        "created_at": get_timestamp()
    }

    bookings[return_id] = booking
    write_json(bookings_file, bookings)

    log_event("MOCK_PICKUP_BOOKED", {
        "handoff": handoff,
        "booking_mode": "MOCK",
        "policy_evidence": policy_evidence
    })

    return booking, True


class ConversationSession:
    """
    Manages state, history, and actions for an ongoing customer conversation.
    """

    def __init__(self, orders=None, customer_id="CUS-001", bookings_file=DEFAULT_BOOKINGS_FILE, evidence_file=DEFAULT_EVIDENCE_FILE, reference_date=None):
        self.customer_id = customer_id
        self.orders = orders if orders is not None else load_orders(customer_id=self.customer_id)
        self.bookings_file = Path(bookings_file)
        self.evidence_file = Path(evidence_file)
        self.reference_date = reference_date or date.today()

        self.state = STATE_IDLE
        self.chat_history = []

        # Return flow context
        self.current_order = None
        self.candidate_orders = []
        self.reason = None
        self.refund_method = None
        self.policy_evidence = None
        self.last_created_return = None

    def reset_return_flow(self):
        """Reset return flow state to idle."""
        self.state = STATE_IDLE
        self.current_order = None
        self.candidate_orders = []
        self.reason = None
        self.refund_method = None
        self.policy_evidence = None
        self.last_created_return = None

    def ask_qwen_chat(self, user_text):
        """Chat with Qwen while retaining multi-turn history."""
        system_prompt = (
            "You are a helpful, conversational AI shopping and return assistant.\n"
            "- Answer questions directly, politely, and concisely.\n"
            "- Solve simple arithmetic directly when asked.\n"
            "- Understand follow-ups using conversation history.\n"
            "- You can assist users with store products, return policies, and order questions.\n"
            "- Return eligibility and booking are handled strictly by policy verification."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            *self.chat_history,
            {"role": "user", "content": user_text}
        ]

        if is_ollama_available():
            try:
                reply = chat_completion(messages, temperature=0.4, timeout=60)
                if reply:
                    self.chat_history.append({"role": "user", "content": user_text})
                    self.chat_history.append({"role": "assistant", "content": reply})
                    return reply
            except Exception:
                pass

        # Fallback if Ollama is unavailable
        fallback = (
            "I'm here to assist you with checking your orders, return eligibility, "
            "and scheduling pickups. How can I help you today?"
        )
        return fallback

    def handle_greeting(self, user_text):
        return "Hello! How can I help you today? Do you need any assistance returning an item or tracking a refund?"

    def handle_order_lookup(self, user_text):
        recent = get_recent_orders(self.orders, limit=5)
        if not recent:
            return "You don't have any orders on file."

        lines = ["[Your Recent Orders]"]
        for idx, o in enumerate(recent, start=1):
            curr = "Rs." if o.get("currency") == "INR" else f"{o.get('currency')} "
            item_tag = f" [{o.get('order_item_id')}]" if o.get("order_item_id") else ""
            lines.append(
                f"{idx}. {o['product_name']}{item_tag} (Order: {o['order_id']}) - "
                f"{curr}{o['price']} | Delivered: {o['delivery_date']} | Tag: {o['policy_tag']}"
            )
        lines.append("\nIf you would like to return any of these, just let me know which one!")
        return "\n".join(lines)

    def handle_track_return(self, user_text):
        """
        Track existing return requests.
        """
        details = extract_return_details(user_text)
        return_id = details.get("return_id")

        from agent.post_approval_agent import inspect_return, assess_return_status
        from database.db import get_db

        # If no explicit return_id, look for recent return by this customer
        if not return_id:
            try:
                with get_db() as connection:
                    row = connection.execute(
                        """
                        SELECT r.return_id, p.name AS product_name, r.status
                        FROM returns r
                        JOIN order_items oi ON oi.order_item_id = r.order_item_id
                        JOIN orders o ON o.order_id = oi.order_id
                        JOIN products p ON p.product_id = oi.product_id
                        WHERE o.customer_id = ?
                        ORDER BY r.requested_at DESC
                        LIMIT 1
                        """,
                        (self.customer_id,),
                    ).fetchone()
                    if row:
                        return_id = row["return_id"]
            except Exception:
                pass

        if not return_id:
            return (
                "I couldn't find a recent return for your account.\n"
                "Please provide your Return ID (e.g. `RET-XXXXXX`) to track its status."
            )

        try:
            state = inspect_return(return_id)
            assessment = assess_return_status(state)
        except Exception as error:
            return f"Unable to track return `{return_id}`: {error}"

        ret = state.get("return", {})
        pickup = state.get("pickup") or {}
        refund = state.get("refund") or {}

        status_lines = [
            f"📦 **Return Status for `{return_id}`**",
            f"- **Product:** {ret.get('product_name', 'Item')}",
            f"- **Return State:** `{ret.get('return_status', 'UNKNOWN')}`",
            f"- **Stage:** `{assessment.get('stage', 'N/A')}`",
            f"- **Courier Pickup:** `{pickup.get('status', 'NONE')}` (Ref: `{pickup.get('pickup_id', 'N/A')}`)",
        ]

        if refund:
            amt = (refund.get("amount_paise") or 0) / 100
            status_lines.append(f"- **Refund:** `{refund.get('status', 'NONE')}` (Rs. {amt:.2f} via {refund.get('method', 'N/A')})")

        action = assessment.get("next_action")
        if action:
            status_lines.append(f"- **Next Step:** `{action}`")

        explanation = assessment.get("explanation")
        if explanation:
            status_lines.append(f"\n{explanation}")

        return "\n".join(status_lines)



    def handle_turn(self, user_text):
        """
        Main entry point for processing a single user turn in the conversation.
        Returns a response string for the user.
        """
        clean_text = user_text.strip()
        if not clean_text:
            return "Please let me know how I can help."

        # Check for global exit or reset keywords
        if clean_text.lower() in {"cancel", "abort", "reset", "stop"} and self.state != STATE_IDLE:
            self.reset_return_flow()
            return "Return process cancelled. How else can I assist you?"

        # STATE: AWAITING SELECTION AMONG CANDIDATES
        if self.state == STATE_SELECTING_ORDER:
            return self._handle_candidate_selection(clean_text)

        # STATE: AWAITING REASON
        if self.state == STATE_AWAITING_REASON:
            return self._handle_reason_selection(clean_text)

        # STATE: AWAITING REFUND METHOD
        if self.state == STATE_AWAITING_REFUND_METHOD:
            return self._handle_refund_method_selection(clean_text)

        # STATE: AWAITING APPROVAL
        if self.state == STATE_AWAITING_APPROVAL:
            return self._handle_approval_response(clean_text)

        # STATE: IDLE - classify intent
        intent = classify_intent(clean_text)

        if intent == INTENT_GREETING:
            return self.handle_greeting(clean_text)

        if intent == INTENT_TRACK_RETURN:
            return self.handle_track_return(clean_text)

        if intent == INTENT_POLICY:
            return answer_policy_question(clean_text)

        if intent == INTENT_ORDER_LOOKUP:
            return self.handle_order_lookup(clean_text)

        if intent == INTENT_CHAT:
            return self.ask_qwen_chat(clean_text)


        if intent == INTENT_UNCLEAR:
            return (
                "I'm not sure I understood. Would you like to:\n"
                "1. **Start a return** for an order\n"
                "2. **View your recent orders**\n"
                "3. **Ask about our return policy**\n"
                "Please let me know!"
            )

        # Otherwise: INTENT_RETURN_REQUEST
        return self._start_return_flow(clean_text)

    def _start_return_flow(self, user_text):
        """Handle initiation of a return request."""
        details = extract_return_details(user_text)
        hint = details.get("product_hint", "")
        order_id = details.get("order_id")

        candidates = find_candidates(
            user_text=user_text,
            hint=hint,
            order_id=order_id,
            orders=self.orders,
            reference_date=self.reference_date
        )

        if not candidates:
            # Check if user mentioned an order ID that doesn't exist
            if order_id:
                log_event("ORDER_NOT_RESOLVED", {
                    "user_request": user_text,
                    "qwen_hint": hint,
                    "order_id": order_id
                }, self.evidence_file)
                return (
                    f"I couldn't find an order with ID `{order_id}` in your records.\n"
                    "Please double-check the Order ID or tell me the product name."
                )

            # Check if user explicitly asked to see/browse orders or returnable items
            user_lower = user_text.lower()
            asks_to_browse = any(phrase in user_lower for phrase in [
                "show my orders", "show orders", "what can i return", "what items can i return",
                "list my orders", "view my orders", "what did i order", "the things that i ordered",
                "things that i ordered", "things i ordered", "all items i ordered"
            ])

            if asks_to_browse:
                # Prioritize delivered orders that are eligible for return
                eligible_recent = []
                for o in self.orders:
                    if o.get("order_status") == "DELIVERED":
                        el, _, _ = check_eligibility(o, self.reference_date)
                        if el:
                            eligible_recent.append(o)
                            if len(eligible_recent) >= 4:
                                break

                recent = eligible_recent if eligible_recent else get_recent_orders(self.orders, limit=4)
                self.state = STATE_SELECTING_ORDER
                self.candidate_orders = recent

                lines = [
                    "Here are your recent return-eligible purchases. Which one would you like to return?",
                ]
                for idx, o in enumerate(recent, start=1):
                    curr = "Rs." if o.get("currency") == "INR" else f"{o.get('currency')} "
                    lines.append(f"{idx}. {o['product_name']} (Order: {o['order_id']}, {curr}{o['price']})")
                lines.append("\nPlease select a number (1-4) or tell me the product name:")
                return "\n".join(lines)

            # User asked generally without naming an item or asking to browse
            return "I'd be glad to help you with your return! Could you please specify which item or order you would like to return?"

        if len(candidates) == 1:
            return self._proceed_with_single_order(candidates[0], details)

        # Multiple candidates found -> Ask customer to disambiguate
        self.state = STATE_SELECTING_ORDER
        self.candidate_orders = candidates
        # Stash any pre-extracted details
        if details.get("reason"):
            self.reason = details["reason"]
        # Check if multiple distinct brands are present to ask: "Which pair do you mean: Nike or Adidas?"
        brands = [o.get("brand", "") for o in candidates if o.get("brand")]
        distinct_brands = list(dict.fromkeys(brands))
        clarification_msg = "Which one do you mean?"
        if len(distinct_brands) >= 2:
            clarification_msg = f"Which pair do you mean: {' or '.join(distinct_brands[:3])}?"

        lines = [f"I found multiple orders that match your request. {clarification_msg}"]
        for idx, o in enumerate(candidates, start=1):
            curr = "Rs." if o.get("currency") == "INR" else f"{o.get('currency')} "
            lines.append(
                f"{idx}. {o['product_name']} | Order: {o['order_id']} | "
                f"{curr}{o['price']} | Delivered: {o['delivery_date']}"
            )
        lines.append(f"\nPlease enter the number (1-{len(candidates)}) or order ID:")
        return "\n".join(lines)



    def _handle_candidate_selection(self, user_text):
        """User is choosing from multiple candidates."""
        text = user_text.strip()
        chosen = None

        # Check numeric selection or patterns like "#2", "item 2", "number 2"
        match = re.search(r'(?:item|option|number|#)?\s*(\d+)\b', text, re.IGNORECASE)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(self.candidate_orders):
                chosen = self.candidate_orders[idx]
        elif text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(self.candidate_orders):
                chosen = self.candidate_orders[idx]

        # Check order ID or name match
        if not chosen:
            for o in self.candidate_orders:
                if (
                    normalize(o["order_id"]) in normalize(text)
                    or normalize(o["product_name"]) in normalize(text)
                    or normalize(o["brand"]) in normalize(text)
                ):
                    chosen = o
                    break

        if not chosen:
            # Check if user is asking to return a different product or starting a new query
            user_lower = text.lower()
            details = extract_return_details(text)
            has_product_hint = bool(details.get("product_hint"))
            has_order_id = bool(details.get("order_id"))
            is_new_request = any(w in user_lower for w in [
                "return", "shoes", "shoe", "sneakers", "shirt", "jeans", "headphones", "order",
                "bought", "track", "cancel", "help", "show", "what", "can you", "can u"
            ])

            if has_product_hint or has_order_id or is_new_request:
                self.reset_return_flow()
                return self.handle_turn(user_text)

            return (
                f"Please choose an option number from 1 to {len(self.candidate_orders)}, "
                "or specify the product name."
            )

        # Reset candidates and proceed
        details = {
            "reason": self.reason,
            "refund_method": self.refund_method
        }
        self.candidate_orders = []
        return self._proceed_with_single_order(chosen, details)

    def _proceed_with_single_order(self, order, details=None):
        """Validate eligibility and advance to reason/refund selection or approval."""
        self.current_order = order
        eligible, message, evidence = check_eligibility(order, self.reference_date)
        self.policy_evidence = evidence

        log_event("POLICY_CHECK", {
            "user_request": order["product_name"],
            "eligible": eligible,
            "decision": message,
            "evidence": evidence
        }, self.evidence_file)

        curr = "Rs." if order.get("currency") == "INR" else f"{order.get('currency')} "
        header = (
            f"[Selected Order]: {order['product_name']}\n"
            f"- Order ID: {order['order_id']}\n"
            f"- Delivered: {order['delivery_date']}\n"
            f"- Tag: {order['policy_tag']}\n"
            f"- Price: {curr}{order['price']}\n\n"
            f"Policy Check Result: {message}\n"
        )

        if not eligible:
            self.reset_return_flow()
            alts = ""
            if "days ago" in message:
                alts = "\n" + format_alternatives(order)
            return f"{header}\nUnfortunately, this item cannot be returned.{alts}"

        # If eligible, check if reason and refund method are already known
        if details:
            if details.get("reason"):
                self.reason = details["reason"]
            if details.get("refund_method"):
                self.refund_method = details["refund_method"]

        if not self.reason:
            self.state = STATE_AWAITING_REASON
            lines = [
                header,
                "\n[Eligible for Return] What is the reason for return?",
                "1. Too Small / Wrong Size",
                "2. Defective / Damaged",
                "3. Quality Issue",
                "4. Other",
                "\nPlease choose 1-4 (or describe the issue):"
            ]
            return "\n".join(lines)

        if not self.refund_method:
            self.state = STATE_AWAITING_REFUND_METHOD
            lines = [
                header,
                f"\nReason noted: {self.reason.replace('_', ' ').title()}.",
                "Where should the refund go?",
                "1. Bank card (original payment method)",
                "2. Store credit (instant balance)",
                "\nPlease choose 1 or 2:"
            ]
            return "\n".join(lines)

        # Both reason and refund_method known -> proceed to approval
        return self._present_approval_summary()

    def _handle_reason_selection(self, user_text):
        text = user_text.strip()
        if text in RETURN_REASONS:
            self.reason = RETURN_REASONS[text]
        else:
            # Check keywords
            details = extract_return_details(user_text)
            if details.get("reason"):
                self.reason = details["reason"]
            else:
                self.reason = "OTHER"

        if not self.refund_method:
            self.state = STATE_AWAITING_REFUND_METHOD
            lines = [
                f"Reason noted: {self.reason.replace('_', ' ').title()}.\n",
                "Where should the refund go?",
                "1. Bank card (original payment method)",
                "2. Store credit (instant balance)",
                "\nPlease choose 1 or 2:"
            ]
            return "\n".join(lines)

        return self._present_approval_summary()

    def _handle_refund_method_selection(self, user_text):
        text = user_text.strip()
        if text in REFUND_METHODS:
            self.refund_method = REFUND_METHODS[text]
        else:
            details = extract_return_details(user_text)
            if details.get("refund_method"):
                self.refund_method = details["refund_method"]
            elif "card" in text.lower() or "bank" in text.lower():
                self.refund_method = "BANK_CARD"
            elif "credit" in text.lower() or "store" in text.lower():
                self.refund_method = "STORE_CREDIT"
            else:
                return "Please select 1 for Bank Card or 2 for Store Credit."

        return self._present_approval_summary()

    def _present_approval_summary(self):
        self.state = STATE_AWAITING_APPROVAL
        order = self.current_order
        curr = "Rs." if order.get("currency") == "INR" else f"{order.get('currency')} "

        summary = (
            "========== APPROVAL SUMMARY ==========\n"
            f"Product: {order['product_name']}\n"
            f"Order ID: {order['order_id']}\n"
            f"Return Reason: {self.reason}\n"
            f"Refund Destination: {self.refund_method}\n"
            f"Refund Amount: {curr}{order['price']}\n"
            f"Action: Schedule Mock Pickup & Issue Refund\n"
            f"Mode: MOCK\n"
            "======================================\n\n"
            "Approve this exact request? Type YES to confirm, or NO to cancel:"
        )
        return summary

    def _handle_approval_response(self, user_text):
        text = user_text.strip().upper()
        order = self.current_order
        is_yes = (
            text in {"YES", "Y", "CONFIRM", "APPROVE", "PROCEED"}
            or "YES" in text
            or "CONFIRM" in text
            or "APPROVE" in text
            or "RETURN THE PRODUCT" in text
            or "RETURN PRODUCT" in text
        )

        if is_yes:
            mapped_reason = normalize_return_reason(self.reason)
            order_item_id = order.get("order_item_id")
            customer_id = order.get("customer_id") or self.customer_id

            # If order has order_item_id, create the return atomically in the SQLite database!
            if order_item_id:
                try:
                    from database.return_service import create_return as db_create_return
                    result = db_create_return(
                        customer_id=customer_id,
                        order_item_id=order_item_id,
                        quantity=1,
                        reason=mapped_reason,
                        approval_confirmed=True
                    )
                    return_id = result["return_id"]
                    pickup_id = result["pickup_id"]
                    refund_id = result["refund_id"]
                    refund_amt = result.get("refund_amount_paise", 0) / 100

                    handoff = {
                        "order_id": order["order_id"],
                        "order_item_id": order_item_id,
                        "return_id": return_id,
                        "pickup_reference": pickup_id,
                        "refund_id": refund_id,
                        "refund_amount": refund_amt,
                        "currency": "INR",
                        "refund_method": self.refund_method or "BANK_CARD",
                        "return_status": "APPROVED",
                        "database_persisted": True
                    }

                    log_event("RETURN_APPROVED_IN_DB", {
                        "handoff": handoff,
                        "db_result": result,
                        "policy_evidence": self.policy_evidence
                    }, self.evidence_file)

                    self.reset_return_flow()
                    self.last_created_return = {
                        "return_id": return_id,
                        "pickup_id": pickup_id,
                        "refund_id": refund_id,
                        "refund_amount": refund_amt,
                        "refund_method": self.refund_method or "BANK_CARD",
                        "status": "APPROVED",
                        "order_id": order["order_id"],
                        "order_item_id": order_item_id,
                        "product_name": order["product_name"]
                    }
                    handoff_str = json.dumps(handoff, indent=2)

                    amt_str = f"₹{refund_amt:,.2f}" if refund_amt else f"₹{order.get('price', 0):,.2f}"
                    dest_str = "Original Bank Card" if "CARD" in str(self.refund_method or "").upper() else "Store Credit"
                    return (
                        f"✅ **Return Request Approved & Pickup Successfully Scheduled!**\n\n"
                        f"Here is a summary of your return:\n"
                        f"• **Product:** {order['product_name']}\n"
                        f"• **Order ID:** `{order['order_id']}`\n"
                        f"• **Return ID:** `{return_id}`\n"
                        f"• **Courier Pickup Ref:** `{pickup_id}`\n"
                        f"• **Refund Amount:** {amt_str}\n"
                        f"• **Refund Destination:** {dest_str}\n"
                        f"• **Status:** Approved (Pickup scheduled)\n\n"
                        f"Your pickup has been booked. Once collected, your refund will be processed and credited to your designated account."
                    )
                except Exception as db_err:
                    log_event("DB_RETURN_CREATION_FAILED", {
                        "order_id": order["order_id"],
                        "error": str(db_err)
                    }, self.evidence_file)

            # Fallback for purely in-memory / JSON test fixtures
            booking, created = create_mock_booking(
                order=order,
                reason=self.reason,
                refund_method=self.refund_method,
                policy_evidence=self.policy_evidence,
                bookings_file=self.bookings_file
            )

            handoff = {
                "order_id": booking["order_id"],
                "return_id": booking["return_id"],
                "pickup_reference": booking["pickup_reference"],
                "refund_amount": booking["refund_amount"],
                "currency": booking["currency"],
                "refund_method": booking["refund_method"],
                "return_status": booking["return_status"]
            }

            handoff_str = json.dumps(handoff, indent=2)
            self.reset_return_flow()

            return (
                f"✅ **Return Request Approved & Pickup Successfully Scheduled!**\n\n"
                f"Here is a summary of your return:\n"
                f"• **Product:** {order['product_name']}\n"
                f"• **Order ID:** `{booking['order_id']}`\n"
                f"• **Return ID:** `{booking['return_id']}`\n"
                f"• **Courier Pickup Ref:** `{booking['pickup_reference']}`\n"
                f"• **Refund Amount:** {booking['currency']} {booking['refund_amount']}\n"
                f"• **Refund Destination:** {booking['refund_method']}\n"
                f"• **Status:** Approved (Pickup scheduled)\n\n"
                f"Your pickup has been booked. Once collected, your refund will be processed and credited to your designated account."
            )


        else:
            log_event("BOOKING_NOT_APPROVED", {
                "order_id": order["order_id"]
            }, self.evidence_file)
            self.reset_return_flow()
            return "No booking made. Return request cancelled. How else can I assist you?"
