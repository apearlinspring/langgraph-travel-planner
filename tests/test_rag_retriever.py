from langchain_core.documents import Document

from app.rag.retriever import AdvancedHybridRetriever


def test_multi_query_retrieval_fuses_variants_instead_of_concatenating():
    primary_doc = Document(
        page_content="西安亲子短动线，可午休，少排队。",
        metadata={"child_id": "doc-primary"},
    )
    first_query_doc = Document(
        page_content="西安普通历史文化攻略。",
        metadata={"child_id": "doc-first-query"},
    )

    retriever = object.__new__(AdvancedHybridRetriever)
    retriever.k = 2
    retriever.bm25_weight = 0.4
    retriever.dense_weight = 0.6
    retriever.use_cache = False
    retriever._cache = None

    def fake_bm25_search(query, k, metadata_filter=None):
        if "短动线" in query:
            return [primary_doc]
        return [first_query_doc, primary_doc]

    def fake_dense_search(query, k, metadata_filter=None):
        if "短动线" in query:
            return [(primary_doc, 0.9)]
        return [(first_query_doc, 0.9)]

    retriever._bm25_search = fake_bm25_search
    retriever._dense_search = fake_dense_search

    results = retriever.retrieve(
        "西安亲子攻略",
        queries=["西安亲子攻略", "西安亲子攻略 短动线 少排队 可午休"],
    )

    assert [doc.metadata["child_id"] for doc in results] == [
        "doc-primary",
        "doc-first-query",
    ]


def test_retriever_boosts_precise_multimodal_candidate_after_fusion():
    image_doc = Document(
        page_content="城市公园中沿河步道适合老人低强度路线和亲子散步。",
        metadata={
            "child_id": "doc-image",
            "content_modality": "image",
            "source_format": "jpg",
            "source": "samplelib-city-park.jpg",
        },
    )
    video_doc = Document(
        page_content="城市道路视频样例，包含交通动线和低强度出行提示。",
        metadata={
            "child_id": "doc-video",
            "content_modality": "video",
            "source_format": "mp4",
            "source": "samplelib-city-road.mp4",
        },
    )

    retriever = object.__new__(AdvancedHybridRetriever)
    retriever.k = 2
    retriever.bm25_weight = 0.4
    retriever.dense_weight = 0.6
    retriever.use_cache = False
    retriever._cache = None

    def fake_bm25_search(query, k, metadata_filter=None):
        return [video_doc, image_doc]

    def fake_dense_search(query, k, metadata_filter=None):
        return [(video_doc, 0.9), (image_doc, 0.8)]

    retriever._bm25_search = fake_bm25_search
    retriever._dense_search = fake_dense_search

    results = retriever.retrieve("城市公园老人低强度路线")

    assert [doc.metadata["child_id"] for doc in results] == [
        "doc-image",
        "doc-video",
    ]


def test_retriever_prioritizes_explicit_destination_over_cross_city_candidate():
    matching_doc = Document(
        page_content="西安古都历史和本地小吃攻略。",
        metadata={
            "child_id": "doc-xian",
            "title": "西安公开目的地知识样例",
            "category": "destinations",
            "source_type": "destination_guide",
        },
    )
    cross_city_doc = Document(
        page_content="第一次自由行可看历史文化景点并品尝本地小吃。",
        metadata={
            "child_id": "doc-nanjing",
            "title": "南京公开目的地知识样例",
            "category": "destinations",
            "source_type": "destination_guide",
        },
    )

    retriever = object.__new__(AdvancedHybridRetriever)
    retriever.k = 2
    retriever.bm25_weight = 0.4
    retriever.dense_weight = 0.6
    retriever.use_cache = False
    retriever._cache = None
    retriever._bm25_search = lambda query, k, metadata_filter=None: [
        cross_city_doc,
        matching_doc,
    ]
    retriever._dense_search = lambda query, k, metadata_filter=None: [
        (cross_city_doc, 0.95),
        (matching_doc, 0.8),
    ]

    results = retriever.retrieve("第一次去西安自由行，想看历史文化和本地小吃。")

    assert [doc.metadata["child_id"] for doc in results] == [
        "doc-xian",
        "doc-nanjing",
    ]
