import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from langgraph.store.postgres import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.core.memory_models import (
    MemoryAuditEntry,
    TravelHistory,
    TravelRecord,
    UserMemory,
    UserProfile,
)
from app.utils.logger import app_logger


class StoreManager:
    """Singleton manager for the LangGraph PostgreSQL store."""

    _instance: Optional["StoreManager"] = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        self.store: Optional[AsyncPostgresStore] = None
        self.pool: Optional[AsyncConnectionPool] = None

    @classmethod
    async def get_instance(cls) -> "StoreManager":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance.initialize()
        elif cls._instance.store is None:
            async with cls._lock:
                if cls._instance.store is None:
                    await cls._instance.initialize()
        return cls._instance

    @classmethod
    def get_status_snapshot(cls) -> dict:
        """Return a lightweight health snapshot without touching the database."""
        manager = cls._instance
        pool = manager.pool if manager is not None else None
        initialized = bool(manager and manager.store is not None)
        return {
            "status": "ready" if initialized else "uninitialized",
            "initialized": initialized,
            "pool_open": bool(pool and not pool.closed),
        }

    async def initialize(self) -> None:
        """Initialize the underlying store and run migrations once."""
        if self.store is not None:
            return

        try:
            app_logger.info("Initializing PostgreSQL store")

            self.pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=2,
                max_size=20,
                timeout=30,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await self.pool.open()

            self.store = AsyncPostgresStore(self.pool)
            await self.store.setup()

            app_logger.info("PostgreSQL store is ready")
        except Exception:
            app_logger.exception("Failed to initialize PostgreSQL store")
            raise

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None
            self.store = None
            app_logger.info("PostgreSQL store pool closed")

    def get_store(self) -> AsyncPostgresStore:
        if self.store is None:
            raise RuntimeError("Store is not initialized")
        return self.store


async def get_store() -> AsyncPostgresStore:
    manager = await StoreManager.get_instance()
    return manager.get_store()


@asynccontextmanager
async def store_lifespan():
    manager = await StoreManager.get_instance()
    try:
        yield manager.get_store()
    finally:
        await manager.close()


class UserMemoryService:
    """Read and write long-term user memory via LangGraph store."""

    def __init__(self, store: AsyncPostgresStore) -> None:
        self.store = store

    def _get_current_time(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _prepare_audit_entries(
        self,
        entries: Optional[List[MemoryAuditEntry | dict]],
    ) -> list[MemoryAuditEntry]:
        prepared: list[MemoryAuditEntry] = []
        for entry in entries or []:
            audit_entry = (
                entry
                if isinstance(entry, MemoryAuditEntry)
                else MemoryAuditEntry(**entry)
            )
            if not audit_entry.recorded_at:
                audit_entry.recorded_at = self._get_current_time()
            prepared.append(audit_entry)
        return prepared

    def _merge_audit_log(
        self,
        existing: list[MemoryAuditEntry],
        entries: Optional[List[MemoryAuditEntry | dict]],
        *,
        max_entries: int = 40,
    ) -> list[MemoryAuditEntry]:
        merged = [*existing, *self._prepare_audit_entries(entries)]
        return merged[-max_entries:]

    async def get_user_profile(self, user_id: str) -> UserProfile:
        try:
            result = await self.store.aget(namespace=("user_profiles", user_id), key="profile")
            if result and result.value:
                return UserProfile(**result.value)
            return UserProfile()
        except Exception as exc:
            app_logger.error(f"Failed to load user profile for {user_id}: {exc}")
            return UserProfile()

    async def save_user_profile(self, user_id: str, profile: UserProfile) -> None:
        profile.updated_at = self._get_current_time()
        await self.store.aput(
            namespace=("user_profiles", user_id),
            key="profile",
            value=profile.model_dump(),
        )
        app_logger.info(f"Saved user profile: {user_id}")

    async def update_travel_styles(
        self,
        user_id: str,
        styles: List[str],
        *,
        audit_entries: Optional[List[MemoryAuditEntry | dict]] = None,
    ) -> None:
        profile = await self.get_user_profile(user_id)
        profile.travel_styles = list(set(profile.travel_styles).union(styles))
        profile.memory_audit_log = self._merge_audit_log(
            profile.memory_audit_log,
            audit_entries,
        )
        await self.save_user_profile(user_id, profile)

    async def update_dietary_restrictions(
        self,
        user_id: str,
        restrictions: List[str],
        *,
        audit_entries: Optional[List[MemoryAuditEntry | dict]] = None,
    ) -> None:
        profile = await self.get_user_profile(user_id)
        profile.dietary_restrictions = list(set(profile.dietary_restrictions).union(restrictions))
        profile.memory_audit_log = self._merge_audit_log(
            profile.memory_audit_log,
            audit_entries,
        )
        await self.save_user_profile(user_id, profile)

    async def update_food_preferences(
        self,
        user_id: str,
        preferences: List[str],
        *,
        audit_entries: Optional[List[MemoryAuditEntry | dict]] = None,
    ) -> None:
        profile = await self.get_user_profile(user_id)
        profile.food_preferences = list(set(profile.food_preferences).union(preferences))
        profile.memory_audit_log = self._merge_audit_log(
            profile.memory_audit_log,
            audit_entries,
        )
        await self.save_user_profile(user_id, profile)

    async def get_travel_history(self, user_id: str) -> TravelHistory:
        try:
            result = await self.store.aget(namespace=("travel_history", user_id), key="history")
            if result and result.value:
                return TravelHistory(**result.value)
            return TravelHistory()
        except Exception as exc:
            app_logger.error(f"Failed to load travel history for {user_id}: {exc}")
            return TravelHistory()

    async def save_travel_history(self, user_id: str, history: TravelHistory) -> None:
        history.updated_at = self._get_current_time()
        await self.store.aput(
            namespace=("travel_history", user_id),
            key="history",
            value=history.model_dump(),
        )
        app_logger.info(f"Saved travel history: {user_id}")

    async def add_completed_trip(
        self,
        user_id: str,
        destination: str,
        start_date: str,
        end_date: str,
        visited_attractions: List[str],
        *,
        audit_entries: Optional[List[MemoryAuditEntry | dict]] = None,
    ) -> None:
        history = await self.get_travel_history(user_id)
        history.completed_trips.append(
            TravelRecord(
                destination=destination,
                start_date=start_date,
                end_date=end_date,
                visited_attractions=visited_attractions,
            )
        )
        history.visited_attractions = list(
            set(history.visited_attractions).union(visited_attractions)
        )
        if audit_entries is None:
            audit_entries = [
                MemoryAuditEntry(
                    field="history.completed_trips",
                    value=destination,
                    source="memory_tool:add_travel_record_tool",
                    reason="用户陈述历史出行记录，可作为避免重复推荐的长期事实",
                    confidence=0.75,
                    scope="stable",
                    accepted=True,
                )
            ]
        history.memory_audit_log = self._merge_audit_log(
            history.memory_audit_log,
            audit_entries,
        )
        await self.save_travel_history(user_id, history)
        app_logger.info(f"Added completed trip for {user_id}: {destination}")

    async def update_accommodation_preference(
        self,
        user_id: str,
        preferred_types: Optional[List[str]] = None,
        avg_budget: Optional[float] = None,
        *,
        audit_entries: Optional[List[MemoryAuditEntry | dict]] = None,
    ) -> None:
        history = await self.get_travel_history(user_id)

        if preferred_types:
            history.accommodation_preference.preferred_types = list(
                set(history.accommodation_preference.preferred_types).union(preferred_types)
            )

        if avg_budget is not None:
            current = history.accommodation_preference.avg_budget_per_night
            history.accommodation_preference.avg_budget_per_night = (
                (current + avg_budget) / 2 if current is not None else avg_budget
            )
        history.memory_audit_log = self._merge_audit_log(
            history.memory_audit_log,
            audit_entries,
        )

        await self.save_travel_history(user_id, history)
        app_logger.info(f"Updated accommodation preference for {user_id}")

    async def get_visited_destinations(self, user_id: str) -> List[str]:
        history = await self.get_travel_history(user_id)
        return list({trip.destination for trip in history.completed_trips})

    async def get_visited_attractions(self, user_id: str) -> List[str]:
        history = await self.get_travel_history(user_id)
        return history.visited_attractions

    async def search_memories(self, user_id: str, query: str):
        return await self.store.asearch(
            namespace=("user_profiles", user_id),
            query=query,
            limit=5,
        )

    async def get_user_memory(self, user_id: str) -> UserMemory:
        profile, history = await asyncio.gather(
            self.get_user_profile(user_id),
            self.get_travel_history(user_id),
        )
        return UserMemory(user_id=user_id, profile=profile, history=history)

    async def format_memory_for_prompt(self, user_id: str) -> str:
        memory = await self.get_user_memory(user_id)
        parts = ["**用户历史偏好**："]

        if memory.profile.travel_styles:
            parts.append(f"- 旅行风格：{', '.join(memory.profile.travel_styles)}")
        if memory.profile.dietary_restrictions:
            parts.append(f"- 饮食禁忌：{', '.join(memory.profile.dietary_restrictions)}")
        if memory.profile.food_preferences:
            parts.append(f"- 饮食偏好：{', '.join(memory.profile.food_preferences)}")

        if memory.history.completed_trips:
            destinations = list({trip.destination for trip in memory.history.completed_trips})
            parts.append(f"- 去过的目的地：{', '.join(destinations[-5:])}")

        if memory.history.visited_attractions:
            parts.append(
                f"- 去过的景点：{', '.join(memory.history.visited_attractions[-10:])}（最近10个）"
            )

        acc_pref = memory.history.accommodation_preference
        if acc_pref.preferred_types:
            parts.append(f"- 住宿偏好：{', '.join(acc_pref.preferred_types)}")
        if acc_pref.avg_budget_per_night:
            parts.append(f"- 住宿预算：约 {acc_pref.avg_budget_per_night:.0f} 元/晚")

        audit_lines = self._format_memory_audit_for_prompt(
            [*memory.profile.memory_audit_log, *memory.history.memory_audit_log]
        )
        if audit_lines:
            parts.append("- 记忆依据：" + "；".join(audit_lines))

        if len(parts) == 1:
            return ""
        return "\n".join(parts)

    def _format_memory_audit_for_prompt(
        self,
        audit_log: list[MemoryAuditEntry],
        *,
        limit: int = 4,
    ) -> list[str]:
        accepted = [entry for entry in audit_log if entry.accepted]
        lines: list[str] = []
        for entry in accepted[-limit:]:
            confidence = f"{entry.confidence:.2f}"
            lines.append(
                f"{entry.field}={entry.value}（来源：{entry.source}，"
                f"抽取方式：{entry.extraction_method}，"
                f"原因：{entry.reason}，置信度：{confidence}）"
            )
        return lines


async def get_user_memory_service() -> UserMemoryService:
    store = await get_store()
    return UserMemoryService(store)
