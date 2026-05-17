# RAG（检索增强生成）演示与评测指南

## 演示口径

本项目的 RAG 不只是“查几段攻略再回答”，而是给旅行顾问流程提供可解释依据：目的地知识、成熟路线样板、报价边界、风险规则、SOP（标准作业流程）和报告交付标准。面试时建议强调三件事：

- 检索命中的是“依据”，最终交付仍由状态机、工具调用和 `report_data`（结构化报告数据）共同完成。
- 产品化路线允许弱匹配：用户只说“想去新疆”，也可以先召回新疆 8 天小团/包车样板，再说明示例价、待核验和自由行替代。
- 结果不暴露 RAG、工具名、内部知识库或 `product_id`，面向用户只说“成熟路线样板”“合作产品候选”“省心路线方向”。

## 怎么看评测

运行命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
uv run python scripts\evaluate_rag_retrieval.py --json
uv run python scripts\evaluate_rag_retrieval.py --output docs\RAG与知识库\rag-retrieval-evaluation.md
```

指标解释：

| 指标 | 面试解释 |
|---|---|
| `source recall@K` | 前 K 个结果里是否召回到标注的具体知识文档。 |
| `category recall@K` | 前 K 个结果里是否覆盖正确知识类别，例如 `products`、`pricing`、`risk`。 |
| `source type recall@K` | 是否召回正确来源类型，例如公开目的地知识或内部业务知识。 |
| `hit rate@K` | 前 K 个结果里是否至少有一个相关依据。 |
| `MRR`（平均倒数排名） | 第一个相关结果越靠前，分数越高。 |

不要把它解释成线上全量效果。它是轻量标注集，用于证明知识组织、metadata（元数据）和检索策略能稳定命中关键证据。

## 产品化查询样例

当前标注集中新增了三类产品化演示查询：

- `想去新疆`：目的地级弱匹配，期望召回 `ZX-PROD-XINJIANG-PRIVATE-8D`。
- `西藏 两个人 预算一万多 省心`：目的地、人数、预算和省心意图混合匹配，期望召回 `ZX-PROD-TIBET-COUPLE-7D`。
- `西安 三天 亲子 性价比`：目的地、天数、人群和价格敏感混合匹配，期望召回 `ZX-PROD-XIAN-FAMILY-3D`。

演示时可以打开 `docs/RAG与知识库/rag-retrieval-evaluation.md`，看这些场景在 `metadata_aware_bm25` 下的 `first relevant rank` 和 `top sources`。如果用户没有拒绝产品，Agent（智能体）可以软推一个路线候选；如果用户明确说自由行、自己订或不要产品，中间件会收敛到自由规划。

## 产品目录边界

新增路线样板位于 `data/documents/internal/products/`。每个样板统一保留：

- `product_id`
- `source_kind: demo_catalog`
- `inventory_status: demo_only`
- `external_product_ref: null`
- 目的地、天数、适合人群、`persona_tags`
- 示例价口径、包含/不含、交通住宿口径、每日行程骨架、待核验项

这些字段为未来真实库存 API（应用程序接口）预留映射点，但本轮不接真实供应链，不写真实库存、真实报价、密钥或供应商资料。

## 面试可说的短句

> 我这里看 RAG 不是只看最终回复像不像，而是看它有没有检索到正确产品样板、正确知识类别和可解释依据。比如用户只说想去新疆，系统也能召回新疆 8 天包车小团样板，但对用户表达时会说明这是成熟路线候选、示例价待核验，也可以继续按自由行拆开规划。

## 样板调研边界

本轮只参考公开旅游产品页面的结构和字段组织方式，例如行程天数、费用包含/不含、交通住宿口径和待核验项；没有复制第三方品牌、文案、实时库存、价格承诺或联系方式。样板用于演示产品能力，真实商业接入应通过独立库存服务和合同口径完成。
