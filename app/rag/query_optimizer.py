"""
查询优化模块
包含 Multi-Query、HyDE、查询改写等策略
"""
from typing import List
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from app.utils.logger import app_logger
from app.utils.llm_factory import build_chat_model

load_dotenv()

_rag_model = None


def _get_rag_model():
    """懒加载 RAG 查询优化模型，避免 original 策略也初始化模型。"""

    global _rag_model
    if _rag_model is None:
        _rag_model = build_chat_model(
            profile="rag",
            temperature=0,
        )
    return _rag_model


LOCAL_EXPANSION_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("美食", "小吃", "餐厅", "吃"), ("特色美食", "本地小吃", "餐厅街区")),
    (("住宿", "酒店", "民宿", "住哪"), ("住宿区域", "酒店", "民宿", "交通便利")),
    (("景点", "景区", "门票", "开放时间"), ("景点介绍", "门票", "开放时间", "预约")),
    (("历史", "文化", "博物馆", "古城"), ("历史文化", "博物馆", "古迹", "城市漫游")),
    (("亲子", "孩子", "带娃"), ("亲子", "少排队", "短动线", "可午休")),
    (("老人", "银发", "长辈"), ("低强度", "少步行", "休息点", "无障碍")),
    (("省心", "旅行社", "产品", "小团"), ("产品路线", "成熟路线", "适合人群", "服务边界")),
    (("预算", "报价", "费用", "价格"), ("费用包含", "费用不含", "预算置信度", "待核验")),
    (("风险", "避坑", "天气", "预约失败"), ("风险提示", "Plan B", "预约", "二次核验")),
    (("报告", "导出", "交付"), ("报告结构", "预算明细", "待核验项", "风险提示")),
)


class LocalQueryExpander:
    """Deterministic query expansion for common travel-planning intents."""

    def __init__(self, max_variants: int = 3):
        self.max_variants = max_variants

    def optimize(self, query: str) -> List[str]:
        normalized = query.lower()
        variants: list[str] = [query]
        for triggers, expansions in LOCAL_EXPANSION_RULES:
            if not any(trigger.lower() in normalized for trigger in triggers):
                continue
            expanded_terms = " ".join(expansions)
            variants.append(f"{query} {expanded_terms}")
            if len(variants) > self.max_variants:
                break

        deduped: list[str] = []
        seen: set[str] = set()
        for item in variants:
            normalized_item = " ".join(item.split())
            if normalized_item and normalized_item not in seen:
                seen.add(normalized_item)
                deduped.append(normalized_item)
        return deduped[: self.max_variants + 1]


class MultiQueryOptimizer:
    """
    Multi-Query 优化器
    生成查询的多个变体以提高召回率
    """

    def __init__(self, num_variants: int = 3):
        self.num_variants = num_variants

        # 定义提示模板
        self.prompt = ChatPromptTemplate.from_template(
            """你是一个查询优化专家。给定一个用户查询，生成 {num} 个语义相似但表述不同的查询变体。

原始查询：{query}

要求：
1. 保持原查询的核心意图
2. 使用不同的词汇和表述方式
3. 考虑同义词、相关概念
4. 每行一个变体，不要编号

变体列表："""
        )

    def optimize(self, query: str) -> List[str]:
        """
        生成查询变体

        Args:
            query: 原始查询

        Returns:
            包含原始查询和变体的列表
        """

        app_logger.info(f"生成查询变体: {query}")

        # 调用 LLM 生成变体
        messages = self.prompt.format_messages(
            query=query,
            num=self.num_variants
        )

        response = _get_rag_model().invoke(messages)

        # 解析结果
        variants = [line.strip() for line in response.content.strip().split('\n') if line.strip()]

        # 添加原始查询
        all_queries = [query] + variants[:self.num_variants]

        app_logger.debug(f"生成了 {len(all_queries)} 个查询变体")
        for i, q in enumerate(all_queries):
            app_logger.debug(f"  {i + 1}. {q}")

        return all_queries

# ============== 示例用法 ==============

if __name__ == "__main__":
    optimizer = MultiQueryOptimizer(num_variants=3)

    original_query = "西安有哪些适合亲子游的景点？"
    variants = optimizer.optimize(original_query)

    print("\n=== Multi-Query 优化结果 ===")
    for i, q in enumerate(variants, 1):
        print(f"{i}. {q}")


class HyDEOptimizer:
    """
    HyDE (Hypothetical Document Embeddings) 优化器
    生成假设性文档用于检索
    """

    def __init__(self):
        self.prompt = ChatPromptTemplate.from_template(
            """请根据以下问题，生成一段假设性的回答文档。这个文档应该包含可能的答案内容。

问题：{query}

要求：
1. 200-300 字
2. 包含具体的景点名称、特点、推荐理由
3. 使用旅游攻略的语言风格

假设性文档："""
        )

    def generate_hypothetical_doc(self, query: str) -> str:
        """
        生成假设性文档

        Args:
            query: 原始查询

        Returns:
            假设性文档文本
        """

        app_logger.info(f"生成假设性文档: {query}")

        messages = self.prompt.format_messages(query=query)
        response = _get_rag_model().invoke(messages)

        hypothetical_doc = response.content.strip()

        app_logger.debug(f"假设性文档: {hypothetical_doc[:100]}...")

        return hypothetical_doc


# ============== 示例用法 ==============

if __name__ == "__main__":
    hyde = HyDEOptimizer()

    query = "西安有哪些适合亲子游的景点？"
    doc = hyde.generate_hypothetical_doc(query)

    print("\n=== HyDE 生成的假设性文档 ===")
    print(doc)


class QueryRewriter:
    """
    查询改写器
    修正错别字、口语化表达
    """

    def __init__(self):
        self.prompt = ChatPromptTemplate.from_template(
            """你是一个查询改写专家。请将用户的口语化查询改写为更规范的书面表达。

原始查询：{query}

要求：
1. 修正错别字
2. 将口语转为书面语
3. 保持查询意图不变
4. 只返回改写后的查询，不要解释

改写后："""
        )

    def rewrite(self, query: str) -> str:
        """
        改写查询

        Args:
            query: 原始查询

        Returns:
            改写后的查询
        """

        app_logger.info(f"改写查询: {query}")

        messages = self.prompt.format_messages(query=query)
        response = _get_rag_model().invoke(messages)

        rewritten = response.content.strip()

        app_logger.debug(f"改写结果: {rewritten}")

        return rewritten


# ============== 综合优化器 ==============

class AdvancedQueryOptimizer:
    """
    综合查询优化器
    整合 Multi-Query、HyDE、查询改写
    """

    def __init__(self, strategy: str = "multi_query"):
        """
        Args:
            strategy: 优化策略
                - "original": 直接使用原始查询
                - "local_multi_query": 使用本地规则生成查询变体
                - "multi_query": 使用 Multi-Query
                - "hyde": 使用 HyDE
                - "rewrite": 使用查询改写
                - "hybrid": 组合使用
        """
        self.strategy = strategy
        self.local_expander = LocalQueryExpander()
        self.multi_query = MultiQueryOptimizer()
        self.hyde = HyDEOptimizer()
        self.rewriter = QueryRewriter()

    def optimize(self, query: str) -> List[str]:
        """
        根据策略优化查询

        Returns:
            优化后的查询列表
        """

        if self.strategy in {"original", "none", "direct"}:
            return [query]

        if self.strategy in {"local_multi_query", "auto"}:
            return self.local_expander.optimize(query)

        if self.strategy == "multi_query":
            return self.multi_query.optimize(query)

        elif self.strategy == "hyde":
            hypothetical_doc = self.hyde.generate_hypothetical_doc(query)
            return [query, hypothetical_doc]

        elif self.strategy == "rewrite":
            rewritten = self.rewriter.rewrite(query)
            return [rewritten]

        elif self.strategy == "hybrid":
            # 先改写，再生成变体
            rewritten = self.rewriter.rewrite(query)
            variants = self.multi_query.optimize(rewritten)
            return variants

        else:
            app_logger.warning(f"未知策略: {self.strategy}，使用原始查询")
            return [query]  #本质上是为了对齐下游
