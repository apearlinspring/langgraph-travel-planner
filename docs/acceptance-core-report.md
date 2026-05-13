# Acceptance Core Evidence（核心验收证据）报告

## 结论

2026-05-13 在 `codex/core-preflight-readiness` 分支完成 acceptance-core（核心验收）preflight（预检）真实环境复核。当前真实环境 runtime readiness（运行时就绪检查）和 core preflight 均为 `passed（通过）`，原先阻塞 9 个核心场景前置判断的 MCP（模型上下文协议）冷启动降级已关闭。

本文件仍不把 preflight 结果等同于 9 个 acceptance-core 场景通过。它只说明真实环境依赖、后端 ready（就绪检查）和 core 所需 MCP 服务已经满足进入 9 场景跑批的前置条件。

环境闭环历史见 [acceptance-runtime-close-loop.md](./acceptance-runtime-close-loop.md)，本轮 smoke 预算收口见本文后续记录。

## 基准与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-acceptance-runner-resilience`
- 分支：`codex/acceptance-runner-resilience`
- 基准命令：`git fetch origin --prune; git merge --ff-only origin/main`
- 结果：本分支从最新 `origin/main` 基线继续；本轮不推 `main`。
- 本地 Python（编程语言运行时）环境：如缺少 `.venv`，用 `uv run --frozen ...` 或 `uv sync --frozen` 按锁文件创建。

执行过的核心门禁命令：

```powershell
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python.exe -m scripts.init_rag
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

后续运行 9 个 acceptance-core（核心验收）场景时，使用带韧性预算的入口，不写真实 `.env` 内容，不提交 `.runtime/` 原始产物：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200
```

单场景或子集复跑用于定位失败，不替代完整 core 结论：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-subset --scenario-timeout 900
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --scenario risk_weather_disruption --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-subset --scenario-timeout 900 --global-timeout 1800
```

若发生 timeout（超时）、global_timeout（全局超时）、conversation_busy（会话占用）、runtime budget（运行预算）或 evidence closure（证据闭环）失败，摘要会在 `run_context` 和每个场景结果中保留脱敏分类。每个场景结束后都会即时刷新 JSON（JavaScript 对象表示法）和 Markdown（标记文本）summary（摘要），因此已完成场景的机器结论不会被后续长循环吞掉。

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
- MCP 启动探测问题：已确认默认 8 秒对真实远端 MCP 冷启动偏短；默认值和 `.env.example` 已调整为 25 秒，core preflight 复测通过。
- Agent（智能体）业务链路问题：已减少无效重试和跨交通方式扩散调用。
- RAG 证据问题：smoke 通过。
- `report_data`（结构化报告数据）契约问题：smoke 通过。
- runtime budget 问题：smoke 当前通过，仍需在 9 个核心场景中复核稳定性。
- evaluation gate 误判：未发现。

## 下一步

下一步可以在同一真实环境下运行 9 个 acceptance-core 场景。若 core 场景失败，按失败维度拆解报告质量、RAG、MCP、工具治理、运行预算和旅行社业务证据；不要用 preflight 或 smoke 通过结果替代核心验收。
