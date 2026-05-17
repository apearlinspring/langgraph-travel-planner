import sqlite3
from datetime import date
from pathlib import Path

from langchain_core.documents import Document
import pytest

from app.rag.document_loader import DocumentManager
from app.rag.contracts import (
    CONTRACT_VERSION,
    INTERNAL_KNOWLEDGE_BASE,
    validate_internal_document_file,
    validate_internal_knowledge_base,
)
from app.rag.agency_retrieval import document_to_evidence, format_evidence_response
from app.rag.pipeline import AdvancedRAGPipeline
from app.rag.query_optimizer import AdvancedQueryOptimizer
from app.rag.readiness import RagReadinessError
from app.rag.readiness import (
    INTERNAL_VECTORSTORE_CONTRACT,
    check_chroma_collection_readiness,
)
from app.rag.text_splitter import AdvancedParentDocumentSplitter
from app.tools import rag_tools


def test_document_manager_loads_internal_documents_with_business_metadata():
    documents = DocumentManager().load_internal_documents()

    categories = {doc.metadata.get("category") for doc in documents}
    product_documents = [
        doc for doc in documents if doc.metadata.get("category") == "products"
    ]
    product_required_fields = {
        "product_id",
        "source_kind",
        "inventory_status",
        "destination",
        "theme",
        "duration",
        "audience",
        "persona_tags",
        "service_level",
        "price_band",
        "source",
        "product_source",
        "evidence_type",
    }

    assert {"products", "sop", "pricing", "risk", "report"}.issubset(categories)
    assert all(doc.metadata.get("source_type") == "agency_internal" for doc in documents)
    assert all(doc.metadata.get("visibility") == "internal" for doc in documents)
    assert all(doc.metadata.get("contract_version") == CONTRACT_VERSION for doc in documents)
    assert all(doc.metadata.get("knowledge_base") == INTERNAL_KNOWLEDGE_BASE for doc in documents)
    assert all(doc.metadata.get("evidence_level") for doc in documents)
    assert all(doc.metadata.get("applicable_modes") for doc in documents)
    assert all(doc.metadata.get("last_reviewed") for doc in documents)
    assert all(doc.metadata.get("freshness_status") == "current" for doc in documents)
    assert all(doc.metadata.get("requires_verification") in {"true", "false"} for doc in documents)
    assert all(doc.metadata.get("constraints") for doc in documents)
    assert all("source_type:" not in doc.page_content for doc in documents)
    assert len(product_documents) >= 7
    assert all(
        product_required_fields.issubset(doc.metadata)
        for doc in product_documents
    )
    assert {
        doc.metadata.get("product_id") for doc in product_documents
    } >= {
        "ZX-PROD-XIAN-FAMILY-3D",
        "ZX-PROD-TIBET-COUPLE-7D",
        "ZX-PROD-XINJIANG-PRIVATE-8D",
        "ZX-PROD-YUNNAN-LIGHT-6D",
        "ZX-PROD-SUZHOU-SENIOR-4D",
        "ZX-PROD-CHANGSHA-TEAM-4D",
        "ZX-PROD-XIAMEN-COUPLE-3D",
        "ZX-PROD-GUILIN-FREE-4D",
    }


def test_document_manager_filters_internal_documents_by_category():
    documents = DocumentManager().load_internal_documents(category="pricing")

    assert documents
    assert {doc.metadata.get("category") for doc in documents} == {"pricing"}
    assert any("报价" in doc.page_content for doc in documents)
    assert all("待核验" in doc.metadata.get("constraints", "") or "锁价" in doc.metadata.get("constraints", "") for doc in documents)


def test_document_manager_loads_public_documents_with_evidence_contract():
    documents = DocumentManager().load_destination_documents()

    assert documents
    assert all(doc.metadata.get("contract_version") == CONTRACT_VERSION for doc in documents)
    assert all(doc.metadata.get("visibility") == "public" for doc in documents)
    assert all(doc.metadata.get("evidence_level") == "guide" for doc in documents)
    assert all("二次核实" in doc.metadata.get("constraints", "") for doc in documents)


def test_document_to_evidence_matches_refactor_plan_contract():
    evidence = document_to_evidence(
        Document(
            page_content="# 报价规则\n- 预算必须区分真实价格和估算价格。",
            metadata={
                "source": "internal/pricing/pricing_rules.md",
                "source_type": "agency_internal",
                "category": "pricing",
                "visibility": "internal",
                "evidence_level": "rule",
                "last_reviewed": "2026-05-11",
                "applicable_modes": "agency_plan|free_planning",
                "constraints": "不得承诺锁价|必须标记待核验",
            },
        )
    )

    assert evidence["source"].endswith("pricing_rules.md")
    assert evidence["source_type"] == "agency_internal"
    assert evidence["category"] == "pricing"
    assert evidence["visibility"] == "internal"
    assert evidence["title"] == "报价规则"
    assert evidence["relevance_score"] > 0
    assert evidence["evidence_level"] == "rule"
    assert evidence["applicable_modes"] == ["agency_plan", "free_planning"]
    assert "不得承诺锁价" in evidence["constraints"]
    assert evidence["freshness_status"] == "current"
    assert evidence["requires_verification"] is False


def test_low_confidence_evidence_requires_verification_and_blocks_commitments():
    evidence = document_to_evidence(
        Document(
            page_content="# 公开规则抽象\n- 只能作为参考，不能承诺预订结果。",
            metadata={
                "source": "internal/pricing/reference.md",
                "source_type": "agency_internal",
                "category": "pricing",
                "visibility": "internal",
                "evidence_level": "reference",
                "last_reviewed": "2026-05-11",
                "applicable_modes": "agency_plan|free_planning",
            },
        )
    )

    assert evidence["requires_verification"] is True
    assert "锁价" in evidence["prohibited_commitments"]

    response = format_evidence_response(
        query="报价边界",
        documents=[
            Document(
                page_content="# 公开规则抽象\n- 只能作为参考，不能承诺预订结果。",
                metadata={
                    "source": "internal/pricing/reference.md",
                    "source_type": "agency_internal",
                    "category": "pricing",
                    "visibility": "internal",
                    "evidence_level": "reference",
                    "last_reviewed": "2026-05-11",
                    "applicable_modes": "agency_plan|free_planning",
                },
            )
        ],
        visibility="internal",
    )

    assert '"requires_verification": true' in response
    assert "不得生成锁价、库存、支付、预订或客服承诺" in response
    assert "禁止承诺：锁价" in response


def test_product_evidence_includes_matching_fields_and_direction_summary():
    documents = [
        Document(
            page_content="# 西安亲子省心轻定制\n- 短动线、可午休、少排队。",
            metadata={
                "source": "data/documents/internal/products/xian_family_light_custom.md",
                "source_type": "agency_internal",
                "category": "products",
                "visibility": "internal",
                "evidence_level": "standard",
                "last_reviewed": "2026-05-11",
                "applicable_modes": "agency_plan",
                "product_id": "ZX-PROD-XIAN-FAMILY-3D",
                "source_kind": "demo_catalog",
                "inventory_status": "demo_only",
                "external_product_ref": "null",
                "destination": "西安",
                "theme": "亲子省心轻定制",
                "duration": "3天2晚",
                "audience": "family|child",
                "persona_tags": "price_sensitivity|parent_child",
                "service_level": "light_custom",
                "price_band": "comfort",
                "demo_price_label": "3999 起/2大1小（演示口径）",
                "product_source": "fictional_internal_catalog",
                "evidence_type": "fictional_product_template",
                "service_boundary": "路线规划|预约提醒|风险预案",
                "quote_basis": "规划服务口径|动态费用待二次核验",
                "verification_items": "交通票价|酒店库存|博物馆预约",
            },
        ),
        Document(
            page_content="# 苏州银发舒缓省心\n- 少步行、少换乘、休息点充足。",
            metadata={
                "source": "data/documents/internal/products/suzhou_senior_slow_custom.md",
                "source_type": "agency_internal",
                "category": "products",
                "visibility": "internal",
                "evidence_level": "standard",
                "last_reviewed": "2026-05-11",
                "applicable_modes": "agency_plan",
                "product_id": "ZX-PROD-SUZHOU-SENIOR-4D",
                "destination": "苏州",
                "theme": "银发舒缓路线",
                "duration": "4天3晚",
                "audience": "senior|family",
                "service_level": "escorted_planning",
                "price_band": "comfort",
                "product_source": "fictional_internal_catalog",
                "evidence_type": "fictional_product_template",
                "service_boundary": "低强度路线规划|休息点设计",
                "quote_basis": "舒缓节奏服务口径|资源待二次核验",
                "verification_items": "酒店电梯与无障碍|园林预约",
            },
        ),
    ]

    evidence = document_to_evidence(documents[0])
    response = format_evidence_response(
        query="省心产品方向",
        documents=documents,
        visibility="internal",
        include_product_directions=True,
    )

    assert evidence["product_id"] == "ZX-PROD-XIAN-FAMILY-3D"
    assert evidence["audience"] == ["family", "child"]
    assert evidence["source_kind"] == "demo_catalog"
    assert evidence["inventory_status"] == "demo_only"
    assert evidence["persona_tags"] == ["price_sensitivity", "parent_child"]
    assert evidence["service_boundary"] == ["路线规划", "预约提醒", "风险预案"]
    assert "【产品化方向】" in response
    assert "适用人群" in response
    assert "画像标签" in response
    assert "服务边界" in response
    assert "报价口径" in response
    assert "待核验项" in response
    assert "切回自由规划" in response


def test_validate_internal_knowledge_base_passes_current_corpus():
    report = validate_internal_knowledge_base(
        "data/documents/internal",
        today=date(2026, 5, 11),
    )

    assert report.passed is True
    assert report.checked_files >= 10
    assert not report.errors


def test_validate_product_document_requires_matching_fields(tmp_path):
    path = tmp_path / "internal" / "products" / "missing_product_fields.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        """---
source_type: agency_internal
category: products
visibility: internal
applicable_modes:
  - agency_plan
evidence_level: standard
last_reviewed: "2026-05-11"
---
# 缺少产品匹配字段
""",
        encoding="utf-8",
    )

    findings = validate_internal_document_file(
        path,
        internal_root=tmp_path / "internal",
        today=date(2026, 5, 11),
    )

    assert {
        "product_id",
        "destination",
        "theme",
        "duration",
        "audience",
        "source_kind",
        "inventory_status",
        "persona_tags",
        "service_level",
        "price_band",
        "source",
        "evidence_type",
    }.issubset({finding.field for finding in findings})


def test_validate_internal_document_fails_missing_metadata(tmp_path):
    path = tmp_path / "internal" / "pricing" / "missing.md"
    path.parent.mkdir(parents=True)
    path.write_text("# 缺少 metadata\n", encoding="utf-8")

    findings = validate_internal_document_file(
        path,
        internal_root=tmp_path / "internal",
        today=date(2026, 5, 11),
    )

    assert {finding.field for finding in findings} >= {
        "source_type",
        "category",
        "visibility",
        "applicable_modes",
        "evidence_level",
        "last_reviewed",
    }


def test_validate_internal_document_fails_expired_wrong_category_and_public_visibility(tmp_path):
    path = tmp_path / "internal" / "pricing" / "bad.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        """---
source_type: destination_guide
category: products
visibility: public
applicable_modes:
  - agency_plan
evidence_level: locked
last_reviewed: "2024-01-01"
---
# 错误分类
""",
        encoding="utf-8",
    )

    findings = validate_internal_document_file(
        path,
        internal_root=tmp_path / "internal",
        today=date(2026, 5, 11),
    )
    messages = "\n".join(f"{item.field}:{item.message}" for item in findings)

    assert "source_type" in messages
    assert "visibility" in messages
    assert "目录分类" in messages
    assert "evidence_level" in messages
    assert "超过 365 天" in messages


def _write_readiness_fixture(
    path: Path,
    *,
    collection_name: str = "agency_internal_knowledge",
    metadata_overrides: dict[str, str | None] | None = None,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "knowledge_base": INTERNAL_KNOWLEDGE_BASE,
        "source": "data/documents/internal/products/xian_family_light_custom.md",
        "source_type": "agency_internal",
        "category": "products",
        "visibility": "internal",
        "evidence_level": "standard",
        "applicable_modes": "agency_plan",
        "constraints": "不得承诺锁价",
        "last_reviewed": "2026-05-11",
        "freshness_status": "current",
        "requires_verification": "false",
        "product_id": "ZX-PROD-XIAN-FAMILY-3D",
        "source_kind": "demo_catalog",
        "inventory_status": "demo_only",
        "destination": "西安",
        "theme": "亲子省心轻定制",
        "duration": "3天2晚",
        "audience": "family|child",
        "persona_tags": "price_sensitivity|parent_child",
        "service_level": "light_custom",
        "price_band": "comfort",
        "evidence_type": "fictional_product_template",
        "chroma:document": "product_id 西安亲子省心轻定制 路线 产品 适合人群 服务边界",
    }
    for key, value in (metadata_overrides or {}).items():
        if value is None:
            metadata.pop(key, None)
        else:
            metadata[key] = value

    connection = sqlite3.connect(path / "chroma.sqlite3")
    try:
        connection.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("CREATE TABLE segments (id TEXT PRIMARY KEY, collection TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT, embedding_id TEXT)"
        )
        connection.execute(
            """
            CREATE TABLE embedding_metadata (
                id INTEGER,
                key TEXT,
                string_value TEXT,
                int_value INTEGER,
                float_value REAL,
                bool_value INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO collections (id, name) VALUES (?, ?)",
            ("collection-id", collection_name),
        )
        connection.execute(
            "INSERT INTO segments (id, collection) VALUES (?, ?)",
            ("segment-id", "collection-id"),
        )
        connection.execute(
            "INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?)",
            (1, "segment-id", "embedding-1"),
        )
        for key, value in metadata.items():
            connection.execute(
                """
                INSERT INTO embedding_metadata
                    (id, key, string_value, int_value, float_value, bool_value)
                VALUES (?, ?, ?, NULL, NULL, NULL)
                """,
                (1, key, value),
            )
        connection.commit()
    finally:
        connection.close()


def _internal_readiness(path: Path, *, collection_name: str = "agency_internal_knowledge"):
    return check_chroma_collection_readiness(
        configured_path=str(path),
        collection_name=collection_name,
        label=INTERNAL_VECTORSTORE_CONTRACT["label"],
        expected_metadata={
            "contract_version": CONTRACT_VERSION,
            "knowledge_base": INTERNAL_VECTORSTORE_CONTRACT["knowledge_base"],
            "visibility": INTERNAL_VECTORSTORE_CONTRACT["visibility"],
        },
        required_metadata=INTERNAL_VECTORSTORE_CONTRACT["required_metadata"],
        category_required_metadata=INTERNAL_VECTORSTORE_CONTRACT[
            "category_required_metadata"
        ],
        retrieval_probes=(),
    )


def test_readiness_finding_codes_cover_collection_metadata_missing_and_mismatch(tmp_path):
    missing_collection_path = tmp_path / "missing-collection"
    missing_metadata_path = tmp_path / "missing-metadata"
    mismatch_path = tmp_path / "mismatch"

    _write_readiness_fixture(missing_collection_path, collection_name="wrong")
    _write_readiness_fixture(missing_metadata_path, metadata_overrides={"product_id": None})
    _write_readiness_fixture(mismatch_path, metadata_overrides={"visibility": "public"})

    missing_collection = _internal_readiness(missing_collection_path)
    missing_metadata = _internal_readiness(missing_metadata_path)
    mismatch = _internal_readiness(mismatch_path)

    assert missing_collection.details["finding_code"] == "collection_missing"
    assert missing_metadata.details["finding_code"] == "metadata_missing"
    assert "product_id" in missing_metadata.details["missing_metadata"]
    assert mismatch.details["finding_code"] == "metadata_mismatch"
    assert mismatch.details["metadata_mismatch"]["key"] == "visibility"


def test_internal_rag_tools_are_separate_from_public_rag_tools():
    public_tool_names = {tool.name for tool in rag_tools.get_rag_tools()}
    internal_tool_names = {tool.name for tool in rag_tools.get_internal_rag_tools()}

    assert "search_destination_guide" in public_tool_names
    assert "search_agency_product_templates" not in public_tool_names
    assert "search_agency_product_templates" in internal_tool_names
    assert "search_agency_pricing_rules" in internal_tool_names


async def _fake_internal_pipeline():
    class FakePipeline:
        def retrieve(self, query):
            return [
                Document(
                    page_content=f"内部报价规则命中：{query}",
                    metadata={"source": "internal/pricing/pricing_rules.md"},
                )
            ]

    return FakePipeline()


@pytest.mark.asyncio
async def test_internal_pricing_tool_uses_internal_pipeline(monkeypatch):
    monkeypatch.setattr(
        rag_tools,
        "_get_internal_rag_pipeline",
        _fake_internal_pipeline,
    )

    result = await rag_tools.search_agency_pricing_rules.ainvoke(
        {"query": "预算包含什么"}
    )

    assert "内部报价规则命中" in result
    assert "报价" in result
    assert "RAG 检索证据契约" in result
    assert '"knowledge_base": "agency_internal_knowledge"' in result
    assert '"category": "pricing"' in result
    assert '"evidence_level": "rule"' in result
    assert "待二次核实" in result


async def _fake_internal_pipeline_with_category_filter():
    class FakePipeline:
        def retrieve(self, query, metadata_filter=None):
            assert metadata_filter == {"category": "pricing"}
            return [
                Document(
                    page_content=f"报价规则命中：{query}",
                    metadata={
                        "source": "internal/pricing/pricing_rules.md",
                        "category": "pricing",
                        "visibility": "internal",
                    },
                ),
                Document(
                    page_content="内部产品模板，不应该被报价工具返回。",
                    metadata={
                        "source": "internal/products/route_templates.md",
                        "category": "products",
                        "visibility": "internal",
                    },
                ),
            ]

    return FakePipeline()


@pytest.mark.asyncio
async def test_internal_pricing_tool_prefilters_by_category(monkeypatch):
    monkeypatch.setattr(
        rag_tools,
        "_get_internal_rag_pipeline",
        _fake_internal_pipeline_with_category_filter,
    )

    result = await rag_tools.search_agency_pricing_rules.ainvoke(
        {"query": "省心方案费用包含不包含"}
    )

    assert "报价规则命中" in result
    assert "内部产品模板" not in result
    assert '"category": "pricing"' in result


async def _fake_internal_pipeline_with_wrong_category():
    class FakePipeline:
        def retrieve(self, query):
            return [
                Document(
                    page_content="内部产品模板，不应该被报价工具返回。",
                    metadata={
                        "source": "internal/products/route_templates.md",
                        "category": "products",
                        "visibility": "internal",
                    },
                )
            ]

    return FakePipeline()


@pytest.mark.asyncio
async def test_internal_rag_tool_blocks_cross_category_results(monkeypatch):
    monkeypatch.setattr(
        rag_tools,
        "_get_internal_rag_pipeline",
        _fake_internal_pipeline_with_wrong_category,
    )

    result = await rag_tools.search_agency_pricing_rules.ainvoke(
        {"query": "预算包含什么"}
    )

    assert "暂未命中" in result
    assert "pricing" in result
    assert "内部产品模板" not in result


def test_parent_document_ids_are_stable_across_worktrees():
    splitter = AdvancedParentDocumentSplitter()
    source = (
        r"D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner"
        r"\data\documents\internal\pricing\pricing_rules.md"
    )
    legacy_source = (
        r"D:\Users\Administrator\PycharmProjects\ZhiXing\other-worktree"
        r"\data\documents\internal\pricing\pricing_rules.md"
    )
    parent_docs, child_docs = splitter.split_documents(
        [Document(page_content="报价规则：费用包含和不包含需要拆开说明。", metadata={"source": source})]
    )

    assert parent_docs[0].metadata["parent_id"] == (
        "data/documents/internal/pricing/pricing_rules.md__parent_0"
    )
    legacy_child = Document(
        page_content=child_docs[0].page_content,
        metadata={
            "parent_id": (
                f"{legacy_source}__parent_0"
            )
        },
    )

    assert splitter.get_parent_context([legacy_child]) == [parent_docs[0]]


def test_rag_pipeline_respects_disabled_llm_reranker(monkeypatch):
    class FailingReranker:
        def __init__(self, *args, **kwargs):
            raise AssertionError("LLM reranker should not be created")

    class FakeVectorStore:
        pass

    monkeypatch.setattr("app.rag.pipeline.LLMReranker", FailingReranker)

    pipeline = AdvancedRAGPipeline(
        vectorstore=FakeVectorStore(),
        all_documents=[Document(page_content="内部路线标准")],
        parent_splitter=object(),
        use_llm_reranker=False,
        enable_cache=False,
    )

    assert pipeline.reranker is None


def test_rag_pipeline_marks_stale_internal_documents_for_verification():
    pipeline = object.__new__(AdvancedRAGPipeline)
    docs = [
        Document(
            page_content="过期报价规则",
            metadata={
                "visibility": "internal",
                "evidence_level": "rule",
                "last_reviewed": "2024-01-01",
            },
        )
    ]

    result = pipeline._annotate_governance_metadata(docs)

    assert result[0].metadata["freshness_status"] == "expired"
    assert result[0].metadata["requires_verification"] == "true"
    assert "锁价" in result[0].metadata["prohibited_commitments"]


def test_rag_pipeline_skips_llm_rerank_during_retrieve():
    docs = [
        Document(page_content="doc-1"),
        Document(page_content="doc-2"),
        Document(page_content="doc-3"),
    ]

    class FakeCache:
        def get(self, query, top_k):
            return None

        def set(self, query, top_k, value):
            self.value = value

    class FakeOptimizer:
        def optimize(self, query):
            return [query]

    class FakeRetriever:
        def retrieve(self, query, queries):
            return docs

    class FakeParentSplitter:
        def get_parent_context(self, documents):
            return documents

    class FakeContextReorder:
        def reorder(self, documents):
            return list(documents)

    pipeline = object.__new__(AdvancedRAGPipeline)
    pipeline.top_k = 2
    pipeline.reranker = None
    pipeline.cache = FakeCache()
    pipeline.query_optimizer = FakeOptimizer()
    pipeline.retriever = FakeRetriever()
    pipeline.parent_splitter = FakeParentSplitter()
    pipeline.context_reorder = FakeContextReorder()

    result = pipeline.retrieve("省心路线")

    assert [doc.page_content for doc in result] == ["doc-1", "doc-2"]


def test_original_query_optimizer_does_not_call_llm(monkeypatch):
    monkeypatch.setattr(
        "app.rag.query_optimizer._get_rag_model",
        lambda: (_ for _ in ()).throw(AssertionError("RAG model should not be loaded")),
    )

    optimizer = AdvancedQueryOptimizer(strategy="original")

    assert optimizer.optimize("省心路线") == ["省心路线"]


def test_public_rag_pipeline_defaults_to_original_query_strategy(monkeypatch):
    captured = {}

    class FakeParentSplitter:
        def split_documents(self, documents):
            return documents, documents

    class FakeVectorStoreManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def load_vectorstore(self):
            return object()

        def create_vectorstore(self, documents):
            return object()

    class FakePipeline:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(rag_tools, "AdvancedParentDocumentSplitter", FakeParentSplitter)
    monkeypatch.setattr(rag_tools, "VectorStoreManager", FakeVectorStoreManager)
    monkeypatch.setattr(rag_tools, "AdvancedRAGPipeline", FakePipeline)
    monkeypatch.setattr(rag_tools, "_has_existing_vectorstore", lambda _: False)

    rag_tools._create_pipeline(
        documents=[Document(page_content="杭州西湖攻略")],
        persist_directory="data/vectorstore",
        collection_name="travel_guides",
        label="公开攻略 RAG",
    )

    assert captured["query_strategy"] == "original"
    assert captured["use_llm_reranker"] is False


async def _fake_public_pipeline_with_xian_document():
    class FakePipeline:
        def retrieve(self, query):
            return [
                Document(
                    page_content="西安兵马俑和城墙适合安排在古都文化路线中。",
                    metadata={"source": "data/documents/destinations/xian.md"},
                )
            ]

    return FakePipeline()


@pytest.mark.asyncio
async def test_public_rag_blocks_other_destination_content(monkeypatch):
    monkeypatch.setattr(
        rag_tools,
        "_get_rag_pipeline",
        _fake_public_pipeline_with_xian_document,
    )

    result = await rag_tools.search_destination_guide.ainvoke(
        {"query": "杭州 3天2晚 自由行攻略"}
    )

    assert "暂未覆盖" in result
    assert "杭州" in result
    assert "兵马俑" not in result


@pytest.mark.asyncio
async def test_public_rag_keeps_matching_destination_content(monkeypatch):
    monkeypatch.setattr(
        rag_tools,
        "_get_rag_pipeline",
        _fake_public_pipeline_with_xian_document,
    )

    result = await rag_tools.search_destination_guide.ainvoke(
        {"query": "西安 3天2晚 自由行攻略"}
    )

    assert "兵马俑" in result
    assert "xian.md" in result


async def _failing_rag_pipeline():
    class FailingPipeline:
        def retrieve(self, query):
            raise RuntimeError("temporary embedding outage")

    return FailingPipeline()


@pytest.mark.asyncio
async def test_public_rag_tool_degrades_to_empty_evidence_on_retrieval_failure(monkeypatch):
    monkeypatch.setattr(rag_tools, "_get_rag_pipeline", _failing_rag_pipeline)

    result = await rag_tools.search_destination_guide.ainvoke(
        {"query": "长沙 4天3晚 攻略"}
    )

    assert "RAG 检索证据契约" in result
    assert '"result_status": "empty"' in result
    assert "检索暂时不可用" in result
    assert "待二次核实" in result


@pytest.mark.asyncio
async def test_public_rag_tool_returns_readiness_diagnostics(monkeypatch):
    async def _not_ready_pipeline():
        raise RagReadinessError(
            "Public RAG vector store collection 'travel_guides' has no runtime retrieval hit for probe 'food_recommendations'.",
            {
                "finding_code": "retrieval_no_hit",
                "retrieval_probe_gap": {"probe": {"name": "food_recommendations"}},
            },
        )

    monkeypatch.setattr(rag_tools, "_get_rag_pipeline", _not_ready_pipeline)

    result = await rag_tools.search_food_recommendations.ainvoke(
        {"query": "西安 美食 推荐"}
    )

    assert '"result_status": "empty"' in result
    assert "reason=retrieval_no_hit" in result
    assert "probe=food_recommendations" in result
    assert "诊断信息" in result


@pytest.mark.asyncio
async def test_internal_rag_tool_degrades_to_empty_evidence_on_retrieval_failure(monkeypatch):
    monkeypatch.setattr(rag_tools, "_get_internal_rag_pipeline", _failing_rag_pipeline)

    result = await rag_tools.search_agency_pricing_rules.ainvoke(
        {"query": "长沙 4天3晚 报价规则"}
    )

    assert "RAG 检索证据契约" in result
    assert '"knowledge_base": "agency_internal_knowledge"' in result
    assert '"result_status": "empty"' in result
    assert "pricing" in result
    assert "检索暂时不可用" in result
