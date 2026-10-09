import json

import pytest

from app.mcp_core.servers import weather_server


class FakeResponse:
    def __init__(self, payload: dict) -> None:
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

    async def get(self, *args, **kwargs):
        if self._error:
            raise self._error
        return self._response


@pytest.mark.asyncio
async def test_weather_server_returns_forecast_payload(monkeypatch):
    monkeypatch.setattr(weather_server, "AMAP_API_KEY", "test-key")
    monkeypatch.setattr(
        weather_server.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(
            response=FakeResponse(
                {
                    "status": "1",
                    "forecasts": [
                        {
                            "city": "Xian",
                            "adcode": "610100",
                            "province": "Shaanxi",
                            "reporttime": "2026-04-27 10:00:00",
                            "casts": [{"date": "2026-04-28", "dayweather": "Sunny"}],
                        }
                    ],
                }
            ),
            **kwargs,
        ),
    )

    raw = await weather_server.get_weather_forecast.fn("610100")
    payload = json.loads(raw)

    assert payload["city"] == "Xian"
    assert payload["adcode"] == "610100"
    assert payload["casts"][0]["date"] == "2026-04-28"


@pytest.mark.asyncio
async def test_weather_server_surfaces_upstream_error(monkeypatch):
    monkeypatch.setattr(weather_server, "AMAP_API_KEY", "test-key")
    monkeypatch.setattr(
        weather_server.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(
            response=FakeResponse(
                {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}
            ),
            **kwargs,
        ),
    )

    raw = await weather_server.get_weather_forecast.fn("610100")
    payload = json.loads(raw)

    assert payload == {"error": "INVALID_USER_KEY", "infocode": "10001"}
