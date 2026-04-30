import sys

import pytest

from app.mcp_core.client import MCPClientManager


@pytest.fixture(autouse=True)
def reset_mcp_manager():
    MCPClientManager.reset_instance()
    yield
    MCPClientManager.reset_instance()


def test_hotel_server_uses_new_env_var_when_available(monkeypatch):
    monkeypatch.setenv("AIGOHOTEL_API_KEY", "new-key")
    monkeypatch.setenv("AIGOHOTEL_MCP_API", "legacy-key")

    MCPClientManager.refresh_server_configs()

    hotel_config = MCPClientManager.SERVER_CONFIGS["aigohotel-mcp"]
    assert hotel_config["command"] == "uvx"
    assert hotel_config["args"] == ["--from", "aigohotel-mcp", "aigohotel-mcp"]
    assert hotel_config["env"]["AIGOHOTEL_API_KEY"] == "new-key"


def test_hotel_server_falls_back_to_legacy_env_var(monkeypatch):
    monkeypatch.delenv("AIGOHOTEL_API_KEY", raising=False)
    monkeypatch.setenv("AIGOHOTEL_MCP_API", "legacy-key")
    monkeypatch.delenv("AIGOHOTEL_SECRET_KEY", raising=False)

    MCPClientManager.refresh_server_configs()

    hotel_config = MCPClientManager.SERVER_CONFIGS["aigohotel-mcp"]
    assert hotel_config["env"]["AIGOHOTEL_API_KEY"] == "legacy-key"


def test_hotel_server_is_omitted_when_no_credentials_exist(monkeypatch):
    monkeypatch.delenv("AIGOHOTEL_API_KEY", raising=False)
    monkeypatch.delenv("AIGOHOTEL_MCP_API", raising=False)
    monkeypatch.delenv("AIGOHOTEL_SECRET_KEY", raising=False)

    MCPClientManager.refresh_server_configs()

    assert "aigohotel-mcp" not in MCPClientManager.SERVER_CONFIGS


def test_local_stdio_servers_use_current_python(monkeypatch):
    monkeypatch.setenv("AIGOHOTEL_API_KEY", "new-key")

    MCPClientManager.refresh_server_configs()

    assert MCPClientManager.SERVER_CONFIGS["weather"]["command"] == sys.executable
    assert MCPClientManager.SERVER_CONFIGS["search"]["command"] == sys.executable
