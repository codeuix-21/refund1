
import json
import random
from datetime import date, datetime, timedelta, timezone

from pathlib import Path
from database.db import get_db, init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent


CUSTOMER_ID = "CUS-001"
ORDER_COUNT = 55

# Fixed random seed means the generated product/order combinations
# remain reproducible.
rng = random.Random(42)


PRODUCTS = [
    {
        "id": "PROD-001",
        "name": "Running Shoes",
        "brand": "Nike",
        "category": "Footwear",
        "aliases": ["trainers", "running sneakers", "jogging shoes"],
        "window": 30,
        "returnable": 1,
    },
    {
        "id": "PROD-002",
        "name": "Everyday Sneakers",
        "brand": "Adidas",
        "category": "Footwear",
        "aliases": ["sneakers", "casual shoes"],
        "window": 15,
        "returnable": 1,
    },
    {
        "id": "PROD-003",
        "name": "Cotton T-Shirt",
        "brand": "Puma",
        "category": "Clothing",
        "aliases": ["tee", "tshirt", "shirt"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-004",
        "name": "Slim Fit Jeans",
        "brand": "Levis",
        "category": "Clothing",
        "aliases": ["denim", "jeans", "pants"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-005",
        "name": "Wireless Headphones",
        "brand": "Sony",
        "category": "Electronics",
        "aliases": ["headphones", "wireless headset"],
        "window": 7,
        "returnable": 1,
    },
    {
        "id": "PROD-006",
        "name": "Bluetooth Speaker",
        "brand": "JBL",
        "category": "Electronics",
        "aliases": ["speaker", "portable speaker"],
        "window": 7,
        "returnable": 1,
    },
    {
        "id": "PROD-007",
        "name": "Mechanical Keyboard",
        "brand": "Keychron",
        "category": "Electronics",
        "aliases": ["keyboard", "gaming keyboard"],
        "window": 7,
        "returnable": 1,
    },
    {
        "id": "PROD-008",
        "name": "Gaming Mouse",
        "brand": "Logitech",
        "category": "Electronics",
        "aliases": ["mouse", "computer mouse"],
        "window": 7,
        "returnable": 1,
    },
    {
        "id": "PROD-009",
        "name": "Laptop Backpack",
        "brand": "American Tourister",
        "category": "Accessories",
        "aliases": ["backpack", "bag", "laptop bag"],
        "window": 15,
        "returnable": 1,
    },
    {
        "id": "PROD-010",
        "name": "Digital Watch",
        "brand": "Casio",
        "category": "Accessories",
        "aliases": ["watch", "wristwatch"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-011",
        "name": "Steel Water Bottle",
        "brand": "Milton",
        "category": "Home",
        "aliases": ["bottle", "water flask"],
        "window": 15,
        "returnable": 1,
    },
    {
        "id": "PROD-012",
        "name": "Desk Lamp",
        "brand": "Philips",
        "category": "Home",
        "aliases": ["lamp", "study lamp"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-013",
        "name": "Yoga Mat",
        "brand": "Boldfit",
        "category": "Fitness",
        "aliases": ["exercise mat", "workout mat"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-014",
        "name": "Dumbbell Set",
        "brand": "Decathlon",
        "category": "Fitness",
        "aliases": ["weights", "dumbbells"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-015",
        "name": "Personalized Mug",
        "brand": "Printo",
        "category": "Home",
        "aliases": ["custom mug", "printed mug"],
        "window": 0,
        "returnable": 0,
    },
    {
        "id": "PROD-016",
        "name": "Running Shorts",
        "brand": "Under Armour",
        "category": "Clothing",
        "aliases": ["gym shorts", "sports shorts"],
        "window": 10,
        "returnable": 1,
    },
    {
        "id": "PROD-017",
        "name": "USB-C Hub",
        "brand": "Anker",
        "category": "Electronics",
        "aliases": ["usb hub", "laptop hub"],
        "window": 7,
        "returnable": 1,
    },
    {
        "id": "PROD-018",
        "name": "Travel Duffel Bag",
        "brand": "Wildcraft",
        "category": "Accessories",
        "aliases": ["duffel", "gym bag", "travel bag"],
        "window": 15,
        "returnable": 1,
    },
]


# Prices are stored in paise, not rupees.
PRODUCT_PRICES_PAISE = {
    "PROD-001": 549900,
    "PROD-002": 399900,
    "PROD-003": 89900,
    "PROD-004": 199900,
    "PROD-005": 499900,
    "PROD-006": 349900,
    "PROD-007": 599900,
    "PROD-008": 249900,
    "PROD-009": 179900,
    "PROD-010": 299900,
    "PROD-011": 69900,
    "PROD-012": 129900,
    "PROD-013": 99900,
    "PROD-014": 249900,
    "PROD-015": 49900,
    "PROD-016": 129900,
    "PROD-017": 189900,
    "PROD-018": 149900,
}


PAYMENT_METHODS = [
    "UPI",
    "BANK_CARD",
    "NET_BANKING",
    "WALLET",
]


def utc_now():
    """Return a timezone-aware UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def insert_customer(connection):
    connection.execute(
        """
        INSERT OR IGNORE INTO customers (
            customer_id, name, email, created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            CUSTOMER_ID,
            "Aarav Sharma",
            "aarav.sharma@example.com",
            utc_now(),
        ),
    )


def insert_products(connection):
    for product in PRODUCTS:
        connection.execute(
            """
            INSERT OR IGNORE INTO products (
                product_id,
                name,
                brand,
                category,
                aliases,
                return_window_days,
                is_returnable
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product["id"],
                product["name"],
                product["brand"],
                product["category"],
                json.dumps(product["aliases"]),
                product["window"],
                product["returnable"],
            ),
        )


def generate_order(connection, order_number, today):
    order_id = f"ORD-{1000 + order_number}"

    # Choose an order date from today back to 150 days ago.
    days_ago = rng.randint(0, 150)
    order_date = today - timedelta(days=days_ago)

    # Recent orders are more likely to still be placed or shipped.
    if days_ago < 2:
        status = "PLACED"
        delivery_date = None
    elif days_ago < 7:
        status = "SHIPPED"
        delivery_date = None
    else:
        status_roll = rng.random()

        if status_roll < 0.10:
            status = "CANCELLED"
            delivery_date = None
        else:
            status = "DELIVERED"
            delivery_date = order_date + timedelta(
                days=rng.randint(1, 6)
            )

    payment_method = rng.choice(PAYMENT_METHODS)

    connection.execute(
        """
        INSERT OR IGNORE INTO orders (
            order_id,
            customer_id,
            order_date,
            delivery_date,
            status,
            payment_method,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            CUSTOMER_ID,
            order_date.isoformat(),
            delivery_date.isoformat() if delivery_date else None,
            status,
            payment_method,
            utc_now(),
        ),
    )

    # Cancelled orders do not need purchased items in this demo.
    if status == "CANCELLED":
        return

    # Never repeat the same product within a single order.
    item_count = rng.randint(1, 3)
    selected_products = rng.sample(PRODUCTS, item_count)

    for item_number, product in enumerate(selected_products, start=1):
        order_item_id = f"{order_id}-ITEM-{item_number}"

        quantity = rng.randint(1, 3)
        unit_price_paise = PRODUCT_PRICES_PAISE[product["id"]]

        connection.execute(
            """
            INSERT OR IGNORE INTO order_items (
                order_item_id,
                order_id,
                product_id,
                quantity,
                unit_price_paise
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_item_id,
                order_id,
                product["id"],
                quantity,
                unit_price_paise,
            ),
        )


def seed_legacy_orders_json(connection):
    orders_json_path = PROJECT_ROOT / "orders.json"
    if not orders_json_path.exists():
        return
    try:
        with open(orders_json_path, "r", encoding="utf-8") as f:
            orders_data = json.load(f)
        for idx, o in enumerate(orders_data, start=1):
            order_id = o["order_id"]
            prod_id = f"PROD-JSON-{idx:03d}"
            item_id = f"{order_id}-ITEM-1"
            del_date = o.get("delivery_date")
            order_date = (date.fromisoformat(del_date) - timedelta(days=3)).isoformat() if del_date else "2026-10-01"
            tag = o.get("policy_tag", "")
            is_returnable = 0 if "NON_RETURNABLE" in tag else 1
            window = 7 if "7_DAYS" in tag else (14 if "14_DAYS" in tag else 30)
            price_paise = int(o.get("price", 0) * 100)
            aliases_json = json.dumps(o.get("aliases", []))

            connection.execute("""
                INSERT OR IGNORE INTO products (
                    product_id, name, brand, category, aliases, return_window_days, is_returnable
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (prod_id, o["product_name"], o.get("brand", "Generic"), "General", aliases_json, window, is_returnable))

            connection.execute("""
                INSERT OR IGNORE INTO orders (
                    order_id, customer_id, order_date, delivery_date, status, payment_method, created_at
                ) VALUES (?, 'CUS-001', ?, ?, 'DELIVERED', 'BANK_CARD', '2026-10-01T00:00:00+00:00')
            """, (order_id, order_date, del_date))

            connection.execute("""
                INSERT OR IGNORE INTO order_items (
                    order_item_id, order_id, product_id, quantity, unit_price_paise
                ) VALUES (?, ?, ?, 1, ?)
            """, (item_id, order_id, prod_id, price_paise))
    except Exception:
        pass


def seed_database():
    # Ensure the tables and indexes exist first.
    init_db()

    today = date.today()

    with get_db() as connection:
        insert_customer(connection)
        insert_products(connection)
        seed_legacy_orders_json(connection)

        for number in range(1, ORDER_COUNT + 1):
            generate_order(connection, number, today)

        # Report what is in the database after seeding.
        customer_count = connection.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        product_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        order_count = connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        item_count = connection.execute(
            "SELECT COUNT(*) FROM order_items"
        ).fetchone()[0]

    print("Database seeding completed.")
    print(f"Customers: {customer_count}")
    print(f"Products: {product_count}")
    print(f"Orders: {order_count}")
    print(f"Order items: {item_count}")

    try:
        from database.date_sync import sync_delivery_dates
        sync_delivery_dates()
    except Exception:
        pass


if __name__ == "__main__":
    seed_database()
