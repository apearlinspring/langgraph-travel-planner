"""
初始化 RAG 系统
加载文档、切分、创建向量数据库
"""
import asyncio
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_RAG_IMPORT_ERROR: ImportError | None = None
DocumentManager: Any = None
AdvancedParentDocumentSplitter: Any = None
VectorStoreManager: Any = None
validate_internal_knowledge_base: Any = None
settings: Any = None
app_logger: Any = None

try:
    from app.rag.document_loader import DocumentManager
    from app.rag.text_splitter import AdvancedParentDocumentSplitter
    from app.rag.vectorstore import VectorStoreManager
    from app.rag.contracts import validate_internal_knowledge_base
    from app.config import settings
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


def _actionable_rag_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
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


def _build_vectorstore(
    *,
    documents: list,
    persist_directory: str,
    collection_name: str,
    label: str,
):
    """切分文档并创建一个向量库集合。"""
    _ensure_runtime_imports()
    if not documents:
        raise RagInitializationError(f"{label} 没有可索引文档")

    _log_info(f"切分文档: {label}...")
    splitter = AdvancedParentDocumentSplitter()
    parent_docs, child_docs = splitter.split_documents(documents)

    _log_info(f"创建向量数据库: {label}...")
    vs_manager = VectorStoreManager(
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
    vs_manager.create_vectorstore(child_docs)

    _log_info(f"{label} 初始化完成！")
    _log_info(f"   - 文档数量：{len(documents)}")
    _log_info(f"   - 父文档数量：{len(parent_docs)}")
    _log_info(f"   - 子文档数量：{len(child_docs)}")
    _log_info(f"   - 向量数据库：{vs_manager.persist_directory}")


async def initialize_rag() -> None:
    """初始化 RAG 系统"""

    _ensure_runtime_imports()
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

    # ========== 3. 创建公开攻略与内部知识向量库 ==========
    _build_vectorstore(
        documents=destination_documents,
        persist_directory=settings.rag_vectorstore_path,
        collection_name=settings.rag_collection_name,
        label="公开攻略 RAG",
    )
    _build_vectorstore(
        documents=internal_documents,
        persist_directory=settings.rag_internal_vectorstore_path,
        collection_name=settings.rag_internal_collection_name,
        label="旅行社内部知识库 RAG",
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
