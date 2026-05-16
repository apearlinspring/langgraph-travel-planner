# Acceptance Core Evidence Pack（核心验收证据包）

## 结论

- 状态: failed（失败）
- 场景: 6 / 9 passed（通过）
- 状态统计: failed=3, passed=6
- 运行日期: 2026-05-16
- 来源摘要: latest `.runtime` acceptance summary（验收摘要）: `20260516-074331-acceptance-summary.json`
- 原始产物: `.runtime/` 仅本地使用，不提交

## 场景状态地图

| 场景 | 模式 | 状态 | 首 token | 工具调用数 | 证据闭环 | 运行预算 |
|---|---|---:|---:|---:|---|---|
| free_weekend_nearby | free_planning | passed（通过） | 31.645s | 11 | passed（通过） | passed（通过） |
| free_city_three_days | free_planning | passed（通过） | 8.819s | 10 | passed（通过） | passed（通过） |
| agency_couple_relaxed | agency_plan | passed（通过） | 26.337s | 14 | passed（通过） | passed（通过） |
| agency_family_parent_child | agency_plan | passed（通过） | 20.047s | 15 | passed（通过） | passed（通过） |
| agency_senior_low_stress | agency_plan | passed（通过） | 27.348s | 10 | passed（通过） | passed（通过） |
| edge_hotel_tool_fallback | free_planning | failed（失败） | 33.966s | 10 | passed（通过） | passed（通过） |
| pricing_agency_quote_explanation | agency_plan | passed（通过） | 83.665s | 28 | passed（通过） | passed（通过） |
| risk_weather_disruption | agency_plan | failed（失败） | 68.422s | 10 | missing: report_data, budget, budget_confidence, risk, verification_items, agency_business_evidence | - |
| edge_transport_tool_fallback | free_planning | failed（失败） | 35.816s | 11 | passed（通过） | passed（通过） |

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
| 旅行社业务证据 | 8 |

缺口：
- risk_weather_disruption: report_data, budget, budget_confidence, risk, verification_items, agency_business_evidence

## 运行预算

- 总耗时: 3974.049 秒
- 平均耗时: 441.561 秒
- 工具调用: 119 次
- 工具失败: 63 次
- fallback（兜底）: 64 次
- 估算 token（文本令牌）: 38401
- 工具计数: generate_itinerary_tool=8, generate_order_tool=8, get-station-code-of-citys=1, get-tickets=1, get_weather_forecast=1, query_destination_info=8, query_train_options=1, query_trains=1, query_transport_options=1, record_requirement_tool=8, search_agency_pricing_rules=2, search_agency_product_templates=2, search_agency_risk_playbook=2, search_agency_service_sop=2, search_destination_guide=3, search_food_recommendations=5, search_travel_info=1, select_accommodation_tool=8, select_destination_tool=8, select_food_tool=8, select_transport_tool=8, summarize_budget_tool=8

## 运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: free_weekend_nearby, free_city_three_days, agency_couple_relaxed, agency_family_parent_child, agency_senior_low_stress, edge_hotel_tool_fallback, pricing_agency_quote_explanation, risk_weather_disruption, edge_transport_tool_fallback
- 待运行场景: -
- 失败分类: acceptance_gate=2, timeout=1

## 失败分类明细

| 场景 | 分类 | 结论 | 处理状态 |
|---|---|---|---|
| edge_hotel_tool_fallback | acceptance_gate（验收门禁）/ 工具覆盖 | 已产出 `report_data` 且证据闭环通过，但 tool governance（工具治理）低于阈值；门禁指出缺少预期 `query_hotel_options` 调用。当前链路因日期未确认保护而直接记录住宿兜底，没有执行真实酒店查询。 | failed（失败），不得记为 passed（通过）。 |
| risk_weather_disruption | timeout（超时）/ 运行预算 / 证据闭环 | 场景达到 900s 单场预算后停止，未产出 `report_data`，缺少预算、风险、待核验项和旅行社业务证据。 | failed（失败），需要后续排查慢轮次和最终报告推进。 |
| edge_transport_tool_fallback | acceptance_gate（验收门禁）/ 工具覆盖 | 已产出 `report_data` 且证据闭环通过，但 tool governance（工具治理）低于阈值；门禁指出缺少预期 `query_transport_options` 调用。当前链路因日期未确认保护而直接记录交通兜底，没有执行真实交通查询。 | failed（失败），不得记为 passed（通过）。 |

补充说明：本轮曾尝试让“查不到/兜底”语义触发查询工具的日期守卫验证，但单场复跑更不稳定，未纳入最终修复。保留当前严格日期边界，失败按工具覆盖和运行预算如实记录。

## 状态说明

- passed（通过）：预检通过且所有场景门禁通过。
- degraded（降级）：存在非阻塞 warning（警告）或治理风险，不能等同于通过。
- failed（失败）：至少一个场景或质量维度失败。
- blocked（环境阻塞）：真实依赖不足，不能生成有效通过结论。
- pending（待运行）：partial summary（部分摘要）中尚未完成的场景。

## 脱敏与提交边界

- 证据包只保留状态、计数、预算和闭环字段，不写入 `.env`、真实密钥、手机号、邮箱或 JWT（JSON Web Token，令牌认证）。
- 源 JSON（JavaScript 对象表示法）快照和 summary 保持在 `.runtime/`，由 `.gitignore` 忽略，不进入提交。
- 导出脚本仅读取 `.runtime` 摘要文件，不读取或写入 `.env`。

## 注意事项

- 整批状态为 failed（失败），不能等同于 passed（通过）。
