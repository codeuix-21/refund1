import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient

from database import db
from server import app

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "database" / "schema.sql"

@pytest.fixture
def mock_llm_chat():
    with patch("agent.post_approval_agent.chat") as mock_chat:
        mock_chat.return_value = "The return process is on schedule with no actions needed from customer."
        yield mock_chat

@pytest.fixture
def test_db_env(mock_llm_chat):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_db_path = Path(temp_dir) / "test_api.db"
        
        with patch.object(db, "DB_PATH", temp_db_path), \
             patch.object(db, "SCHEMA_PATH", SCHEMA_FILE):
            
            db.init_db()
            
            with db.get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO customers (customer_id, name, email, created_at)
                    VALUES ('CUS-001', 'Test Customer', 'test@example.com', '2026-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO products (product_id, name, brand, category, aliases, return_window_days, is_returnable)
                    VALUES ('PROD-001', 'Test Running Shoes', 'BrandX', 'Footwear', '["shoes"]', 30, 1)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO products (product_id, name, brand, category, aliases, return_window_days, is_returnable)
                    VALUES ('PROD-NONRET', 'Hygiene Item', 'BrandY', 'Personal Care', '[]', 0, 0)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO orders (order_id, customer_id, order_date, delivery_date, status, payment_method, created_at)
                    VALUES ('ORD-001', 'CUS-001', '2026-01-01', date('now', '-5 days'), 'DELIVERED', 'UPI', '2026-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO orders (order_id, customer_id, order_date, delivery_date, status, payment_method, created_at)
                    VALUES ('ORD-SHIPPED', 'CUS-001', '2026-01-01', NULL, 'SHIPPED', 'UPI', '2026-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price_paise)
                    VALUES ('ITEM-001', 'ORD-001', 'PROD-001', 5, 250000)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price_paise)
                    VALUES ('ITEM-NONRET', 'ORD-001', 'PROD-NONRET', 1, 100000)
                    """
                )
                conn.execute(
                    """
                    INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price_paise)
                    VALUES ('ITEM-SHIPPED', 'ORD-SHIPPED', 'PROD-001', 1, 250000)
                    """
                )

            async def _dummy_worker(**kwargs):
                return

            with patch("server.approved_return_worker", side_effect=_dummy_worker):
                with TestClient(app, raise_server_exceptions=False) as client:
                    yield {
                        "client": client,
                        "db_path": temp_db_path,
                        "customer_id": "CUS-001",
                        "order_item_id": "ITEM-001",
                    }
