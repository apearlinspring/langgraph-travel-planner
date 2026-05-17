"""
初始化 RAG 系统
加载文档、切分、创建向量数据库
"""
import asyncio
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_RAG_IMPORT_ERROR: ImportError | None = None
DocumentManager: Any = None
AdvancedParentDocumentSplitter: Any = None
VectorStoreManager: Any = None
validate_internal_knowledge_base: Any = None
check_chroma_collection_readiness: Any = None
PUBLIC_VECTORSTORE_CONTRACT: Any = None
INTERNAL_VECTORSTORE_CONTRACT: Any = None
has_real_env_value: Any = None
settings: Any = None
app_logger: Any = None

try:
    from app.rag.document_loader import DocumentManager
    from app.rag.text_splitter import AdvancedParentDocumentSplitter
    from app.rag.vectorstore import VectorStoreManager
    from app.rag.contracts import validate_internal_knowledge_base
    from app.rag.readiness import (
        INTERNAL_VECTORSTORE_CONTRACT,
        PUBLIC_VECTORSTORE_CONTRACT,
        check_chroma_collection_readiness,
    )
    from app.config import PROJECT_ROOT, has_real_env_value, settings
    from app.utils.logger import app_logger
except ImportError as exc:
    _RAG_IMPORT_ERROR = exc


class RagInitializationError(RuntimeError):
    """Raised when RAG bootstrap cannot create a usable vector store."""


def _log_info(message: str) -> None:
    if app_logger is not None:
        app_logger.info(message)
    else:
        print(message)


def _log_error(message: str) -> None:
    if app_logger is not None:
        app_logger.error(message)
    else:
        print(message, file=sys.stderr)


def _missing_dependency_error(error: ImportError) -> str:
    missing = getattr(error, "name", None) or str(error)
    return (
        "RAG 初始化尚未开始，因为 Python 运行依赖缺失："
        f"{missing}。请先安装项目依赖，例如执行 uv sync，"
        "或在已创建的虚拟环境中执行 .\\.venv\\Scripts\\python -m pip install -r requirements.txt。"
        "如果缺的是 sentence-transformers 或 Chroma 相关依赖，安装后再运行 "
        ".\\.venv\\Scripts\\python -m scripts.init_rag。"
    )


def _ensure_runtime_imports() -> None:
    if _RAG_IMPORT_ERROR is not None:
        raise RagInitializationError(_missing_dependency_error(_RAG_IMPORT_ERROR)) from _RAG_IMPORT_ERROR


def _ensure_model_credentials() -> None:
    _ensure_runtime_imports()
    if has_real_env_value(settings.dashscope_api_key):
        return
    raise RagInitializationError(
        "blocked: RAG 初始化需要真实 DASHSCOPE_API_KEY。"
        "该密钥同时用于 DashScope embedding（向量嵌入）模型 text-embedding-v2，"
        "也用于后续 RAG query optimizer（查询优化器）/ LLM（大语言模型）相关能力。"
        "请在本机 .env 中配置 DASHSCOPE_API_KEY 后重新运行 "
        ".\\.venv\\Scripts\\python -m scripts.init_rag；不要把真实密钥写入文档、测试或提交。"
    )


def _actionable_rag_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    if message.startswith("blocked:"):
        return message
    return (
        "RAG 初始化失败，已停止。请检查："
        "1) data/documents/destinations/ 是否有公开目的地 Markdown 文档；"
        "2) data/documents/internal/ 的 metadata 是否通过 scripts/validate_rag_knowledge.py；"
        "3) DASHSCOPE_API_KEY 是否已配置，当前 embedding（嵌入向量）创建依赖 DashScope；"
        "4) sentence-transformers 模型依赖是否已安装并可下载；"
        "5) RAG_VECTORSTORE_PATH 与 RAG_INTERNAL_VECTORSTORE_PATH 指向的目录是否可写；"
        "6) 如果在离线环境运行，请先准备 embedding（嵌入向量）模型缓存。"
        f" 原始错误类型：{error.__class__.__name__}，摘要：{message}"
    )


def _resolve_project_path(configured_path: str | Path) -> Path:
    """Resolve a configured path using the same project-root rule as runtime readiness."""

    path = Path(configured_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _assert_safe_vectorstore_path(path: Path) -> None:
    """Reject paths that are too broad to replace as a generated vector store."""

    resolved = path.resolve()
    project_root = PROJECT_ROOT.resolve()
    unsafe_paths = {
        resolved.anchor,
        str(project_root),
        str(project_root / "data"),
        str(project_root / ".runtime"),
    }
    if str(resolved) in unsafe_paths or resolved.parent == resolved:
        raise RagInitializationError(
            f"blocked: refusing to refresh unsafe vector store path: {resolved}"
        )
    if len(resolved.parts) < 3:
        raise RagInitializationError(
            f"blocked: vector store path is too broad to refresh safely: {resolved}"
        )


def _new_refresh_auxiliary_path(target_dir: Path, kind: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    suffix = f"{timestamp}-{os.getpid()}-{uuid4().hex[:8]}"
    return target_dir.parent / f".rag-vectorstore-{kind}s" / f"{target_dir.name}-{suffix}"


def _cleanup_refresh_build(build_dir: Path) -> None:
    if not build_dir.exists():
        return
    if build_dir.parent.name != ".rag-vectorstore-builds":
        raise RagInitializationError(
            f"blocked: refusing to remove non-build vector store path: {build_dir}"
        )
    shutil.rmtree(build_dir)


def _replace_vectorstore_directory(
    *,
    target_dir: Path,
    build_dir: Path,
    label: str,
) -> Path | None:
    """Replace a vector store directory with a verified build, preserving the old one."""

    _assert_safe_vectorstore_path(target_dir)
    if not build_dir.exists():
        raise RagInitializationError(f"{label} 构建目录不存在，无法替换: {build_dir}")
    if build_dir.parent.name != ".rag-vectorstore-builds":
        raise RagInitializationError(
            f"blocked: refusing to promote non-build vector store path: {build_dir}"
        )
    if target_dir.exists() and not target_dir.is_dir():
        raise RagInitializationError(f"{label} 目标路径不是目录: {target_dir}")

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    backup_dir: Path | None = None
    if target_dir.exists():
        backup_dir = _new_refresh_auxiliary_path(target_dir, "backup")
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target_dir), str(backup_dir))
        _log_info(f"{label} 旧向量库已备份: {backup_dir}")

    try:
        shutil.move(str(build_dir), str(target_dir))
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not target_dir.exists():
            shutil.move(str(backup_dir), str(target_dir))
        raise

    _log_info(f"{label} 已替换为新向量库: {target_dir}")
    return backup_dir


def _rollback_vectorstore_replacement(
    *,
    target_dir: Path,
    backup_dir: Path | None,
    label: str,
) -> None:
    """Best-effort rollback after a post-replacement readiness failure."""

    if backup_dir is None or not backup_dir.exists():
        return
    failed_dir = _new_refresh_auxiliary_path(target_dir, "failed")
    failed_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        shutil.move(str(target_dir), str(failed_dir))
        _log_error(f"{label} 新向量库已移入失败目录: {failed_dir}")
    shutil.move(str(backup_dir), str(target_dir))
    _log_error(f"{label} 已回滚到旧向量库: {target_dir}")


def _build_vectorstore(
    *,
    documents: list,
    persist_directory: str,
    collection_name: str,
    label: str,
    refresh: bool = True,
) -> Path:
    """切分文档并创建一个向量库集合。"""
    _ensure_runtime_imports()
    if not documents:
        raise RagInitializationError(f"{label} 没有可索引文档")

    target_dir = _resolve_project_path(persist_directory)
    _assert_safe_vectorstore_path(target_dir)
    build_dir = (
        _new_refresh_auxiliary_path(target_dir, "build") if refresh else target_dir
    )

    _log_info(f"切分文档: {label}...")
    splitter = AdvancedParentDocumentSplitter()
    parent_docs, child_docs = splitter.split_documents(documents)

    _log_info(f"创建向量数据库: {label}...")
    vs_manager = VectorStoreManager(
        persist_directory=str(build_dir),
        collection_name=collection_name,
    )
    try:
        vs_manager.create_vectorstore(child_docs)
    except Exception:
        if refresh:
            _cleanup_refresh_build(build_dir)
        raise

    _log_info(f"{label} 初始化完成！")
    _log_info(f"   - 文档数量：{len(documents)}")
    _log_info(f"   - 父文档数量：{len(parent_docs)}")
    _log_info(f"   - 子文档数量：{len(child_docs)}")
    _log_info(f"   - 向量数据库：{vs_manager.persist_directory}")
    return build_dir


def _verify_vectorstore_ready(
    *,
    persist_directory: str,
    collection_name: str,
    label: str,
    contract: dict,
) -> None:
    """Fail init if Chroma exists but does not satisfy the readiness contract."""

    check = check_chroma_collection_readiness(
        configured_path=persist_directory,
        collection_name=collection_name,
        label=contract["label"],
        expected_metadata={
            "contract_version": "rag.evidence.v1",
            "knowledge_base": contract["knowledge_base"],
            "visibility": contract["visibility"],
        },
        required_metadata=contract["required_metadata"],
        retrieval_probes=contract["retrieval_probes"],
        project_root=PROJECT_ROOT,
    )
    if not check.ready:
        raise RagInitializationError(
            f"{label} 初始化后仍未就绪: {check.finding} details={check.details}"
        )
    _log_info(
        f"{label} ready: collection={collection_name}, "
        f"embeddings={check.details.get('embedding_count')}, "
        f"path={check.details.get('path')}"
    )


def _refresh_vectorstore(
    *,
    documents: list,
    persist_directory: str,
    collection_name: str,
    label: str,
    contract: dict,
) -> None:
    """Build, verify, replace, and post-verify one vector store."""

    target_dir = _resolve_project_path(persist_directory)
    build_dir = _build_vectorstore(
        documents=documents,
        persist_directory=persist_directory,
        collection_name=collection_name,
        label=label,
        refresh=True,
    )
    try:
        _verify_vectorstore_ready(
            persist_directory=str(build_dir),
            collection_name=collection_name,
            label=label,
            contract=contract,
        )
    except Exception:
        _cleanup_refresh_build(build_dir)
        raise

    backup_dir = _replace_vectorstore_directory(
        target_dir=target_dir,
        build_dir=build_dir,
        label=label,
    )
    try:
        _verify_vectorstore_ready(
            persist_directory=str(target_dir),
            collection_name=collection_name,
            label=label,
            contract=contract,
        )
    except Exception:
        _rollback_vectorstore_replacement(
            target_dir=target_dir,
            backup_dir=backup_dir,
            label=label,
        )
        raise


async def initialize_rag() -> None:
    """初始化 RAG 系统"""

    _ensure_runtime_imports()
    _ensure_model_credentials()
    _log_info("开始初始化 RAG 系统...")

    # ========== 1. 加载文档 ==========
    _log_info("加载文档...")
    doc_manager = DocumentManager()
    destination_documents = doc_manager.load_destination_documents()

    if not destination_documents:
        raise RagInitializationError("未找到文档，请先添加文档到 data/documents/destinations/")

    # ========== 2. 校验并加载内部知识库 ==========
    internal_dir = doc_manager.base_dir / "internal"
    validation = validate_internal_knowledge_base(internal_dir)
    if not validation.passed:
        for finding in validation.errors:
            _log_error(
                "内部知识库 metadata 校验失败: "
                f"{finding.path} {finding.field} {finding.message}"
            )
        raise RagInitializationError(
            "内部知识库 metadata 校验失败，请先运行 "
            ".\\.venv\\Scripts\\python scripts\\validate_rag_knowledge.py --json"
        )
    internal_documents = doc_manager.load_internal_documents()
    if not internal_documents:
        raise RagInitializationError("未找到内部知识库文档，请检查 data/documents/internal/")

    # ========== 3. 安全刷新公开攻略与内部知识向量库 ==========
    _refresh_vectorstore(
        documents=destination_documents,
        persist_directory=settings.rag_vectorstore_path,
        collection_name=settings.rag_collection_name,
        label="公开攻略 RAG",
        contract=PUBLIC_VECTORSTORE_CONTRACT,
    )
    _refresh_vectorstore(
        documents=internal_documents,
        persist_directory=settings.rag_internal_vectorstore_path,
        collection_name=settings.rag_internal_collection_name,
        label="旅行社内部知识库 RAG",
        contract=INTERNAL_VECTORSTORE_CONTRACT,
    )


def main() -> int:
    try:
        _ensure_runtime_imports()
        asyncio.run(initialize_rag())
    except Exception as error:
        _log_error(_actionable_rag_error(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
