from starlette.testclient import TestClient
from server import app
import re

def test_frontend_serving():
    client = TestClient(app)

    # 1. Root route /
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "html" in r_root.headers.get("content-type", "")
    assert "<div id=\"root\"></div>" in r_root.text

    # 2. Check JS asset
    match = re.search(r'src="(/assets/[^"]+)"', r_root.text)
    assert match is not None
    asset_path = match.group(1)
    r_js = client.get(asset_path)
    assert r_js.status_code == 200
    assert len(r_js.content) > 1000

    # 3. Check CSS asset
    match_css = re.search(r'href="(/assets/[^"]+)"', r_root.text)
    assert match_css is not None
    css_path = match_css.group(1)
    r_css = client.get(css_path)
    assert r_css.status_code == 200
    assert len(r_css.content) > 500

def test_api_orders_and_refunds():
    client = TestClient(app)
    r_orders = client.get("/api/orders?customer_id=CUS-001")
    assert r_orders.status_code == 200
    assert "orders" in r_orders.json()
    assert len(r_orders.json()["orders"]) > 0

    r_refunds = client.get("/api/refunds?customer_id=CUS-001")
    assert r_refunds.status_code == 200
    assert "refunds" in r_refunds.json()

def test_chat_visual_items():
    client = TestClient(app)
    r_chat = client.post("/api/chat", json={
        "message": "I want to return the things that I ordered",
        "session_id": "test_visual_suite",
        "customer_id": "CUS-001"
    })
    assert r_chat.status_code == 200
    data = r_chat.json()
    assert data["state"] == "SELECTING_ORDER"
    assert len(data["visual_items"]) > 0
    assert "order_id" in data["visual_items"][0]
    assert "product_name" in data["visual_items"][0]
