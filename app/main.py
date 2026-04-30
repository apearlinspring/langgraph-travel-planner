"""
FastAPI application entrypoint.
"""
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import chat, conversations, users
from app.core.checkpointer import CheckpointerManager
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

    core_ready = (
        startup_complete
        and checkpointer_status["initialized"]
        and store_status["initialized"]
    )
    degraded = mcp_status["status"] in {"degraded", "unavailable"}

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
            mcp_snapshot = await mcp.warmup()
            if mcp_snapshot["status"] == "healthy":
                app_logger.info("MCP warmup completed with all servers healthy")
            else:
                app_logger.warning(
                    "MCP warmup completed in degraded mode: "
                    f"{mcp_snapshot['healthy_servers']} healthy, "
                    f"{mcp_snapshot['unavailable_servers']} unavailable"
                )

            app.state.startup_complete = True

            yield

            app.state.startup_complete = False
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
