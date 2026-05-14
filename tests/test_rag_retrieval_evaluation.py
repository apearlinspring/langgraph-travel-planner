import json
from pathlib import Path

import pytest

from app.evaluation.rag_retrieval import (
    IndexedDocument,
    RagRetrievalScenario,
    evaluate_rag_retrieval,
    load_rag_retrieval_documents,
    load_rag_retrieval_scenarios,
    render_rag_retrieval_markdown,
)


def _summary_by_strategy(result, strategy: str, top_k: int):
    return next(
        summary
        for summary in result.summaries
        if summary.strategy == strategy and summary.top_k == top_k
    )


def test_load_default_rag_retrieval_scenarios_cover_business_categories():
    scenarios = load_rag_retrieval_scenarios()
    scenario_ids = {scenario.id for scenario in scenarios}
    categories = {
        category
        for scenario in scenarios
        for category in scenario.expected_categories
    }
    source_types = {
        source_type
        for scenario in scenarios
        for source_type in scenario.expected_source_types
    }

    assert len(scenarios) >= 8
    assert len(scenario_ids) == len(scenarios)
    assert {"destinations", "products", "pricing", "risk", "report", "sop"}.issubset(
        categories
    )
    assert {"destination_guide", "agency_internal"}.issubset(source_types)


def test_default_rag_retrieval_evaluation_runs_offline():
    result = evaluate_rag_retrieval(top_k_values=(3, 5))
    baseline_top_3 = _summary_by_strategy(result, "baseline_bm25", 3)
    metadata_top_3 = _summary_by_strategy(result, "metadata_aware_bm25", 3)
    metadata_top_5 = _summary_by_strategy(result, "metadata_aware_bm25", 5)

    assert result.scenario_count >= 8
    assert result.document_count >= 10
    assert baseline_top_3.scenario_count == result.scenario_count
    assert metadata_top_3.source_recall >= baseline_top_3.source_recall
    assert metadata_top_3.category_recall >= baseline_top_3.category_recall
    assert metadata_top_5.category_recall >= metadata_top_3.category_recall
    assert result.improvement["top_k"] == 3.0


def test_rag_retrieval_markdown_contains_metrics():
    result = evaluate_rag_retrieval(top_k_values=(3,))
    rendered = render_rag_retrieval_markdown(result)

    assert "# RAG Retrieval Evaluation" in rendered
    assert "metadata_aware_bm25" in rendered
    assert "source recall" in rendered
    assert "Scenario Details" in rendered


def test_rag_retrieval_evaluation_accepts_in_memory_documents():
    documents = [
        IndexedDocument(
            source="data/documents/internal/pricing/pricing_rules.md",
            category="pricing",
            source_type="agency_internal",
            visibility="internal",
            page_content="报价 费用包含 不含 待核验 预算置信度",
            metadata={"title": "Pricing", "applicable_modes": ["agency_plan"]},
        ),
        IndexedDocument(
            source="data/documents/destinations/xian.md",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="西安 历史 景点 美食 攻略 自由行",
            metadata={"title": "Xi'an", "applicable_modes": ["free_planning"]},
        ),
    ]
    scenarios = [
        RagRetrievalScenario(
            id="pricing",
            name="Pricing",
            query="旅行社报价费用包含不含和预算置信度",
            expected_sources=["data/documents/internal/pricing/pricing_rules.md"],
            expected_categories=["pricing"],
            expected_source_types=["agency_internal"],
        )
    ]

    result = evaluate_rag_retrieval(
        scenarios=scenarios,
        documents=documents,
        top_k_values=(1,),
        strategies=("metadata_aware_bm25",),
    )

    summary = _summary_by_strategy(result, "metadata_aware_bm25", 1)
    assert summary.source_recall == pytest.approx(1.0)
    assert summary.hit_rate == pytest.approx(1.0)


def test_load_rag_retrieval_scenarios_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "rag_retrieval.json"
    path.write_text(
        json.dumps(
            {
                "version": "rag_retrieval_scenarios.v1",
                "scenarios": [
                    {
                        "id": "duplicate",
                        "name": "One",
                        "query": "报价规则",
                        "expected_sources": ["data/documents/internal/pricing/pricing_rules.md"],
                        "expected_categories": ["pricing"],
                    },
                    {
                        "id": "duplicate",
                        "name": "Two",
                        "query": "服务流程",
                        "expected_sources": ["data/documents/internal/sop/service_sop.md"],
                        "expected_categories": ["sop"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate scenario id"):
        load_rag_retrieval_scenarios(path)


def test_load_rag_retrieval_documents_uses_local_knowledge_base():
    documents = load_rag_retrieval_documents()
    sources = {document.source for document in documents}
    categories = {document.category for document in documents}

    assert "data/documents/destinations/xian.md" in sources
    assert "data/documents/internal/pricing/pricing_rules.md" in sources
    assert {"destinations", "pricing", "sop", "risk", "report", "products"}.issubset(
        categories
    )
