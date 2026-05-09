"""
文档加载与预处理
"""
from pathlib import Path
from typing import List
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_core.documents import Document
from app.utils.logger import app_logger


class DocumentManager:
    """文档管理器"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            # 获取项目根目录 (从当前文件向上找到项目根)
            # document_loader.py -> rag -> app -> 项目根
            project_root = Path(__file__).parent.parent.parent
            self.base_dir = project_root / "data" / "documents"
        else:
            self.base_dir = Path(base_dir)

    def _load_markdown_documents(
        self,
        directory: Path,
        *,
        source_type: str,
        default_category: str,
        visibility: str,
    ) -> List[Document]:
        """加载指定目录下的 Markdown 文档，并补充统一元数据。"""

        if not directory.exists():
            app_logger.warning(f"文档目录不存在: {directory}")
            return []

        loader = DirectoryLoader(
            str(directory),
            glob="**/*.md",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
        )
        documents = loader.load()

        for doc in documents:
            source = Path(doc.metadata.get("source", ""))
            try:
                relative_source = source.relative_to(directory)
                category = (
                    relative_source.parts[0]
                    if len(relative_source.parts) > 1
                    else default_category
                )
            except ValueError:
                category = default_category

            doc.metadata.update(
                {
                    "source_type": source_type,
                    "category": category,
                    "visibility": visibility,
                }
            )

        app_logger.info(
            f"加载 {len(documents)} 个 {source_type} 文档，目录: {directory}"
        )
        return documents

    def load_destination_documents(self) -> List[Document]:
        """加载所有目的地文档"""
        return self._load_markdown_documents(
            self.base_dir / "destinations",
            source_type="destination_guide",
            default_category="destinations",
            visibility="public",
        )

    def load_internal_documents(self, category: str | None = None) -> List[Document]:
        """加载旅行社内部知识库文档，可按 category 过滤。"""

        documents = self._load_markdown_documents(
            self.base_dir / "internal",
            source_type="agency_internal",
            default_category="general",
            visibility="internal",
        )
        if category is None:
            return documents
        return [doc for doc in documents if doc.metadata.get("category") == category]

    def load_food_documents(self) -> List[Document]:
        """加载美食文档"""
        # 类似实现
        pass

    def load_accommodation_documents(self) -> List[Document]:
        """加载住宿文档"""
        # 类似实现
        pass
