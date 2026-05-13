# Acceptance Core Evidence（核心验收证据）报告

## 结论

2026-05-13 在 `codex/live-smoke-evidence` 分支、HEAD `c4487eb` 完成 acceptance-smoke（验收烟测）真实链路复核。当前真实环境 runtime readiness（运行时就绪检查）、smoke preflight（预检）和 smoke 场景均为 `passed（通过）`，原先阻塞 9 个核心场景前置判断的 smoke runtime budget（运行预算）失败已关闭。

本文件仍不把 smoke 结果等同于 9 个 acceptance-core（核心验收）场景通过。它只说明最小真实链路已经闭环，下一步应先复跑 acceptance-core preflight，确认 12306 等 core 所需 MCP 服务 healthy 后，再进入 9 个核心场景。

环境闭环历史见 [acceptance-runtime-close-loop.md](./acceptance-runtime-close-loop.md)，本轮 smoke 预算收口见本文后续记录。

## 基准与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-smoke-evidence`
- 分支：`codex/live-smoke-evidence`
- 基准命令：`git fetch origin --prune; git merge --ff-only origin/main`
- 结果：快进到最新主线 `c4487eb`。
- 本地 Python（编程语言运行时）环境：`.venv` 已存在。

执行过的核心门禁命令：

```powershell
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python.exe -m scripts.init_rag
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

## 环境闭环摘要

- `.env` 存在：是，未提交。
- `.env` 存在但未打印内容，未提交。
- PostgreSQL（关系型数据库）：`healthy`。
- Redis（内存数据结构存储）：`healthy`。
- `scripts.init_db --mode bootstrap`：退出码 `0`。
- `scripts.init_rag`：退出码 `0`。当前本地 ignored 向量库已有内容，复跑后公开库和内部库 embedding（向量嵌入）计数翻倍；这是本地证据风险，不提交向量库原始产物。
- runtime readiness（运行时就绪检查）：`status=passed`，`blocked_reasons=[]`。
- `/health/live`：`alive`。
- `/health/ready`：完整 ready 为 `degraded`，核心依赖 ready；降级来自本 smoke 场景外的 MCP（模型上下文协议）服务。smoke preflight 的 `backend_ready=passed`，因为所需 `search` 和 `weather` 均 healthy。

## Preflight 结果

- `preflight.status=passed`
- `preflight.blocked=false`
- `backend_live=passed`
- `backend_ready=passed`
- `missing_required=[]`
- `degraded_optional=[]`
- `backend_ready` finding（发现项）：后端 readiness 只因 selected scenario set（选中场景集合）外的 MCP 服务降级。

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

- `total_elapsed_seconds=556.393`，预算 `900.0`
- `first_token_seconds=84.103`，场景预算 `90.0`
- `tool_call_count=21`，场景预算 `36`
- `tool_failure_count=13`
- `fallback_count=13`
- `error_event_count=0`
- `report_event_count=1`
- `report_data=true`
- `evidence_closure.missing=[]`

本地原始产物只保留在 `.runtime/`，不提交：

- `.runtime\acceptance-smoke\20260513-150047-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260513-150047-acceptance-summary.md`
- `.runtime\evaluations\20260513-230047-pricing_agency_quote_explanation.json`

## 失败归因

本轮没有修改 evaluation gate（评估门禁）通过语义，也没有把失败伪装成通过。修复集中在 smoke 场景输入和工具调用稳定性：

归因分类：

- 环境/密钥/外部 API（应用程序接口）问题：已关闭到 smoke preflight passed。
- MCP 启动探测问题：smoke 所需服务 healthy；最终复核时 `12306-mcp` 仍为 degraded，需要在 9 场景运行前恢复或通过 core preflight。
- Agent（智能体）业务链路问题：已减少无效重试和跨交通方式扩散调用。
- RAG 证据问题：smoke 通过。
- `report_data`（结构化报告数据）契约问题：smoke 通过。
- runtime budget 问题：smoke 当前通过，仍需在 9 个核心场景中复核稳定性。
- evaluation gate 误判：未发现。

## 下一步

下一步先在同一真实环境下运行 acceptance-core preflight。只有 core preflight 通过，尤其是 `12306-mcp` 等 core 所需 MCP 服务恢复 healthy 后，再运行 9 个 acceptance-core 场景。若 core 场景失败，按失败维度拆解报告质量、RAG、MCP、工具治理、运行预算和旅行社业务证据；不要用 smoke 通过结果替代核心验收。
