# RAG（检索增强生成）演示与评测指南

## 2026-07-12 北京公开样例校准复跑结果

本轮文档校准只复跑轻量召回评测，不重建向量库，不连接真实模型或外部 API（应用程序接口），也不更新服务器服务。当前仓库资产快照为：`data/evaluation/rag_retrieval_scenarios.json` 包含 27 条召回场景，`data/documents/` 下共有 26 份 Markdown（标记文本）知识文档，其中公开目的地样例覆盖西安、杭州、厦门、桂林、南京和北京 6 份，`data/documents/internal/products/` 下有 11 份产品/路线样板。

执行命令：

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
uv run python scripts\evaluate_rag_retrieval.py --output docs\RAG与知识库\rag-retrieval-evaluation.md
```

当前 `metadata_aware_bm25` 在 top-5 下的结果：

- `source_recall`: 100.00%
- `category_recall`: 100.00%
- `source_type_recall`: 100.00%
- `visibility_recall`: 100.00%
- `hit_rate`: 100.00%
- `safety_pass_rate`: 100.00%
- `mrr`: 0.9815

当前 mixed-corpus safety gate（公开+内部混合候选库安全门）覆盖 11 个公开安全场景、26 份候选文档，`metadata_aware_bm25` top-3 的 source/category/source_type/visibility recall 均为 100%，`safety_pass_rate` 为 100%。这只表示这 11 条标注查询在当前离线候选库中没有返回场景禁止的内部产品、报价、SOP（标准作业流程）、风控、报告规范或内部门票参考知识；未知查询、提示注入、真实向量检索和线上链路仍需单独验证。

当前轻量评测的剩余缺口不是“召回失败”，而是样本仍是小规模公开模拟语料：西安、杭州、厦门、桂林、南京和北京样例用于工程验收，不代表真实库存、实时价格、供应商承诺或官方预约结果。

## 2026-07-11 南京样例校准结果（历史快照）

本轮扩充前的快照为 26 条召回场景、25 份 Markdown 文档、5 个公开目的地（西安、杭州、厦门、桂林和南京）与 10 个 mixed-corpus safety 场景；`metadata_aware_bm25` top-5 的 source/category/source type/visibility recall 和 safety pass rate 均为 100%，MRR 为 0.9808。这些数字只是 2026-07-11 历史离线快照，不是当前规模，也不代表真实向量库或在线 Agent 验收。

## 2026-05-17 真实环境刷新结果（历史参考）

本轮在 `codex/productized-rag-real-env-refresh` 分支、`origin/main@ea682ff` 基准上复跑。真实 `.env` 仅在本机用于运行；`.env`、`.runtime/`、`.venv/`、`data/vectorstore/` 和 `data/vectorstore_internal/` 均由 Git（版本控制系统）忽略，未写入本文档。

执行范围只覆盖本地真实环境验证，不更新服务器服务：

- `uv run python -m scripts.init_rag`：通过。公开攻略 RAG 写入 18 条 embeddings（嵌入向量），内部知识库 RAG 写入 130 条 embeddings；Chroma（向量库组件）元数据文件均生成并通过 readiness（就绪状态）检查。仅出现非阻塞 telemetry（遥测）告警。
- `uv run python scripts\evaluate_rag_retrieval.py --json`：通过。`metadata_aware_bm25` 在 top-5 下 source/category/source_type recall（来源、类别和来源类型召回率）均为 100%，hit rate（命中率）为 100%，MRR（平均倒数排名）为 0.9500。
- 产品化重点召回：`想去新疆` 命中 `xinjiang_private_group_8d.md` 第 1 位；`西藏 两个人 预算一万多 省心` 召回 `tibet_couple_light_custom_7d.md` 第 2 位；`西安 三天 亲子 性价比` 命中 `xian_family_light_custom.md` 第 1 位。
- 本地后端在 `127.0.0.1:8001` 启动验证，避免误连已占用 `8000` 的其他服务。`/health/live` 返回 `alive`，`/health/ready` 返回 `ready`；MCP（模型上下文协议）服务池 6 个服务 healthy（健康），共 37 个 tools（工具）。
- `uv run python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8001 --json`：通过，`status=passed`，`readiness_status=ready`，无 blocked reasons（环境阻塞原因）。
- `uv run python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8001 --json --summary-dir .runtime\acceptance-smoke`：通过。`pricing_agency_quote_explanation` 1/1 passed（通过），Agent（智能体）综合分 100.0，工业指标平均分 94.29，`report_data`、预算、预算置信度、风险、待核验项和旅行社业务证据均闭环。

运行观察：

- 真实铁路上游查询出现 `get-tickets` payload failure（载荷失败）和 guarded timeout（受保护超时），系统按兜底证据继续推进，没有把失败包装成真实票价或锁定库存。
- LangSmith（LangChain 可观测平台）上报出现 429 rate limit（速率限制），不影响本地 API（应用程序接口）链路和 acceptance-smoke（验收冒烟测试）门禁结果。
- `.runtime/acceptance-smoke/20260517-141657-acceptance-summary.*` 和 `.runtime/evaluations/20260517-221657-pricing_agency_quote_explanation.json` 仅作为本机原始证据保留，不进入提交。

## 演示口径

本项目的 RAG 不只是“查几段攻略再回答”，而是给旅行顾问流程提供可解释依据：目的地知识、成熟路线样板、报价边界、风险规则、SOP（标准作业流程）和报告交付标准。项目展示时建议强调三件事：

- 检索命中的是“依据”，最终交付仍由状态机、工具调用和 `report_data`（结构化报告数据）共同完成。
- 产品化路线允许弱匹配：用户只说“想去新疆”，也可以先召回新疆 8 天小团/包车样板，再说明示例价、待核验和自由行替代。
- 结果不暴露 RAG、工具名、内部知识库或 `product_id`，面向用户只说“成熟路线样板”“合作产品候选”“省心路线方向”。

## 怎么看评测

当前仓库资产快照：`data/evaluation/rag_retrieval_scenarios.json` 包含 27 条召回场景，`data/documents/` 下共有 26 份 Markdown（标记文本）知识文档，其中公开目的地样例覆盖西安、杭州、厦门、桂林、南京和北京 6 份，`data/documents/internal/products/` 下有 11 份产品/路线样板。历史运行结果只代表当时知识库与场景规模，实际结论以重新运行脚本输出为准。

运行命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
uv run python scripts\evaluate_rag_retrieval.py --json
uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
uv run python scripts\evaluate_rag_retrieval.py --output docs\RAG与知识库\rag-retrieval-evaluation.md
```

指标解释：

| 指标 | 项目解释 |
|---|---|
| `source recall@K` | 前 K 个结果里是否召回到标注的具体知识文档。 |
| `category recall@K` | 前 K 个结果里是否覆盖正确知识类别，例如 `products`、`pricing`、`risk`。 |
| `source type recall@K` | 是否召回正确来源类型，例如公开目的地知识或内部业务知识。 |
| `visibility recall@K` | 是否召回正确可见性，例如 `public` 或 `internal`。 |
| `hit rate@K` | 前 K 个结果里是否至少有一个相关依据。 |
| `safety pass rate` | 返回结果中没有命中场景标记的 forbidden（禁止）类别、来源类型或可见性。 |
| `MRR`（平均倒数排名） | 第一个相关结果越靠前，分数越高。 |

不要把它解释成线上全量效果。它是轻量标注集，用于证明知识组织、metadata（元数据）和检索策略能稳定命中关键证据。

`passed` 只表示当前命令在当前本地知识文档和标注场景下通过；如果缺真实向量库、缺真实密钥、后端不可达或 mixed-corpus safety gate 失败，应记为 `blocked`，不能包装成真实验收通过。

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

## 展示可说的短句

> 我这里看 RAG 不是只看最终回复像不像，而是看它有没有检索到正确产品样板、正确知识类别和可解释依据。比如用户只说想去新疆，系统也能召回新疆 8 天包车小团样板，但对用户表达时会说明这是成熟路线候选、示例价待核验，也可以继续按自由行拆开规划。

## 样板调研边界

本轮只参考公开旅游产品页面的结构和字段组织方式，例如行程天数、费用包含/不含、交通住宿口径和待核验项；没有复制第三方品牌、文案、实时库存、价格承诺或联系方式。样板用于演示产品能力，真实商业接入应通过独立库存服务和合同口径完成。
