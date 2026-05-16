# Acceptance Core Evidence Pack（核心验收证据包）

## 结论

- 状态: failed（失败）
- 场景: 6 / 9 passed（通过）
- 状态统计: failed=3, passed=6, degraded=0, blocked=0, skipped=0
- 运行日期: 2026-05-16
- 基准: `origin/main@620947b`
- 分支: `codex/acceptance-core-rerun-closeout`
- 来源摘要: `.runtime/acceptance-core/20260516-102402-acceptance-summary.json`
- 原始产物: `.runtime/` 仅本地使用，不提交

本轮完整运行了 9 个 core（核心）场景，没有用 1 场景 smoke（冒烟验收）覆盖 core 证据包。`risk_weather_disruption` 本轮已通过；当前阻塞项是 1 个证据闭环失败和 2 个工具覆盖门禁失败。

## 场景状态地图

| 场景 | 模式 | 状态 | 首 token（文本令牌） | 工具调用数 | 证据闭环 | 运行预算 |
|---|---|---:|---:|---:|---|---|
| free_weekend_nearby | free_planning | failed（失败） | 18.453s | 7 | missing: report_data, budget, budget_confidence, risk, verification_items | - |
| free_city_three_days | free_planning | passed（通过） | 11.754s | 12 | passed（通过） | passed（通过） |
| agency_couple_relaxed | agency_plan | passed（通过） | 34.629s | 11 | passed（通过） | passed（通过） |
| agency_family_parent_child | agency_plan | passed（通过） | 21.458s | 13 | passed（通过） | passed（通过） |
| agency_senior_low_stress | agency_plan | passed（通过） | 15.676s | 13 | passed（通过） | passed（通过） |
| edge_hotel_tool_fallback | free_planning | failed（失败） | 36.969s | 12 | passed（通过） | passed（通过） |
| pricing_agency_quote_explanation | agency_plan | passed（通过） | 10.335s | 15 | passed（通过） | passed（通过） |
| risk_weather_disruption | agency_plan | passed（通过） | 31.990s | 26 | passed（通过） | passed（通过） |
| edge_transport_tool_fallback | free_planning | failed（失败） | 31.046s | 12 | passed（通过） | passed（通过） |

## 证据闭环

- 结果数: 9
- 闭环通过: 8

| 检查项 | 通过场景数 |
|---|---:|
| 快照 | 9 |
| 结构化报告 | 8 |
| 预算 | 8 |
| 预算置信度 | 8 |
| 风险 | 8 |
| 待核验项 | 8 |
| 旅行社业务证据 | 9 |

缺口：

- `free_weekend_nearby`: report_data, budget, budget_confidence, risk, verification_items

## 运行预算

- 总耗时: 3509.789 秒
- 平均耗时: 389.977 秒
- 工具调用: 121 次
- 工具失败: 72 次
- fallback（兜底）: 73 次
- 估算 token（文本令牌）: 41846
- 工具计数: generate_itinerary_tool=8, generate_order_tool=8, query_destination_info=8, record_requirement_tool=8, select_accommodation_tool=8, select_destination_tool=8, select_food_tool=8, select_transport_tool=8, summarize_budget_tool=8, search_food_recommendations=6, query_hotel_options=5, search_agency_product_templates=3, query_transport_options=2, search_agency_risk_playbook=2, search_destination_guide=2, search_travel_info=2, get-station-code-of-citys=1, get-tickets=1, query_train_options=1, query_trains=1, search_agency_pricing_rules=1

## 运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: free_weekend_nearby, free_city_three_days, agency_couple_relaxed, agency_family_parent_child, agency_senior_low_stress, edge_hotel_tool_fallback, pricing_agency_quote_explanation, risk_weather_disruption, edge_transport_tool_fallback
- 待运行场景: -
- 失败分类: acceptance_gate=2, evidence_closure=1

## 失败分类明细

| 场景 | 分类 | 结论 | 处理状态 |
|---|---|---|---|
| free_weekend_nearby | evidence_closure（证据闭环）/ live_run（真实链路运行） | 场景完成但未产出结构化 `report_data`，因此缺少预算、预算置信度、风险和待核验项。 | failed（失败），不得记为 passed（通过）。 |
| edge_hotel_tool_fallback | acceptance_gate（验收门禁）/ 工具覆盖 | 已产出 `report_data` 且证据闭环通过，但 tool governance（工具治理）低于阈值；门禁指出缺少预期 `query_hotel_options` 调用。 | failed（失败），不得记为 passed（通过）。 |
| edge_transport_tool_fallback | acceptance_gate（验收门禁）/ 工具覆盖 | 已产出 `report_data` 且证据闭环通过，但 tool governance（工具治理）低于阈值；门禁指出缺少预期 `query_transport_options` 调用。 | failed（失败），不得记为 passed（通过）。 |

补充说明：本轮 `risk_weather_disruption` 已通过，不再记录为 timeout（超时）失败。当前 6/9 passed 仍未达到发布门禁，不能降门禁或改写结论。

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

- 整批状态为 failed（失败），不能等同于 passed（通过）。
- 下一步应修复 `free_weekend_nearby` 的最终报告产出，以及 edge（边界）场景的酒店/交通工具覆盖门禁，再复跑 smoke 和完整 9 场景 core。
