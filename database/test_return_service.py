
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import db
from database.return_service import (
    ReturnError,
    check_eligibility,
    create_return,
)


class ReturnServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test.db"

        # Redirect this test's database connections to a temporary DB.
        self.path_patcher = patch.object(
            db, "DB_PATH", self.test_db_path
        )
        self.path_patcher.start()

        self.schema_patcher = patch.object(
            db, "SCHEMA_PATH",
            Path(__file__).resolve().parent / "schema.sql"
        )
        self.schema_patcher.start()

        db.init_db()

        with db.get_db() as connection:
            connection.execute(
                """
                INSERT INTO customers (
                    customer_id, name, email, created_at
                )
                VALUES ('CUS-001', 'Test Customer',
                        'test@example.com', '2026-01-01T00:00:00+00:00')
                """
            )

            connection.execute(
                """
                INSERT INTO products (
                    product_id, name, brand, category, aliases,
                    return_window_days, is_returnable
                )
                VALUES (
                    'PROD-001', 'Test Shoes', 'Test Brand',
                    'Footwear', '["shoes"]', 30, 1
                )
                """
            )

            connection.execute(
                """
                INSERT INTO orders (
                    order_id, customer_id, order_date, delivery_date,
                    status, payment_method, created_at
                )
                VALUES (
                    'ORD-001', 'CUS-001', '2026-01-01',
                    date('now', '-5 days'), 'DELIVERED', 'UPI',
                    '2026-01-01T00:00:00+00:00'
                )
                """
            )

            connection.execute(
                """
                INSERT INTO order_items (
                    order_item_id, order_id, product_id,
                    quantity, unit_price_paise
                )
                VALUES (
                    'ITEM-001', 'ORD-001', 'PROD-001', 2, 250000
                )
                """
            )

    def tearDown(self):
        self.path_patcher.stop()
        self.schema_patcher.stop()
        self.temp_dir.cleanup()

    def test_eligible_item(self):
        with db.get_db() as connection:
            result = check_eligibility(
                connection, "CUS-001", "ITEM-001", 1
            )

        self.assertEqual(result["refund_amount_paise"], 250000)
        self.assertEqual(result["remaining_quantity"], 2)

    def test_wrong_customer_is_rejected(self):
        with db.get_db() as connection:
            with self.assertRaises(ReturnError):
                check_eligibility(
                    connection, "CUS-999", "ITEM-001", 1
                )

    def test_zero_quantity_is_rejected(self):
        with db.get_db() as connection:
            with self.assertRaises(ReturnError):
                check_eligibility(
                    connection, "CUS-001", "ITEM-001", 0
                )

    def test_approved_return_creates_pickup_and_refund(self):
        result = create_return(
            customer_id="CUS-001",
            order_item_id="ITEM-001",
            quantity=1,
            reason="DEFECTIVE",
            approval_confirmed=True,
        )

        self.assertEqual(result["status"], "APPROVED")
        self.assertIsNotNone(result["pickup_id"])
        self.assertIsNotNone(result["refund_id"])

        with db.get_db() as connection:
            refund = connection.execute(
                """
                SELECT amount_paise, method, status
                FROM refunds WHERE refund_id = ?
                """,
                (result["refund_id"],),
            ).fetchone()

        self.assertEqual(refund["amount_paise"], 250000)
        self.assertEqual(refund["method"], "UPI")
        self.assertEqual(refund["status"], "PENDING")

    def test_cannot_return_more_than_purchased_quantity(self):
        create_return(
            customer_id="CUS-001",
            order_item_id="ITEM-001",
            quantity=2,
            reason="DEFECTIVE",
            approval_confirmed=True,
        )

        with self.assertRaises(ReturnError):
            create_return(
                customer_id="CUS-001",
                order_item_id="ITEM-001",
                quantity=1,
                reason="DAMAGED",
                approval_confirmed=True,
            )

    def test_invalid_reason_is_rejected(self):
        with self.assertRaises(ReturnError):
            create_return(
                customer_id="CUS-001",
                order_item_id="ITEM-001",
                quantity=1,
                reason="CHANGED_MIND_MAYBE",
                approval_confirmed=True,
            )


if __name__ == "__main__":
    unittest.main()
