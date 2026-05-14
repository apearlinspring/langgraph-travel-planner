# Acceptance Core Evidence（核心验收证据）报告

## 结论

2026-05-14 在 `codex/round-core-fixes-integration-review` 分支完成 acceptance-core（核心验收）9 场景真实环境跑批。9 个场景均生成机器摘要，真实环境 runtime readiness（运行时就绪检查）和 core preflight（预检）均为 `passed（通过）`，但全量结果为 `failed（失败）`，不能建议合入 `main`。

失败没有通过放宽 runtime budget（运行预算）或 warning ratio（警戒比例）掩盖。所有场景均生成 `report_data`，`evidence_closure.missing=[]`，`error_event_count=0`，`session_busy_event_count=0`，`duplicate_tool_call_same_turn=0`。剩余阻塞集中在首 token（文本令牌）慢路径和一个已修复的规划模式边界误判。

环境闭环历史见 [acceptance-runtime-close-loop.md](./acceptance-runtime-close-loop.md)，复跑步骤见 [live-acceptance-runbook.md](./live-acceptance-runbook.md)。

## 基准与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-round-core-fixes-integration-review`
- 分支：`codex/round-core-fixes-integration-review`
- 基准命令：`git fetch origin; git status --short --branch; git log --oneline -5`
- 结果：本轮没有先合 `main`；只在当前分支做真实验收和小范围修复。
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

完整跑批命令：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core-full --scenario-timeout 900 --global-timeout 7200
```

机器摘要：

- `.runtime\acceptance-core-full\20260514-083740-acceptance-summary.json`
- `.runtime\acceptance-core-full\20260514-083740-acceptance-summary.md`

总体状态：

- `status=failed`
- `passed=false`
- `completed=9`
- `pending=0`
- `passed_count=5`
- `degraded_count=1`
- `failed_count=3`

| 场景 | status | failure_category | tools | duplicate | error | busy | report_data | evidence missing | runtime_budget |
|---|---:|---|---:|---:|---:|---:|---|---|---|
| `free_weekend_nearby` | passed | - | 15 | 0 | 0 | 0 | yes | `[]` | passed |
| `free_city_three_days` | passed | - | 11 | 0 | 0 | 0 | yes | `[]` | passed |
| `agency_couple_relaxed` | passed | - | 18 | 0 | 0 | 0 | yes | `[]` | passed |
| `agency_family_parent_child` | passed | - | 20 | 0 | 0 | 0 | yes | `[]` | passed |
| `agency_senior_low_stress` | degraded | `acceptance_gate` | 20 | 0 | 0 | 0 | yes | `[]` | passed, first-token warning |
| `edge_hotel_tool_fallback` | failed | `runtime_budget` | 25 | 0 | 0 | 0 | yes | `[]` | failed |
| `pricing_agency_quote_explanation` | passed | - | 23 | 0 | 0 | 0 | yes | `[]` | passed |
| `risk_weather_disruption` | failed | `runtime_budget` | 15 | 0 | 0 | 0 | yes | `[]` | failed |
| `edge_transport_tool_fallback` | failed | `acceptance_gate` | 23 | 0 | 0 | 0 | yes | `[]` | passed, first-token warning |

## 失败与降级归因

- `agency_senior_low_stress`：`degraded`，runtime budget 只触发 warning，首 token 使用 85.0% 的首 token 预算；无 error、busy、duplicate。
- `edge_hotel_tool_fallback`：`failed/runtime_budget`，首 token 80.59 秒超过 75 秒，总耗时使用 98.0% 的运行预算。工具质量通过，`query_hotel_options` 真实查询可返回结果，但场景中有阶段回退和多轮慢首 token 叠加。
- `risk_weather_disruption`：`failed/runtime_budget`，首 token 83.683 秒超过 75 秒；工具数 15，未见工具循环或会话占用。
- `edge_transport_tool_fallback`：完整跑批中因 `agency_context.mode=agency_plan` 与 expected `free_planning` 不一致失败，同时 runtime budget 仅 warning。随后做了小修复并单场复跑，模式边界已修复，但该单场仍因首 token 98.651 秒超过 75 秒而 `failed/runtime_budget`。

本轮未发现：

- `conversation_busy` 或 `session_busy` 复发。
- `duplicate_tool_call_same_turn` 复发。
- `report_data` 缺失。
- `evidence_closure.missing` 非空。
- 因缺 MCP（模型上下文协议）服务导致的 blocked（环境阻塞）。

## 小修复验证

修复范围：

- `app/agency/planning_mode.py`
- `app/core/intent.py`
- `app/tools/state_transition.py`
- `tests/test_planning_mode_boundary.py`

修复要点：

- “省心安排”不再单独作为强旅行社模式信号；只有“省心方案/旅行社/产品/托管/包办/报价/合同”等明确强信号才进入 `agency_plan`。
- `record_requirement_tool` 会用用户原文和需求摘要共同核验模型传入的 `planning_mode=agency_plan`；没有用户强信号支撑时回落 `free_planning`。

验证命令：

```powershell
.\.venv\Scripts\python -m pytest tests\test_planning_mode_boundary.py tests\test_intent_detection.py tests\test_workflow_maintainability.py::test_record_requirement_persists_planning_mode tests\test_workflow_maintainability.py::test_record_requirement_uses_recent_user_agency_signal_when_tool_args_are_plain tests\test_workflow_maintainability.py::test_record_requirement_keeps_hotel_fallback_in_free_planning_without_agency_signal tests\test_workflow_maintainability.py::test_record_requirement_keeps_weak_free_mode_when_hotel_fallback_is_requested -q
```

结果：`38 passed`。测试结束后 LangSmith（LangChain 可观测平台）上报返回 `403 Forbidden`，不影响 pytest（测试框架）退出码。

修复后单场复跑：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario edge_transport_tool_fallback --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core-reruns --scenario-timeout 900 --global-timeout 1200
```

结果：

- 摘要：`.runtime\acceptance-core-reruns\20260514-090232-acceptance-summary.json`
- 快照：`.runtime\evaluations\20260514-170232-edge_transport_tool_fallback.json`
- `agency_context.mode=free_planning`
- `report_quality=passed`
- `rag_quality=passed`
- `tool_quality=passed`
- `runtime_budget=failed`
- `first_token_seconds=98.651`，预算 `75.0`
- `tool_call_count=25`
- `duplicate=0`
- `error_event_count=0`
- `session_busy_event_count=0`
- `report_data=true`
- `evidence_closure.missing=[]`

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

## 当前待处理项

本轮没有修改 evaluation gate（评估门禁）通过语义，也没有把失败伪装成通过。

待继续修复或复核：

- runtime budget：`edge_hotel_tool_fallback`、`risk_weather_disruption`、修复后单场 `edge_transport_tool_fallback` 均因首 token 超过 75 秒失败。需要继续定位是模型服务首 token 波动、上下文压缩后提示过长、阶段回退导致慢路径，还是外部工具结果进入模型后的生成延迟。
- 阶段回退：`edge_hotel_tool_fallback` 在报告前出现需求/天数校正回退，虽然最终报告和证据闭环完整，但推高了总耗时。
- 规划模式边界：`edge_transport_tool_fallback` 的误判已用小修复关闭，后续完整 core 复跑仍需确认该场不再因 `agency_context.mode` 失败。

暂不建议合入 `main`。下一步应优先复核 runtime budget 慢路径，在不放宽预算的前提下降低首 token 和阶段回退耗时，然后重新运行完整 9 场景。
