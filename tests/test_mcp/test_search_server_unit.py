import json

import httpx
import pytest

from app.mcp_core.servers import search_server


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    def __init__(self, response=None, error: Exception | None = None, **_: object) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        if self._error:
            raise self._error
        return self._response


@pytest.mark.asyncio
async def test_search_server_trims_result_content(monkeypatch):
    monkeypatch.setattr(search_server, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        search_server.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(
            response=FakeResponse(
                200,
                {
                    "answer": "A concise answer",
                    "results": [
                        {
                            "title": "Xian guide",
                            "url": "https://example.com/xian",
                            "content": "A" * 350,
                        }
                    ],
                },
            ),
            **kwargs,
        ),
    )

    raw = await search_server.search_travel_info.fn("xian travel guide", max_results=20)
    payload = json.loads(raw)

    assert payload["query"] == "xian travel guide"
    assert payload["answer"] == "A concise answer"
    assert len(payload["results"]) == 1
    assert payload["results"][0]["title"] == "Xian guide"
    assert len(payload["results"][0]["content"]) == 300


@pytest.mark.asyncio
async def test_search_server_returns_timeout_error(monkeypatch):
    monkeypatch.setattr(search_server, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        search_server.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(
            error=httpx.TimeoutException("boom"),
            **kwargs,
        ),
    )

    raw = await search_server.search_travel_info.fn("xian food")
    payload = json.loads(raw)

    assert payload["error"]
    assert "超时" in payload["error"]
