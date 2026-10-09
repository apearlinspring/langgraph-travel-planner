from fastapi.testclient import TestClient

from app import main as app_main


def test_security_headers_include_csp_report_only_without_enforcement():
    client = TestClient(app_main.app)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers

    policy = response.headers["Content-Security-Policy-Report-Only"]
    assert "default-src 'self'" in policy
    assert "script-src 'self' https://cdn.bootcdn.net https://webapi.amap.com" in policy
    assert "style-src 'self' https://cdn.bootcdn.net" in policy
    assert "font-src 'self' data: https://cdn.bootcdn.net" in policy
    assert "https://images.unsplash.com" in policy
    assert "https://*.tile.openstreetmap.org" in policy
    assert "connect-src 'self' http://localhost:8000 http://127.0.0.1:8000" in policy
