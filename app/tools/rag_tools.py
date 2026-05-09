"""
RAG 检索工具
将 Advanced RAG 管道封装为 Agent 可自主调用的工具
"""
from pathlib import Path
from typing import Optional
from langchain.tools import tool
from langchain_core.tools import ToolException
from app.rag.pipeline import AdvancedRAGPipeline
from app.rag.document_loader import DocumentManager
from app.rag.text_splitter import AdvancedParentDocumentSplitter
from app.rag.vectorstore import VectorStoreManager
from app.utils.logger import app_logger


# ============== 全局 RAG 管道实例（懒加载） ==============

_rag_pipeline: Optional[AdvancedRAGPipeline] = None
_parent_splitter: Optional[AdvancedParentDocumentSplitter] = None
_internal_rag_pipeline: Optional[AdvancedRAGPipeline] = None
_internal_parent_splitter: Optional[AdvancedParentDocumentSplitter] = None


_DESTINATION_ALIASES = {
    "北京": ("北京", "beijing"),
    "上海": ("上海", "shanghai"),
    "广州": ("广州", "guangzhou"),
    "深圳": ("深圳", "shenzhen"),
    "杭州": ("杭州", "hangzhou"),
    "南京": ("南京", "nanjing"),
    "苏州": ("苏州", "suzhou"),
    "成都": ("成都", "chengdu"),
    "重庆": ("重庆", "chongqing"),
    "西安": ("西安", "xian", "xi'an", "xi-an"),
    "长沙": ("长沙", "changsha"),
    "武汉": ("武汉", "wuhan"),
    "厦门": ("厦门", "xiamen"),
    "青岛": ("青岛", "qingdao"),
    "大连": ("大连", "dalian"),
    "桂林": ("桂林", "guilin"),
    "丽江": ("丽江", "lijiang"),
    "大理": ("大理", "dali"),
    "昆明": ("昆明", "kunming"),
    "三亚": ("三亚", "sanya"),
    "海口": ("海口", "haikou"),
    "拉萨": ("拉萨", "lasa", "lhasa"),
    "乌鲁木齐": ("乌鲁木齐", "wulumuqi", "urumqi"),
    "哈尔滨": ("哈尔滨", "haerbin", "harbin"),
    "沈阳": ("沈阳", "shenyang"),
    "天津": ("天津", "tianjin"),
    "济南": ("济南", "jinan"),
    "郑州": ("郑州", "zhengzhou"),
    "太原": ("太原", "taiyuan"),
    "合肥": ("合肥", "hefei"),
    "福州": ("福州", "fuzhou"),
    "南昌": ("南昌", "nanchang"),
    "贵阳": ("贵阳", "guiyang"),
    "南宁": ("南宁", "nanning"),
    "兰州": ("兰州", "lanzhou"),
    "西宁": ("西宁", "xining"),
    "银川": ("银川", "yinchuan"),
    "呼和浩特": ("呼和浩特", "huhehaote", "hohhot"),
    "眉县": ("眉县", "meixian"),
    "马尔代夫": ("马尔代夫", "maldives"),
}


def _has_existing_vectorstore(persist_directory: str) -> bool:
    path = Path(persist_directory)
    return path.exists() and any(path.iterdir())


def _create_pipeline(
    *,
    documents: list,
    persist_directory: str,
    collection_name: str,
    label: str,
    query_strategy: str = "original",
) -> tuple[AdvancedRAGPipeline, AdvancedParentDocumentSplitter]:
    """从文档集合创建或加载一条 RAG 管道。"""

    parent_splitter = AdvancedParentDocumentSplitter()
    _parent_docs, child_docs = parent_splitter.split_documents(documents)

    vs_manager = VectorStoreManager(
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
    if _has_existing_vectorstore(persist_directory):
        vectorstore = vs_manager.load_vectorstore()
        app_logger.info(f"✅ {label} 向量数据库加载成功")
    else:
        app_logger.info(f"📦 {label} 向量数据库不存在，创建新的...")
        vectorstore = vs_manager.create_vectorstore(child_docs)

    pipeline = AdvancedRAGPipeline(
        vectorstore=vectorstore,
        all_documents=child_docs,
        parent_splitter=parent_splitter,
        query_strategy=query_strategy,
        use_llm_reranker=False,
        top_k=3,
        enable_cache=True,
    )
    return pipeline, parent_splitter


async def _get_rag_pipeline() -> AdvancedRAGPipeline:
    """获取或初始化全局 RAG 管道实例（单例模式）"""
    global _rag_pipeline, _parent_splitter

    if _rag_pipeline is None:
        app_logger.info("🔧 初始化 RAG 管道...")

        # 1. 加载文档
        doc_manager = DocumentManager()
        documents = doc_manager.load_destination_documents()

        if not documents:
            app_logger.warning("⚠️ 未找到目的地文档，RAG 功能可能受限")
            documents = []

        _rag_pipeline, _parent_splitter = _create_pipeline(
            documents=documents,
            persist_directory="data/vectorstore",
            collection_name="travel_guides",
            label="公开攻略 RAG",
            query_strategy="original",
        )

        app_logger.info("✅ RAG 管道初始化完成")

    return _rag_pipeline


async def _get_internal_rag_pipeline() -> AdvancedRAGPipeline:
    """获取或初始化旅行社内部知识库 RAG 管道。"""
    global _internal_rag_pipeline, _internal_parent_splitter

    if _internal_rag_pipeline is None:
        app_logger.info("🔧 初始化旅行社内部知识库 RAG 管道...")

        doc_manager = DocumentManager()
        documents = doc_manager.load_internal_documents()
        if not documents:
            app_logger.warning("⚠️ 未找到内部知识库文档，内部 RAG 功能可能受限")
            documents = []

        _internal_rag_pipeline, _internal_parent_splitter = _create_pipeline(
            documents=documents,
            persist_directory="data/vectorstore_internal",
            collection_name="agency_internal_knowledge",
            label="旅行社内部知识库 RAG",
            query_strategy="original",
        )

        app_logger.info("✅ 旅行社内部知识库 RAG 管道初始化完成")

    return _internal_rag_pipeline


def _format_rag_results(documents: list, query: str) -> str:
    """格式化 RAG 检索结果"""
    if not documents:
        return f"未找到与「{query}」相关的信息。"

    result_parts = []
    for i, doc in enumerate(documents, 1):
        content = doc.page_content[:800]
        if len(doc.page_content) > 800:
            content += "..."

        source = doc.metadata.get("source", "未知来源")
        result_parts.append(f"【资料 {i}】\n{content}\n来源：{source}")

    return "\n\n".join(result_parts)


def _extract_requested_destinations(query: str) -> set[str]:
    """从查询中识别明确目的地，避免公开攻略库返回其他城市内容。"""
    return {
        destination
        for destination, aliases in _DESTINATION_ALIASES.items()
        if any(alias.lower() in query.lower() for alias in aliases)
    }


def _document_matches_destination(doc, destination: str) -> bool:
    metadata_text = " ".join(str(value) for value in doc.metadata.values())
    haystack = f"{doc.page_content}\n{metadata_text}".lower()
    return any(alias.lower() in haystack for alias in _DESTINATION_ALIASES[destination])


def _filter_documents_by_requested_destinations(
    documents: list,
    requested_destinations: set[str],
) -> list:
    if not requested_destinations:
        return documents

    return [
        doc
        for doc in documents
        if any(
            _document_matches_destination(doc, destination)
            for destination in requested_destinations
        )
    ]


def _format_public_destination_gap(query: str, requested_destinations: set[str]) -> str:
    destination_label = "、".join(sorted(requested_destinations))
    return (
        f"本地公开攻略库暂未覆盖「{destination_label}」的专门资料。"
        "为避免把其他目的地攻略误当作当前目的地，我没有返回不匹配内容；"
        "请优先使用实时搜索工具，或基于当前对话给出通用规划建议。"
        f"\n原始查询：{query}"
    )


async def _retrieve_public(query: str, enhanced_query: str | None = None) -> str:
    pipeline = await _get_rag_pipeline()
    requested_destinations = _extract_requested_destinations(query)
    documents = pipeline.retrieve(enhanced_query or query)

    if requested_destinations:
        matched_documents = _filter_documents_by_requested_destinations(
            documents,
            requested_destinations,
        )
        if not matched_documents:
            app_logger.info(
                "公开攻略 RAG 未命中查询目的地，已拦截不匹配内容: "
                f"{query} -> {sorted(requested_destinations)}"
            )
            return _format_public_destination_gap(query, requested_destinations)
        documents = matched_documents

    return _format_rag_results(documents, query)


async def _retrieve_internal(query: str, enhanced_query: str | None = None) -> str:
    pipeline = await _get_internal_rag_pipeline()
    documents = pipeline.retrieve(enhanced_query or query)
    return _format_rag_results(documents, query)


# ============== RAG 检索工具定义 ==============

@tool
async def search_destination_guide(query: str) -> str:
    """
    从旅游攻略知识库中检索目的地相关信息。

    当你需要获取以下信息时应该使用此工具：
    - 目的地的景点介绍、门票价格、开放时间
    - 旅游攻略、游玩建议、推荐路线
    - 目的地的交通指南、住宿区域推荐
    - 任何需要从知识库获取的旅游相关信息

    Args:
        query: 检索查询，例如 "西安兵马俑门票和游玩建议"、"成都必去景点推荐"

    Returns:
        检索到的相关攻略信息，如果没有找到会返回提示信息
    """
    app_logger.info(f"RAG 工具被调用: {query}")

    try:
        return await _retrieve_public(query)
    except Exception as e:
        app_logger.error(f"❌ RAG 检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_food_recommendations(query: str) -> str:
    """
    从美食知识库中检索目的地美食信息。

    当你需要获取以下信息时应该使用此工具：
    - 目的地的特色美食、必吃小吃
    - 餐厅推荐、美食街区
    - 菜品价格参考

    Args:
        query: 美食相关查询，例如 "西安特色美食推荐"、"成都火锅哪家好"

    Returns:
        检索到的美食推荐信息
    """
    app_logger.info(f"美食检索工具被调用: {query}")

    try:
        return await _retrieve_public(query, f"{query} 美食 餐厅 小吃")
    except Exception as e:
        app_logger.error(f"❌ 美食检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_accommodation_info(query: str) -> str:
    """
    从住宿知识库中检索目的地住宿信息。

    当你需要获取以下信息时应该使用此工具：
    - 目的地的住宿区域推荐
    - 不同类型住宿的特点和价格范围
    - 酒店/民宿选择建议

    Args:
        query: 住宿相关查询，例如 "西安住哪个区域好"、"成都民宿推荐"

    Returns:
        检索到的住宿推荐信息
    """
    app_logger.info(f"住宿检索工具被调用: {query}")

    try:
        return await _retrieve_public(query, f"{query} 住宿 酒店 民宿")
    except Exception as e:
        app_logger.error(f"❌ 住宿检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_travel_tips(query: str) -> str:
    """
    从知识库中检索旅行实用信息和注意事项。

    当你需要获取以下信息时应该使用此工具：
    - 目的地的旅行注意事项、避坑指南
    - 最佳旅游季节、穿衣建议
    - 当地交通、消费水平等实用信息

    Args:
        query: 实用信息查询，例如 "西安旅游注意事项"、"成都几月去最好"

    Returns:
        检索到的旅行实用信息
    """
    app_logger.info(f"旅行贴士检索工具被调用: {query}")

    try:
        return await _retrieve_public(query, f"{query} 注意事项 建议 提示")
    except Exception as e:
        app_logger.error(f"❌ 旅行贴士检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_agency_product_templates(query: str) -> str:
    """
    从旅行社内部产品路线模板中检索成熟路线结构、适合人群和产品化表达。

    当用户希望省心安排、旅行社方案、亲子/情侣/银发/团建等产品化路线时使用。
    """
    try:
        return await _retrieve_internal(query, f"{query} 产品 路线 模板 适合人群 成熟路线")
    except Exception as e:
        app_logger.error(f"❌ 内部产品模板检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_agency_service_sop(query: str) -> str:
    """
    从旅行社内部服务 SOP 中检索顾问流程、话术原则和服务优势表达。

    当需要让回复像真实旅行顾问、解释服务流程或整理交付逻辑时使用。
    """
    try:
        return await _retrieve_internal(query, f"{query} 服务 SOP 顾问 流程 交付")
    except Exception as e:
        app_logger.error(f"❌ 内部服务 SOP 检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_agency_pricing_rules(query: str) -> str:
    """
    从旅行社内部报价规则中检索预算组成、费用依据和预算置信度标准。

    当用户询问预算、报价、费用包含/不包含或最终报告预算说明时使用。
    """
    try:
        return await _retrieve_internal(query, f"{query} 报价 预算 费用 置信度 待核验")
    except Exception as e:
        app_logger.error(f"❌ 内部报价规则检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_agency_risk_playbook(query: str) -> str:
    """
    从旅行社内部风险与避坑手册中检索天气、交通、酒店、景区和体力风险建议。

    当需要给出避坑提醒、Plan B、风险说明或出发前核验清单时使用。
    """
    try:
        return await _retrieve_internal(query, f"{query} 风险 避坑 天气 交通 酒店 景区 Plan B")
    except Exception as e:
        app_logger.error(f"❌ 内部风险手册检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


@tool
async def search_agency_report_standards(query: str) -> str:
    """
    从旅行社内部报告标准中检索最终旅游规划报告的章节、结构和禁止内容。

    当用户要求生成最终报告、导出报告或调整报告结构时使用。
    """
    try:
        return await _retrieve_internal(query, f"{query} 最终报告 章节 结构 导出 禁止内容")
    except Exception as e:
        app_logger.error(f"❌ 内部报告标准检索失败: {e}")
        raise ToolException(f"检索过程中出现错误：{str(e)}")


# ============== 工具集合 ==============

def get_rag_tools() -> list:
    """获取公开攻略 RAG 工具，保持目的地 router 的现有兼容性。"""
    return [
        search_destination_guide,
        search_food_recommendations,
        search_accommodation_info,
        search_travel_tips,
    ]


def get_internal_rag_tools() -> list:
    """获取旅行社内部知识库 RAG 工具。"""
    return [
        search_agency_product_templates,
        search_agency_service_sop,
        search_agency_pricing_rules,
        search_agency_risk_playbook,
        search_agency_report_standards,
    ]
