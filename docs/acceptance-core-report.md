# Acceptance Core Evidence Pack（核心验收证据包）

## 结论

- 状态: passed（通过）
- 场景: 9 / 9 passed（通过）
- 状态统计: passed=9
- 运行日期: 2026-05-14
- 来源摘要: latest `.runtime` acceptance summary（验收摘要）: `20260514-134448-acceptance-summary.json`
- 原始产物: `.runtime/` 仅本地使用，不提交

本文件是可提交、可项目展示的脱敏 Markdown（标记文本）证据包。它只保留 acceptance-core（核心验收）summary（摘要）中的状态、计数、首 token（文本令牌）、工具调用、证据闭环和运行预算字段，不提交 `.runtime/` 原始 JSON（JavaScript 对象表示法）或快照。

自动重建命令：

```powershell
.\.venv\Scripts\python.exe scripts\export_acceptance_evidence.py --runtime-dir .runtime --output docs\acceptance-core-report.md
```

如果 `.runtime` 下没有 acceptance summary，脚本会生成 `missing_summary（缺少摘要）` 报告并以非零退出；这类报告不能作为验收通过证据。

## 场景状态地图

| 场景 | 模式 | 状态 | 首 token | 工具调用数 | 证据闭环 | 运行预算 |
|---|---|---:|---:|---:|---|---|
| `free_weekend_nearby` | `free_planning` | passed（通过） | 12.565s | 14 | passed（通过） | passed（通过） |
| `free_city_three_days` | `free_planning` | passed（通过） | 9.681s | 13 | passed（通过） | passed（通过） |
| `agency_couple_relaxed` | `agency_plan` | passed（通过） | 20.547s | 17 | passed（通过） | passed（通过） |
| `agency_family_parent_child` | `agency_plan` | passed（通过） | 33.636s | 21 | passed（通过） | passed（通过） |
| `agency_senior_low_stress` | `agency_plan` | passed（通过） | 17.513s | 18 | passed（通过） | passed（通过） |
| `edge_hotel_tool_fallback` | `free_planning` | passed（通过） | 29.511s | 19 | passed（通过） | passed（通过） |
| `pricing_agency_quote_explanation` | `agency_plan` | passed（通过） | 74.391s | 26 | passed（通过） | passed（通过） |
| `risk_weather_disruption` | `agency_plan` | passed（通过） | 15.614s | 13 | passed（通过） | passed（通过） |
| `edge_transport_tool_fallback` | `free_planning` | passed（通过） | 40.417s | 15 | passed（通过） | passed（通过） |

## 证据闭环

- 结果数: 9
- 闭环通过: 9
- 缺口: 无

| 检查项 | 通过场景数 |
|---|---:|
| 快照 | 9 |
| 结构化报告 | 9 |
| 预算 | 9 |
| 预算置信度 | 9 |
| 风险 | 9 |
| 待核验项 | 9 |
| 旅行社业务证据 | 9 |

## 运行预算

- 总耗时: 以本地 summary 为准，完整 9 场景均在场景级 budget（预算）内。
- 工具调用: 156 次。
- 工具失败: 0 个验收阻断项；失败/降级外部能力均进入待核验兜底。
- fallback（兜底）: 由各场景工具审计记录，未触发 acceptance gate（验收门禁）失败。
- 估算 token（文本令牌）: 以 `.runtime` summary 聚合值为准，不在提交文档中保留原始上下文。
- 运行预算结论: 9 个场景 `runtime_budget_passed=true`。

## 运行上下文

- partial summary（部分摘要）: 否
- 部分原因: -
- 已完成场景: 9
- 待运行场景: -
- 失败分类: {}

## 历史失败闭环

上一轮完整 9 场景曾为 `failed`：5 passed、1 degraded、3 failed。阻塞点集中在首 token 慢路径和最终报告生成缺口：

- `edge_hotel_tool_fallback`：首轮先等待酒店工具超时，first token 超预算。
- `risk_weather_disruption`：首轮串联目的地、搜索和模式工具后才输出，first token 超预算。
- `edge_transport_tool_fallback`：交通慢链路导致 first token 超预算，并曾误判为 `agency_plan`。
- `agency_senior_low_stress`：首 token warning（警告），后续一度因住宿抢跑导致交通证据缺口。
- `pricing_agency_quote_explanation`：最终报告轮未调用 `generate_order_tool`，导致无 `report_data`。
- `agency_couple_relaxed`：工具调用数触发 warning（警告）。

本轮对应闭环：

- 首轮轻量响应把慢工具延后到确认/推进轮，首 token 均回到预算内。
- 最终报告阶段收窄到 `generate_order_tool` 后，报价场景产出 `report_data`。
- 完整旅行社省心首轮不再先做内部产品检索，情侣省心场景工具数回到预算内。
- 交通阶段前置边界关闭住宿抢跑，`edge_transport_tool_fallback` 保持 `free_planning`。

## 状态说明

- passed（通过）：预检通过且所有场景门禁通过。
- degraded（降级）：存在非阻塞 warning（警告）或治理风险，不能等同于 passed（通过）。
- failed（失败）：至少一个场景或质量维度失败。
- blocked（环境阻塞）：真实依赖不足，不能生成有效通过结论。
- pending（待运行）：partial summary（部分摘要）中尚未完成的场景。

## 脱敏与提交边界

- 未提交 `.runtime/` 原始 JSON、SSE（服务器发送事件）事件、工具输入输出或外部 API（应用程序接口）响应。
- 未写入 `.env`、真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或客户可识别信息。
- 文档仅记录状态、计数、相对摘要文件名和脱敏后的验收指标。
- 导出脚本仅读取 `.runtime` 摘要文件，不读取或写入 `.env`。
