"""
完整的 Advanced RAG 管道
整合所有优化策略
"""
from time import perf_counter
from typing import Any, List
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from app.rag.query_optimizer import AdvancedQueryOptimizer
from app.rag.retriever import AdvancedHybridRetriever
from app.rag.reranker import LLMReranker, LongContextReorder
from app.rag.text_splitter import AdvancedParentDocumentSplitter
from app.utils.logger import app_logger
from app.rag.cache import RAGCache
from app.rag.contracts import (
    evidence_requires_verification,
    freshness_status,
    prohibited_commitments_for_metadata,
)

load_dotenv()


class AdvancedRAGPipeline:
    """
    高级 RAG 管道

    完整流程：
    查询优化 → 混合检索 → 重排序 → 上下文优化
    """

    def __init__(
            self,
            vectorstore: Chroma,
            all_documents: List[Document],
            parent_splitter: AdvancedParentDocumentSplitter,
            query_strategy: str = "multi_query",
            use_llm_reranker: bool = False,
            top_k: int = 3,
            enable_cache: bool = True
    ):
        """
        Args:
            vectorstore: 向量数据库（包含子文档）
            all_documents: 所有子文档列表
            parent_splitter: 父文档切分器（用于映射）
            query_strategy: 查询优化策略
            use_llm_reranker: 是否使用 LLM 重排序
            top_k: 最终返回的文档数量
        """

        self.top_k = top_k
        self.use_llm_reranker = use_llm_reranker

        # 1. 查询优化器
        self.query_optimizer = AdvancedQueryOptimizer(strategy=query_strategy)

        # 2. 混合检索器
        self.retriever = AdvancedHybridRetriever(
            vectorstore=vectorstore,
            documents=all_documents,
            k=top_k * 3  # 先检索更多候选
        )

        # 3. 重排序器。默认关闭 LLM 重排，避免内部知识库小语料检索走慢路径。
        self.reranker = (
            LLMReranker(top_k=top_k * 2)
            if use_llm_reranker
            else None
        )

        # 4. 父文档映射器
        self.parent_splitter = parent_splitter

        # 5. 长上下文重排序
        self.context_reorder = LongContextReorder()

        # 6. 缓存层
        self.cache = RAGCache(enabled=enable_cache)
        self.last_trace: dict[str, Any] = {}

    def _set_trace(
        self,
        *,
        query: str,
        metadata_filter: dict[str, Any] | None,
        cache_hit: bool,
        optimized_queries: list[str],
        child_count: int,
        final_docs: list[Document],
        started_at: float,
    ) -> None:
        sources = [
            str((doc.metadata or {}).get("source") or "unknown")
            for doc in final_docs
        ]
        self.last_trace = {
            "query_preview": query[:120],
            "metadata_filter": dict(metadata_filter or {}),
            "cache_hit": cache_hit,
            "query_strategy": getattr(self.query_optimizer, "strategy", "unknown"),
            "optimized_query_count": len(optimized_queries),
            "child_candidate_count": child_count,
            "final_document_count": len(final_docs),
            "sources": sources,
            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
        }

    def _annotate_governance_metadata(self, documents: List[Document]) -> List[Document]:
        """Add retrieval-time governance flags for old or low-confidence evidence."""

        for doc in documents:
            metadata = doc.metadata or {}
            if metadata.get("visibility") != "internal":
                continue
            metadata["freshness_status"] = freshness_status(metadata.get("last_reviewed"))
            requires_verification = evidence_requires_verification(metadata)
            metadata["requires_verification"] = (
                "true" if requires_verification else "false"
            )
            if requires_verification:
                metadata["prohibited_commitments"] = "|".join(
                    prohibited_commitments_for_metadata(metadata)
                )
            doc.metadata = metadata
        return documents

    def retrieve(
        self,
        query: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> List[Document]:
        """
        完整检索流程

        Args:
            query: 用户查询

        Returns:
            优化后的上下文文档列表
        """

        started_at = perf_counter()

        # 尝试从缓存获取
        cache_query = (
            query
            if not metadata_filter
            else f"{query} || filter={sorted(metadata_filter.items())}"
        )
        cached_result = self.cache.get(cache_query, self.top_k)
        if cached_result:
            self._set_trace(
                query=query,
                metadata_filter=metadata_filter,
                cache_hit=True,
                optimized_queries=[query],
                child_count=len(cached_result),
                final_docs=cached_result,
                started_at=started_at,
            )
            return cached_result

        app_logger.info(f"✅ 开始 Advanced RAG 检索: {query}")

        # ========== 阶段 1：查询优化 ==========
        optimized_queries = self.query_optimizer.optimize(query)
        app_logger.info(f"1️. 查询优化完成，生成 {len(optimized_queries)} 个查询")

        # ========== 阶段 2：混合检索 ==========
        if metadata_filter:
            child_docs = self.retriever.retrieve(
                query=query,
                queries=optimized_queries,
                metadata_filter=metadata_filter,
            )
        else:
            child_docs = self.retriever.retrieve(
                query=query,
                queries=optimized_queries,
            )
        app_logger.info(f"2️. 混合检索完成，获得 {len(child_docs)} 个候选文档")

        # ========== 阶段 3：重排序 ==========
        if self.reranker is not None:
            reranked_child_docs = self.reranker.rerank(
                query=query,
                documents=child_docs,
                top_k=self.top_k * 2
            )
            app_logger.info(f"3️. LLM 重排序完成，保留 {len(reranked_child_docs)} 个文档")
        else:
            reranked_child_docs = child_docs[: self.top_k * 2]
            app_logger.info(
                f"3️. 已跳过 LLM 重排序，保留 {len(reranked_child_docs)} 个文档"
            )

        # ========== 阶段 4：上下文优化 ==========
        # 4.1 映射到父文档
        parent_docs = self.parent_splitter.get_parent_context(reranked_child_docs)
        app_logger.info(f"4️. 父文档映射完成，获得 {len(parent_docs)} 个完整上下文")

        # 4.2 长上下文重排序
        final_docs = self.context_reorder.reorder(parent_docs[:self.top_k])
        final_docs = self._annotate_governance_metadata(final_docs)
        app_logger.info(f"✅ RAG 检索完成，最终返回 {len(final_docs)} 个文档")
        self._set_trace(
            query=query,
            metadata_filter=metadata_filter,
            cache_hit=False,
            optimized_queries=optimized_queries,
            child_count=len(child_docs),
            final_docs=final_docs,
            started_at=started_at,
        )

        # 缓存结果
        self.cache.set(cache_query, self.top_k, final_docs)

        return final_docs
