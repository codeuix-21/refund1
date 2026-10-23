"""
Natural language understanding module.
Combines high-speed rule-based intent and entity recognition with Qwen LLM
classification and reasoning for flexible customer interaction.
"""

import json
import re

from api_client import chat_json, chat_completion, is_ollama_available
from data_parser import normalize
from order_search import extract_order_id_from_text

# Recognized Intents
INTENT_RETURN_REQUEST = "RETURN"
INTENT_GREETING = "GREETING"
INTENT_POLICY = "POLICY"
INTENT_ORDER_LOOKUP = "ORDER_LOOKUP"
INTENT_CONFIRMATION = "CONFIRMATION"
INTENT_CANCELLATION = "CANCELLATION"
INTENT_TRACK_RETURN = "TRACK_RETURN"
INTENT_CHAT = "CHAT"
INTENT_UNCLEAR = "UNCLEAR"

RETURN_REASONS = {
    "1": "TOO_SMALL",
    "2": "DEFECTIVE",
    "3": "QUALITY_ISSUE",
    "4": "OTHER"
}

# Legacy reason normalizer for DB schema compatibility
REASON_MAPPING = {
    "TOO_SMALL": "SIZE_ISSUE",
    "SIZE_ISSUE": "SIZE_ISSUE",
    "DEFECTIVE": "DEFECTIVE",
    "DAMAGED": "DAMAGED",
    "QUALITY_ISSUE": "DEFECTIVE",
    "WRONG_ITEM": "WRONG_ITEM",
    "WRONG_ITEM_SENT": "WRONG_ITEM",
    "NO_LONGER_NEEDED": "NO_LONGER_NEEDED",
    "OTHER": "NO_LONGER_NEEDED",
}


def normalize_return_reason(reason: str | None) -> str:
    """Normalize return reason to match SQLite CHECK constraint."""
    if not reason:
        return "NO_LONGER_NEEDED"
    clean = reason.strip().upper()
    return REASON_MAPPING.get(clean, "NO_LONGER_NEEDED")


REFUND_METHODS = {
    "1": "BANK_CARD",
    "2": "STORE_CREDIT",
    "3": "UPI"
}


def fast_intent_classify(user_text):
    """
    Fast, deterministic intent classification for common phrases.
    Avoids LLM latency and misclassification for standard greetings, policy questions,
    order lookups, return commands, and status tracking.
    """
    text = normalize(user_text)
    if not text:
        return INTENT_UNCLEAR

    # 1. Greetings
    if re.search(r"^(hi|hello|hey|heya|howdy|good (morning|afternoon|evening|day))\b", text):
        # Unless followed immediately by a return or status request
        if re.search(r"\b(return|refund|exchange)\b", text):
            return INTENT_RETURN_REQUEST
        if re.search(r"\b(status|track)\b", text):
            return INTENT_TRACK_RETURN
        return INTENT_GREETING

    # 2. Tracking / Status requests
    if re.search(r"\b(track|status|where is|check on)\b.*\b(return|pickup|refund|ret[-_ ]?[a-z0-9]+)\b|\bstatus of ret\b|\btrack ret\b", text):
        return INTENT_TRACK_RETURN

    # 3. Order lookup requests (including 'show my recent orders')
    if re.search(r"\b(show|list|view|see|check)\s+(my\s+)?(recent\s+)?(orders|purchases|items|history)\b|\bwhat (orders|items|products) (do i have|did i buy|did i order)\b|\bmy orders\b", text):
        return INTENT_ORDER_LOOKUP

    # 4. Policy questions
    if re.search(r"\b(return policy|refund policy|policy on|returnable|how many days|window for return|return window|can i return)\b", text):
        # If user explicitly specifies a product they bought to initiate return:
        # e.g. "can you return the bed sheet set i ordered last week" -> that is a return request!
        if re.search(r"\b(i ordered|i bought|i purchased|for my order|from last week|from yesterday)\b", text):
            return INTENT_RETURN_REQUEST
        # General question like "can i return socks" or "what is your return policy" -> POLICY
        return INTENT_POLICY

    # 5. Direct return / refund requests
    if re.search(r"\b(return|refund|exchange|send back|give back)\b", text):
        return INTENT_RETURN_REQUEST

    # 6. Affirmations / Cancellations
    if re.search(r"^(yes|yep|yeah|sure|confirm|proceed|approve|ok|okay)\b", text):
        return INTENT_CONFIRMATION
    if re.search(r"^(no|nope|cancel|stop|abort|nevermind|dont)\b", text):
        return INTENT_CANCELLATION

    return None


def classify_intent_with_llm(user_text):
    """Fallback to Qwen LLM for classifying complex or nuanced messages."""
    prompt = f"""
Classify the user's message into exactly one category:
- RETURN: The user wants to return, refund, or exchange an item they purchased.
- POLICY: The user is asking about the store's return rules, timelines, hygiene exclusions, or how returns work.
- ORDER_LOOKUP: The user wants to see their order history or what items they ordered.
- GREETING: The user is saying hello or greeting.
- CHAT: General pleasantries, arithmetic, general questions, or chit-chat.
- UNCLEAR: The message is incomprehensible or ambiguous.

Return only JSON:
{{"intent": "CATEGORY"}}

User message: {user_text}
"""
    result = chat_json(
        messages=[
            {"role": "system", "content": "You are a precise intent classifier. Return valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    if result and "intent" in result:
        category = str(result["intent"]).upper().strip()
        valid = {
            "RETURN": INTENT_RETURN_REQUEST,
            "POLICY": INTENT_POLICY,
            "ORDER_LOOKUP": INTENT_ORDER_LOOKUP,
            "GREETING": INTENT_GREETING,
            "CHAT": INTENT_CHAT,
            "UNCLEAR": INTENT_UNCLEAR
        }
        return valid.get(category, INTENT_UNCLEAR)


    return INTENT_UNCLEAR


def classify_intent(user_text):
    """
    Combined intent classifier:
    Uses deterministic fast path first; falls back to LLM if ambiguous.
    """
    intent = fast_intent_classify(user_text)
    if intent is not None:
        return intent

    if is_ollama_available():
        try:
            return classify_intent_with_llm(user_text)
        except Exception:
            pass

    return INTENT_CHAT


def extract_return_details(user_text):
    """
    Extract product hints, order IDs, return IDs, reasons, and refund preferences from user text.
    Uses regex rules and LLM assistance.
    """
    # Extract explicit return ID (must not match the word 'return')
    return_id_match = re.search(r"\bRET[-_ ]([A-Za-z0-9]{4,})\b|\bRET-([A-Za-z0-9]+)\b", str(user_text or ""), re.IGNORECASE)
    return_id = None
    if return_id_match:
        matched_code = return_id_match.group(1) or return_id_match.group(2)
        if matched_code.lower() != "urn":
            return_id = f"RET-{matched_code.upper()}"

    details = {
        "product_hint": "",
        "order_id": extract_order_id_from_text(user_text),
        "return_id": return_id,
        "reason": None,
        "refund_method": None
    }

    text = normalize(user_text)

    # 1. Rule-based reason extraction
    if re.search(r"\b(too small|small|tight|large|loose|wrong size|size doesn t fit|doesn t fit|size issue)\b", text):
        details["reason"] = "TOO_SMALL"
    elif re.search(r"\b(defective|broken|faulty|not working|tear|torn)\b", text):
        details["reason"] = "DEFECTIVE"
    elif re.search(r"\b(damaged|cracked|smashed|dented)\b", text):
        details["reason"] = "DAMAGED"
    elif re.search(r"\b(wrong item|different item|incorrect item|wrong product)\b", text):
        details["reason"] = "WRONG_ITEM"
    elif re.search(r"\b(poor quality|bad quality|cheap|color faded|material issue|disappointed with quality|quality issue)\b", text):
        details["reason"] = "QUALITY_ISSUE"
    elif re.search(r"\b(changed mind|don t need|don t want|no longer needed|other)\b", text):
        details["reason"] = "OTHER"

    # 2. Rule-based refund method extraction
    if re.search(r"\b(bank|card|bank card|account|original payment|credit card|debit card)\b", text):
        details["refund_method"] = "BANK_CARD"
    elif re.search(r"\b(store credit|credit|gift card)\b", text):
        details["refund_method"] = "STORE_CREDIT"
    elif re.search(r"\b(upi|gpay|phonepe|paytm)\b", text):
        details["refund_method"] = "UPI"

    # 3. Product hint extraction via LLM if available
    if is_ollama_available():
        prompt = f"""
Extract the product the customer wants to return.
Return ONLY JSON:
{{
  "product_hint": "brand or product words",
  "order_id": null
}}

Rules:
- Do not invent an order ID.
- If no specific product is mentioned, set product_hint to "".

Customer message: {user_text}
"""
        try:
            result = chat_json(
                messages=[
                    {"role": "system", "content": "Extract structured product information faithfully."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            if result:
                hint = result.get("product_hint")
                if isinstance(hint, str) and hint.strip():
                    details["product_hint"] = hint.strip()
                extracted_oid = result.get("order_id")
                if extracted_oid and not details["order_id"]:
                    details["order_id"] = str(extracted_oid).strip()
        except Exception:
            pass

    # Fallback product hint from text if LLM didn't find one
    if not details["product_hint"]:
        # Strip common return filler words
        clean = re.sub(r"\b(i want to|can u|can you|please|help me|return|refund|exchange|the|my|i ordered|last week|yesterday|today)\b", "", text)
        details["product_hint"] = clean.strip()

    return details


def answer_policy_question(user_text):
    """Provide a deterministic, comprehensive answer to store return policy questions."""
    text = normalize(user_text)

    # Specific hygiene item question
    if re.search(r"\b(socks?|toothbrush|perfume|hygiene|undergarments?)\b", text):
        return (
            "[Hygiene Policy Notice]\n"
            "For health and personal hygiene reasons, items tagged NON_RETURNABLE_HYGIENE "
            "(such as socks, electric toothbrushes, perfumes, and intimate items) cannot be returned once delivered.\n"
            "If your item arrived damaged or defective, please contact customer support for a replacement or resolution."
        )

    # Specific electronics question
    if re.search(r"\b(phone|smartphone|laptop|electronics?|headphones?|speaker)\b", text):
        return (
            "[Electronics Return Policy]\n"
            "- Smartphones & Headphones: 7-day return window from delivery date.\n"
            "- Laptops & Speakers: 14-day return window from delivery date.\n"
            "- Items must include all original packaging, chargers, and accessories.\n"
            "Would you like me to check an order for you?"
        )

    # General return policy
    return (
        "[Store Return Policy Summary]\n"
        "- Standard Return Window: Most items (shoes, clothing, laptops, home goods) have a 14-day return window.\n"
        "- Select Categories: Smartphones, headphones, and certain apparel items have a 7-day return window.\n"
        "- Hygiene & Personal Care: Socks, electric toothbrushes, and perfumes are strictly non-returnable.\n"
        "- Doorstep Pickup: Return pickups are free and scheduled directly at your delivery address.\n"
        "- Refund Methods: Choose between a refund to your original Bank Card (3-5 business days) or instant Store Credit.\n\n"
        "To start a return, mention what item or order ID you'd like to return (e.g., 'Return my shoes from last week' or 'Show my recent orders')."
    )

