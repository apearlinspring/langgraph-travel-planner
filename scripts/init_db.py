"""数据库初始化与迁移入口。"""
import asyncio
import argparse
import sys
from pathlib import Path
from typing import Any

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_BOOTSTRAP_IMPORT_ERROR: ImportError | None = None
command: Any = None
Config: Any = None
AsyncConnectionPool: Any = None
AsyncPostgresSaver: Any = None
AsyncPostgresStore: Any = None
settings: Any = None
normalize_runtime_environment: Any = None
app_logger: Any = None
create_business_tables_legacy: Any = None

try:
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
except ImportError as exc:
    _BOOTSTRAP_IMPORT_ERROR = exc


ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"


def _log_info(message: str) -> None:
    if app_logger is not None:
        app_logger.info(message)
    else:
        print(message)


def _log_warning(message: str) -> None:
    if app_logger is not None:
        app_logger.warning(message)
    else:
        print(message, file=sys.stderr)


def _log_error(message: str) -> None:
    if app_logger is not None:
        app_logger.error(message)
    else:
        print(message, file=sys.stderr)


def _missing_dependency_error(error: ImportError) -> str:
    missing = getattr(error, "name", None) or str(error)
    return (
        "数据库初始化尚未开始，因为 Python 运行依赖缺失："
        f"{missing}。请先安装项目依赖，例如执行 uv sync，"
        "或在已创建的虚拟环境中执行 .\\.venv\\Scripts\\python -m pip install -r requirements.txt。"
        "依赖安装完成后再运行 .\\.venv\\Scripts\\python -m scripts.init_db --mode bootstrap。"
    )


def _ensure_runtime_imports() -> None:
    if _BOOTSTRAP_IMPORT_ERROR is not None:
        raise RuntimeError(_missing_dependency_error(_BOOTSTRAP_IMPORT_ERROR)) from _BOOTSTRAP_IMPORT_ERROR


async def _probe_postgres_tcp() -> None:
    """Fail fast when PostgreSQL is not reachable before heavier bootstrap work."""

    timeout = settings.postgres_connect_timeout_seconds
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.postgres_host, settings.postgres_port),
            timeout=timeout,
        )
    except Exception as error:
        raise RuntimeError(
            "PostgreSQL TCP 连接不可用："
            f"{settings.postgres_host}:{settings.postgres_port} "
            f"在 {timeout:.1f}s 内未连通。请先启动数据库或修正 POSTGRES_HOST/POSTGRES_PORT。"
        ) from error
    writer.close()
    await writer.wait_closed()


def _actionable_database_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return (
        "数据库初始化失败，已停止。请按顺序检查："
        "1) Docker Desktop 是否正在运行；"
        "2) docker compose up -d postgres 是否成功，必要时查看 docker compose ps postgres；"
        "3) .env 或环境变量中的 POSTGRES_HOST/PORT/DB/USER/PASSWORD；"
        "4) pgvector/pgvector 镜像是否支持 CREATE EXTENSION vector；"
        "5) 业务表迁移可用时执行 alembic upgrade head。"
        f" 原始错误类型：{error.__class__.__name__}，摘要：{message}"
    )


def build_alembic_config() -> Config:
    """Build Alembic config without exposing database credentials in alembic.ini."""

    _ensure_runtime_imports()
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def run_business_migrations(revision: str = "head") -> None:
    """Apply versioned business-table migrations."""

    _ensure_runtime_imports()
    _log_info(f"执行业务表 Alembic 迁移到 revision={revision}")
    command.upgrade(build_alembic_config(), revision)
    _log_info("[ok] 业务表 Alembic 迁移完成")


async def _init_langgraph_tables(db_url: str) -> None:
    """Initialize LangGraph-owned Checkpointer and Store tables."""

    _ensure_runtime_imports()
    _log_info("初始化 LangGraph Checkpointer 表...")
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        await checkpointer.setup()
    _log_info("[ok] LangGraph Checkpointer 表创建/迁移成功")

    _log_info("初始化 LangGraph Store 表...")
    async with AsyncPostgresStore.from_conn_string(db_url) as store:
        await store.setup()
    _log_info("[ok] LangGraph Store 表创建/迁移成功")


async def _enable_pgvector(db_url: str) -> None:
    """Enable pgvector extension for LangGraph Store vector indexing."""

    _ensure_runtime_imports()
    _log_info("启用 pgvector 扩展...")
    async with AsyncConnectionPool(
        conninfo=db_url,
        min_size=1,
        max_size=2,
        timeout=settings.postgres_pool_timeout_seconds,
        kwargs={"connect_timeout": settings.postgres_connect_timeout_seconds},
    ) as pool:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                await conn.commit()
    _log_info("[ok] pgvector 扩展启用成功")


async def init_database(
    *,
    revision: str = "head",
    apply_business_migrations: bool = True,
    initialize_langgraph: bool = True,
    enable_pgvector: bool = True,
    legacy_create_all: bool = False,
) -> None:
    """Initialize or migrate database objects according to explicit boundaries."""

    _ensure_runtime_imports()
    db_url = settings.database_url
    _log_info(f"连接数据库: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")

    try:
        await _probe_postgres_tcp()

        if legacy_create_all:
            runtime_env = normalize_runtime_environment(settings.app_env)
            if runtime_env in {"staging", "production"}:
                raise RuntimeError("staging/production 不允许使用 legacy create_all 初始化业务表")
            _log_warning("使用 legacy create_all 创建业务表，仅限本地一次性调试")
            await create_business_tables_legacy()
            _log_info("[ok] legacy 业务表 create_all 完成")
        elif apply_business_migrations:
            run_business_migrations(revision)

        if initialize_langgraph:
            await _init_langgraph_tables(db_url)

        if enable_pgvector:
            await _enable_pgvector(db_url)

        _log_info("数据库初始化/迁移完成")
    except Exception as e:
        _log_error(f"[failed] 数据库初始化失败: {e}")
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
    try:
        _ensure_runtime_imports()
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
    except Exception as error:
        _log_error(_actionable_database_error(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
