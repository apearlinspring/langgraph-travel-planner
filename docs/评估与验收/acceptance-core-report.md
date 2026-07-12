# Acceptance Core Evidence Pack（核心验收证据包）

## 2026-07-12 当前统一验收结论

- 证据范围：`final-core-6`（当前工作树完整 9 场统一运行）
- 当前门禁状态：passed（通过）
- 当前场景结果：9 / 9 passed（通过）
- 报告质量分：9 个场景均为 `100`
- Agent（智能体）工业指标分：9 个场景均为 `100`
- runtime budget（运行预算）：9 个场景均为 passed（通过）
- 运行日期：2026-07-12
- 工作树基准：`b45b280-dirty`
- `origin/main`：`b45b280`
- 工作树状态：`dirty_items=186`；本结论对应当时未提交工作树，不能等同于干净 commit（提交）可复现证据
- 真实依赖：本地 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG（检索增强生成）和 MCP（模型上下文协议）
- 本地证据：`.runtime/` 中的 `final-core-6` 运行产物；该目录仅作未提交的本地证据目录，未读取或复制原始快照内容到本文档
- 验收后内容边界校准：`final-core-6` 完成后，仅调整北京知识文档中的一句内容边界措辞，业务代码没有变化；该措辞已通过相关测试和 RAG 离线校验，运行时向量索引已由主线程按当前文档重建

本轮不是历史分批结果的拼接，而是在同一后端代码快照和同一组真实本地依赖上完整执行 9 个 acceptance-core（核心验收）场景。9 个场景均同时通过报告质量、Agent 工业指标和运行预算门禁。

### 当前场景状态地图

| 场景 | 模式 | 状态 | 报告质量分 | Agent 工业指标分 | 运行预算 | 场景耗时 |
|---|---|---:|---:|---:|---|---:|
| free_weekend_nearby | free_planning | passed（通过） | 100 | 100 | passed（通过） | 281.55 秒 |
| free_city_three_days | free_planning | passed（通过） | 100 | 100 | passed（通过） | 374.48 秒 |
| agency_couple_relaxed | agency_plan | passed（通过） | 100 | 100 | passed（通过） | 420.78 秒 |
| agency_family_parent_child | agency_plan | passed（通过） | 100 | 100 | passed（通过） | 291.11 秒 |
| agency_senior_low_stress | agency_plan | passed（通过） | 100 | 100 | passed（通过） | 407.35 秒 |
| edge_hotel_tool_fallback | free_planning | passed（通过） | 100 | 100 | passed（通过） | 370.48 秒 |
| pricing_agency_quote_explanation | agency_plan | passed（通过） | 100 | 100 | passed（通过） | 296.81 秒 |
| risk_weather_disruption | agency_plan | passed（通过） | 100 | 100 | passed（通过） | 210.70 秒 |
| edge_transport_tool_fallback | free_planning | passed（通过） | 100 | 100 | passed（通过） | 539.33 秒 |

- 9 个场景耗时逐项合计：3192.59 秒。
- 跑批记录总历时：约 3198.4 秒；与逐项合计的差额来自场景间调度和收尾开销。

### 当前 RAG 与外部能力边界

- 当前 RAG 评估集合：27 个场景。
- 当前知识文档：26 个 Markdown（轻量标记语言）文档。
- public corpus（公开语料）覆盖 6 个目的地。
- mixed-corpus safety（混合语料安全）覆盖 11 个场景。
- 铁路查询使用临时本地非官方社区 12306 sidecar（伴随服务）`v0.3.9`，地址为 `127.0.0.1:18081`。它不是 12306 官方服务，也不构成生产环境可用性或 SLA（服务等级协议）承诺。

### 本轮诊断与修复闭环

- 将阶段工具结果统一为结构化 state outcome（状态结果），明确区分 `applied`、`already_applied` 和 `not_applied`，避免失败调用被误记为成功迁移。
- 收紧“一轮一阶段”推进规则，防止单轮跨越多个业务阶段或在条件不足时提前生成报告。
- 对结构化行程、预算汇总和订单生成采用确定性报告工具派发，降低模型未按要求选择零参数工具造成的随机失败。
- 对动态交通断言增加逐句限定；缺少实时证据时明确标注待二次核验并以官方实时结果为准。
- 补齐北京目的地 RAG 语料与评估覆盖，修正精确目的地检索边界。
- 分离静态偏好与 pending（待补充）数值字段，避免偏好复用污染人数、天数和预算等本轮必要参数。

### 性能口径与当前限制

- 首 token（文本令牌）约 `0.01s` 只对应固定 ACK（确认回执），只能证明连接后很快收到确认；它不代表有意义首内容时延，也不代表总处理时延。端到端耗时应以场景表中的实际值为准。
- `final-core-6` 证明当前本地工作树在一次统一运行中 9 / 9 通过，不证明多次重复运行稳定性、线上容量、外部服务长期可靠性或生产可用性。
- 当前工作树含 186 个未提交项目；若要对外提供可复现证据，仍需将目标代码和正式文档整理到明确 commit 后再执行一次干净基准验收。

## 2026-05-17 历史单次跑批结论

- 证据范围：`historical_single_run`（历史单次运行）
- 当时门禁状态: passed（通过）
- 当时场景结果: 9 / 9 passed（通过）
- 状态统计: passed=9, failed=0, degraded=0, blocked=0, skipped=0
- 运行日期: 2026-05-17
- 基准: `origin/main@335a1d4`
- 分支: `codex/acceptance-core-real-run-stabilization`
- readiness（就绪检查）: passed（通过），后端 `/health/ready` 为 `ready`
- acceptance-smoke（冒烟验收）摘要: `.runtime/evaluations/summaries/20260517-111953-smoke-20260517-191226.json`
- acceptance-core（核心验收）摘要: `.runtime/evaluations/summaries/20260517-122852-core-20260517-192057.json`
- 原始产物: `.runtime/` 仅本地使用，不提交
- 当前验证状态：pending（待复跑）；后续代码、Prompt、模型、依赖或门禁变化后不得继承本结论

本轮在真实本地后端、真实 PostgreSQL（关系型数据库）/ Redis（内存数据结构存储）、RAG（检索增强生成）向量库和 MCP（模型上下文协议）依赖 ready 后，按顺序执行 readiness、`init_db`、`init_rag`、1 场 `acceptance-smoke` 和完整 9 场 `acceptance-core`。没有用 1 场景 smoke 覆盖 9 场景 core 证据。

> 重要校准：这份记录只证明 `origin/main@335a1d4` 在旧门禁下的一次场景跑批。该轮 161 次工具调用中有 108 次失败并进入 fallback（约 67.1%），说明当时门禁过度奖励“诚实兜底”，没有充分约束工具链可用性。当前代码已对普通场景默认要求工具失败数、失败率和 fallback 数均为 0；只有两个专门的 fallback 场景显式允许各项最多 16 次、失败率最多 100%。因此历史 9/9 不能代表当前门禁下仍通过，也不能证明轨迹最优、重复运行稳定、线上质量或生产可用。

### 历史场景状态地图

| 场景 | 模式 | 状态 | 工具调用数 | 工具失败/兜底 | 报告分 | Agent（智能体）工业指标 | 无依据断言率 | 证据闭环 | 运行预算 |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| free_weekend_nearby | free_planning | passed（通过） | 13 | 8 / 8 | 105.0 | 100.0 | 0.0 | passed（通过） | passed（通过） |
| free_city_three_days | free_planning | passed（通过） | 17 | 14 / 14 | 105.0 | 100.0 | 0.0 | passed（通过） | passed（通过） |
| agency_couple_relaxed | agency_plan | passed（通过） | 22 | 10 / 10 | 105.0 | 97.78 | 0.0 | passed（通过） | passed（通过） |
| agency_family_parent_child | agency_plan | passed（通过） | 14 | 11 / 11 | 105.0 | 100.0 | 0.0 | passed（通过） | passed（通过） |
| agency_senior_low_stress | agency_plan | passed（通过） | 16 | 15 / 15 | 105.0 | 100.0 | 0.0 | passed（通过） | passed（通过） |
| edge_hotel_tool_fallback | free_planning | passed（通过） | 13 | 13 / 13 | 105.0 | 100.0 | 0.0 | passed（通过） | passed（通过） |
| pricing_agency_quote_explanation | agency_plan | passed（通过） | 26 | 15 / 15 | 105.0 | 97.78 | 0.0 | passed（通过） | passed（通过） |
| risk_weather_disruption | agency_plan | passed（通过） | 27 | 14 / 14 | 105.0 | 97.78 | 0.0 | passed（通过） | passed（通过） |
| edge_transport_tool_fallback | free_planning | passed（通过） | 13 | 8 / 8 | 105.0 | 100.0 | 0.0 | passed（通过） | passed（通过） |

### 历史重点观察

- `agency_senior_low_stress`: 已产出 `report_data`，不再因为 `selected_accommodation_types` 缺失在 `itinerary_generation` 前置校验中失败。
- `free_city_three_days` / `agency_couple_relaxed`: 本轮真实运行未再触发 `APIConnectionError`；两个场景均产出 `report_data` 并通过运行预算。代码门禁已保留 recovered transient API（应用程序接口） error（错误）分类，避免最终证据闭环成功时被可恢复连接抖动无条件硬失败。
- `pricing_agency_quote_explanation`: 通过 `agent_industrial_metrics` 门禁，`unsupported_claim_rate=0.0`；stage transition（阶段迁移）非 strict（严格）期望不会单独覆盖通过状态。
- `risk_weather_disruption`: 通过运行预算，状态为 passed，不再因工具调用接近预算而降级整体状态。

### 历史证据闭环

- 结果数: 9
- 闭环通过: 9

| 检查项 | 通过场景数 |
|---|---:|
| 快照 | 9 |
| 结构化报告 | 9 |
| 预算 | 9 |
| 预算置信度 | 9 |
| 风险 | 9 |
| 待核验项 | 9 |
| 旅行社业务证据 | 9 |

结构化结果、报告、预算、风险和待核验项在当时九个场景中没有缺口；工具可用性、重复试验、人工 gold set（标准答案集）、轨迹最优性和当前版本复跑仍有缺口。

### 历史工业指标与运行预算

- Agent 工业指标平均分: 99.26
- intent_accuracy（意图识别准确率）: 1.0
- tool_call_precision（工具调用精确率）: 0.963
- tool_call_recall（工具调用召回率）: 1.0
- stage_transition_accuracy（阶段迁移准确率）: 1.0
- unsupported_claim_rate（无依据断言率）: 0.0
- 动态断言数: 48
- 无依据断言数: 0

运行预算汇总：

- 总耗时: 4069.92 秒
- 平均耗时: 452.213 秒
- 工具调用: 161 次
- 工具失败: 108 次
- fallback（兜底）: 108 次
- 估算 token（文本令牌）: 43972
- 工具计数: generate_itinerary_tool=10, summarize_budget_tool=10, generate_order_tool=9, query_destination_info=9, query_hotel_options=9, query_transport_options=9, record_requirement_tool=9, select_accommodation_tool=9, select_destination_tool=9, select_food_tool=9, select_transport_tool=9, search_food_recommendations=5, search_destination_guide=4, get-station-code-of-citys=3, get-tickets=3, query_train_options=3, query_trains=3, search_agency_product_templates=2, search_travel_info=2, get_weather_forecast=1

工具失败和 fallback 计数来自真实外部工具的重试、降级和待核验兜底路径；它们虽然被诚实记录，但 108 / 161 的失败比例仍代表明显可靠性问题。`passed` 只是旧 acceptance gate（验收门禁）的历史输出，不能作为当前可用性结论。

### 历史运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: free_weekend_nearby, free_city_three_days, agency_couple_relaxed, agency_family_parent_child, agency_senior_low_stress, edge_hotel_tool_fallback, pricing_agency_quote_explanation, risk_weather_disruption, edge_transport_tool_fallback
- 待运行场景: -
- 失败分类: -

### 历史关键验证命令

```powershell
uv run python scripts/check_runtime_readiness.py --target acceptance --env-file .env --base-url http://127.0.0.1:8011 --check-backend --json
```

结果：退出码 `0`，`status=passed`，`readiness_status=ready`。

```powershell
uv run python -m scripts.init_db
```

结果：退出码 `0`，业务表、LangGraph（图式智能体编排框架）Checkpointer（检查点）/ Store（存储）和 pgvector（PostgreSQL 向量扩展）初始化完成。

```powershell
uv run python -m scripts.init_rag
```

结果：退出码 `0`。public vector store（公开向量库）18 条 embedding（向量嵌入），internal vector store（内部向量库）106 条 embedding；Chroma（向量库组件）telemetry（遥测）告警不影响退出码。

```powershell
uv run python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8011 --output-dir .runtime\evaluations\smoke-20260517-191226 --summary-dir .runtime\evaluations\summaries --summary-prefix smoke-20260517-191226 --timeout 900 --scenario-timeout 900 --global-timeout 1800 --json
```

结果：1 / 1 passed，summary 路径为 `.runtime/evaluations/summaries/20260517-111953-smoke-20260517-191226.json`。

```powershell
uv run python scripts/run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8011 --output-dir .runtime\evaluations\core-20260517-192057 --summary-dir .runtime\evaluations\summaries --summary-prefix core-20260517-192057 --timeout 900 --scenario-timeout 900 --global-timeout 10800 --continue-on-error --json
```

结果：summary 已写入且 `status=passed`，9 / 9 passed，路径为 `.runtime/evaluations/summaries/20260517-122852-core-20260517-192057.json`。该次运行在 final JSON（JavaScript Object Notation，结构化数据格式）打印阶段暴露 Windows GBK stdout 编码异常；场景结果和 summary 已完整生成，本提交已修复 `scripts/run_evaluation_scenarios.py` 的 UTF-8 安全输出并增加回归测试。

### 历史脱敏与提交边界

- 证据包只保留状态、计数、预算和闭环字段，不写入 `.env`、真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或会话/用户标识。
- 源 JSON 快照、summary、stdout、stderr 和向量库保持在 `.runtime/`、`data/vectorstore/`、`data/vectorstore_internal/`，由 `.gitignore` 忽略，不进入提交。
- 文档仅读取 `.runtime` 摘要字段，不读取或写入 `.env`。

### 历史注意事项

- 本轮 core 可作为 `origin/main@335a1d4` 和当时环境的历史本地证据，不能作为当前分支或当前工作树的通过证据。
- 当前版本必须按新失败/兜底预算重跑 smoke 和完整 9 场景 core；未重跑前公开状态只能写 `pending`，不能写 `passed`。
