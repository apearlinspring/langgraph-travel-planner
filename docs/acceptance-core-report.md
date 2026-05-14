# Acceptance Core Evidence（核心验收证据）报告

## 结论

2026-05-14 在 `codex/round-core-fixes-integration-review` 分支完成新一轮 acceptance-core（核心验收）9 场景真实环境跑批。9 个场景均生成机器摘要，总体 `status=passed`，没有 `degraded（降级）` 或 `failed（失败）` 场景。

本轮没有合并 `main`，没有放宽 runtime budget（运行预算）或 warning ratio（警戒比例），也没有改写验收门禁结果。所有真实密钥只来自本地 `.env`，未打印、未写入文档、未提交；`.runtime/` 原始产物仅保留本地。

## 本轮修复摘要

- StepConfigMiddleware（阶段配置中间件）新增首轮轻量响应策略：首轮复杂酒店、天气、交通、风险、老人低压力或完整旅行社省心方案请求，先快速确认理解并暂缓慢工具，下一轮再记录需求和核验证据。
- `record_requirement_tool` 会保留首轮暂缓请求的规划模式线索，避免首轮轻量响应后丢失 `agency_plan` 或 `free_planning` 边界。
- `order_generation` 阶段遇到明确最终报告或 `report_data` 请求时，工具列表收窄为 `generate_order_tool`，避免模型只输出短文本却不生成结构化报告。
- 交通阶段在尚未记录交通方案时，不允许住宿确认轮跨阶段抢跑酒店查询；先写入交通，再进入住宿。
- 规划模式边界继续保持：`free_city_three_days` 和 `edge_transport_tool_fallback` 均为 `free_planning`，明确旅行社顾问、报价、服务标准、风险闭环场景仍进入 `agency_plan`。

## 环境与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-round-core-fixes-integration-review`
- 分支：`codex/round-core-fixes-integration-review`
- 后端：`http://127.0.0.1:8000`
- `/health/live`：`alive`
- `/health/ready`：`ready`
- MCP（模型上下文协议）服务：6 healthy，0 unavailable，37 tools

执行过的真实环境命令：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

关键复跑命令：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario edge_hotel_tool_fallback --scenario risk_weather_disruption --scenario edge_transport_tool_fallback --scenario agency_senior_low_stress --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core-reruns --scenario-timeout 900 --global-timeout 2400
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario pricing_agency_quote_explanation --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core-reruns --scenario-timeout 900 --global-timeout 1800
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core-full --scenario-timeout 900 --global-timeout 7200
```

本地回归命令：

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_step_prompt_rendering.py tests\test_planning_mode_boundary.py tests\test_tool_loop_guard.py tests\test_evaluation_live_runner.py tests\test_runtime_metrics.py -q
.\.venv\Scripts\python -m pytest -q
```

结果：

- `compileall`：退出码 `0`
- 重点 pytest（测试框架）：`102 passed`
- 全量 pytest：`434 passed, 24 deselected`
- 测试结束后 LangSmith（LangChain 可观测平台）上报返回 `403 Forbidden`，不影响 pytest 退出码。

## 4 场景子集

子集用于复核上一轮失败/降级点：酒店慢兜底、天气风险、交通兜底和银发低压力方案。结果：`status=passed`，`passed=true`。

| 场景 | status | first_token_seconds | tool_call_count | duplicate | error | busy | report_data | evidence missing | runtime_budget |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `edge_hotel_tool_fallback` | passed | 23.194 | 12 | 0 | 0 | 0 | yes | `[]` | passed |
| `risk_weather_disruption` | passed | 22.958 | 12 | 0 | 0 | 0 | yes | `[]` | passed |
| `edge_transport_tool_fallback` | passed | 28.170 | 22 | 0 | 0 | 0 | yes | `[]` | passed |
| `agency_senior_low_stress` | passed | 18.010 | 14 | 0 | 0 | 0 | yes | `[]` | passed |

补充回归点：

| 场景 | status | first_token_seconds | tool_call_count | duplicate | error | busy | report_data | evidence missing | runtime_budget |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `agency_couple_relaxed` | passed | 42.339 | 13 | 0 | 0 | 0 | yes | `[]` | passed |
| `pricing_agency_quote_explanation` | passed | 58.028 | 22 | 0 | 0 | 0 | yes | `[]` | passed |

## 完整 9 场景结果

机器摘要：

- `.runtime\acceptance-core-full\20260514-134448-acceptance-summary.json`
- `.runtime\acceptance-core-full\20260514-134448-acceptance-summary.md`

总体：

- `status=passed`
- `passed=true`
- `completed=9`
- `pending=0`
- `passed_count=9`
- `degraded_count=0`
- `failed_count=0`
- `failure_classification_counts={}`

| 场景 | status | first_token_seconds | tool_call_count | duplicate | error | busy | report_data | evidence missing | runtime_budget | mode |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|
| `free_weekend_nearby` | passed | 12.565 | 14 | 0 | 0 | 0 | yes | `[]` | passed | `free_planning` |
| `free_city_three_days` | passed | 9.681 | 13 | 0 | 0 | 0 | yes | `[]` | passed | `free_planning` |
| `agency_couple_relaxed` | passed | 20.547 | 17 | 0 | 0 | 0 | yes | `[]` | passed | `agency_plan` |
| `agency_family_parent_child` | passed | 33.636 | 21 | 0 | 0 | 0 | yes | `[]` | passed | `agency_plan` |
| `agency_senior_low_stress` | passed | 17.513 | 18 | 0 | 0 | 0 | yes | `[]` | passed | `agency_plan` |
| `edge_hotel_tool_fallback` | passed | 29.511 | 19 | 0 | 0 | 0 | yes | `[]` | passed | `free_planning` |
| `pricing_agency_quote_explanation` | passed | 74.391 | 26 | 0 | 0 | 0 | yes | `[]` | passed | `agency_plan` |
| `risk_weather_disruption` | passed | 15.614 | 13 | 0 | 0 | 0 | yes | `[]` | passed | `agency_plan` |
| `edge_transport_tool_fallback` | passed | 40.417 | 15 | 0 | 0 | 0 | yes | `[]` | passed | `free_planning` |

说明：当前 summary 未显式输出 `duplicate_tool_call_same_turn` 字段；本报告按每个快照的同轮同名工具事件分组复核，9 个场景均为 `0`，且 acceptance gate（验收门禁）无 duplicate 相关 finding（发现项）。

## 历史失败闭环

上一轮完整 9 场景曾为 `failed`：5 passed、1 degraded、3 failed。阻塞点集中在首 token 慢路径和最终报告生成缺口：

- `edge_hotel_tool_fallback`：首轮先等待酒店工具超时，first token 超预算。
- `risk_weather_disruption`：首轮串联目的地、搜索和模式工具后才输出，first token 超预算。
- `edge_transport_tool_fallback`：交通慢链路导致 first token 超预算，并曾误判为 `agency_plan`。
- `agency_senior_low_stress`：首 token warning（警告），后续一度因住宿抢跑导致交通证据缺口。
- `pricing_agency_quote_explanation`：最终报告轮未调用 `generate_order_tool`，导致无 `report_data`。
- `agency_couple_relaxed`：工具调用数触发 81.2% warning。

本轮对应闭环：

- 首轮轻量响应把慢工具延后到确认/推进轮，首 token 均回到预算内。
- 最终报告阶段强制收窄到 `generate_order_tool` 后，报价场景产出 `report_data`。
- 完整旅行社省心首轮不再先做内部产品检索，情侣省心场景工具数降回预算内。
- 交通阶段前置边界关闭住宿抢跑，`edge_transport_tool_fallback` 保持 `free_planning`。

## 脱敏说明

- 未打印、提交或写入 `.env` 真实值。
- 文档仅记录状态、计数、路径和脱敏指标，不包含真实手机号、邮箱、JWT（JSON Web Token，令牌认证）或外部 API（应用程序接口）原始响应。
- `.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/` 仅本地使用，不提交。

## 合入建议

在当前真实环境和本地回归结果下，建议将 `codex/round-core-fixes-integration-review` 合入 `main`。合入前仍建议维护者按本 runbook（运行手册）在目标环境复跑 `/health/ready`、preflight（预检）和完整 acceptance-core。
