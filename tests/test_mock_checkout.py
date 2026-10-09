from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.mock_checkout import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_mock_checkout_page_is_demo_only():
    client = _client()

    response = client.get("/api/v1/mock-checkout/ORDER-ABC12345")

    assert response.status_code == 200
    assert "M1 模拟订单确认" in response.text
    assert "不会发起真实支付" in response.text
    assert "/api/v1/mock-checkout/ORDER-ABC12345/complete" in response.text


def test_mock_checkout_complete_redirects_to_frontend_marker():
    client = _client()

    response = client.get(
        "/api/v1/mock-checkout/ORDER-ABC12345/complete",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?mock_checkout=confirmed&order_id=ORDER-ABC12345"


def test_mock_checkout_status_never_claims_payment_or_booking():
    client = _client()

    response = client.get("/api/v1/mock-checkout/ORDER-ABC12345/status")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "demo_only"
    assert payload["real_payment"] is False
    assert payload["real_booking"] is False
    assert payload["inventory_locked"] is False
    assert payload["fulfillment_triggered"] is False


def test_mock_checkout_rejects_non_generated_order_ids():
    client = _client()

    response = client.get("/api/v1/mock-checkout/pay_123")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_mock_order_id"
