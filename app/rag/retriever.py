"""
混合检索器：BM25 + Dense + RRF 融合（优化版）
"""
import hashlib
from typing import Any, List, Tuple
from collections import defaultdict
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from app.rag.retrieval_boost import (
    destination_match_priority,
    explicit_query_destinations,
    query_document_boost,
)
from app.utils.logger import app_logger


def _stable_document_id(doc: Document) -> str:
    """Return a stable id for fusing and caching retrieval candidates."""

    metadata = doc.metadata or {}
    for key in ("child_id", "parent_id"):
        value = metadata.get(key)
        if value:
            return str(value)
    source = str(metadata.get("source") or "unknown")
    basis = f"{source}|{doc.page_content[:500]}"
    return hashlib.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()


def _rank_fused_documents(
    query: str,
    scores: dict[str, float],
    doc_map: dict[str, Document],
    *,
    boost_scale: float = 0.03,
) -> list[tuple[str, float]]:
    """Rank fused candidates with a small query-aware boost."""

    query_destinations = explicit_query_destinations(
        query,
        (
            (document.metadata or {}, document.page_content)
            for document in doc_map.values()
        ),
    )
    return sorted(
        scores.items(),
        key=lambda item: (
            destination_match_priority(
                query_destinations,
                metadata=doc_map[item[0]].metadata or {},
                page_content=doc_map[item[0]].page_content,
            ),
            -(
                item[1]
                + boost_scale
                * query_document_boost(
                    query,
                    metadata=doc_map[item[0]].metadata or {},
                    page_content=doc_map[item[0]].page_content,
                )
            ),
            -item[1],
            str((doc_map[item[0]].metadata or {}).get("source") or ""),
        ),
    )


class AdvancedHybridRetriever:
    """
    高级混合检索器

    改进点：
    1. 支持查询优化
    2. 权重可配置
    3. 缓存机制
    """

    def __init__(
            self,
            vectorstore: Chroma,
            documents: List[Document],
            k: int = 5,
            bm25_weight: float = 0.4,
            dense_weight: float = 0.6,
            use_cache: bool = True
    ):
        self.vectorstore = vectorstore
        self.documents = documents
        self.k = k
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.use_cache = use_cache

        # 缓存
        self._cache = {} if use_cache else None

        # 初始化 BM25
        self._init_bm25()

    def _init_bm25(self):
        """初始化 BM25 索引"""

        app_logger.info("🔧 初始化 BM25 索引...")

        # 创建 BM25 检索器
        self.bm25_retriever = BM25Retriever.from_documents(self.documents)
        self.bm25_retriever.k = self.k * 2

        app_logger.info("✅ BM25 索引初始化完成")

    def _filter_documents(self, metadata_filter: dict[str, Any] | None) -> List[Document]:
        if not metadata_filter:
            return self.documents
        return [
            doc
            for doc in self.documents
            if all((doc.metadata or {}).get(key) == value for key, value in metadata_filter.items())
        ]

    def _bm25_search(
        self,
        query: str,
        k: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> List[Document]:
        """BM25 检索"""
        if not metadata_filter:
            return self.bm25_retriever.invoke(query)[:k]

        documents = self._filter_documents(metadata_filter)
        if not documents:
            return []
        retriever = BM25Retriever.from_documents(documents)
        retriever.k = k
        return retriever.invoke(query)[:k]

    def _dense_search(
        self,
        query: str,
        k: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> List[Tuple[Document, float]]:
        """Dense 检索（向量相似度）"""
        kwargs: dict[str, Any] = {"k": k}
        if metadata_filter:
            kwargs["filter"] = metadata_filter
        results = self.vectorstore.similarity_search_with_score(query, **kwargs)
        #Chroma中默认使用L2距离，这样输出的distance是无上限的，而我们希望把其控制在0到1之间，也就是相似度
        # Chroma 返回的是 (doc, distance)，需要转换为 (doc, similarity)
        similarity_results = [
            (doc, 1 / (1 + distance))
            for doc, distance in results
        ]

        return similarity_results

    def _add_rrf_scores(
        self,
        scores: dict[str, float],
        doc_map: dict[str, Document],
        bm25_results: List[Document],
        dense_results: List[Tuple[Document, float]],
        *,
        k: int = 60,
        query_weight: float = 1.0,
    ) -> None:
        """
        累加倒数排名融合（Reciprocal Rank Fusion）分数。
        """

        # BM25 贡献
        for rank, doc in enumerate(bm25_results, 1):
            doc_id = _stable_document_id(doc)
            doc_map[doc_id] = doc
            scores[doc_id] += query_weight * self.bm25_weight * (1 / (k + rank))

        # Dense 贡献
        for rank, (doc, score) in enumerate(dense_results, 1):
            doc_id = _stable_document_id(doc)
            doc_map[doc_id] = doc
            scores[doc_id] += query_weight * self.dense_weight * (1 / (k + rank))

    def _rrf_fusion(
            self,
            query: str,
            bm25_results: List[Document],
            dense_results: List[Tuple[Document, float]],
            k: int = 60
    ) -> List[Document]:
        """
        倒数排名融合（Reciprocal Rank Fusion）

        公式：RRF_score(d) = Σ 1/(k + rank_r(d))
        """

        scores = defaultdict(float)
        doc_map = {}
        self._add_rrf_scores(scores, doc_map, bm25_results, dense_results, k=k)

        # 排序
        sorted_docs = _rank_fused_documents(query, scores, doc_map)

        return [doc_map[doc_id] for doc_id, _ in sorted_docs[:self.k]]

    def retrieve(
        self,
        query: str,
        queries: List[str] = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> List[Document]:
        """
        混合检索

        Args:
            query: 主查询
            queries: 可选的查询变体（来自查询优化）

        Returns:
            检索结果列表
        """

        # 检查缓存
        normalized_queries = tuple(queries or (query,))
        cache_key = (
            query,
            normalized_queries,
            tuple(sorted((metadata_filter or {}).items())),
        )
        if self.use_cache and cache_key in self._cache:
            app_logger.info("命中缓存")
            return self._cache[cache_key]

        # 如果提供了查询变体，合并结果
        if queries and len(queries) > 1:
            app_logger.info(f"使用 {len(queries)} 个查询变体进行检索")
            final_results = self._multi_query_retrieve(
                query,
                queries,
                metadata_filter=metadata_filter,
            )
        else:
            final_results = self._single_retrieve(query, metadata_filter=metadata_filter)

        # 缓存结果
        if self.use_cache:
            self._cache[cache_key] = final_results

        return final_results

    def _multi_query_retrieve(
        self,
        query: str,
        queries: list[str],
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Retrieve and fuse candidates across multiple query variants."""

        scores = defaultdict(float)
        doc_map: dict[str, Document] = {}
        seen_queries: set[str] = set()
        for index, variant in enumerate(queries):
            normalized_variant = " ".join(str(variant or "").split())
            if not normalized_variant or normalized_variant in seen_queries:
                continue
            seen_queries.add(normalized_variant)
            query_weight = 1.0 if index == 0 or normalized_variant == query else 0.85
            bm25_results = self._bm25_search(
                normalized_variant,
                k=self.k * 2,
                metadata_filter=metadata_filter,
            )
            dense_results = self._dense_search(
                normalized_variant,
                k=self.k * 2,
                metadata_filter=metadata_filter,
            )
            self._add_rrf_scores(
                scores,
                doc_map,
                bm25_results,
                dense_results,
                query_weight=query_weight,
            )

        sorted_docs = _rank_fused_documents(query, scores, doc_map)
        final_docs = [doc_map[doc_id] for doc_id, _score in sorted_docs[: self.k]]
        app_logger.info(f"多查询融合完成，返回 {len(final_docs)} 个结果")
        return final_docs

    def _single_retrieve(
        self,
        query: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> List[Document]:
        """单个查询的检索"""

        # BM25 检索
        bm25_results = self._bm25_search(
            query,
            k=self.k * 2,
            metadata_filter=metadata_filter,
        )
        app_logger.debug(f"BM25 检索到 {len(bm25_results)} 个候选")

        # Dense 检索
        dense_results = self._dense_search(
            query,
            k=self.k * 2,
            metadata_filter=metadata_filter,
        )
        app_logger.debug(f"Dense 检索到 {len(dense_results)} 个候选")

        # RRF 融合
        fused_docs = self._rrf_fusion(query, bm25_results, dense_results)

        app_logger.info(f"混合检索完成，返回 {len(fused_docs)} 个结果")

        return fused_docs
