"""数据库初始化与迁移入口。"""
import asyncio
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from alembic import command
from alembic.config import Config
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from app.config import settings
from app.config import normalize_runtime_environment
from app.utils.logger import app_logger
import app.models  # noqa: F401
from app.models.base import init_db as create_business_tables_legacy


ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"


def build_alembic_config() -> Config:
    """Build Alembic config without exposing database credentials in alembic.ini."""

    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def run_business_migrations(revision: str = "head") -> None:
    """Apply versioned business-table migrations."""

    app_logger.info(f"执行业务表 Alembic 迁移到 revision={revision}")
    command.upgrade(build_alembic_config(), revision)
    app_logger.info("✅ 业务表 Alembic 迁移完成")


async def _init_langgraph_tables(db_url: str) -> None:
    """Initialize LangGraph-owned Checkpointer and Store tables."""

    app_logger.info("初始化 LangGraph Checkpointer 表...")
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        await checkpointer.setup()
    app_logger.info("✅ LangGraph Checkpointer 表创建/迁移成功")

    app_logger.info("初始化 LangGraph Store 表...")
    async with AsyncPostgresStore.from_conn_string(db_url) as store:
        await store.setup()
    app_logger.info("✅ LangGraph Store 表创建/迁移成功")


async def _enable_pgvector(db_url: str) -> None:
    """Enable pgvector extension for LangGraph Store vector indexing."""

    app_logger.info("启用 pgvector 扩展...")
    async with AsyncConnectionPool(conninfo=db_url, min_size=1, max_size=2) as pool:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                await conn.commit()
    app_logger.info("✅ pgvector 扩展启用成功")


async def init_database(
    *,
    revision: str = "head",
    apply_business_migrations: bool = True,
    initialize_langgraph: bool = True,
    enable_pgvector: bool = True,
    legacy_create_all: bool = False,
) -> None:
    """Initialize or migrate database objects according to explicit boundaries."""

    db_url = settings.database_url
    app_logger.info(f"连接数据库: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")

    try:
        if legacy_create_all:
            runtime_env = normalize_runtime_environment(settings.app_env)
            if runtime_env in {"staging", "production"}:
                raise RuntimeError("staging/production 不允许使用 legacy create_all 初始化业务表")
            app_logger.warning("使用 legacy create_all 创建业务表，仅限本地一次性调试")
            await create_business_tables_legacy()
            app_logger.info("✅ legacy 业务表 create_all 完成")
        elif apply_business_migrations:
            run_business_migrations(revision)

        if initialize_langgraph:
            await _init_langgraph_tables(db_url)

        if enable_pgvector:
            await _enable_pgvector(db_url)

        app_logger.info("数据库初始化/迁移完成")
    except Exception as e:
        app_logger.error(f"❌ 数据库初始化失败: {e}")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("bootstrap", "migrate", "langgraph", "pgvector"),
        default="bootstrap",
        help=(
            "bootstrap=业务迁移+LangGraph 表+pgvector；"
            "migrate=仅业务 Alembic 迁移；langgraph=仅 LangGraph 表；pgvector=仅扩展。"
        ),
    )
    parser.add_argument(
        "--revision",
        default="head",
        help="Alembic revision to upgrade to when business migrations run.",
    )
    parser.add_argument(
        "--legacy-create-all",
        action="store_true",
        help="Use SQLAlchemy create_all for local throwaway development only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = args.mode
    asyncio.run(
        init_database(
            revision=args.revision,
            apply_business_migrations=mode in {"bootstrap", "migrate"},
            initialize_langgraph=mode in {"bootstrap", "langgraph"},
            enable_pgvector=mode in {"bootstrap", "pgvector"},
            legacy_create_all=args.legacy_create_all,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
