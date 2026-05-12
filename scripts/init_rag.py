"""
初始化 RAG 系统
加载文档、切分、创建向量数据库
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.document_loader import DocumentManager
from app.rag.text_splitter import AdvancedParentDocumentSplitter
from app.rag.vectorstore import VectorStoreManager
from app.rag.contracts import validate_internal_knowledge_base
from app.utils.logger import app_logger


class RagInitializationError(RuntimeError):
    """Raised when RAG bootstrap cannot create a usable vector store."""


def _actionable_rag_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return (
        "RAG 初始化失败，已停止。请检查："
        "1) data/documents/destinations/ 是否有公开目的地 Markdown 文档；"
        "2) data/documents/internal/ 的 metadata 是否通过 validate_rag_knowledge；"
        "3) sentence-transformers 模型依赖是否已安装并可下载；"
        "4) data/vectorstore 与 data/vectorstore_internal 是否可写。"
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
    if not documents:
        raise RagInitializationError(f"{label} 没有可索引文档")

    app_logger.info(f"切分文档: {label}...")
    splitter = AdvancedParentDocumentSplitter()
    parent_docs, child_docs = splitter.split_documents(documents)

    app_logger.info(f"创建向量数据库: {label}...")
    vs_manager = VectorStoreManager(
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
    vs_manager.create_vectorstore(child_docs)

    app_logger.info(f"{label} 初始化完成！")
    app_logger.info(f"   - 文档数量：{len(documents)}")
    app_logger.info(f"   - 父文档数量：{len(parent_docs)}")
    app_logger.info(f"   - 子文档数量：{len(child_docs)}")
    app_logger.info(f"   - 向量数据库：{vs_manager.persist_directory}")


async def initialize_rag() -> None:
    """初始化 RAG 系统"""

    app_logger.info("开始初始化 RAG 系统...")

    # ========== 1. 加载文档 ==========
    app_logger.info("加载文档...")
    doc_manager = DocumentManager()
    destination_documents = doc_manager.load_destination_documents()

    if not destination_documents:
        raise RagInitializationError("未找到文档，请先添加文档到 data/documents/destinations/")

    # ========== 2. 校验并加载内部知识库 ==========
    internal_dir = doc_manager.base_dir / "internal"
    validation = validate_internal_knowledge_base(internal_dir)
    if not validation.passed:
        for finding in validation.errors:
            app_logger.error(
                "内部知识库 metadata 校验失败: "
                f"{finding.path} {finding.field} {finding.message}"
            )
        raise SystemExit(1)
    internal_documents = doc_manager.load_internal_documents()
    if not internal_documents:
        raise RagInitializationError("未找到内部知识库文档，请检查 data/documents/internal/")

    # ========== 3. 创建公开攻略与内部知识向量库 ==========
    _build_vectorstore(
        documents=destination_documents,
        persist_directory="data/vectorstore",
        collection_name="travel_guides",
        label="公开攻略 RAG",
    )
    _build_vectorstore(
        documents=internal_documents,
        persist_directory="data/vectorstore_internal",
        collection_name="agency_internal_knowledge",
        label="旅行社内部知识库 RAG",
    )


def main() -> int:
    try:
        asyncio.run(initialize_rag())
    except Exception as error:
        app_logger.error(_actionable_rag_error(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
