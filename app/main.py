"""
FastAPI application entrypoint.
"""
import asyncio
import sys
import time
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import (
    admin,
    approvals,
    chat,
    conversations,
    guide_import,
    maps,
    mock_checkout,
    users,
)
from app.config import (
    RUNTIME_READINESS_VERSION,
    runtime_configuration_snapshot,
    settings,
)
from app.core.approval import ApprovalGovernanceManager
from app.core.checkpointer import CheckpointerManager
from app.core.rate_limit import ApiRateLimitMiddleware
from app.core.resilience import capture_runtime_step
from app.core.session_lock import session_lock_manager
from app.core.store import StoreManager
from app.mcp_core.client import MCPClientManager
from app.utils.logger import app_logger

CSP_REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
CSP_REPORT_ONLY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' https://cdn.bootcdn.net https://webapi.amap.com",
        "style-src 'self' https://cdn.bootcdn.net",
        (
            "img-src 'self' data: https://images.unsplash.com "
            "https://*.tile.openstreetmap.org https://*.tile.opentopomap.org "
            "https://*.basemaps.cartocdn.com"
        ),
        "font-src 'self' data: https://cdn.bootcdn.net",
        "connect-src 'self' http://localhost:8000 http://127.0.0.1:8000",
    ]
)

if sys.platform == "win32":
    # Keep psycopg-compatible event loops even when the app is imported directly
    # by tools such as FastAPI TestClient instead of going through app.run.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _append_finding(dependency: dict, finding: str) -> None:
    findings = dependency.setdefault("findings", [])
    if finding and finding not in findings:
        findings.append(finding)


def _set_dependency_status(
    dependencies: dict[str, dict],
    key: str,
    status: str,
    *,
    finding: str | None = None,
    details: dict | None = None,
) -> None:
    dependency = dependencies.get(key)
    if dependency is None:
        return
    dependency["status"] = status
    if finding:
        _append_finding(dependency, finding)
    if details:
        dependency.setdefault("details", {}).update(details)


def _dependency_missing_required(dependency: dict) -> bool:
    return dependency.get("requirement") == "required" and dependency.get("status") in {
        "blocked",
        "not_ready",
        "unavailable",
    }


def build_runtime_dependency_payload(
    *,
    checkpointer_status: dict,
    store_status: dict,
    mcp_status: dict,
    session_lock_status: dict,
) -> dict:
    """Build the structured runtime dependency matrix for readiness output."""

    config_snapshot = runtime_configuration_snapshot(app_env=settings.app_env)
    dependencies = deepcopy(config_snapshot["dependencies"])

    postgresql = dependencies.get("postgresql", {})
    if postgresql.get("status") == "blocked":
        _set_dependency_status(
            dependencies,
            "postgresql",
            "not_ready",
            finding="PostgreSQL required environment is missing or placeholder-like.",
        )
    elif checkpointer_status.get("initialized") and store_status.get("initialized"):
        _set_dependency_status(
            dependencies,
            "postgresql",
            "ready",
            details={
                "checkpointer": checkpointer_status.get("status"),
                "store": store_status.get("status"),
            },
        )
    else:
        _set_dependency_status(
            dependencies,
            "postgresql",
            "not_ready",
            finding="Checkpointer or Store is not initialized.",
            details={
                "checkpointer": checkpointer_status.get("status"),
                "store": store_status.get("status"),
            },
        )

    redis_requirement = dependencies.get("redis", {}).get("requirement")
    lock_status = session_lock_status.get("status")
    if lock_status == "ready":
        redis_status = "ready"
    elif lock_status == "degraded":
        redis_status = "not_ready" if redis_requirement == "required" else "degraded"
    else:
        redis_status = "not_ready" if redis_requirement == "required" else "degraded"
    _set_dependency_status(
        dependencies,
        "redis",
        redis_status,
        finding=session_lock_status.get("reason"),
        details={
            "session_lock_backend": session_lock_status.get("backend"),
            "configured_backend": session_lock_status.get("configured_backend"),
            "redis_available": session_lock_status.get("redis_available"),
        },
    )

    llm_dependency = dependencies.get("llm", {})
    if llm_dependency.get("status") == "configured":
        _set_dependency_status(dependencies, "llm", "ready")
    elif llm_dependency.get("requirement") == "required":
        _set_dependency_status(
            dependencies,
            "llm",
            "not_ready",
            finding="DASHSCOPE_API_KEY is required for this environment.",
        )
    else:
        _set_dependency_status(dependencies, "llm", "not_configured")

    rag_dependency = dependencies.get("rag_vector_store", {})
    if rag_dependency.get("status") == "configured":
        _set_dependency_status(
            dependencies,
            "rag_vector_store",
            "ready",
        )
    else:
        rag_requirement = rag_dependency.get("requirement")
        _set_dependency_status(
            dependencies,
            "rag_vector_store",
            "not_ready" if rag_requirement == "required" else "not_configured",
        )

    mcp_raw_status = mcp_status.get("status")
    if mcp_raw_status == "healthy":
        mcp_dependency_status = "ready"
    elif mcp_raw_status in {"degraded", "unavailable"}:
        mcp_dependency_status = "degraded"
    else:
        mcp_dependency_status = "uninitialized"
    _set_dependency_status(
        dependencies,
        "mcp",
        mcp_dependency_status,
        finding="Some MCP services are unavailable." if mcp_dependency_status == "degraded" else None,
        details={
            "healthy_servers": mcp_status.get("healthy_servers"),
            "unavailable_servers": mcp_status.get("unavailable_servers"),
            "uninitialized_servers": mcp_status.get("uninitialized_servers"),
            "tool_count": mcp_status.get("tool_count"),
        },
    )

    for key in ("map", "search", "hotel", "flight", "langsmith", "auth_jwt"):
        dependency = dependencies.get(key)
        if not dependency:
            continue
        if dependency.get("status") == "configured":
            _set_dependency_status(dependencies, key, "ready")
        elif dependency.get("requirement") == "required":
            _set_dependency_status(dependencies, key, "not_ready")
        else:
            _set_dependency_status(dependencies, key, "not_configured")

    _set_dependency_status(
        dependencies,
        "rail",
        "service_checked" if mcp_status.get("servers", {}).get("12306-mcp") else "uninitialized",
    )

    missing_required = [
        key for key, dependency in dependencies.items() if _dependency_missing_required(dependency)
    ]
    degraded_optional = [
        key
        for key, dependency in dependencies.items()
        if dependency.get("requirement") == "optional"
        and dependency.get("status") in {"degraded", "not_configured", "uninitialized"}
    ]
    return {
        "version": RUNTIME_READINESS_VERSION,
        "environment": config_snapshot["environment"],
        "value_policy": config_snapshot["value_policy"],
        "dotenv_present": config_snapshot["dotenv_present"],
        "dependencies": dependencies,
        "missing_required": missing_required,
        "degraded_optional": degraded_optional,
    }


def build_readiness_payload(startup_complete: bool) -> tuple[dict, int]:
    """Summarize dependency readiness for probes and dashboards."""
    checkpointer_status = CheckpointerManager.get_status_snapshot()
    store_status = StoreManager.get_status_snapshot()
    mcp_status = MCPClientManager.get_status_snapshot()
    session_lock_status = session_lock_manager.get_status_snapshot()
    approval_governance_status = ApprovalGovernanceManager.get_status_snapshot()
    runtime_payload = build_runtime_dependency_payload(
        checkpointer_status=checkpointer_status,
        store_status=store_status,
        mcp_status=mcp_status,
        session_lock_status=session_lock_status,
    )

    core_ready = (
        startup_complete
        and checkpointer_status["initialized"]
        and store_status["initialized"]
        and session_lock_status["status"] != "unavailable"
        and approval_governance_status["ready"]
        and not runtime_payload["missing_required"]
    )
    degraded = (
        mcp_status["status"] in {"degraded", "unavailable"}
        or session_lock_status["status"] == "degraded"
    )

    if core_ready and not degraded:
        overall_status = "ready"
        status_code = 200
    elif core_ready:
        overall_status = "degraded"
        status_code = 200
    else:
        overall_status = "not_ready"
        status_code = 503

    blocking_items = list(runtime_payload["missing_required"])
    if not startup_complete:
        blocking_items.append("startup")
    if not checkpointer_status["initialized"]:
        blocking_items.append("checkpointer")
    if not store_status["initialized"]:
        blocking_items.append("store")
    if session_lock_status["status"] == "unavailable":
        blocking_items.append("session_lock")
    if not approval_governance_status["ready"]:
        blocking_items.append("approval_governance")

    payload = {
        "version": RUNTIME_READINESS_VERSION,
        "status": overall_status,
        "environment": runtime_payload["environment"],
        "startup_complete": startup_complete,
        "startup": getattr(app.state, "startup", None),
        "missing_required": runtime_payload["missing_required"],
        "blocking_items": sorted(dict.fromkeys(blocking_items)),
        "degraded_optional": runtime_payload["degraded_optional"],
        "dependencies": runtime_payload["dependencies"],
        "services": {
            "checkpointer": checkpointer_status,
            "store": store_status,
            "mcp": mcp_status,
            "session_lock": session_lock_status,
            "approval_governance": approval_governance_status,
        },
    }
    return payload, status_code


def _new_startup_state() -> dict[str, Any]:
    return {
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "steps": {},
    }


def _set_startup_step(
    app: FastAPI,
    step: str,
    status: str,
    *,
    elapsed_seconds: float | None = None,
    timeout_seconds: float | None = None,
    error_type: str | None = None,
    error: str | None = None,
) -> None:
    startup = getattr(app.state, "startup", None)
    if startup is None:
        startup = _new_startup_state()
        app.state.startup = startup
    payload: dict[str, Any] = {"status": status}
    if elapsed_seconds is not None:
        payload["elapsed_seconds"] = elapsed_seconds
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    if error_type is not None:
        payload["error_type"] = error_type
    if error is not None:
        payload["error"] = error
    startup.setdefault("steps", {})[step] = payload


async def _startup_step(
    app: FastAPI,
    step: str,
    operation: Callable[[], Awaitable[Any]],
    *,
    timeout_seconds: float | None,
) -> Any | None:
    _set_startup_step(app, step, "running", timeout_seconds=timeout_seconds)
    result, snapshot = await capture_runtime_step(
        step,
        operation,
        timeout_seconds=timeout_seconds,
    )
    _set_startup_step(app, step, **snapshot.to_dict())
    if snapshot.status == "ready":
        app_logger.info(
            "Runtime startup step ready: "
            f"{step} in {snapshot.elapsed_seconds:.3f}s"
        )
    else:
        app_logger.warning(
            "Runtime startup step did not become ready: "
            f"{step} status={snapshot.status} error={snapshot.error}"
        )
    return result


async def _warmup_mcp_servers(
    *,
    servers: list[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    mcp = await MCPClientManager.get_instance()
    return await mcp.warmup(
        servers=servers,
        timeout_overrides={server: timeout_seconds for server in servers},
    )


async def _run_runtime_startup(app: FastAPI) -> None:
    """Initialize slow dependencies in the background after liveness is available."""

    app.state.startup = _new_startup_state()
    app.state.startup_complete = False
    ApprovalGovernanceManager.configure_uninitialized(settings.app_env)

    dependency_timeout = settings.runtime_startup_dependency_timeout_seconds

    checkpointer_task = asyncio.create_task(
        _startup_step(
            app,
            "checkpointer",
            CheckpointerManager.get_instance,
            timeout_seconds=dependency_timeout,
        ),
        name="startup:checkpointer",
    )
    store_task = asyncio.create_task(
        _startup_step(
            app,
            "store",
            StoreManager.get_instance,
            timeout_seconds=dependency_timeout,
        ),
        name="startup:store",
    )
    approval_task = asyncio.create_task(
        _startup_step(
            app,
            "approval_governance",
            ApprovalGovernanceManager.verify_database,
            timeout_seconds=dependency_timeout,
        ),
        name="startup:approval_governance",
    )

    MCPClientManager.refresh_server_configs()
    startup_servers = MCPClientManager.get_startup_server_names()
    if startup_servers:
        mcp_task = asyncio.create_task(
            _startup_step(
                app,
                "mcp_startup_servers",
                lambda: _warmup_mcp_servers(
                    servers=startup_servers,
                    timeout_seconds=settings.runtime_mcp_startup_timeout_seconds,
                ),
                timeout_seconds=(
                    max(len(startup_servers), 1)
                    * settings.runtime_mcp_startup_timeout_seconds
                    + 1.0
                ),
            ),
            name="startup:mcp_startup_servers",
        )
    else:
        _set_startup_step(app, "mcp_startup_servers", "skipped")
        mcp_task = None

    checkpointer_manager, store_manager, approval_snapshot = await asyncio.gather(
        checkpointer_task,
        store_task,
        approval_task,
    )
    if checkpointer_manager is None:
        manager = getattr(CheckpointerManager, "_instance", None)
        if manager is not None:
            await manager.close()
    if store_manager is None:
        manager = getattr(StoreManager, "_instance", None)
        if manager is not None:
            await manager.close()
    app.state.startup_complete = (
        checkpointer_manager is not None
        and store_manager is not None
        and isinstance(approval_snapshot, dict)
        and approval_snapshot.get("status") == "ready"
    )

    optional_servers = [
        server
        for server in MCPClientManager.OPTIONAL_STARTUP_SERVERS
        if server in MCPClientManager.SERVER_CONFIGS
    ]
    if optional_servers:
        await _startup_step(
            app,
            "mcp_optional_servers",
            lambda: _warmup_mcp_servers(
                servers=optional_servers,
                timeout_seconds=settings.runtime_mcp_optional_startup_timeout_seconds,
            ),
            timeout_seconds=(
                max(len(optional_servers), 1)
                * settings.runtime_mcp_optional_startup_timeout_seconds
                + 1.0
            ),
        )
    else:
        _set_startup_step(app, "mcp_optional_servers", "skipped")

    if mcp_task is not None:
        await mcp_task

    startup = app.state.startup
    startup["finished_at"] = time.time()
    startup["status"] = "ready" if app.state.startup_complete else "not_ready"


def _consume_startup_task_result(task: asyncio.Task) -> None:
    with suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc is not None:
            app_logger.error(f"Runtime background startup task failed: {exc}")


async def _close_runtime_manager_singletons() -> None:
    mcp = getattr(MCPClientManager, "_instance", None)
    store_manager = getattr(StoreManager, "_instance", None)
    checkpointer_manager = getattr(CheckpointerManager, "_instance", None)
    if mcp is not None:
        await mcp.close()
        app_logger.info("MCP manager closed")
    if store_manager is not None:
        await store_manager.close()
    if checkpointer_manager is not None:
        await checkpointer_manager.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage core dependency startup and shutdown."""
    app.state.startup_complete = False
    settings.validate_security_baseline()

    loop = asyncio.get_running_loop()
    app_logger.info(f"FastAPI event loop: {type(loop).__name__}")
    app_logger.info("Starting application")

    startup_task = asyncio.create_task(
        _run_runtime_startup(app),
        name="runtime-background-startup",
    )
    startup_task.add_done_callback(_consume_startup_task_result)

    try:
        yield
    finally:
        app.state.startup_complete = False
        if not startup_task.done():
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task
        await _close_runtime_manager_singletons()

    app_logger.info("Application stopped")


app = FastAPI(
    title="LangGraph Travel Planner",
    description="Multi-agent travel planning service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    ApiRateLimitMiddleware,
    enabled=settings.api_rate_limit_enabled,
    requests_per_window=settings.api_rate_limit_requests_per_window,
    window_seconds=settings.api_rate_limit_window_seconds,
    backend=settings.api_rate_limit_backend,
    redis_url=settings.redis_url,
    key_prefix=settings.api_rate_limit_key_prefix,
    protected_prefixes=settings.api_rate_limit_protected_prefixes,
    exempt_paths=settings.api_rate_limit_exempt_paths,
    local_fallback=settings.api_rate_limit_local_fallback,
    operation_timeout_seconds=settings.api_rate_limit_redis_operation_timeout_seconds,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Cache-Control"],
    allow_origin_regex=settings.allow_origin_regex,
)


@app.middleware("http")
async def append_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(CSP_REPORT_ONLY_HEADER, CSP_REPORT_ONLY_POLICY)
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    if request.url.scheme == "https" or settings.auth_cookie_secure_resolved:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

app.include_router(users.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(guide_import.router, prefix="/api/v1")
app.include_router(maps.router, prefix="/api/v1")
app.include_router(mock_checkout.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "LangGraph Travel Planner",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    payload, status_code = build_readiness_payload(
        startup_complete=getattr(app.state, "startup_complete", False)
    )
    return JSONResponse(status_code=status_code, content=payload)
