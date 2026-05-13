# Acceptance Core Evidence（核心验收证据）报告

## 结论

2026-05-13 在 `codex/smoke-runtime-budget` 分支完成 acceptance-smoke（验收烟测）真实链路复核。当前真实环境 readiness（就绪检查）、preflight（预检）和 smoke 场景均为 `passed（通过）`，原先阻塞 9 个核心场景前置判断的 smoke runtime budget（运行预算）失败已关闭。

本文件仍不把 smoke 结果等同于 9 个 acceptance-core（核心验收）场景通过。它只说明核心验收的前置环境和最小真实链路已经闭环，下一步可以在同一真实环境下运行 9 个核心场景。

环境闭环历史见 [acceptance-runtime-close-loop.md](./acceptance-runtime-close-loop.md)，本轮 smoke 预算收口见本文后续记录。

## 基准与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-smoke-runtime-budget`
- 分支：`codex/smoke-runtime-budget`
- 基准命令：`git fetch origin --prune`
- 结果：当前分支基于最新 `origin/main` 创建，并记录本轮 smoke 预算收口改动。
- 本地 Python（编程语言运行时）环境：当前工作树原本缺 `.venv`，已用 `uv sync --frozen` 按 `uv.lock` 重建。

执行过的核心门禁命令：

```powershell
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

## 环境闭环摘要

- `.env` 存在：是，未提交。
- `.env` 本地追加非密钥配置：`RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS=25`。
- PostgreSQL（关系型数据库）：`healthy`。
- Redis（内存数据结构存储）：`healthy`。
- `scripts.init_db --mode bootstrap`：退出码 `0`。
- `scripts.init_rag`：退出码 `0`。
- runtime readiness（运行时就绪检查）：`status=passed`，`blocked_reasons=[]`。
- `/health/live`：`alive`。
- `/health/ready`：重启后 `ready`，MCP（模型上下文协议）服务 6 healthy，0 unavailable，37 tools。

## Preflight 结果

首次 preflight 在后端 ready 检查处 blocked：

- `amap=degraded`
- `12306-mcp=degraded`
- `VariFlight-Aviation=degraded`
- 共同原因：MCP service connection is unavailable。

脱敏复测证明不是凭据缺失，而是默认 8 秒 MCP 启动探测超时偏短；25 秒超时下：

- `amap`: healthy，15 tools
- `12306-mcp`: healthy，8 tools
- `VariFlight-Aviation`: healthy，9 tools

调整本地非密钥超时配置并重启后：

- `preflight.status=passed`
- `preflight.blocked=false`
- `backend_live=passed`
- `backend_ready=passed`
- `missing_required=[]`
- `degraded_optional=[]`

## 9 个核心场景状态

本轮没有运行 9 个 acceptance-core 场景，因此没有新的场景级 pass/fail 结论。preflight-only（仅预检）输出中场景状态为 `skipped（跳过）` 属于预期，不代表业务场景通过或失败。

| 场景 | 本轮状态 | 说明 |
|---|---|---|
| `free_weekend_nearby` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `free_city_three_days` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `agency_couple_relaxed` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `agency_family_parent_child` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `agency_senior_low_stress` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `edge_hotel_tool_fallback` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `pricing_agency_quote_explanation` | not_run / smoke_passed | 核心批未运行；最小 smoke 真实链路已通过。 |
| `risk_weather_disruption` | not_run | preflight 通过后未进入 9 场景跑批。 |
| `edge_transport_tool_fallback` | not_run | preflight 通过后未进入 9 场景跑批。 |

核心场景状态统计：

- `passed`: 0
- `failed`: 0
- `blocked`: 0
- `degraded`: 0
- `not_run`: 9

## Smoke 后置判断

acceptance-smoke 真实运行结果：

- `status=passed`
- `passed=true`
- `blocked_count=0`
- `degraded_count=0`
- `failed_count=0`
- `scenario_id=pricing_agency_quote_explanation`
- `report_quality=passed`
- `rag_quality=passed`
- `tool_quality=passed`
- `evidence_closure=passed`
- `runtime_quality=passed`
- `runtime_budget=passed`

关键通过指标：

- `total_elapsed_seconds=521.809`，预算 `900.0`
- `first_token_seconds=69.408`，场景预算 `90.0`
- `tool_call_count=24`，场景预算 `36`
- `tool_failure_count=10`
- `fallback_count=10`
- `error_event_count=0`
- `report_event_count=1`
- `report_data=true`
- `evidence_closure.missing=[]`

本地原始产物只保留在 `.runtime/`，不提交：

- `.runtime\acceptance-smoke\20260513-084157-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260513-084157-acceptance-summary.md`
- `.runtime\evaluations\20260513-164157-pricing_agency_quote_explanation.json`

## 失败归因

本轮没有修改 evaluation gate（评估门禁）通过语义，也没有把失败伪装成通过。修复集中在 smoke 场景输入和工具调用稳定性：

归因分类：

- 环境/密钥/外部 API（应用程序接口）问题：已关闭到 preflight passed。
- MCP 启动探测问题：通过本地非密钥超时配置关闭。
- Agent（智能体）业务链路问题：已减少无效重试和跨交通方式扩散调用。
- RAG 证据问题：smoke 通过。
- `report_data`（结构化报告数据）契约问题：smoke 通过。
- runtime budget 问题：smoke 当前通过，仍需在 9 个核心场景中复核稳定性。
- evaluation gate 误判：未发现。

## 下一步

下一步在同一真实环境下运行 9 个 acceptance-core 场景。若 core 场景失败，按失败维度拆解报告质量、RAG、MCP、工具治理、运行预算和旅行社业务证据；不要用 smoke 通过结果替代核心验收。
