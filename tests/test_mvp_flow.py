"""Сквозной сценарий MVP: продавец проходит верификацию и создаёт товар,
покупатель находит его, оформляет и оплачивает заказ, получает и оценивает."""

import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["STORAGE_DIR"] = str(Path(_tmp) / "storage")
os.environ["SEED_DEMO_DATA"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from config import settings  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register(client, email, role, name="Test"):
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "first_name": name, "role": role},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_full_flow(client):
    seller = register(client, "seller@test.ru", "seller", "Кабан")
    buyer = register(client, "buyer@test.ru", "customer", "Алексей")
    admin = client.post(
        "/api/auth/login", json={"email": settings.admin_email, "password": settings.admin_password}
    ).json()["access_token"]

    # нельзя зарегистрироваться админом
    r = client.post(
        "/api/auth/register",
        json={"email": "x@test.ru", "password": "password123", "first_name": "X", "role": "admin"},
    )
    assert r.status_code == 422

    # продавец: профиль, товар, фото
    assert client.post("/api/seller/products", headers=auth(seller), json={}).status_code == 409
    r = client.put("/api/seller/profile", headers=auth(seller), json={"name": "Siberian Core"})
    assert r.json()["verification_status"] == "draft"

    r = client.post(
        "/api/seller/products",
        headers=auth(seller),
        json={
            "name": "Гибридные шорты",
            "price": "2200.00",
            "category": "hybrid",
            "composition": "88% полиэстер",
            "delivery_days": 4,
            "size_table": {"headers": ["Размер", "Талия"], "rows": [["M", "76-82"], ["L", "82-88"]]},
            "instructions": [
                {"kind": "technology", "name": "Технологии", "steps": [{"name": "Плоские швы"}]},
                {"kind": "care", "name": "Уход", "steps": [{"name": "Стирка при 30°"}]},
            ],
        },
    )
    assert r.status_code == 201, r.text
    product_id = r.json()["id"]
    r = client.post(
        f"/api/seller/products/{product_id}/media",
        headers=auth(seller),
        files={"file": ("photo.png", b"\x89PNG fake", "image/png")},
    )
    assert r.status_code == 201
    image_url = r.json()["image_url"]
    assert client.get(image_url).status_code == 200

    # до верификации товар не виден в каталоге
    assert client.get("/api/products", params={"q": "шорты"}).json() == []

    # верификация
    r = client.post(
        "/api/seller/documents",
        headers=auth(seller),
        data={"document_type": "inn"},
        files={"file": ("inn.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    assert client.get(f"/api/documents/{doc_id}/file", headers=auth(buyer)).status_code == 404
    assert client.get(f"/api/documents/{doc_id}/file", headers=auth(admin)).status_code == 200

    pending = client.get(
        "/api/admin/sellers", headers=auth(admin), params={"verification_status": "pending"}
    ).json()
    assert [s["name"] for s in pending] == ["Siberian Core"]
    assert client.get("/api/admin/sellers", headers=auth(seller)).status_code == 403
    r = client.post(
        f"/api/admin/sellers/{pending[0]['id']}/verification",
        headers=auth(admin),
        json={"approve": True},
    )
    assert r.json()["verification_status"] == "verified"

    # покупатель: поиск, карточка, корзина
    found = client.get("/api/products", params={"q": "ШОРТЫ"}).json()
    assert [p["id"] for p in found] == [product_id]
    assert found[0]["seller"]["is_verified"] is True
    detail = client.get(f"/api/products/{product_id}").json()
    assert {i["kind"] for i in detail["instructions"]} == {"technology", "care"}

    assert client.post("/api/cart/items", headers=auth(seller), json={"product_id": product_id}).status_code == 403
    r = client.post("/api/cart/items", headers=auth(buyer), json={"product_id": product_id})
    assert r.status_code == 422  # размер обязателен
    r = client.post(
        "/api/cart/items", headers=auth(buyer), json={"product_id": product_id, "size": "M", "amount": 2}
    )
    assert r.json()["total"] == "4400.00"
    assert r.json()["max_delivery_days"] == 4

    # заказ и оплата
    r = client.post(
        "/api/orders",
        headers=auth(buyer),
        json={"delivery_address": "Красноярск, ул. Ленина, 10", "delivery_method": "courier", "payment_method": "card"},
    )
    assert r.status_code == 201, r.text
    order = r.json()["order"]
    assert order["status"] == "new" and "/pay/" in r.json()["payment_url"]
    assert client.get("/api/cart", headers=auth(buyer)).json()["items"] == []

    # поддельный webhook отклоняется
    r = client.post(
        "/api/webhooks/yookassa",
        json={"event": "payment.succeeded", "payment_id": "pay_x", "order_id": order["id"], "amount": "4400.00", "signature": "bad"},
    )
    assert r.status_code == 400

    r = client.post(f"/api/payments/test/{order['id']}/pay", headers=auth(buyer))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid" and r.json()["tracking_number"]

    # оценить до получения нельзя
    review = {"order_id": order["id"], "product_id": product_id, "rating": 5}
    assert client.post("/api/reviews", headers=auth(buyer), json=review).status_code == 409

    r = client.patch(f"/api/seller/orders/{order['id']}/status", headers=auth(seller), json={"status": "shipped"})
    assert r.json()["status"] == "shipped"
    r = client.post(f"/api/orders/{order['id']}/confirm-delivery", headers=auth(buyer))
    assert r.json()["status"] == "delivered"

    assert client.post("/api/reviews", headers=auth(buyer), json=review).status_code == 201
    assert client.post("/api/reviews", headers=auth(buyer), json=review).status_code == 409
    assert client.get(f"/api/orders/{order['id']}", headers=auth(buyer)).json()["rated_product_ids"] == [product_id]

    # аналитика продавца
    stats = client.get("/api/seller/analytics", headers=auth(seller)).json()
    assert stats["orders_count"] == 1
    assert stats["units_sold"] == 2
    assert stats["revenue"] == "4400.00"
    assert stats["average_rating"] == 5.0
    assert stats["products_with_sales"] == 1

    # товар из заказа нельзя удалить, только снять с продажи
    assert client.delete(f"/api/seller/products/{product_id}", headers=auth(seller)).status_code == 409
    r = client.patch(f"/api/seller/products/{product_id}", headers=auth(seller), json={"is_active": False})
    assert r.json()["is_active"] is False
    assert client.get(f"/api/products/{product_id}").status_code == 404
