import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.utils.logger import app_logger


class CheckpointerManager:
    """Singleton manager for the LangGraph PostgreSQL checkpointer."""

    _instance: Optional["CheckpointerManager"] = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        self.pool: Optional[AsyncConnectionPool] = None
        self.checkpointer: Optional[AsyncPostgresSaver] = None

    @classmethod
    async def get_instance(cls) -> "CheckpointerManager":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance.initialize()
        elif cls._instance.checkpointer is None:
            async with cls._lock:
                if cls._instance.checkpointer is None:
                    await cls._instance.initialize()
        return cls._instance

    @classmethod
    def get_status_snapshot(cls) -> dict:
        """Return a lightweight health snapshot without touching the database."""
        manager = cls._instance
        pool = manager.pool if manager is not None else None
        initialized = bool(manager and manager.checkpointer is not None)
        return {
            "status": "ready" if initialized else "uninitialized",
            "initialized": initialized,
            "pool_open": bool(pool and not pool.closed),
        }

    async def initialize(self) -> None:
        """Initialize the connection pool and run required migrations once."""
        if self.checkpointer is not None:
            return

        try:
            app_logger.info("Initializing PostgreSQL checkpointer")

            self.pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=2,
                max_size=20,
                timeout=settings.postgres_pool_timeout_seconds,
                kwargs={
                    "autocommit": True,
                    "connect_timeout": settings.postgres_connect_timeout_seconds,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await self.pool.open()

            checkpointer = AsyncPostgresSaver(self.pool)
            await checkpointer.setup()
            self.checkpointer = checkpointer

            app_logger.info("PostgreSQL checkpointer is ready")
        except Exception:
            app_logger.exception("Failed to initialize PostgreSQL checkpointer")
            raise

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None
            self.checkpointer = None
            app_logger.info("PostgreSQL checkpointer pool closed")

    def get_checkpointer(self) -> AsyncPostgresSaver:
        if self.checkpointer is None:
            raise RuntimeError("Checkpointer is not initialized")
        return self.checkpointer


async def get_checkpointer() -> AsyncPostgresSaver:
    manager = await CheckpointerManager.get_instance()
    return manager.get_checkpointer()


@asynccontextmanager
async def checkpointer_lifespan():
    manager = await CheckpointerManager.get_instance()
    try:
        yield manager.get_checkpointer()
    finally:
        await manager.close()
