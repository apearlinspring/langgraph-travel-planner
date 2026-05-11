"""
FastAPI application entrypoint.
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import approvals, chat, conversations, maps, users
from app.config import (
    PROJECT_ROOT,
    RUNTIME_READINESS_VERSION,
    runtime_configuration_snapshot,
    settings,
)
from app.core.approval import ApprovalGovernanceManager
from app.core.checkpointer import CheckpointerManager
from app.core.session_lock import session_lock_manager
from app.core.store import StoreManager
from app.mcp_core.client import MCPClientManager
from app.utils.logger import app_logger

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


def _has_vectorstore_files(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


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

    vectorstore_path = Path(settings.rag_vectorstore_path)
    if not vectorstore_path.is_absolute():
        vectorstore_path = PROJECT_ROOT / vectorstore_path
    if _has_vectorstore_files(vectorstore_path):
        _set_dependency_status(
            dependencies,
            "rag_vector_store",
            "ready",
            details={"path": str(vectorstore_path)},
        )
    else:
        rag_requirement = dependencies.get("rag_vector_store", {}).get("requirement")
        _set_dependency_status(
            dependencies,
            "rag_vector_store",
            "not_ready" if rag_requirement == "required" else "not_configured",
            finding="RAG vector store has not been initialized.",
            details={"path": str(vectorstore_path)},
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

    payload = {
        "version": RUNTIME_READINESS_VERSION,
        "status": overall_status,
        "environment": runtime_payload["environment"],
        "startup_complete": startup_complete,
        "missing_required": runtime_payload["missing_required"],
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage core dependency startup and shutdown."""
    import asyncio

    app.state.startup_complete = False

    loop = asyncio.get_running_loop()
    app_logger.info(f"FastAPI event loop: {type(loop).__name__}")
    app_logger.info("Starting application")

    checkpointer_manager = None
    store_manager = None
    mcp = None
    optional_warmup_task = None

    try:
        try:
            checkpointer_manager = await CheckpointerManager.get_instance()
            app_logger.info("Checkpointer ready")
        except Exception as exc:
            app_logger.exception("Checkpointer startup blocked readiness: %s", exc)

        try:
            store_manager = await StoreManager.get_instance()
            app_logger.info("Store ready")
        except Exception as exc:
            app_logger.exception("Store startup blocked readiness: %s", exc)

        try:
            mcp = await MCPClientManager.get_instance()
            startup_servers = MCPClientManager.get_startup_server_names()
            if len(startup_servers) != len(MCPClientManager.SERVER_CONFIGS):
                app_logger.info(
                    "Skipping optional MCP startup warmup for: "
                    + ", ".join(
                        server
                        for server in MCPClientManager.SERVER_CONFIGS
                        if server not in startup_servers
                    )
                )
            mcp_snapshot = await mcp.warmup(servers=startup_servers)
            if mcp_snapshot["status"] == "healthy":
                app_logger.info("MCP warmup completed with all servers healthy")
            else:
                app_logger.warning(
                    "MCP warmup completed in degraded mode: "
                    f"{mcp_snapshot['healthy_servers']} healthy, "
                    f"{mcp_snapshot['unavailable_servers']} unavailable"
                )
        except Exception as exc:
            app_logger.exception("MCP startup degraded readiness: %s", exc)

        approval_governance_snapshot = await ApprovalGovernanceManager.verify_database()
        if approval_governance_snapshot["status"] == "ready":
            app_logger.info("Approval governance persistence ready")
        else:
            app_logger.warning(
                "Approval governance is not fully ready: "
                f"{approval_governance_snapshot}"
            )

        app.state.startup_complete = (
            checkpointer_manager is not None
            and store_manager is not None
            and approval_governance_snapshot["status"] == "ready"
        )

        optional_servers = [
            server
            for server in MCPClientManager.OPTIONAL_STARTUP_SERVERS
            if server in MCPClientManager.SERVER_CONFIGS
        ]
        if mcp is not None and optional_servers:
            app_logger.info(
                "Starting optional MCP background warmup for: "
                + ", ".join(optional_servers)
            )
            optional_warmup_task = asyncio.create_task(
                mcp.warmup(
                    servers=optional_servers,
                    timeout_overrides={server: 180.0 for server in optional_servers},
                )
            )

        yield
    finally:
        app.state.startup_complete = False
        if optional_warmup_task is not None and not optional_warmup_task.done():
            optional_warmup_task.cancel()
        if mcp is not None:
            await mcp.close()
            app_logger.info("MCP manager closed")
        if store_manager is not None:
            await store_manager.close()
        if checkpointer_manager is not None:
            await checkpointer_manager.close()

    app_logger.info("Application stopped")


app = FastAPI(
    title="LangGraph Travel Planner",
    description="Multi-agent travel planning service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")
app.include_router(maps.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
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
