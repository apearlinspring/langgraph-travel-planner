from langchain_core.documents import Document
import pytest

from app.rag.document_loader import DocumentManager
from app.rag.contracts import CONTRACT_VERSION, INTERNAL_KNOWLEDGE_BASE
from app.rag.agency_retrieval import document_to_evidence
from app.rag.pipeline import AdvancedRAGPipeline
from app.rag.query_optimizer import AdvancedQueryOptimizer
from app.tools import rag_tools


def test_document_manager_loads_internal_documents_with_business_metadata():
    documents = DocumentManager().load_internal_documents()

    categories = {doc.metadata.get("category") for doc in documents}

    assert {"products", "sop", "pricing", "risk", "report"}.issubset(categories)
    assert all(doc.metadata.get("source_type") == "agency_internal" for doc in documents)
    assert all(doc.metadata.get("visibility") == "internal" for doc in documents)
    assert all(doc.metadata.get("contract_version") == CONTRACT_VERSION for doc in documents)
    assert all(doc.metadata.get("knowledge_base") == INTERNAL_KNOWLEDGE_BASE for doc in documents)
    assert all(doc.metadata.get("evidence_level") for doc in documents)
    assert all(doc.metadata.get("applicable_modes") for doc in documents)
    assert all(doc.metadata.get("constraints") for doc in documents)


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
