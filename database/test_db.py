
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from database import db
from database.seed import seed_database


@pytest.fixture(autouse=True)
def isolated_test_db():
    """Run test_db against an isolated temporary database with seed data."""
    temp_dir = tempfile.TemporaryDirectory()
    test_db_path = Path(temp_dir.name) / "seed_test.db"

    with patch.object(db, "DB_PATH", test_db_path):
        seed_database()
        yield
    temp_dir.cleanup()


def test_seed_counts():
    """Check that seeding created the expected records."""
    with db.get_db() as connection:
        customers = connection.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        products = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

        orders = connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        assert customers >= 1
        assert products >= 18
        assert orders >= 55


def test_foreign_keys_enabled():
    """Check foreign-key enforcement on configured connections."""
    with db.get_db() as connection:
        enabled = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        assert enabled == 1


def test_product_aliases_are_valid_json():
    """Every product should contain valid JSON aliases."""
    with db.get_db() as connection:
        invalid = connection.execute(
            """
            SELECT product_id
            FROM products
            WHERE json_valid(aliases) = 0
            """
        ).fetchall()

        assert invalid == []


def test_order_items_reference_existing_orders_and_products():
    """No order item should have a missing parent record."""
    with db.get_db() as connection:
        violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        assert violations == []


def test_invalid_order_status_is_rejected():
    """The schema should reject an unsupported order status."""
    with db.get_db() as connection:
        try:
            connection.execute(
                """
                INSERT INTO orders (
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
                    "TEST-INVALID-ORDER",
                    "CUS-001",
                    "2026-01-01",
                    None,
                    "MAGIC_STATUS",
                    "UPI",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(
                "Database accepted an invalid order status."
            )


def test_database_file_exists():
    """The configured SQLite database should exist in the isolated environment."""
    assert db.DB_PATH.exists()
