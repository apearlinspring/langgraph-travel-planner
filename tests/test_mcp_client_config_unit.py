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
    assert hotel_config["command"] == sys.executable
    assert hotel_config["args"] == ["-m", "aigohotel_mcp.server"]
    assert hotel_config["command"] != "uvx"
    assert "--from" not in hotel_config["args"]
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
    assert MCPClientManager.SERVER_TOOL_LOAD_TIMEOUTS["aigohotel-mcp"] == 25.0


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


def test_service_health_table_marks_optional_hotel_as_skipped_without_credentials(monkeypatch):
    monkeypatch.setenv("AMAP_API_KEY", "real-ish-amap")
    monkeypatch.setenv("TAVILY_API_KEY", "real-ish-tavily")
    monkeypatch.setenv("VARIFLIGHT_API_KEY", "real-ish-variflight")
    monkeypatch.delenv("AIGOHOTEL_API_KEY", raising=False)
    monkeypatch.delenv("AIGOHOTEL_MCP_API", raising=False)
    monkeypatch.delenv("AIGOHOTEL_SECRET_KEY", raising=False)

    MCPClientManager.refresh_server_configs()
    service_health = MCPClientManager.build_service_health_table(
        configured_servers=MCPClientManager.configured_server_names_for_env(),
        require_probe=False,
    )

    assert set(service_health) == set(MCPClientManager.SERVICE_DEFINITIONS)
    assert service_health["weather"]["status"] == "healthy"
    assert service_health["search"]["status"] == "healthy"
    assert service_health["12306-mcp"]["status"] == "healthy"
    assert service_health["aigohotel-mcp"]["status"] == "skipped"
    assert service_health["aigohotel-mcp"]["core_requirement"] == "optional"
    assert all(
        entry["status"] in MCPClientManager.SERVICE_HEALTH_STATUSES
        for entry in service_health.values()
    )


def test_service_health_table_blocks_required_hotel_when_acceptance_declares_it(monkeypatch):
    env = {
        "AMAP_API_KEY": "real-ish-amap",
        "TAVILY_API_KEY": "real-ish-tavily",
        "VARIFLIGHT_API_KEY": "real-ish-variflight",
    }

    service_health = MCPClientManager.build_service_health_table(
        required_servers=["aigohotel-mcp"],
        configured_servers=MCPClientManager.configured_server_names_for_env(env),
        env=env,
        require_probe=False,
    )

    hotel = service_health["aigohotel-mcp"]
    assert hotel["status"] == "blocked"
    assert hotel["requirement"] == "required"
    assert hotel["configured"] is False
    assert "required by the selected acceptance scenarios" in hotel["reason"]
