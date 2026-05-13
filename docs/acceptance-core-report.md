# Acceptance Core Evidence（核心验收证据）报告

## 结论

2026-05-13 在 `codex/core-preflight-readiness` 分支完成 acceptance-core（核心验收）preflight（预检）真实环境复核。当前真实环境 runtime readiness（运行时就绪检查）和 core preflight 均为 `passed（通过）`，原先阻塞 9 个核心场景前置判断的 MCP（模型上下文协议）冷启动降级已关闭。

2026-05-14 在 `codex/acceptance-core-full-run` 分支启动 9 场景真实跑批，详见 [acceptance-core-full-run.md](./acceptance-core-full-run.md)。本轮确认 core preflight 通过且环境不再阻塞，但 9 场景未通过：5 个场景落盘，2 个 passed、3 个 failed/incomplete，剩余 4 个因第 6 场景长时间工具循环而未运行。

本文件仍不把 preflight 结果等同于 9 个 acceptance-core 场景通过。它只说明真实环境依赖、后端 ready（就绪检查）和 core 所需 MCP 服务已经满足进入 9 场景跑批的前置条件。

环境闭环历史见 [acceptance-runtime-close-loop.md](./acceptance-runtime-close-loop.md)，本轮 smoke 预算收口见本文后续记录。

## 基准与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-core-preflight-readiness`
- 分支：`codex/core-preflight-readiness`
- 基准命令：`git fetch origin --prune; git merge --ff-only origin/main`
- 结果：从最新主线 `0c80978` 创建工作树。
- 本地 Python（编程语言运行时）环境：新工作树用 `uv sync --frozen` 按锁文件创建 `.venv`。

执行过的核心门禁命令：

```powershell
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python.exe -m scripts.init_rag
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

## 环境闭环摘要

- `.env` 存在：是，未提交。
- `.env` 存在但未打印内容，未提交；本轮不把真实密钥写入文档或提交说明。
- PostgreSQL（关系型数据库）：`healthy`。
- Redis（内存数据结构存储）：`healthy`。
- `scripts.init_db --mode bootstrap`：退出码 `0`。
- `scripts.init_rag`：退出码 `0`。新工作树本地生成公开和内部 RAG（检索增强生成）向量库；这些 ignored（忽略）产物不提交。
- runtime readiness（运行时就绪检查）：`status=passed`，`blocked_reasons=[]`。
- `/health/live`：`alive`。
- `/health/ready`：在 `RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS=25` 下为 `ready`；MCP 服务 6 healthy、0 unavailable、37 tools。
- 本轮已把默认 `RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS` 从 8 秒调整为 25 秒，并同步 `.env.example` 与运行文档，避免远端 MCP 冷启动被误判为 degraded（降级）。

## Preflight 结果

- `preflight.status=passed`
- `preflight.blocked=false`
- `backend_live=passed`
- `backend_ready=passed`
- `missing_required=[]`
- `degraded_optional=[]`
- core 所需 MCP 服务：`12306-mcp`、`VariFlight-Aviation`、`aigohotel-mcp`、`amap`、`search`、`weather` 均满足 preflight。
- 首次用默认 8 秒 MCP 启动超时启动后端时，`amap`、`12306-mcp`、`VariFlight-Aviation` 曾 degraded；提高到 25 秒后复测通过。

## 9 个核心场景状态

2026-05-14 已进入真实 9 场景跑批，但未完成整批。停止原因不是环境阻塞，而是第 6 个场景继续工具循环且整批已超过 75 分钟。原始快照保留在 `.runtime/`，不提交。

| 场景 | 本轮状态 | 说明 |
|---|---|---|
| `free_weekend_nearby` | failed | 生成 `report_data`，但 runtime budget 失败：`tool_call_count=40 > 32`，`error_event_count=1 > 0`。 |
| `free_city_three_days` | failed | 自由行场景误生成 `agency_context.mode=agency_plan`，报告和 RAG 模式对齐失败。 |
| `agency_couple_relaxed` | passed | 综合分 100，证据闭环和 runtime budget 通过。 |
| `agency_family_parent_child` | passed | 综合分 100，证据闭环和 runtime budget 通过。 |
| `agency_senior_low_stress` | failed/incomplete | 第 8 回合超时 900 秒，未生成 `report_data`。 |
| `edge_hotel_tool_fallback` | not_run | 第 6 场景工具循环后人工停止。 |
| `pricing_agency_quote_explanation` | not_run / smoke_passed | 核心批未运行；最小 smoke 真实链路已通过。 |
| `risk_weather_disruption` | not_run | 第 6 场景工具循环后人工停止。 |
| `edge_transport_tool_fallback` | not_run | 第 6 场景工具循环后人工停止。 |

核心场景状态统计：

- `passed`: 2
- `failed/incomplete`: 3
- `blocked`: 0
- `degraded`: 0
- `not_run`: 4

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
- MCP 启动探测问题：已确认默认 8 秒对真实远端 MCP 冷启动偏短；默认值和 `.env.example` 已调整为 25 秒，core preflight 复测通过。
- Agent（智能体）业务链路问题：已减少无效重试和跨交通方式扩散调用。
- RAG 证据问题：smoke 通过。
- `report_data`（结构化报告数据）契约问题：smoke 通过。
- runtime budget 问题：smoke 当前通过，仍需在 9 个核心场景中复核稳定性。
- evaluation gate 误判：未发现。

## 下一步

下一步先不要直接复跑 9 场景。先按 [acceptance-core-full-run.md](./acceptance-core-full-run.md) 拆分修复 runtime loop guard（运行时循环保护）、RAG runtime contract（RAG 运行时契约）、planning mode boundary（规划模式边界）和 acceptance runner resilience（验收运行器韧性）。修完后先复跑 `free_weekend_nearby`、`free_city_three_days`、`agency_senior_low_stress` 三个代表场景，再恢复完整 9 场景。
