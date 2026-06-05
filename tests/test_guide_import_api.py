from __future__ import annotations

import ipaddress
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.v1 import guide_import
from app.models.base import get_db


def _build_client(*, authenticated: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(guide_import.router, prefix="/api/v1")

    async def _override_db():
        yield object()

    app.dependency_overrides[get_db] = _override_db
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id="guide-import-user",
            preferences={"role": "user"},
        )
    return TestClient(app)


def _stub_public_dns(monkeypatch):
    monkeypatch.setattr(
        guide_import,
        "_resolve_host_ips",
        lambda _hostname: [ipaddress.ip_address("93.184.216.34")],
    )


def test_fetch_guide_import_extracts_static_page_text(monkeypatch):
    _stub_public_dns(monkeypatch)

    async def _fake_fetch(_client, url):
        assert url == "https://example.com/hangzhou-guide"
        return guide_import._FetchedResponse(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            encoding="utf-8",
            body=(
                "<html><head><title>杭州慢游攻略</title>"
                "<style>.hidden{display:none}</style></head>"
                "<body><h1>杭州 4 日慢游</h1>"
                "<script>window.secret='should not leak'</script>"
                "<p>Day1 西湖、雷峰塔、河坊街。</p>"
                "<p>Day2 灵隐寺、飞来峰、龙井村，适合茶文化慢游。</p>"
                "</body></html>"
            ).encode("utf-8"),
        )

    monkeypatch.setattr(guide_import, "_fetch_url_once", _fake_fetch)
    client = _build_client()

    response = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "https://example.com/hangzhou-guide"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["final_url"] == "https://example.com/hangzhou-guide"
    assert payload["source_domain"] == "example.com"
    assert payload["title"] == "杭州慢游攻略"
    assert "西湖" in payload["text"]
    assert "灵隐寺" in payload["text"]
    assert "should not leak" not in payload["text"]
    assert "display:none" not in payload["text"]
    assert payload["truncated"] is False


def test_fetch_guide_import_truncates_long_text(monkeypatch):
    _stub_public_dns(monkeypatch)
    long_text = "杭州西湖慢游路线。" * 300

    async def _fake_fetch(_client, _url):
        return guide_import._FetchedResponse(
            status_code=200,
            headers={"content-type": "text/plain; charset=utf-8"},
            encoding="utf-8",
            body=long_text.encode("utf-8"),
        )

    monkeypatch.setattr(guide_import, "_fetch_url_once", _fake_fetch)
    client = _build_client()

    response = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "https://example.com/long-guide"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["truncated"] is True
    assert len(payload["text"]) == guide_import.MAX_EXTRACTED_TEXT_CHARS
    assert "前半段" in payload["message"]


def test_fetch_guide_import_rejects_invalid_scheme(monkeypatch):
    _stub_public_dns(monkeypatch)
    client = _build_client()

    response = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "file:///C:/Windows/system.ini"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "guide_import_url_rejected"


def test_fetch_guide_import_rejects_localhost_and_private_ip(monkeypatch):
    _stub_public_dns(monkeypatch)
    client = _build_client()

    localhost = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "http://localhost:8000/internal"},
    )
    private_ip = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "http://127.0.0.1/internal"},
    )

    assert localhost.status_code == 422
    assert private_ip.status_code == 422
    assert localhost.json()["detail"]["code"] == "guide_import_url_rejected"
    assert private_ip.json()["detail"]["code"] == "guide_import_url_rejected"


def test_fetch_guide_import_rejects_redirect_to_private_address(monkeypatch):
    _stub_public_dns(monkeypatch)

    async def _fake_fetch(_client, url):
        assert url == "https://example.com/redirect"
        return guide_import._FetchedResponse(
            status_code=302,
            headers={"location": "http://127.0.0.1/private"},
            encoding="utf-8",
            body=b"",
        )

    monkeypatch.setattr(guide_import, "_fetch_url_once", _fake_fetch)
    client = _build_client()

    response = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "https://example.com/redirect"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "guide_import_url_rejected"


def test_fetch_guide_import_requires_authenticated_user():
    client = _build_client(authenticated=False)

    response = client.post(
        "/api/v1/guide-import/fetch",
        json={"url": "https://example.com/hangzhou-guide"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_required"
