"""
Order lookup, search, and disambiguation utilities.
Handles keyword matching, category expansion, alias search, and date-range filtering.
"""

from datetime import date
from pathlib import Path
import json
import re

from data_parser import normalize, parse_requested_period

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ORDERS_FILE = BASE_DIR / "orders.json"

CATEGORY_MAP = {
    "shoes": ["shoes", "sneakers", "running shoes", "casual shoes"],
    "shoe": ["shoes", "sneakers", "running shoes", "casual shoes"],
    "sneakers": ["shoes", "sneakers"],
    "phone": ["smartphone", "galaxy", "phone"],
    "smartphone": ["smartphone", "phone"],
    "headphones": ["headphones", "headset"],
    "jeans": ["jeans", "denim"],
    "shirt": ["t shirt", "tshirt", "cotton shirt", "shirt"],
    "tshirt": ["t shirt", "tshirt", "cotton shirt", "shirt"],
    "socks": ["socks"],
    "sock": ["socks"],
    "watch": ["watch", "wrist watch"],
    "backpack": ["backpack", "travel bag", "rucksack", "duffel"],
    "bag": ["backpack", "travel bag", "rucksack", "duffel"],
    "duffel": ["duffel", "gym bag", "travel bag"],
    "chair": ["office chair", "desk chair"],
    "speaker": ["bluetooth speaker", "speaker"],
    "wallet": ["wallet", "leather wallet"],
    "perfume": ["perfume", "fragrance"],
    "toothbrush": ["toothbrush", "electric toothbrush"],
    "bedsheet": ["bed sheet", "bedsheet", "bed sheet set"],
    "sheets": ["bed sheet", "bedsheet", "bed sheet set"],
    "mixer": ["mixer", "grinder", "mixer grinder"],
    "keyboard": ["keyboard", "gaming keyboard", "mechanical keyboard"],
    "mouse": ["mouse", "computer mouse", "gaming mouse"],
    "bottle": ["bottle", "water flask", "water bottle"],
    "dumbbells": ["dumbbells", "dumbbell set", "weights"],
    "lamp": ["lamp", "desk lamp"],
    "laptop": ["laptop"],
    "yoga mat": ["yoga mat", "exercise mat"],
    "mat": ["yoga mat", "exercise mat"],
}


def load_orders_from_db(customer_id="CUS-001"):
    """Load orders from SQLite mock store database."""
    try:
        from database.db import get_db, DB_PATH
        if not DB_PATH.exists():
            return []

        with get_db() as connection:
            query = """
            SELECT
                o.order_id,
                o.customer_id,
                o.order_date,
                o.delivery_date,
                o.status AS order_status,
                o.payment_method,
                oi.order_item_id,
                oi.quantity,
                oi.unit_price_paise,
                p.product_id,
                p.name AS product_name,
                p.brand,
                p.category,
                p.aliases,
                p.return_window_days,
                p.is_returnable
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            """
            params = ()
            if customer_id:
                query += " WHERE o.customer_id = ?"
                params = (customer_id,)
            query += " ORDER BY o.delivery_date DESC, o.order_date DESC"

            rows = connection.execute(query, params).fetchall()

        orders = []
        for r in rows:
            aliases_raw = r["aliases"]
            if isinstance(aliases_raw, str):
                try:
                    aliases = json.loads(aliases_raw)
                except Exception:
                    aliases = [aliases_raw]
            else:
                aliases = list(aliases_raw or [])

            unit_price_paise = r["unit_price_paise"] or 0
            is_ret = bool(r["is_returnable"])
            window = r["return_window_days"] or 0
            policy_tag = f"{window}_DAYS_RETURNABLE" if is_ret else "NON_RETURNABLE_HYGIENE"

            orders.append({
                "order_id": r["order_id"],
                "order_item_id": r["order_item_id"],
                "customer_id": r["customer_id"],
                "product_id": r["product_id"],
                "product_name": r["product_name"],
                "brand": r["brand"],
                "category": r["category"],
                "aliases": aliases,
                "quantity": r["quantity"],
                "unit_price_paise": unit_price_paise,
                "price": round(unit_price_paise / 100, 2),
                "currency": "INR",
                "order_date": r["order_date"],
                "delivery_date": r["delivery_date"],
                "order_status": r["order_status"],
                "payment_method": r["payment_method"],
                "return_window_days": window,
                "is_returnable": is_ret,
                "policy_tag": policy_tag,
                "source_id": f"DB-{r['order_id']}",
                "source_url": f"mock://orders/{r['order_id']}"
            })
        return orders
    except Exception:
        return []


def load_orders(file_path=None, customer_id="CUS-001", prefer_db=True):
    """
    Load orders. If prefer_db is True and no explicit file_path is given,
    load directly from the SQLite mock store database.
    Falls back to JSON file (DEFAULT_ORDERS_FILE) if DB has no records or fails.
    """
    if prefer_db and file_path is None:
        db_orders = load_orders_from_db(customer_id=customer_id)
        if db_orders:
            return db_orders

    path = Path(file_path) if file_path else DEFAULT_ORDERS_FILE
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def extract_order_id_from_text(text):
    """
    Extract an order ID if present in the text (e.g. 'ORD-123', 'ORD 123', 'ORD-1039', 'ORD1039').
    Returns formatted 'ORD-XXX' or None.
    """
    if not text:
        return None
    match = re.search(r"\bORD[-_ ]?(\d+)\b", str(text), re.IGNORECASE)
    if match:
        return f"ORD-{match.group(1)}"
    return None


def extract_return_id_from_text(text):
    """
    Extract a return ID if present in the text (e.g. 'RET-57443A5F09AD', 'RET-123').
    Returns formatted 'RET-XXX' or None (avoids matching the word 'return').
    """
    if not text:
        return None
    match = re.search(r"\bRET[-_ ]([A-Za-z0-9]{4,})\b|\bRET-([A-Za-z0-9]+)\b", str(text), re.IGNORECASE)
    if match:
        code = match.group(1) or match.group(2)
        if code.lower() != "urn":
            return f"RET-{code.upper()}"
    return None


def get_order_by_id(order_id, orders=None):
    """Look up an order by its order_id or order_item_id."""
    if not order_id:
        return None
    orders = orders if orders is not None else load_orders()
    clean_id = str(order_id).strip().upper()
    for order in orders:
        if (
            order.get("order_id", "").upper() == clean_id
            or order.get("order_item_id", "").upper() == clean_id
        ):
            return order
    return None


def get_recent_orders(orders=None, limit=5):
    """Return the N most recent orders sorted by delivery date descending."""
    orders = orders if orders is not None else load_orders()
    def sort_key(o):
        return o.get("delivery_date", "") or ""
    sorted_orders = sorted(orders, key=sort_key, reverse=True)
    return sorted_orders[:limit]


def format_order_summary(order):
    """Return a customer-friendly summary string for an order."""
    name = order.get("product_name", "Unknown Product")
    order_id = order.get("order_id", "N/A")
    item_id = order.get("order_item_id")
    price = order.get("price", 0)
    currency = order.get("currency", "INR")
    curr_symbol = "Rs. " if currency == "INR" else f"{currency} "
    del_date = order.get("delivery_date", "N/A")
    item_suffix = f" [{item_id}]" if item_id else ""
    return f"{name}{item_suffix} (Order: {order_id} | {curr_symbol}{price} | Delivered: {del_date})"



def find_candidates(user_text, hint=None, order_id=None, orders=None, reference_date=None):
    """
    Resolve products from order data applying:
    1. Direct order ID match.
    2. Brand, product name, and alias matching.
    3. Category synonym expansion.
    4. Requested date-range constraints.
    5. Scoring and ranking.
    """
    orders = orders if orders is not None else load_orders()
    if not orders:
        return []

    # Check for order ID in explicit argument, or extracted from user_text / hint
    explicit_id = (
        order_id
        or extract_order_id_from_text(user_text)
        or extract_order_id_from_text(hint)
    )

    if explicit_id:
        matching_items = [
            o for o in orders
            if o.get("order_id", "").upper() == explicit_id.upper()
            or o.get("order_item_id", "").upper() == explicit_id.upper()
        ]
        if matching_items:
            if hint:
                hint_norm = normalize(hint)
                sub_matched = [
                    o for o in matching_items
                    if normalize(o.get("product_name", "")) in hint_norm
                    or hint_norm in normalize(o.get("product_name", ""))
                    or any(normalize(a) in hint_norm for a in o.get("aliases", []))
                ]
                if sub_matched:
                    return sub_matched
            return matching_items

    combined = normalize(f"{user_text or ''} {hint or ''}")
    words = set(combined.split())
    requested_period = parse_requested_period(user_text or "", reference_date=reference_date)

    scored_candidates = []

    # Identify any brands explicitly mentioned
    all_brands = {normalize(o.get("brand", "")) for o in orders if o.get("brand")}
    mentioned_brands = {b for b in all_brands if b and (b in words or b in combined)}

    for order in orders:
        score = 0
        order_prod_norm = normalize(order.get("product_name", ""))
        order_brand_norm = normalize(order.get("brand", ""))
        aliases = [normalize(a) for a in order.get("aliases", []) if a]

        # Brand match check
        has_brand_match = order_brand_norm in mentioned_brands if mentioned_brands else False
        if mentioned_brands and not has_brand_match:
            # If the user explicitly named a brand, skip items from other brands
            continue

        if has_brand_match:
            score += 40

        # Exact product name match
        if order_prod_norm and (order_prod_norm in combined or combined in order_prod_norm):
            score += 50
        else:
            # Partial alias match
            for alias in aliases:
                if alias and alias in combined:
                    score = max(score, 35)
                elif any(w in alias.split() for w in words if len(w) > 2):
                    score = max(score, 20)

        # Category matching
        for cat_word, cat_synonyms in CATEGORY_MAP.items():
            if cat_word in words:
                if any(syn in order_prod_norm for syn in cat_synonyms):
                    score = max(score, score + 15 if score > 0 else 25)
                    break

        if score == 0:
            continue

        # 3. Apply requested date range to delivery_date if specified
        if requested_period:
            try:
                delivered = date.fromisoformat(order["delivery_date"])
                start_date, end_date = requested_period
                if not (start_date <= delivered <= end_date):
                    continue
                score += 20  # Bonus for matching requested time window
            except (KeyError, ValueError, TypeError):
                continue

        del_str = order.get("delivery_date") or ""
        scored_candidates.append((score, del_str, order))

    if not scored_candidates:
        return []

    # Sort by score desc, then delivery_date desc
    scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top_score = scored_candidates[0][0]

    # Filter out candidates with significantly lower score (more than 25 points below top)
    seen_ids = set()
    results = []
    for score, _, order in scored_candidates:
        if top_score - score > 25:
            continue
        oid = order.get("order_item_id") or order.get("order_id")
        if oid not in seen_ids:
            seen_ids.add(oid)
            results.append(order)

    return results

