
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import db
from database.return_service import create_return
from database.demo_workflow import run_demo_workflow
from agent.recovery_service import set_credit_verification_provider


class DemoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "workflow_test.db"

        self.path_patcher = patch.object(db, "DB_PATH", self.test_db_path)
        self.schema_patcher = patch.object(
            db,
            "SCHEMA_PATH",
            Path(__file__).resolve().parent / "schema.sql",
        )

        self.path_patcher.start()
        self.schema_patcher.start()

        db.init_db()

        with db.get_db() as connection:
            connection.execute(
                """
                INSERT INTO customers
                    (customer_id, name, email, created_at)
                VALUES
                    ('CUS-001', 'Test Customer', 'test@example.com',
                     '2026-01-01T00:00:00+00:00')
                """
            )

            connection.execute(
                """
                INSERT INTO products
                    (product_id, name, brand, category, aliases,
                     return_window_days, is_returnable)
                VALUES
                    ('PROD-001', 'Test Shoes', 'Test Brand',
                     'Footwear', '["shoes"]', 30, 1)
                """
            )

            connection.execute(
                """
                INSERT INTO orders
                    (order_id, customer_id, order_date, delivery_date,
                     status, payment_method, created_at)
                VALUES
                    ('ORD-001', 'CUS-001', '2026-01-01',
                     date('now', '-5 days'), 'DELIVERED', 'UPI',
                     '2026-01-01T00:00:00+00:00')
                """
            )

            connection.execute(
                """
                INSERT INTO order_items
                    (order_item_id, order_id, product_id,
                     quantity, unit_price_paise)
                VALUES
                    ('ITEM-001', 'ORD-001', 'PROD-001', 2, 250000)
                """
            )

    def tearDown(self):
        set_credit_verification_provider(None)
        self.schema_patcher.stop()
        self.path_patcher.stop()
        self.temp_dir.cleanup()

    def test_workflow_completes_successfully(self):
        # Install a mock provider so verification succeeds and CREDITED/COMPLETED are reached.
        set_credit_verification_provider(lambda return_id, refund_id: True)

        # Create a return with explicit approval.
        created = create_return(
            customer_id="CUS-001",
            order_item_id="ITEM-001",
            quantity=1,
            reason="DEFECTIVE",
            approval_confirmed=True,
        )

        # Run the workflow without waiting between stages.
        result = asyncio.run(
            run_demo_workflow(
                return_id=created["return_id"],
                delay_seconds=0,
            )
        )

        self.assertEqual(result["status"], "COMPLETED")

        with db.get_db() as connection:
            return_row = connection.execute(
                """
                SELECT status, completed_at
                FROM returns
                WHERE return_id = ?
                """,
                (created["return_id"],),
            ).fetchone()

            pickup_row = connection.execute(
                """
                SELECT status, picked_up_at, received_at
                FROM pickups
                WHERE pickup_id = ?
                """,
                (created["pickup_id"],),
            ).fetchone()

            refund_row = connection.execute(
                """
                SELECT status, initiated_at, credited_at,
                       amount_paise, method
                FROM refunds
                WHERE refund_id = ?
                """,
                (created["refund_id"],),
            ).fetchone()

            events = connection.execute(
                """
                SELECT event_type, from_status, to_status
                FROM return_events
                WHERE return_id = ?
                ORDER BY event_id
                """,
                (created["return_id"],),
            ).fetchall()

        self.assertEqual(return_row["status"], "COMPLETED")
        self.assertIsNotNone(return_row["completed_at"])

        self.assertEqual(pickup_row["status"], "RECEIVED")
        self.assertIsNotNone(pickup_row["picked_up_at"])
        self.assertIsNotNone(pickup_row["received_at"])

        self.assertEqual(refund_row["status"], "CREDITED")
        self.assertIsNotNone(refund_row["initiated_at"])
        self.assertIsNotNone(refund_row["credited_at"])
        self.assertEqual(refund_row["amount_paise"], 250000)
        self.assertEqual(refund_row["method"], "UPI")

        # 3 events from return creation + 5 workflow events.
        self.assertEqual(len(events), 8)

        transitions = [
            (event["event_type"], event["from_status"], event["to_status"])
            for event in events
        ]

        self.assertIn(
            ("PICKUP", "SCHEDULED", "PICKED_UP"),
            transitions,
        )
        self.assertIn(
            ("PICKUP", "PICKED_UP", "RECEIVED"),
            transitions,
        )
        self.assertIn(
            ("REFUND", "PENDING", "INITIATED"),
            transitions,
        )
        self.assertIn(
            ("REFUND", "INITIATED", "CREDITED"),
            transitions,
        )
        self.assertIn(
            ("RETURN", "APPROVED", "COMPLETED"),
            transitions,
        )

    def test_workflow_stops_at_initiated_without_verification_provider(self):
        """
        TC4 Fix: Without a credit verification provider, run_demo_workflow must
        stop at INITIATED and return status 'APPROVED', not 'COMPLETED'.
        Time passing alone must never auto-credit a refund.
        """
        # Ensure no provider is configured.
        set_credit_verification_provider(None)

        created = create_return(
            customer_id="CUS-001",
            order_item_id="ITEM-001",
            quantity=1,
            reason="DEFECTIVE",
            approval_confirmed=True,
        )

        result = asyncio.run(
            run_demo_workflow(
                return_id=created["return_id"],
                delay_seconds=0,
            )
        )

        # Workflow must halt at INITIATED, not advance to CREDITED/COMPLETED.
        self.assertEqual(result["status"], "APPROVED")
        self.assertEqual(result["refund_status"], "INITIATED")

        with db.get_db() as connection:
            refund_row = connection.execute(
                "SELECT status FROM refunds WHERE refund_id = ?",
                (created["refund_id"],),
            ).fetchone()
            return_row = connection.execute(
                "SELECT status FROM returns WHERE return_id = ?",
                (created["return_id"],),
            ).fetchone()

        self.assertEqual(refund_row["status"], "INITIATED")
        self.assertEqual(return_row["status"], "APPROVED")

    def test_unapproved_return_cannot_start_workflow(self):
        created = create_return(
            customer_id="CUS-001",
            order_item_id="ITEM-001",
            quantity=1,
            reason="DEFECTIVE",
            approval_confirmed=False,
        )

        with self.assertRaises(ValueError):
            asyncio.run(
                run_demo_workflow(
                    return_id=created["return_id"],
                    delay_seconds=0,
                )
            )


if __name__ == "__main__":
    unittest.main()
