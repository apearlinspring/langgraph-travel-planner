from pathlib import Path
import sys

import pytest

from app.mcp_core.client import MCPClientManager
from app.utils.security import REDACTED_VALUE, redact_sensitive_text


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

    def normalized(value: str) -> str:
        return value.replace("\\", "/")

    assert env["FASTMCP_HOME"].endswith(".fastmcp")
    assert normalized(env["LOCALAPPDATA"]).endswith(".runtime/localappdata")
    assert normalized(env["APPDATA"]).endswith(".runtime/appdata")
    assert normalized(env["USERPROFILE"]).endswith(".runtime/userprofile")
    assert normalized(env["TEMP"]).endswith(".runtime/tmp")
    assert normalized(env["TMP"]).endswith(".runtime/tmp")
    assert env["PYTHONUTF8"] == "1"
    assert env["UV_HTTP_TIMEOUT"] == "15"
    assert MCPClientManager.SERVER_TOOL_LOAD_TIMEOUTS["aigohotel-mcp"] == 25.0


def test_12306_server_uses_configured_exclusive_url(monkeypatch):
    endpoint = "https://example.invalid/exclusive-rail/mcp"
    monkeypatch.setenv("ZHIXING_12306_MCP_URL", endpoint)

    MCPClientManager.refresh_server_configs()

    rail_config = MCPClientManager.SERVER_CONFIGS["12306-mcp"]
    assert rail_config == {"url": endpoint, "transport": "streamable_http"}
    assert MCPClientManager.SERVER_TOOL_LOAD_TIMEOUTS["12306-mcp"] == 25.0
    assert MCPClientManager.MCP_RETRY_ATTEMPTS == 2


def test_12306_server_supports_explicit_sse_endpoint(monkeypatch):
    endpoint = "http://127.0.0.1:18081/sse"
    monkeypatch.setenv("ZHIXING_12306_MCP_URL", endpoint)

    MCPClientManager.refresh_server_configs()

    assert MCPClientManager.SERVER_CONFIGS["12306-mcp"] == {
        "url": endpoint,
        "transport": "sse",
    }


def test_12306_server_is_omitted_without_exclusive_url(monkeypatch):
    monkeypatch.delenv("ZHIXING_12306_MCP_URL", raising=False)

    MCPClientManager.refresh_server_configs()

    assert "12306-mcp" not in MCPClientManager.SERVER_CONFIGS


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
    monkeypatch.delenv("ZHIXING_12306_MCP_URL", raising=False)

    MCPClientManager.refresh_server_configs()
    service_health = MCPClientManager.build_service_health_table(
        configured_servers=MCPClientManager.configured_server_names_for_env(),
        require_probe=False,
    )

    assert set(service_health) == set(MCPClientManager.SERVICE_DEFINITIONS)
    assert service_health["weather"]["status"] == "healthy"
    assert service_health["search"]["status"] == "healthy"
    assert service_health["12306-mcp"]["status"] == "skipped"
    assert service_health["aigohotel-mcp"]["status"] == "skipped"
    assert service_health["aigohotel-mcp"]["core_requirement"] == "optional"
    assert all(
        entry["status"] in MCPClientManager.SERVICE_HEALTH_STATUSES
        for entry in service_health.values()
    )


def test_service_health_blocks_required_12306_without_exclusive_url(monkeypatch):
    monkeypatch.delenv("ZHIXING_12306_MCP_URL", raising=False)
    env: dict[str, str] = {}

    service_health = MCPClientManager.build_service_health_table(
        required_servers=["12306-mcp"],
        configured_servers=MCPClientManager.configured_server_names_for_env(env),
        env=env,
        require_probe=False,
    )

    rail = service_health["12306-mcp"]
    assert rail["status"] == "blocked"
    assert rail["required"] is True
    assert rail["configured"] is False
    assert rail["env_vars"] == ["ZHIXING_12306_MCP_URL"]


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


def test_mcp_service_catalog_document_matches_service_definitions():
    doc_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "治理与可观测"
        / "tool-governance-audit.md"
    )
    catalog = doc_path.read_text(encoding="utf-8")

    assert "required_when_declared" in catalog
    for server, definition in MCPClientManager.SERVICE_DEFINITIONS.items():
        assert f"`{server}`" in catalog
        assert f"`{definition['core_requirement']}`" in catalog
        assert f"`{definition['acceptance_requirement']}`" in catalog
        assert str(definition["startup_probe"]) in catalog
        for env_var in definition["env_vars"]:
            assert f"`{env_var}`" in catalog


def test_redaction_masks_url_query_credentials():
    text = (
        "AMap failed: https://mcp.amap.com/mcp?key=amap-secret-1234567890 "
        "VariFlight failed: https://ai.variflight.com/mcp/?api_key=variflight-secret-1234567890 "
        "keep city=南京"
    )

    redacted = redact_sensitive_text(text)

    assert "amap-secret-1234567890" not in redacted
    assert "variflight-secret-1234567890" not in redacted
    assert f"key={REDACTED_VALUE}" in redacted
    assert f"api_key={REDACTED_VALUE}" in redacted
    assert "city=南京" in redacted


def test_mcp_error_formatter_redacts_url_credentials():
    exc = RuntimeError(
        "upstream 403 for https://mcp.amap.com/mcp?key=amap-secret-1234567890"
    )

    formatted = MCPClientManager._format_error(exc)

    assert "amap-secret-1234567890" not in formatted
    assert f"key={REDACTED_VALUE}" in formatted


def test_mcp_error_formatter_redacts_exclusive_12306_url(monkeypatch):
    endpoint = "https://example.invalid/exclusive-rail/mcp"
    monkeypatch.setenv("ZHIXING_12306_MCP_URL", endpoint)

    formatted = MCPClientManager._format_error(
        RuntimeError(f"upstream failed for {endpoint}")
    )

    assert endpoint not in formatted
    assert REDACTED_VALUE in formatted


@pytest.mark.asyncio
async def test_unknown_mcp_session_error_redacts_server_name():
    with pytest.raises(ValueError) as exc_info:
        async with MCPClientManager().session(
            "https://mcp.amap.com/mcp?key=amap-secret-1234567890"
        ):
            pass

    message = str(exc_info.value)
    assert "amap-secret-1234567890" not in message
    assert f"key={REDACTED_VALUE}" in message
