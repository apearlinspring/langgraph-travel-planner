# Acceptance Core Evidence Pack（核心验收证据包）

## 结论

- 状态: passed（通过）
- 场景: 1 / 1 passed（通过）
- 状态统计: passed=1
- 运行日期: 2026-05-14
- 来源摘要: latest `.runtime` acceptance summary（验收摘要）: `20260514-151605-acceptance-summary.json`
- 原始产物: `.runtime/` 仅本地使用，不提交

## 场景状态地图

| 场景 | 模式 | 状态 | 首 token | 工具调用数 | 证据闭环 | 运行预算 |
|---|---|---:|---:|---:|---|---|
| pricing_agency_quote_explanation | agency_plan | passed（通过） | 58.040s | 13 | passed（通过） | passed（通过） |

## 证据闭环

- 结果数: 1
- 闭环通过: 1

| 检查项 | 通过场景数 |
|---|---:|
| 快照 | 1 |
| 结构化报告 | 1 |
| 预算 | 1 |
| 预算置信度 | 1 |
| 风险 | 1 |
| 待核验项 | 1 |
| 旅行社业务证据 | 1 |

## 运行预算

- 总耗时: 395.967 秒
- 平均耗时: 395.967 秒
- 工具调用: 13 次
- 工具失败: 7 次
- fallback（兜底）: 7 次
- 估算 token（文本令牌）: 6189
- 工具计数: generate_itinerary_tool=1, generate_order_tool=1, get_weather_forecast=1, query_destination_info=1, query_hotel_options=1, record_requirement_tool=1, search_food_recommendations=1, select_accommodation_tool=1, select_destination_tool=1, select_food_tool=1, select_transport_tool=1, summarize_budget_tool=1

## 运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: pricing_agency_quote_explanation
- 待运行场景: -

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

- 期望 9 个核心场景，摘要中 selected_count=1。
