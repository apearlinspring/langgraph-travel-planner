# Acceptance Core Evidence Pack（核心验收证据包）

## 结论

- 状态: passed（通过）
- 场景: 9 / 9 passed（通过）
- 状态统计: passed=9, failed=0, degraded=0, blocked=0, skipped=0
- 运行日期: 2026-05-17
- 基准: `origin/main@3b02f41`
- 分支: `codex/acceptance-core-final-gates-fix`
- 来源摘要: `.runtime/acceptance-core/20260517-transport-guard/20260516-223916-acceptance-core.json`
- 原始产物: `.runtime/` 仅本地使用，不提交

本轮在真实本地后端、真实 PostgreSQL（关系型数据库）/ Redis（内存数据结构存储）、RAG（检索增强生成）和 MCP（模型上下文协议）依赖 ready 后，先跑相关单测，再单独复跑 4 个重点失败场景，再跑 `acceptance-smoke`（验收冒烟测试），最后完整运行 9 个 `acceptance-core`（核心验收）场景。没有用 1 场景 smoke 覆盖 9 场景 core 证据。

## 场景状态地图

| 场景 | 模式 | 状态 | 首 token（文本令牌） | 工具调用数 | 证据闭环 | 运行预算 |
|---|---|---:|---:|---:|---|---|
| free_weekend_nearby | free_planning | passed（通过） | 34.992s | 18 | passed（通过） | passed（通过） |
| free_city_three_days | free_planning | passed（通过） | 15.167s | 13 | passed（通过） | passed（通过） |
| agency_couple_relaxed | agency_plan | passed（通过） | 27.290s | 21 | passed（通过） | passed（通过） |
| agency_family_parent_child | agency_plan | passed（通过） | 19.191s | 13 | passed（通过） | passed（通过） |
| agency_senior_low_stress | agency_plan | passed（通过） | 14.119s | 22 | passed（通过） | passed（通过） |
| edge_hotel_tool_fallback | free_planning | passed（通过） | 36.805s | 14 | passed（通过） | passed（通过） |
| pricing_agency_quote_explanation | agency_plan | passed（通过） | 26.891s | 22 | passed（通过） | passed（通过） |
| risk_weather_disruption | agency_plan | passed（通过） | 26.968s | 28 | passed（通过） | passed（通过） |
| edge_transport_tool_fallback | free_planning | passed（通过） | 38.247s | 18 | passed（通过） | passed（通过） |

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

## 工具覆盖与重点修复点

- `free_weekend_nearby`: 最终轮进入 `generate_order_tool`，产出 `report_data`、预算、预算置信度、风险和待核验项。
- `edge_hotel_tool_fallback`: 完整 core 中保留 `query_hotel_options` 审计式调用，并通过工具覆盖门禁。
- `edge_transport_tool_fallback`: 完整 core 中保留 `query_transport_options` 审计式调用，并通过工具覆盖门禁。
- 日期未确认的兜底查询保留 skipped（跳过）/待核验语义，不承诺真实锁价、真实库存或真实班次。

## 运行预算

- 总耗时: 4015.637 秒
- 平均耗时: 446.182 秒
- 工具调用: 169 次
- 工具失败: 106 次
- fallback（兜底）: 106 次
- 估算 token（文本令牌）: 44116
- 工具计数: generate_itinerary_tool=10, query_hotel_options=10, select_accommodation_tool=10, summarize_budget_tool=10, generate_order_tool=9, query_transport_options=9, record_requirement_tool=9, select_destination_tool=9, select_food_tool=9, select_transport_tool=9, query_destination_info=8, search_food_recommendations=6, get-station-code-of-citys=4, get-tickets=4, query_train_options=4, query_trains=4, get_weather_forecast=2, go_back_to_accommodation=1, go_back_to_step=1, search_agency_product_templates=1, search_agency_risk_playbook=1, search_agency_service_sop=1, search_destination_guide=1, search_travel_tips=1

工具失败和 fallback 计数来自真实外部工具的重试、降级和待核验兜底路径；本轮 acceptance gate（验收门禁）、evidence closure（证据闭环）和 runtime budget（运行预算）均为 passed（通过）。

## 运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: free_weekend_nearby, free_city_three_days, agency_couple_relaxed, agency_family_parent_child, agency_senior_low_stress, edge_hotel_tool_fallback, pricing_agency_quote_explanation, risk_weather_disruption, edge_transport_tool_fallback
- 待运行场景: -
- 失败分类: -

## 关键验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_live_runner.py tests\test_intent_detection.py tests\test_planning_mode_boundary.py tests\test_tool_quality_evaluation.py tests\test_hotel_query_tool.py tests\test_transport_query_tool.py tests\test_tool_loop_guard.py tests\test_step_prompt_rendering.py -q
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario edge_transport_tool_fallback --scenario edge_hotel_tool_fallback --scenario free_weekend_nearby --scenario pricing_agency_quote_explanation --continue-on-error --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-fix-singles\20260517-four-after-transport-guard --summary-dir .runtime\acceptance-fix-singles\20260517-four-after-transport-guard --summary-prefix four-after-transport-guard --scenario-timeout 1200 --global-timeout 7200 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-smoke\20260517-transport-guard --summary-dir .runtime\acceptance-smoke\20260517-transport-guard --summary-prefix acceptance-smoke --scenario-timeout 1200 --global-timeout 1800 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --continue-on-error --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-core\20260517-transport-guard --summary-dir .runtime\acceptance-core\20260517-transport-guard --summary-prefix acceptance-core --scenario-timeout 1200 --global-timeout 14400 --json
```

## 状态说明

- passed（通过）：预检通过且所有场景门禁通过。
- degraded（降级）：存在非阻塞 warning（警告）或治理风险，不能等同于通过。
- failed（失败）：至少一个场景或质量维度失败。
- blocked（环境阻塞）：真实依赖不足，不能生成有效通过结论。
- pending（待运行）：partial summary（部分摘要）中尚未完成的场景。

## 脱敏与提交边界

- 证据包只保留状态、计数、预算和闭环字段，不写入 `.env`、真实密钥、手机号、邮箱或 JWT（JSON Web Token，令牌认证）。
- 源 JSON（JavaScript Object Notation，结构化数据格式）快照和 summary（摘要）保持在 `.runtime/`，由 `.gitignore` 忽略，不进入提交。
- 文档仅读取 `.runtime` 摘要字段，不读取或写入 `.env`。

## 注意事项

- 本轮 core 为完整 9 场景 passed（通过），可作为当前分支的真实本地验收证据。
- 若模型、RAG、MCP、外部 API（应用程序接口）配置、报告契约或运行环境变化，仍需重跑 smoke 和完整 9 场景 core。
