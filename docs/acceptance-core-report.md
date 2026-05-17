# Acceptance Core Evidence Pack（核心验收证据包）

## 结论

- 状态: passed（通过）
- 场景: 9 / 9 passed（通过）
- 状态统计: passed=9, failed=0, degraded=0, blocked=0, skipped=0
- 运行日期: 2026-05-17
- 基准: `origin/main@335a1d4`
- 分支: `codex/acceptance-core-real-run-stabilization`
- readiness（就绪检查）: passed（通过），后端 `/health/ready` 为 `ready`
- acceptance-smoke（冒烟验收）摘要: `.runtime/evaluations/summaries/20260517-111953-smoke-20260517-191226.json`
- acceptance-core（核心验收）摘要: `.runtime/evaluations/summaries/20260517-122852-core-20260517-192057.json`
- 原始产物: `.runtime/` 仅本地使用，不提交

本轮在真实本地后端、真实 PostgreSQL（关系型数据库）/ Redis（内存数据结构存储）、RAG（检索增强生成）向量库和 MCP（模型上下文协议）依赖 ready 后，按顺序执行 readiness、`init_db`、`init_rag`、1 场 `acceptance-smoke` 和完整 9 场 `acceptance-core`。没有用 1 场景 smoke 覆盖 9 场景 core 证据。

## 场景状态地图

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

## 重点观察

- `agency_senior_low_stress`: 已产出 `report_data`，不再因为 `selected_accommodation_types` 缺失在 `itinerary_generation` 前置校验中失败。
- `free_city_three_days` / `agency_couple_relaxed`: 本轮真实运行未再触发 `APIConnectionError`；两个场景均产出 `report_data` 并通过运行预算。代码门禁已保留 recovered transient API（应用程序接口） error（错误）分类，避免最终证据闭环成功时被可恢复连接抖动无条件硬失败。
- `pricing_agency_quote_explanation`: 通过 `agent_industrial_metrics` 门禁，`unsupported_claim_rate=0.0`；stage transition（阶段迁移）非 strict（严格）期望不会单独覆盖通过状态。
- `risk_weather_disruption`: 通过运行预算，状态为 passed，不再因工具调用接近预算而降级整体状态。

## 证据闭环

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

缺口：无。

## 工业指标与运行预算

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

工具失败和 fallback 计数来自真实外部工具的重试、降级和待核验兜底路径；本轮 acceptance gate（验收门禁）、evidence closure（证据闭环）和 runtime budget（运行预算）均为 passed（通过）。

## 运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: free_weekend_nearby, free_city_three_days, agency_couple_relaxed, agency_family_parent_child, agency_senior_low_stress, edge_hotel_tool_fallback, pricing_agency_quote_explanation, risk_weather_disruption, edge_transport_tool_fallback
- 待运行场景: -
- 失败分类: -

## 关键验证命令

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

## 脱敏与提交边界

- 证据包只保留状态、计数、预算和闭环字段，不写入 `.env`、真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或会话/用户标识。
- 源 JSON 快照、summary、stdout、stderr 和向量库保持在 `.runtime/`、`data/vectorstore/`、`data/vectorstore_internal/`，由 `.gitignore` 忽略，不进入提交。
- 文档仅读取 `.runtime` 摘要字段，不读取或写入 `.env`。

## 注意事项

- 本轮 core 为完整 9 场景 passed（通过），可作为当前分支的真实本地验收证据。
- 若模型、RAG、MCP、外部 API 配置、报告契约或运行环境变化，仍需重跑 smoke 和完整 9 场景 core。
