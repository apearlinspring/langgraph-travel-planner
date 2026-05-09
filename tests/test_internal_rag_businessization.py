from langchain_core.documents import Document
import pytest

from app.rag.document_loader import DocumentManager
from app.rag.pipeline import AdvancedRAGPipeline
from app.rag.query_optimizer import AdvancedQueryOptimizer
from app.tools import rag_tools


def test_document_manager_loads_internal_documents_with_business_metadata():
    documents = DocumentManager().load_internal_documents()

    categories = {doc.metadata.get("category") for doc in documents}

    assert {"products", "sop", "pricing", "risk", "report"}.issubset(categories)
    assert all(doc.metadata.get("source_type") == "agency_internal" for doc in documents)
    assert all(doc.metadata.get("visibility") == "internal" for doc in documents)


def test_document_manager_filters_internal_documents_by_category():
    documents = DocumentManager().load_internal_documents(category="pricing")

    assert documents
    assert {doc.metadata.get("category") for doc in documents} == {"pricing"}
    assert any("报价" in doc.page_content for doc in documents)


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
