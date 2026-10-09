import json
from pathlib import Path

import pytest

from app.evaluation.rag_retrieval import (
    IndexedDocument,
    RagRetrievalScenario,
    evaluate_rag_mixed_corpus_safety,
    evaluate_rag_retrieval,
    evaluate_rag_retrieval_scenario,
    load_rag_retrieval_documents,
    load_rag_retrieval_scenarios,
    rag_mixed_corpus_safety_failures,
    render_rag_retrieval_markdown,
    retrieve_documents,
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

    assert len(scenarios) >= 12
    assert len(scenario_ids) == len(scenarios)
    assert {
        "retrieval_public_no_internal_product_leak",
        "retrieval_public_hangzhou_no_internal_quote",
        "retrieval_public_xiamen_no_internal_product",
        "retrieval_public_guilin_no_internal_optimizer",
        "retrieval_public_nanjing_culture_food_no_internal",
        "retrieval_public_beijing_senior_low_stress",
        "retrieval_product_xian_family_catalog_fields",
        "retrieval_product_team_budget_transparency",
        "retrieval_product_couple_relaxed",
        "retrieval_product_xinjiang_destination_only",
        "retrieval_product_tibet_budgeted_couple",
        "retrieval_product_xian_family_value",
        "retrieval_product_free_planning_boundary",
    }.issubset(scenario_ids)
    assert {"destinations", "products", "pricing", "risk", "report", "sop"}.issubset(
        categories
    )
    assert {"destination_guide", "agency_internal"}.issubset(source_types)
    assert sum("negative_safety" in scenario.tags for scenario in scenarios) >= 7


def test_default_rag_retrieval_evaluation_runs_offline():
    result = evaluate_rag_retrieval(top_k_values=(3, 5))
    baseline_top_3 = _summary_by_strategy(result, "baseline_bm25", 3)
    metadata_top_3 = _summary_by_strategy(result, "metadata_aware_bm25", 3)
    metadata_top_5 = _summary_by_strategy(result, "metadata_aware_bm25", 5)

    assert result.scenario_count >= 12
    assert result.document_count >= 10
    assert baseline_top_3.scenario_count == result.scenario_count
    assert metadata_top_3.source_recall >= baseline_top_3.source_recall
    assert metadata_top_3.category_recall >= baseline_top_3.category_recall
    assert metadata_top_5.category_recall >= metadata_top_3.category_recall
    assert metadata_top_3.safety_pass_rate == pytest.approx(1.0)
    assert any(summary.source_recall < 1.0 for summary in result.summaries)
    assert result.improvement["top_k"] == 3.0
    product_demo_results = [
        item
        for item in result.scenario_results
        if item.strategy == "metadata_aware_bm25"
        and item.top_k == 3
        and item.scenario_id
        in {
            "retrieval_product_xinjiang_destination_only",
            "retrieval_product_tibet_budgeted_couple",
            "retrieval_product_xian_family_value",
        }
    ]
    assert len(product_demo_results) == 3
    assert all(item.source_recall == pytest.approx(1.0) for item in product_demo_results)
    assert all(item.first_relevant_rank == 1 for item in product_demo_results)


def test_rag_retrieval_markdown_contains_metrics():
    result = evaluate_rag_retrieval(top_k_values=(3,))
    rendered = render_rag_retrieval_markdown(result)

    assert "# RAG（检索增强生成）Retrieval Evaluation（召回评估）" in rendered
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


def test_metadata_aware_retrieval_boosts_precise_multimodal_match():
    documents = [
        IndexedDocument(
            source="samplelib-city-road.mp4",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="城市道路视频样例，包含交通动线和低强度出行提示。",
            metadata={
                "title": "城市道路视频",
                "content_modality": "video",
                "source_format": "mp4",
            },
        ),
        IndexedDocument(
            source="samplelib-city-park.jpg",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="城市公园中沿河步道适合老人低强度路线和亲子散步。",
            metadata={
                "title": "城市公园步道图片",
                "content_modality": "image",
                "source_format": "jpg",
            },
        ),
    ]

    results = retrieve_documents(
        "城市公园老人低强度路线",
        documents,
        strategy="metadata_aware_bm25",
        top_k=2,
    )

    assert results[0].source == "samplelib-city-park.jpg"


def test_metadata_aware_retrieval_prioritizes_explicit_destination_over_generic_overlap():
    documents = [
        IndexedDocument(
            source="data/documents/destinations/xian.md",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="西安古都历史与本地小吃攻略。",
            metadata={"title": "西安公开目的地知识样例"},
        ),
        IndexedDocument(
            source="data/documents/destinations/nanjing.md",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="第一次自由行可看历史文化景点、博物馆并品尝本地小吃。",
            metadata={"title": "南京公开目的地知识样例"},
        ),
    ]

    results = retrieve_documents(
        "第一次去西安自由行，想看历史文化景点，也想吃本地小吃。",
        documents,
        strategy="metadata_aware_bm25",
        top_k=2,
    )

    assert [item.source for item in results] == [
        "data/documents/destinations/xian.md",
        "data/documents/destinations/nanjing.md",
    ]


def test_public_rag_retrieval_scenario_filters_internal_documents():
    documents = [
        IndexedDocument(
            source="data/documents/internal/products/xian_family_light_custom.md",
            category="products",
            source_type="agency_internal",
            visibility="internal",
            page_content="西安自由行 历史景点 美食 住宿区域 旅行社产品",
            metadata={"title": "Internal product"},
        ),
        IndexedDocument(
            source="data/documents/destinations/xian.md",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="西安自由行 历史景点 美食 住宿区域",
            metadata={"title": "Xi'an"},
        ),
    ]
    scenarios = [
        RagRetrievalScenario(
            id="public_safety",
            name="Public safety",
            query="西安自由行历史景点美食住宿区域",
            expected_sources=["data/documents/destinations/xian.md"],
            expected_categories=["destinations"],
            expected_source_types=["destination_guide"],
            expected_visibilities=["public"],
            forbidden_source_types=["agency_internal"],
            forbidden_visibilities=["internal"],
            tags=["public", "free_planning", "negative_safety"],
        )
    ]

    result = evaluate_rag_retrieval(
        scenarios=scenarios,
        documents=documents,
        top_k_values=(1,),
        strategies=("metadata_aware_bm25",),
    )
    scenario_result = result.scenario_results[0]

    assert scenario_result.source_recall == pytest.approx(1.0)
    assert scenario_result.visibility_recall == pytest.approx(1.0)
    assert scenario_result.forbidden_hit_count == 0
    assert scenario_result.safety_passed is True
    assert scenario_result.retrieved[0].visibility == "public"


def test_public_mixed_corpus_safety_gate_blocks_internal_hits_without_prefiltering():
    documents = [
        IndexedDocument(
            source="data/documents/internal/products/xian_family_light_custom.md",
            category="products",
            source_type="agency_internal",
            visibility="internal",
            page_content="西安自由行 历史景点 美食 住宿区域 旅行社产品 少排队 短动线",
            metadata={"title": "Internal product", "applicable_modes": ["agency_plan"]},
        ),
        IndexedDocument(
            source="data/documents/destinations/xian.md",
            category="destinations",
            source_type="destination_guide",
            visibility="public",
            page_content="西安自由行 历史景点 美食 住宿区域 自己订酒店和门票",
            metadata={"title": "Xi'an", "applicable_modes": ["free_planning"]},
        ),
    ]
    scenario = RagRetrievalScenario(
        id="public_mixed_safety",
        name="Public mixed safety",
        query="西安自由行只想自己订酒店和门票，不要旅行社产品，想看历史景点、美食和住宿区域。",
        expected_sources=["data/documents/destinations/xian.md"],
        expected_categories=["destinations"],
        expected_source_types=["destination_guide"],
        expected_visibilities=["public"],
        forbidden_categories=["products"],
        forbidden_source_types=["agency_internal"],
        forbidden_visibilities=["internal"],
        tags=["public", "free_planning", "negative_safety"],
    )

    unguarded = evaluate_rag_retrieval_scenario(
        scenario,
        documents,
        strategy="metadata_aware_bm25",
        top_k=1,
        apply_visibility_filter=False,
    )
    guarded = evaluate_rag_retrieval_scenario(
        scenario,
        documents,
        strategy="metadata_aware_bm25",
        top_k=3,
        apply_visibility_filter=False,
        visibility_bias=True,
        enforce_forbidden_hits=True,
    )

    assert unguarded.forbidden_hit_count == 1
    assert unguarded.safety_passed is False
    assert guarded.source_recall == pytest.approx(1.0)
    assert guarded.forbidden_hit_count == 0
    assert guarded.safety_passed is True
    assert [item.visibility for item in guarded.retrieved] == ["public"]


def test_default_public_mixed_corpus_safety_evaluation_runs_against_real_documents():
    result = evaluate_rag_mixed_corpus_safety(top_k_values=(3,))
    summary = _summary_by_strategy(result, "metadata_aware_bm25", 3)
    public_safety_results = [
        item
        for item in result.scenario_results
        if item.strategy == "metadata_aware_bm25" and item.top_k == 3
    ]

    assert result.scenario_count >= 2
    assert summary.safety_pass_rate == pytest.approx(1.0)
    assert rag_mixed_corpus_safety_failures(result) == []
    assert all(item.safety_passed is True for item in public_safety_results)
    assert all(
        hit.visibility == "public"
        for item in public_safety_results
        for hit in item.retrieved
    )


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
    assert "data/documents/destinations/hangzhou.md" in sources
    assert "data/documents/destinations/xiamen.md" in sources
    assert "data/documents/destinations/guilin.md" in sources
    assert "data/documents/destinations/nanjing.md" in sources
    assert "data/documents/destinations/beijing.md" in sources
    assert "data/documents/internal/pricing/pricing_rules.md" in sources
    assert {"destinations", "pricing", "sop", "risk", "report", "products"}.issubset(
        categories
    )


def test_nanjing_free_city_query_retrieves_matching_public_guide_first():
    retrieved = retrieve_documents(
        "南京 3天2晚 自由行 文化 美食 不赶",
        load_rag_retrieval_documents(),
        strategy="metadata_aware_bm25",
        top_k=3,
        preferred_visibilities=("public",),
        blocked_visibilities=("internal",),
        enforce_blocked=True,
    )

    assert retrieved[0].source == "data/documents/destinations/nanjing.md"
    assert retrieved[0].category == "destinations"
    assert retrieved[0].visibility == "public"


def test_beijing_senior_query_retrieves_matching_public_guide_first():
    retrieved = retrieve_documents(
        "北京 银发 老人 低强度 午休 无障碍 电梯 核心城区 天气 Plan B",
        load_rag_retrieval_documents(),
        strategy="metadata_aware_bm25",
        top_k=3,
        preferred_visibilities=("public",),
        blocked_visibilities=("internal",),
        enforce_blocked=True,
    )

    assert retrieved[0].source == "data/documents/destinations/beijing.md"
    assert retrieved[0].category == "destinations"
    assert retrieved[0].visibility == "public"
