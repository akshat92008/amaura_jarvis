"""API tests for beautiful_ecommerce_website-backend."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "message" in r.json()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200


def test_create_and_get_item():
    r = client.post("/api/v1/items", json={"name": "Test", "price": 9.99})
    assert r.status_code == 201
    item_id = r.json()["id"]
    r = client.get(f"/api/v1/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Test"
