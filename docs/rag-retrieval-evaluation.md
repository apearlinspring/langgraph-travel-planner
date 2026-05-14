# 小型 RAG 召回率评估

## 定位

这份评估补的是 RAG（检索增强生成）链路里的“能不能把问题召回到正确知识源”证据。它不调用真实 LLM（大语言模型）、不连接向量库、不读取 `.env`，而是基于仓库内的公开目的地知识和旅行社内部知识，构造一个可复跑的小型标注集，用于回答面试里常见的“RAG 怎么验证召回效果”。

评估不是生产级全量 benchmark（基准测试），也不替代真实 embedding（向量嵌入）召回压测；它的价值是给当前项目提供一组清楚、可复跑、可解释的 Top-K 召回指标。

## 标注集

场景文件位于 `data/evaluation/rag_retrieval_scenarios.json`，当前覆盖 8 个查询：

- 公开目的地攻略：西安历史文化、美食、自由行攻略。
- 旅行社产品：亲子省心、银发低强度、成熟路线结构。
- 报价规则：费用包含 / 不含、待核验价格、预算置信度、合同边界。
- SOP（标准作业流程）：需求收集、关键项确认、避免重复追问。
- 风险规则：天气、体力、预约失败、Plan B（备用方案）。
- 报告交付：行程、交通住宿、预算、地图路线、风险和待核验项。

每个场景标注：

- `expected_sources`：期望命中的 Markdown（标记文本）知识源。
- `expected_categories`：期望命中的知识分类，例如 `pricing`、`risk`、`sop`。
- `expected_source_types`：公开攻略或旅行社内部资料。

## 对照策略

评估同时跑两种离线检索策略：

- `baseline_bm25`：只用正文做 BM25（词频检索算法）排序，作为朴素关键词基线。
- `metadata_aware_bm25`：正文加 metadata（元数据）字段，并按查询中的旅行社、报价、风险、报告、自由行等语义提示做轻量分类加权，模拟项目线上 RAG 的“正文 + 元数据契约”设计。

这里的加权只使用查询文本和文档 metadata，不读取标注答案，避免把 expected source（期望来源）直接注入检索过程。

## 指标

- `source recall@K`：Top-K 中命中的期望知识源比例。
- `category recall@K`：Top-K 中命中的期望分类比例。
- `source type recall@K`：Top-K 中命中的期望来源类型比例。
- `hit rate@K`：Top-K 是否至少命中一个相关知识源或相关分类。
- `MRR`（平均倒数排名）：第一个相关结果越靠前，分数越高。

## 运行方式

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py
.\.venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py --json
.\.venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py --output .runtime\rag-retrieval-evaluation.md
```

配套测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_rag_retrieval_evaluation.py -q
```

## 简历口径

可以写：

> 为旅行社内部知识 RAG 建立小型离线召回评估集，覆盖目的地攻略、产品路线、SOP、报价、风险和报告交付 6 类知识，使用 Top-K source recall、category recall 和 MRR 对比朴素 BM25 与元数据增强检索策略，用可复跑指标验证知识库组织与检索策略改进。

如果要写百分比，必须以最新脚本输出为准。建议表述为“在 8 条标注查询的小型评估集上，metadata-aware 检索相对正文 BM25 提升了 source recall@3 / category recall@3 / MRR”，不要泛化成大规模线上效果或真实用户指标。

## 当前复跑结果

2026-05-15 使用默认 8 条标注查询、11 份本地知识文档复跑结果：

| strategy | source recall@3 | category recall@3 | source type recall@3 | hit rate@3 | MRR |
|---|---:|---:|---:|---:|---:|
| baseline_bm25 | 93.75% | 93.75% | 100.00% | 100.00% | 0.9167 |
| metadata_aware_bm25 | 100.00% | 100.00% | 100.00% | 100.00% | 0.9375 |

可用于简历的保守描述：

> 在 8 条小型标注查询上，元数据增强检索的 source recall@3 和 category recall@3 达到 100%，相比正文 BM25 基线均提升 6.25 个百分点，MRR 从 0.9167 提升到 0.9375。

## 当前边界

- 标注集规模小，主要用于项目自证和面试讲解，不代表全量线上查询分布。
- 当前脚本评估本地 Markdown 知识召回，不评估真实 Chroma（向量库）和 DashScope embedding（阿里云灵积向量嵌入）效果。
- 真实线上链路仍应结合 `acceptance-core`、RAG 证据质量评分、工具质量和人工抽样一起判断。
