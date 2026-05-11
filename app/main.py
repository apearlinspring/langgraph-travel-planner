"""
FastAPI application entrypoint.
"""
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import approvals, chat, conversations, maps, users
from app.core.checkpointer import CheckpointerManager
from app.core.session_lock import session_lock_manager
from app.core.store import StoreManager
from app.mcp_core.client import MCPClientManager
from app.utils.logger import app_logger

if sys.platform == "win32":
    # Keep psycopg-compatible event loops even when the app is imported directly
    # by tools such as FastAPI TestClient instead of going through app.run.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def build_readiness_payload(startup_complete: bool) -> tuple[dict, int]:
    """Summarize dependency readiness for probes and dashboards."""
    checkpointer_status = CheckpointerManager.get_status_snapshot()
    store_status = StoreManager.get_status_snapshot()
    mcp_status = MCPClientManager.get_status_snapshot()
    session_lock_status = session_lock_manager.get_status_snapshot()

    core_ready = (
        startup_complete
        and checkpointer_status["initialized"]
        and store_status["initialized"]
        and session_lock_status["status"] != "unavailable"
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
        "status": overall_status,
        "startup_complete": startup_complete,
        "services": {
            "checkpointer": checkpointer_status,
            "store": store_status,
            "mcp": mcp_status,
            "session_lock": session_lock_status,
        },
    }
    return payload, status_code


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage core dependency startup and shutdown."""
    import asyncio

    from app.core.checkpointer import checkpointer_lifespan
    from app.core.store import store_lifespan

    app.state.startup_complete = False

    loop = asyncio.get_running_loop()
    app_logger.info(f"FastAPI event loop: {type(loop).__name__}")
    app_logger.info("Starting application")

    async with checkpointer_lifespan():
        app_logger.info("Checkpointer ready")

        async with store_lifespan():
            app_logger.info("Store ready")

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

            app.state.startup_complete = True

            optional_servers = [
                server
                for server in MCPClientManager.OPTIONAL_STARTUP_SERVERS
                if server in MCPClientManager.SERVER_CONFIGS
            ]
            optional_warmup_task = None
            if optional_servers:
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

            app.state.startup_complete = False
            if optional_warmup_task is not None and not optional_warmup_task.done():
                optional_warmup_task.cancel()
            await mcp.close()
            app_logger.info("MCP manager closed")

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
