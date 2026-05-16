"""Small deterministic RAG retrieval benchmark.

This module evaluates whether a query can retrieve the expected knowledge
sources/categories from the repository documents. It is intentionally offline:
no LLM, embedding provider, vector store, or API key is required.
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

try:
    import jieba
except Exception:  # pragma: no cover - minimal dependency shells
    jieba = None
else:
    jieba.setLogLevel(logging.ERROR)

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - minimal dependency shells
    BM25Okapi = None

from app.rag.contracts import metadata_list
from app.rag.document_loader import DocumentManager


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAG_RETRIEVAL_SCENARIO_FILE = (
    PROJECT_ROOT / "data" / "evaluation" / "rag_retrieval_scenarios.json"
)
DEFAULT_DOCUMENTS_DIR = PROJECT_ROOT / "data" / "documents"
RAG_RETRIEVAL_SCENARIO_VERSION = "rag_retrieval_scenarios.v1"
RAG_RETRIEVAL_RESULT_VERSION = "rag_retrieval_eval.v1"
RetrievalStrategy = Literal["baseline_bm25", "metadata_aware_bm25"]


CATEGORY_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "destinations": (
        "攻略",
        "景点",
        "美食",
        "住宿",
        "西安",
        "历史",
        "文化",
        "自由行",
    ),
    "products": (
        "产品",
        "路线",
        "成熟路线",
        "省心",
        "亲子",
        "银发",
        "老人",
        "团建",
        "低强度",
        "少步行",
    ),
    "pricing": (
        "报价",
        "费用",
        "预算",
        "价格",
        "包含",
        "不含",
        "锁价",
        "合同",
        "核验",
        "估算",
    ),
    "risk": (
        "风险",
        "天气",
        "预约",
        "排队",
        "体力",
        "老人",
        "小孩",
        "plan b",
        "兜底",
        "锁价",
        "库存",
    ),
    "report": (
        "报告",
        "交付",
        "导出",
        "结构",
        "地图",
        "待核验",
        "预算明细",
        "风险提示",
    ),
    "sop": (
        "sop",
        "流程",
        "服务",
        "顾问",
        "话术",
        "需求",
        "确认",
        "重复追问",
    ),
}


@dataclass(frozen=True)
class RagRetrievalScenario:
    """One labeled query for source/category recall checks."""

    id: str
    name: str
    query: str
    expected_sources: list[str]
    expected_categories: list[str]
    expected_source_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IndexedDocument:
    """A local knowledge document prepared for deterministic retrieval."""

    source: str
    category: str
    source_type: str
    visibility: str
    page_content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RetrievedDocument:
    """One ranked retrieval hit."""

    rank: int
    source: str
    category: str
    source_type: str
    visibility: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagScenarioRetrievalResult:
    """Metrics for one query under one retrieval strategy."""

    scenario_id: str
    strategy: RetrievalStrategy
    top_k: int
    source_recall: float
    category_recall: float
    source_type_recall: float
    reciprocal_rank: float
    first_relevant_rank: int | None
    retrieved: list[RetrievedDocument]

    @property
    def hit(self) -> bool:
        return self.first_relevant_rank is not None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hit"] = self.hit
        payload["retrieved"] = [item.to_dict() for item in self.retrieved]
        return payload


@dataclass(frozen=True)
class RagRetrievalStrategySummary:
    """Aggregate metrics for one strategy and one top_k."""

    strategy: RetrievalStrategy
    top_k: int
    scenario_count: int
    source_recall: float
    category_recall: float
    source_type_recall: float
    hit_rate: float
    mrr: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagRetrievalEvaluationResult:
    """Full benchmark output."""

    version: str
    scenario_count: int
    document_count: int
    top_k_values: list[int]
    summaries: list[RagRetrievalStrategySummary]
    scenario_results: list[RagScenarioRetrievalResult]
    improvement: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scenario_count": self.scenario_count,
            "document_count": self.document_count,
            "top_k_values": self.top_k_values,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "scenario_results": [result.to_dict() for result in self.scenario_results],
            "improvement": self.improvement,
        }


def _require_string(value: Any, field_name: str, scenario_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a non-empty string")
    return value.strip()


def _require_string_list(value: Any, field_name: str, scenario_id: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must contain only strings")
    return [item.strip() for item in value]


def load_rag_retrieval_scenarios(
    path: Path | str | None = None,
) -> list[RagRetrievalScenario]:
    """Load and validate the retrieval benchmark catalog."""

    scenario_path = Path(path or DEFAULT_RAG_RETRIEVAL_SCENARIO_FILE)
    payload = json.loads(scenario_path.read_text(encoding="utf-8-sig"))
    if payload.get("version") != RAG_RETRIEVAL_SCENARIO_VERSION:
        raise ValueError(f"Scenario catalog version must be {RAG_RETRIEVAL_SCENARIO_VERSION}")
    raw_scenarios = payload.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("Scenario catalog must contain a non-empty scenarios list")

    scenarios: list[RagRetrievalScenario] = []
    seen_ids: set[str] = set()
    for raw in raw_scenarios:
        if not isinstance(raw, dict):
            raise ValueError("Scenario catalog items must be objects")
        scenario_id = _require_string(raw.get("id"), "id", "<unknown>")
        if scenario_id in seen_ids:
            raise ValueError(f"Duplicate scenario id: {scenario_id}")
        seen_ids.add(scenario_id)
        scenarios.append(
            RagRetrievalScenario(
                id=scenario_id,
                name=_require_string(raw.get("name"), "name", scenario_id),
                query=_require_string(raw.get("query"), "query", scenario_id),
                expected_sources=[
                    _normalize_source(item) for item in _require_string_list(
                        raw.get("expected_sources"),
                        "expected_sources",
                        scenario_id,
                    )
                ],
                expected_categories=_require_string_list(
                    raw.get("expected_categories"),
                    "expected_categories",
                    scenario_id,
                ),
                expected_source_types=(
                    _require_string_list(
                        raw.get("expected_source_types"),
                        "expected_source_types",
                        scenario_id,
                    )
                    if raw.get("expected_source_types") is not None
                    else []
                ),
                tags=(
                    _require_string_list(raw.get("tags"), "tags", scenario_id)
                    if raw.get("tags") is not None
                    else []
                ),
            )
        )
    return scenarios


def _normalize_source(source: object) -> str:
    source_text = str(source or "").strip().replace("\\", "/")
    if not source_text:
        return "unknown"
    try:
        path = Path(source_text)
        if path.is_absolute():
            return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except Exception:
        pass
    return source_text.lstrip("./")


def _document_from_langchain(doc: Any) -> IndexedDocument:
    metadata = dict(doc.metadata or {})
    source = _normalize_source(metadata.get("source"))
    return IndexedDocument(
        source=source,
        category=str(metadata.get("category") or "unknown"),
        source_type=str(metadata.get("source_type") or "unknown"),
        visibility=str(metadata.get("visibility") or "unknown"),
        page_content=str(doc.page_content or ""),
        metadata=metadata,
    )


def load_rag_retrieval_documents(
    documents_dir: Path | str | None = None,
) -> list[IndexedDocument]:
    """Load public and internal knowledge documents with RAG metadata."""

    manager = DocumentManager(str(documents_dir or DEFAULT_DOCUMENTS_DIR))
    documents = manager.load_destination_documents() + manager.load_internal_documents()
    return [_document_from_langchain(doc) for doc in documents]


_WORD_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    normalized = str(text or "").lower()
    tokens: list[str] = []
    if jieba is not None:
        tokens.extend(item.strip() for item in jieba.lcut(normalized) if item.strip())
    tokens.extend(item.group(0).strip() for item in _WORD_RE.finditer(normalized))
    return [token for token in tokens if token and not token.isspace()]


def _metadata_text(document: IndexedDocument) -> str:
    metadata = document.metadata
    fields = [
        document.category,
        document.source_type,
        document.visibility,
        str(metadata.get("title") or ""),
        str(metadata.get("product_id") or ""),
        str(metadata.get("destination") or ""),
        str(metadata.get("theme") or ""),
        str(metadata.get("duration") or ""),
        str(metadata.get("audience") or ""),
        str(metadata.get("service_level") or ""),
        str(metadata.get("price_band") or ""),
        str(metadata.get("evidence_type") or ""),
        str(metadata.get("product_source") or ""),
        str(metadata.get("service_boundary") or ""),
        str(metadata.get("quote_basis") or ""),
        str(metadata.get("verification_items") or ""),
        str(metadata.get("evidence_level") or ""),
        str(metadata.get("applicable_modes") or ""),
        str(metadata.get("constraints") or ""),
        str(metadata.get("user_segments") or ""),
        str(metadata.get("regions") or ""),
        str(metadata.get("budget_levels") or ""),
    ]
    return " ".join(fields)


def _infer_category_hints(query: str) -> set[str]:
    normalized = query.lower()
    hints: set[str] = set()
    for category, terms in CATEGORY_QUERY_HINTS.items():
        if any(term.lower() in normalized for term in terms):
            hints.add(category)
    if "旅行社" in normalized or "省心" in normalized:
        hints.update({"products", "sop", "pricing", "risk", "report"})
    if not hints:
        hints.add("destinations")
    return hints


def _infer_source_type_hints(query: str) -> set[str]:
    normalized = query.lower()
    if any(term in normalized for term in ("旅行社", "省心", "报价", "sop", "报告标准", "风险")):
        return {"agency_internal"}
    return {"destination_guide", "agency_internal"}


def _bm25_scores(query_tokens: list[str], corpus_tokens: list[list[str]]) -> list[float]:
    if not corpus_tokens:
        return []
    if BM25Okapi is not None:
        bm25 = BM25Okapi(corpus_tokens)
        return [float(score) for score in bm25.get_scores(query_tokens)]

    # Small fallback for dependency-constrained shells.
    scores: list[float] = []
    query_set = set(query_tokens)
    for tokens in corpus_tokens:
        token_set = set(tokens)
        scores.append(float(len(query_set & token_set) / max(len(query_set), 1)))
    return scores


def _safe_round(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(float(value), 4)


def retrieve_documents(
    query: str,
    documents: list[IndexedDocument],
    *,
    strategy: RetrievalStrategy,
    top_k: int,
) -> list[RetrievedDocument]:
    """Retrieve documents with a deterministic offline strategy."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    include_metadata = strategy == "metadata_aware_bm25"
    corpus_text = [
        document.page_content + ("\n" + _metadata_text(document) if include_metadata else "")
        for document in documents
    ]
    query_tokens = _tokenize(query)
    corpus_tokens = [_tokenize(item) for item in corpus_text]
    scores = _bm25_scores(query_tokens, corpus_tokens)

    if include_metadata:
        category_hints = _infer_category_hints(query)
        source_type_hints = _infer_source_type_hints(query)
        for index, document in enumerate(documents):
            boost = 0.0
            if document.category in category_hints:
                boost += 1.2
            if document.source_type in source_type_hints:
                boost += 0.5
            applicable_modes = set(metadata_list(document.metadata.get("applicable_modes")))
            if "省心" in query and "agency_plan" in applicable_modes:
                boost += 0.2
            if "自由行" in query and "free_planning" in applicable_modes:
                boost += 0.2
            scores[index] += boost

    ranked = sorted(
        zip(documents, scores),
        key=lambda item: (-item[1], item[0].source),
    )
    return [
        RetrievedDocument(
            rank=rank,
            source=document.source,
            category=document.category,
            source_type=document.source_type,
            visibility=document.visibility,
            score=_safe_round(score),
        )
        for rank, (document, score) in enumerate(ranked[:top_k], start=1)
    ]


def _recall(expected: Iterable[str], actual: Iterable[str]) -> float:
    expected_set = {str(item) for item in expected if str(item)}
    if not expected_set:
        return 1.0
    actual_set = {str(item) for item in actual if str(item)}
    return len(expected_set & actual_set) / len(expected_set)


def _first_relevant_rank(
    scenario: RagRetrievalScenario,
    retrieved: list[RetrievedDocument],
) -> int | None:
    expected_sources = set(scenario.expected_sources)
    expected_categories = set(scenario.expected_categories)
    expected_source_types = set(scenario.expected_source_types)
    for item in retrieved:
        if item.source in expected_sources:
            return item.rank
        if item.category in expected_categories and (
            not expected_source_types or item.source_type in expected_source_types
        ):
            return item.rank
    return None


def evaluate_rag_retrieval_scenario(
    scenario: RagRetrievalScenario,
    documents: list[IndexedDocument],
    *,
    strategy: RetrievalStrategy,
    top_k: int,
) -> RagScenarioRetrievalResult:
    """Evaluate one labeled retrieval query."""

    retrieved = retrieve_documents(
        scenario.query,
        documents,
        strategy=strategy,
        top_k=top_k,
    )
    first_rank = _first_relevant_rank(scenario, retrieved)
    return RagScenarioRetrievalResult(
        scenario_id=scenario.id,
        strategy=strategy,
        top_k=top_k,
        source_recall=_safe_round(
            _recall(scenario.expected_sources, [item.source for item in retrieved])
        ),
        category_recall=_safe_round(
            _recall(scenario.expected_categories, [item.category for item in retrieved])
        ),
        source_type_recall=_safe_round(
            _recall(scenario.expected_source_types, [item.source_type for item in retrieved])
        ),
        reciprocal_rank=_safe_round(1 / first_rank if first_rank else 0.0),
        first_relevant_rank=first_rank,
        retrieved=retrieved,
    )


def _average(values: Iterable[float]) -> float:
    items = list(values)
    return _safe_round(sum(items) / len(items)) if items else 0.0


def _summarize(
    results: list[RagScenarioRetrievalResult],
    *,
    strategy: RetrievalStrategy,
    top_k: int,
) -> RagRetrievalStrategySummary:
    selected = [
        result
        for result in results
        if result.strategy == strategy and result.top_k == top_k
    ]
    return RagRetrievalStrategySummary(
        strategy=strategy,
        top_k=top_k,
        scenario_count=len(selected),
        source_recall=_average(result.source_recall for result in selected),
        category_recall=_average(result.category_recall for result in selected),
        source_type_recall=_average(result.source_type_recall for result in selected),
        hit_rate=_average(1.0 if result.hit else 0.0 for result in selected),
        mrr=_average(result.reciprocal_rank for result in selected),
    )


def _summary_lookup(
    summaries: list[RagRetrievalStrategySummary],
    *,
    strategy: RetrievalStrategy,
    top_k: int,
) -> RagRetrievalStrategySummary | None:
    for summary in summaries:
        if summary.strategy == strategy and summary.top_k == top_k:
            return summary
    return None


def _improvement(summaries: list[RagRetrievalStrategySummary], top_k_values: list[int]) -> dict[str, float]:
    if not top_k_values:
        return {}
    top_k = min(top_k_values)
    baseline = _summary_lookup(summaries, strategy="baseline_bm25", top_k=top_k)
    improved = _summary_lookup(summaries, strategy="metadata_aware_bm25", top_k=top_k)
    if baseline is None or improved is None:
        return {}

    def delta(metric: str) -> float:
        return _safe_round(getattr(improved, metric) - getattr(baseline, metric))

    return {
        "top_k": float(top_k),
        "source_recall_delta": delta("source_recall"),
        "category_recall_delta": delta("category_recall"),
        "hit_rate_delta": delta("hit_rate"),
        "mrr_delta": delta("mrr"),
    }


def evaluate_rag_retrieval(
    *,
    scenarios: list[RagRetrievalScenario] | None = None,
    documents: list[IndexedDocument] | None = None,
    scenario_path: Path | str | None = None,
    documents_dir: Path | str | None = None,
    top_k_values: Iterable[int] = (3, 5),
    strategies: Iterable[RetrievalStrategy] = ("baseline_bm25", "metadata_aware_bm25"),
) -> RagRetrievalEvaluationResult:
    """Run the deterministic retrieval benchmark."""

    loaded_scenarios = scenarios or load_rag_retrieval_scenarios(scenario_path)
    loaded_documents = documents or load_rag_retrieval_documents(documents_dir)
    top_ks = sorted({int(item) for item in top_k_values})
    if not top_ks or any(item <= 0 for item in top_ks):
        raise ValueError("top_k_values must contain positive integers")

    results: list[RagScenarioRetrievalResult] = []
    for scenario in loaded_scenarios:
        for strategy in strategies:
            for top_k in top_ks:
                results.append(
                    evaluate_rag_retrieval_scenario(
                        scenario,
                        loaded_documents,
                        strategy=strategy,
                        top_k=top_k,
                    )
                )

    summaries = [
        _summarize(results, strategy=strategy, top_k=top_k)
        for strategy in strategies
        for top_k in top_ks
    ]
    return RagRetrievalEvaluationResult(
        version=RAG_RETRIEVAL_RESULT_VERSION,
        scenario_count=len(loaded_scenarios),
        document_count=len(loaded_documents),
        top_k_values=top_ks,
        summaries=summaries,
        scenario_results=results,
        improvement=_improvement(summaries, top_ks),
    )


def render_rag_retrieval_markdown(result: RagRetrievalEvaluationResult) -> str:
    """Render a concise human-readable benchmark report."""

    lines = [
        "# RAG Retrieval Evaluation",
        "",
        f"- version: `{result.version}`",
        f"- scenarios: `{result.scenario_count}`",
        f"- documents: `{result.document_count}`",
        f"- top_k_values: `{', '.join(str(item) for item in result.top_k_values)}`",
        "",
        "## Summary",
        "",
        "| strategy | top_k | source recall | category recall | source type recall | hit rate | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in result.summaries:
        lines.append(
            "| "
            f"{summary.strategy} | {summary.top_k} | "
            f"{summary.source_recall:.2%} | {summary.category_recall:.2%} | "
            f"{summary.source_type_recall:.2%} | {summary.hit_rate:.2%} | "
            f"{summary.mrr:.4f} |"
        )

    if result.improvement:
        lines.extend(
            [
                "",
                "## Metadata-aware Delta",
                "",
                f"- top_k: `{int(result.improvement['top_k'])}`",
                f"- source_recall_delta: `{result.improvement['source_recall_delta']:.2%}`",
                f"- category_recall_delta: `{result.improvement['category_recall_delta']:.2%}`",
                f"- hit_rate_delta: `{result.improvement['hit_rate_delta']:.2%}`",
                f"- mrr_delta: `{result.improvement['mrr_delta']:.4f}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Scenario Details",
            "",
            "| scenario | strategy | top_k | source recall | category recall | first relevant rank | top sources |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for item in result.scenario_results:
        top_sources = "<br>".join(hit.source for hit in item.retrieved[:3])
        lines.append(
            "| "
            f"{item.scenario_id} | {item.strategy} | {item.top_k} | "
            f"{item.source_recall:.2%} | {item.category_recall:.2%} | "
            f"{item.first_relevant_rank or ''} | {top_sources} |"
        )
    lines.append("")
    return "\n".join(lines)
