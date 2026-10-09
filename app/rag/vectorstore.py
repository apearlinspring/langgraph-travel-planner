"""
向量数据库管理
"""
from typing import List
from pathlib import Path
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from app.config import settings
from app.utils.logger import app_logger


class VectorStoreManager:
    """向量数据库管理器"""

    def __init__(
            self,
            persist_directory: str | None = None,
            collection_name: str | None = None,
    ):
        self.persist_directory = Path(persist_directory or settings.rag_vectorstore_path)
        self.collection_name = collection_name or settings.rag_collection_name

        # 创建目录
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # 初始化 Embedding 模型
        self.embeddings = DashScopeEmbeddings(
            model="text-embedding-v2",
            dashscope_api_key=settings.dashscope_api_key
        )

        # 初始化向量数据库
        self.vectorstore = None

    def create_vectorstore(
            self,
            documents: List[Document]
    ) -> Chroma:
        """创建向量数据库"""

        app_logger.info(f"创建向量数据库（{len(documents)} 个文档）...")

        self.vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=str(self.persist_directory),
            collection_name=self.collection_name
        )

        app_logger.info("✅ 向量数据库创建完成")

        return self.vectorstore

    def load_vectorstore(self) -> Chroma:
        """加载已有向量数据库"""

        app_logger.info("加载向量数据库...")

        self.vectorstore = Chroma(
            persist_directory=str(self.persist_directory),
            embedding_function=self.embeddings,
            collection_name=self.collection_name
        )

        app_logger.info("✅ 向量数据库加载完成")

        return self.vectorstore

    def get_vectorstore(self) -> Chroma:
        """获取向量数据库实例"""
        if self.vectorstore is None:
            try:
                return self.load_vectorstore()
            except:
                app_logger.warning("⚠️ 向量数据库不存在，需先创建")
                raise RuntimeError("向量数据库未初始化")
        return self.vectorstore

    def close(self) -> None:
        """关闭本地 Chroma 资源并释放持久化索引文件句柄。

        Chroma 0.5 没有公开的 ``close`` API。持久化客户端会把 System
        缓存在进程级注册表中，仅删除 Python 包装对象无法释放 Windows 上的
        HNSW 文件句柄，因此这里需要停止该实例并只移除它自己的缓存项。
        """

        vectorstore = self.vectorstore
        self.vectorstore = None
        if vectorstore is None:
            return

        client = getattr(vectorstore, "_client", None)
        if client is None:
            return

        identifier = getattr(client, "_identifier", None)
        system = getattr(client, "_system", None)
        try:
            if system is not None:
                system.stop()
        finally:
            systems = getattr(type(client), "_identifier_to_system", None)
            if isinstance(systems, dict) and identifier is not None:
                systems.pop(identifier, None)
