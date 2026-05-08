"""
Resilient MCP client manager.
"""
import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.utils.logger import app_logger

load_dotenv()


class MCPClientManager:
    """Manage MCP server connections independently so one failure does not poison the rest."""

    _instance: Optional["MCPClientManager"] = None
    _lock = asyncio.Lock()

    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    RUNTIME_ROOT = os.path.join(PROJECT_ROOT, ".runtime")
    MCP_HOME_DIR = os.path.join(PROJECT_ROOT, ".fastmcp")
    MCP_RETRY_ATTEMPTS = 2
    MCP_RETRY_DELAY_SECONDS = 1.0
    OPTIONAL_STARTUP_SERVERS = {"aigohotel-mcp"}
    SERVER_RETRY_ATTEMPTS = {"aigohotel-mcp": 1}
    SERVER_TOOL_LOAD_TIMEOUTS = {"aigohotel-mcp": 25.0}
    AIGOHOTEL_MCP_MODULE = "aigohotel_mcp.server"
    ENV_VARS: dict[str, str] = {}
    SERVER_CONFIGS: dict[str, dict[str, Any]] = {}

    @classmethod
    def _build_python_env(cls) -> dict[str, str]:
        env_vars = os.environ.copy()
        local_appdata = os.path.join(cls.RUNTIME_ROOT, "localappdata")
        appdata = os.path.join(cls.RUNTIME_ROOT, "appdata")
        userprofile = os.path.join(cls.RUNTIME_ROOT, "userprofile")
        temp_dir = os.path.join(cls.RUNTIME_ROOT, "tmp")

        for path in [
            cls.RUNTIME_ROOT,
            cls.MCP_HOME_DIR,
            local_appdata,
            appdata,
            userprofile,
            temp_dir,
        ]:
            os.makedirs(path, exist_ok=True)

        env_vars["PYTHONPATH"] = cls.PROJECT_ROOT + os.pathsep + env_vars.get("PYTHONPATH", "")
        env_vars.setdefault("UV_CACHE_DIR", os.path.join(cls.PROJECT_ROOT, ".uv-wheel-cache"))
        env_vars.setdefault("UV_PYTHON_INSTALL_DIR", os.path.join(cls.PROJECT_ROOT, ".uv-python"))
        env_vars.setdefault("UV_TOOL_DIR", os.path.join(cls.PROJECT_ROOT, ".uv-tools"))
        env_vars.setdefault("UV_HTTP_TIMEOUT", "15")
        env_vars["FASTMCP_HOME"] = cls.MCP_HOME_DIR
        env_vars["LOCALAPPDATA"] = local_appdata
        env_vars["APPDATA"] = appdata
        env_vars["USERPROFILE"] = userprofile
        env_vars["HOME"] = userprofile
        env_vars["TMP"] = temp_dir
        env_vars["TEMP"] = temp_dir
        env_vars["PYTHONUTF8"] = "1"
        uv_default_index = (
            os.getenv("UV_DEFAULT_INDEX")
            or os.getenv("PIP_INDEX_URL")
            or "https://pypi.org/simple"
        )
        env_vars.setdefault("UV_DEFAULT_INDEX", uv_default_index)
        insecure_host = os.getenv("UV_INSECURE_HOST") or os.getenv("PIP_TRUSTED_HOST", "")
        if not insecure_host:
            parsed = urlparse(uv_default_index)
            insecure_host = parsed.netloc
        if insecure_host:
            env_vars.setdefault("UV_INSECURE_HOST", insecure_host)
        return env_vars

    @staticmethod
    def _resolve_hotel_api_key() -> str:
        return (
            os.getenv("AIGOHOTEL_API_KEY", "")
            or os.getenv("AIGOHOTEL_MCP_API", "")
            or os.getenv("AIGOHOTEL_SECRET_KEY", "")
        )

    @classmethod
    def refresh_server_configs(cls) -> None:
        """Rebuild server configs from the current environment."""
        base_env = cls._build_python_env()
        server_configs: dict[str, dict[str, Any]] = {
            "weather": {
                "command": sys.executable,
                "args": ["-m", "app.mcp_core.servers.weather_server"],
                "transport": "stdio",
                "env": base_env,
            },
            "search": {
                "command": sys.executable,
                "args": ["-m", "app.mcp_core.servers.search_server"],
                "transport": "stdio",
                "env": base_env,
            },
            "amap": {
                "url": f"https://mcp.amap.com/mcp?key={os.getenv('AMAP_API_KEY', '')}",
                "transport": "http",
            },
            "12306-mcp": {
                "url": "https://mcp.api-inference.modelscope.net/215d3cfb299e47/mcp",
                "transport": "streamable_http",
            },
            "VariFlight-Aviation": {
                "url": (
                    "https://ai.variflight.com/servers/aviation/mcp/"
                    f"?api_key={os.getenv('VARIFLIGHT_API_KEY', '')}"
                ),
                "transport": "streamable_http",
            },
        }

        hotel_api_key = cls._resolve_hotel_api_key()
        if hotel_api_key:
            hotel_env = base_env.copy()
            hotel_env["AIGOHOTEL_API_KEY"] = hotel_api_key
            server_configs["aigohotel-mcp"] = {
                "command": sys.executable,
                "args": ["-m", cls.AIGOHOTEL_MCP_MODULE],
                "transport": "stdio",
                "env": hotel_env,
            }

        cls.ENV_VARS = base_env
        cls.SERVER_CONFIGS = server_configs

    def __init__(self) -> None:
        self._clients: dict[str, MultiServerMCPClient] = {}
        self._tool_cache: dict[str, list[Any]] = {}
        self._server_status: dict[str, dict[str, Any]] = {
            server: self._build_status_entry(server, "uninitialized")
            for server in self.SERVER_CONFIGS
        }

    @classmethod
    async def get_instance(cls, servers: list[str] | None = None) -> "MCPClientManager":
        """Return the singleton manager and optionally warm up a subset of servers."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls.refresh_server_configs()
                    cls._instance = cls()

        if servers:
            await cls._instance.warmup(servers=servers)

        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton for tests."""
        cls._instance = None
        cls.refresh_server_configs()

    @classmethod
    def get_status_snapshot(cls) -> dict[str, Any]:
        """Return a serializable snapshot for health checks."""
        if cls._instance is None:
            cls.refresh_server_configs()
            return {
                "status": "uninitialized",
                "healthy_servers": 0,
                "unavailable_servers": 0,
                "uninitialized_servers": len(cls.SERVER_CONFIGS),
                "tool_count": 0,
                "servers": {
                    server: cls._build_status_entry(server, "uninitialized")
                    for server in cls.SERVER_CONFIGS
                },
            }

        return cls._instance._snapshot()

    @classmethod
    def _build_status_entry(
        cls,
        server: str,
        status: str,
        *,
        tool_count: int = 0,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "tool_count": tool_count,
            "error": error,
            "transport": cls.SERVER_CONFIGS.get(server, {}).get("transport"),
        }

    @classmethod
    def get_startup_server_names(cls) -> list[str]:
        """Return MCP servers that are safe to warm up during startup."""
        return [
            server
            for server in cls.SERVER_CONFIGS
            if server not in cls.OPTIONAL_STARTUP_SERVERS
        ]

    @classmethod
    def get_default_tool_server_names(cls, *, include_optional: bool = False) -> list[str]:
        """Return the default server list for generic tool collection."""
        if include_optional:
            return list(cls.SERVER_CONFIGS.keys())
        return cls.get_startup_server_names()

    def _normalize_servers(self, servers: list[str] | None) -> list[str]:
        target_servers = servers or list(self.SERVER_CONFIGS.keys())
        valid_servers = []
        for server in target_servers:
            if server not in self.SERVER_CONFIGS:
                app_logger.warning(f"Skipping unknown MCP server: {server}")
                continue
            valid_servers.append(server)
        return valid_servers

    def _get_or_create_client(self, server: str) -> MultiServerMCPClient:
        client = self._clients.get(server)
        if client is None:
            client = MultiServerMCPClient({server: self.SERVER_CONFIGS[server]})
            self._clients[server] = client
        return client

    @asynccontextmanager
    async def session(self, server: str) -> AsyncIterator[Any]:
        """Open a single MCP session for callers that need multiple tool calls."""
        if server not in self.SERVER_CONFIGS:
            raise ValueError(f"Unknown MCP server: {server}")

        client = self._get_or_create_client(server)
        try:
            async with client.session(server) as session:
                cached_tool_count = len(self._tool_cache.get(server, []))
                self._server_status[server] = self._build_status_entry(
                    server,
                    "healthy",
                    tool_count=cached_tool_count,
                )
                yield session
        except Exception as exc:
            self._tool_cache.pop(server, None)
            self._clients.pop(server, None)
            self._server_status[server] = self._build_status_entry(
                server,
                "unavailable",
                error=self._format_error(exc),
            )
            app_logger.warning(
                f"MCP server session failed: {server} - {self._format_error(exc)}"
            )
            raise

    @staticmethod
    def _format_error(exc: Exception | None) -> str:
        if exc is None:
            return "unknown error"
        message = str(exc).strip()
        return message or exc.__class__.__name__

    async def _load_server_tools(self, server: str, *, force_refresh: bool = False) -> list[Any]:
        return await self._load_server_tools_with_overrides(
            server,
            force_refresh=force_refresh,
            timeout_override=None,
        )

    async def _load_server_tools_with_overrides(
        self,
        server: str,
        *,
        force_refresh: bool = False,
        timeout_override: float | None,
    ) -> list[Any]:
        if not force_refresh and server in self._tool_cache:
            return self._tool_cache[server]

        last_error: Exception | None = None
        timeout_seconds = (
            timeout_override if timeout_override is not None else self.SERVER_TOOL_LOAD_TIMEOUTS.get(server)
        )
        retry_attempts = self.SERVER_RETRY_ATTEMPTS.get(server, self.MCP_RETRY_ATTEMPTS)
        for attempt in range(1, retry_attempts + 1):
            try:
                if force_refresh or attempt > 1:
                    self._clients.pop(server, None)
                client = self._get_or_create_client(server)
                tool_task = client.get_tools()
                tools = (
                    await asyncio.wait_for(tool_task, timeout=timeout_seconds)
                    if timeout_seconds
                    else await tool_task
                )
                self._tool_cache[server] = tools
                self._server_status[server] = self._build_status_entry(
                    server,
                    "healthy",
                    tool_count=len(tools),
                )
                if attempt > 1:
                    app_logger.info(
                        f"MCP server recovered after retry: {server} ({len(tools)} tools, attempt {attempt})"
                    )
                else:
                    app_logger.info(f"MCP server ready: {server} ({len(tools)} tools)")
                return tools
            except Exception as exc:
                last_error = exc
                self._tool_cache.pop(server, None)
                self._clients.pop(server, None)
                if attempt < retry_attempts:
                    app_logger.warning(
                        f"MCP server start failed: {server} (attempt {attempt}/{retry_attempts}) - {self._format_error(exc)}"
                    )
                    await asyncio.sleep(self.MCP_RETRY_DELAY_SECONDS)
                    continue

        self._server_status[server] = self._build_status_entry(
            server,
            "unavailable",
            error=self._format_error(last_error),
        )
        app_logger.warning(
            f"MCP server unavailable: {server} - {self._format_error(last_error)}"
        )
        return []

    async def warmup(
        self,
        servers: list[str] | None = None,
        *,
        force_refresh: bool = False,
        timeout_overrides: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Probe requested servers and cache tools for the healthy ones."""
        target_servers = self._normalize_servers(servers)
        if not target_servers:
            return self._snapshot()

        await asyncio.gather(
            *(
                self._load_server_tools_with_overrides(
                    server,
                    force_refresh=force_refresh,
                    timeout_override=(timeout_overrides or {}).get(server),
                )
                for server in target_servers
            )
        )
        snapshot = self._snapshot()
        app_logger.info(
            "MCP warmup summary: "
            f"{snapshot['healthy_servers']} healthy, "
            f"{snapshot['unavailable_servers']} unavailable, "
            f"{snapshot['tool_count']} tools"
        )
        return snapshot

    async def close(self) -> None:
        """Drop cached clients and status so the next request can reinitialize cleanly."""
        self._clients = {}
        self._tool_cache = {}
        self._server_status = {
            server: self._build_status_entry(server, "uninitialized")
            for server in self.SERVER_CONFIGS
        }
        app_logger.info("MCP client manager state cleared")

    async def get_tools(
        self,
        servers: list[str] | None = None,
        *,
        force_refresh: bool = False,
        timeout_overrides: dict[str, float] | None = None,
    ) -> list[Any]:
        """Get tools from all healthy requested servers."""
        target_servers = self._normalize_servers(servers)
        if not target_servers:
            return []

        tool_groups = await asyncio.gather(
            *(
                self._load_server_tools_with_overrides(
                    server,
                    force_refresh=force_refresh,
                    timeout_override=(timeout_overrides or {}).get(server),
                )
                for server in target_servers
            )
        )

        tools = [tool for group in tool_groups for tool in group]
        app_logger.info(
            f"Loaded {len(tools)} MCP tools from "
            f"{sum(1 for server in target_servers if self._server_status[server]['status'] == 'healthy')} "
            f"healthy servers"
        )
        return tools

    def _snapshot(self) -> dict[str, Any]:
        healthy_servers = sum(
            1 for status in self._server_status.values() if status["status"] == "healthy"
        )
        unavailable_servers = sum(
            1 for status in self._server_status.values() if status["status"] == "unavailable"
        )
        uninitialized_servers = sum(
            1 for status in self._server_status.values() if status["status"] == "uninitialized"
        )
        tool_count = sum(len(tools) for tools in self._tool_cache.values())

        if unavailable_servers:
            overall_status = "degraded" if healthy_servers else "unavailable"
        elif healthy_servers:
            overall_status = "healthy"
        else:
            overall_status = "uninitialized"

        return {
            "status": overall_status,
            "healthy_servers": healthy_servers,
            "unavailable_servers": unavailable_servers,
            "uninitialized_servers": uninitialized_servers,
            "tool_count": tool_count,
            "servers": deepcopy(self._server_status),
        }


async def get_mcp_client(servers: list[str] | None = None) -> MCPClientManager:
    """Return the MCP client manager singleton."""
    return await MCPClientManager.get_instance(servers)


MCPClientManager.refresh_server_configs()
