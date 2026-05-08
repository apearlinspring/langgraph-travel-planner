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
    monkeypatch.setenv("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    monkeypatch.setenv("PIP_TRUSTED_HOST", "pypi.tuna.tsinghua.edu.cn")

    MCPClientManager.refresh_server_configs()

    hotel_config = MCPClientManager.SERVER_CONFIGS["aigohotel-mcp"]
    assert hotel_config["command"] == "uvx"
    assert hotel_config["args"] == ["--from", "aigohotel-mcp==0.3.1", "aigohotel-mcp"]
    assert hotel_config["env"]["AIGOHOTEL_API_KEY"] == "new-key"
    assert hotel_config["env"]["UV_DEFAULT_INDEX"] == "https://pypi.tuna.tsinghua.edu.cn/simple"
    assert hotel_config["env"]["UV_INSECURE_HOST"] == "pypi.tuna.tsinghua.edu.cn"


def test_hotel_server_falls_back_to_legacy_env_var(monkeypatch):
    monkeypatch.delenv("AIGOHOTEL_API_KEY", raising=False)
    monkeypatch.setenv("AIGOHOTEL_MCP_API", "legacy-key")
    monkeypatch.delenv("AIGOHOTEL_SECRET_KEY", raising=False)

    MCPClientManager.refresh_server_configs()

    hotel_config = MCPClientManager.SERVER_CONFIGS["aigohotel-mcp"]
    assert hotel_config["env"]["AIGOHOTEL_API_KEY"] == "legacy-key"


def test_hotel_server_is_optional_for_startup(monkeypatch):
    monkeypatch.setenv("AIGOHOTEL_API_KEY", "new-key")

    MCPClientManager.refresh_server_configs()

    assert "aigohotel-mcp" in MCPClientManager.SERVER_CONFIGS
    assert "aigohotel-mcp" not in MCPClientManager.get_startup_server_names()


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


def test_local_stdio_servers_use_stable_runtime_dirs(monkeypatch):
    monkeypatch.setenv("AIGOHOTEL_API_KEY", "new-key")

    MCPClientManager.refresh_server_configs()

    env = MCPClientManager.SERVER_CONFIGS["weather"]["env"]
    assert env["FASTMCP_HOME"].endswith(".fastmcp")
    assert env["LOCALAPPDATA"].endswith(".runtime\\localappdata")
    assert env["APPDATA"].endswith(".runtime\\appdata")
    assert env["USERPROFILE"].endswith(".runtime\\userprofile")
    assert env["TEMP"].endswith(".runtime\\tmp")
    assert env["TMP"].endswith(".runtime\\tmp")
    assert env["PYTHONUTF8"] == "1"
    assert env["UV_HTTP_TIMEOUT"] == "15"


def test_uv_defaults_to_public_pypi_when_no_index_is_configured(monkeypatch):
    monkeypatch.setenv("AIGOHOTEL_API_KEY", "new-key")
    monkeypatch.delenv("UV_DEFAULT_INDEX", raising=False)
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("UV_INSECURE_HOST", raising=False)
    monkeypatch.delenv("PIP_TRUSTED_HOST", raising=False)

    MCPClientManager.refresh_server_configs()

    env = MCPClientManager.SERVER_CONFIGS["aigohotel-mcp"]["env"]
    assert env["UV_DEFAULT_INDEX"] == "https://pypi.org/simple"
    assert env["UV_INSECURE_HOST"] == "pypi.org"
