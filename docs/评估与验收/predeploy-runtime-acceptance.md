# Predeploy Runtime Acceptance

## 2026-05-17 历史结论

- 分支：`codex/acceptance-core-final-gates-fix`。
- 基准：用户指定保持 `origin/main@3b02f41`；本轮在当前分支未合入状态下执行。
- 当时状态：passed。`acceptance-smoke` 1/1 passed，完整 `acceptance-core` 9 场景 9/9 passed。
- 真实环境：使用本机真实 `.env`；`.env` 存在且未被 Git 跟踪，未打印或写入真实密钥。
- 后端：使用当前分支 `main.py` 启动，`/health/live=alive` 且 `/health/ready=ready`。
- 原始证据：`.runtime/` 仅本地保留，不提交。
- 记录状态：历史参考。2026-07-12 的严格门禁单次统一结果见 `acceptance-core-report.md` 顶部 `final-core-6`，运行基准为当时未提交工作树。

旧 core 跑批的工具失败/兜底比例较高；后续版本新增了严格失败预算，当前版本需按新门禁重新执行。

## 当前重新验收的判定口径

- run-level gate 采用 fail-closed（缺证据即失败）：场景结果的 `status/passed`、`acceptance_gate.status/passed` 和 `evidence_closure.passed` 必须一致通过。缺少门禁或证据闭环、状态非法、布尔值与状态矛盾，都使整批结果 failed。
- `tool_failure_count` 只统计 `service_exception`；只有缺少更具体语义时，原始 `failed`、`failure`、`timeout`、`error` 才回落为 `service_exception`。`failed + empty_*_result` 仍是 `not_found` fallback，不是硬失败；`needs_verification`、参数不足和治理跳过只属于 degraded。
- `tool_failure_ratio` 按 `tool_failure_count / tool_call_count` 计算；无调用且无失败时为 0.0，无调用却有失败记录时按 1.0 处理。整批摘要按整批总数计算，单场景 runtime budget 按该场景计算。
- 普通场景默认要求工具失败数、失败率和 fallback 数均为 0；只有显式声明预算的专门降级场景可以有界放宽。

具体启动顺序和 `ZHIXING_12306_MCP_URL` 配置见 [真实环境验收手册](live-acceptance-runbook.md)。backend-probing preflight 必须在后端启动后执行。

## 环境与初始化

| 项目 | 结果 | 脱敏证据 |
|---|---:|---|
| `.env` | present / ignored | 仅确认存在和未跟踪，不记录变量值 |
| PostgreSQL | ready | 本地服务可用，`scripts.init_db --mode bootstrap` passed |
| Redis | ready | 本地服务可用 |
| RAG | ready | public/internal 向量库就绪；向量库目录不提交 |
| 后端健康 | ready | `/health/live=alive`，`/health/ready=ready` |
| MCP | ready | `/health/ready` 显示所需服务 healthy |
| LLM | ready | `DASHSCOPE_API_KEY` 存在性校验通过，未输出密钥 |

## 单测与重点场景

| 项目 | 值 |
|---|---:|
| 相关单测 | 185 passed，1 个第三方弃用 warning |
| 重点 4 场景 summary | `.runtime/acceptance-fix-singles/20260517-four-after-transport-guard/20260516-212155-four-after-transport-guard.json` |
| 重点 4 场景 | 4 / 4 passed |
| 覆盖场景 | `free_weekend_nearby`, `edge_hotel_tool_fallback`, `pricing_agency_quote_explanation`, `edge_transport_tool_fallback` |

重点结果：

- `free_weekend_nearby`: 产出结构化 `report_data`，预算、预算置信度、风险和待核验项齐全。
- `edge_hotel_tool_fallback`: 保留 `query_hotel_options` 审计式调用，通过工具覆盖门禁。
- `edge_transport_tool_fallback`: 保留 `query_transport_options` 审计式调用，通过工具覆盖门禁。
- `pricing_agency_quote_explanation`: runtime budget 通过，首 token 40.277s。

## Smoke 结果

| 项目 | 值 |
|---|---:|
| summary | `.runtime/acceptance-smoke/20260517-transport-guard/20260516-212958-acceptance-smoke.json` |
| 场景 | `pricing_agency_quote_explanation` |
| 状态 | passed |
| 场景数 | 1 / 1 |
| elapsed | 308.394s |
| first token | 37.061s |
| tool calls | 19 |
| `report_data` | true |
| evidence closure | passed |

smoke 结果只证明最小报价说明链路可用；本轮已继续复跑完整 9 场景 core，没有用 smoke 结论覆盖 core 证据。

## Core 结果

| 项目 | 值 |
|---|---:|
| summary | `.runtime/acceptance-core/20260517-transport-guard/20260516-223916-acceptance-core.json` |
| 状态 | passed |
| 场景数 | 9 |
| passed | 9 |
| failed | 0 |
| degraded | 0 |
| blocked | 0 |
| 失败分类 | - |
| 证据闭环通过 | 9 / 9 |
| 总耗时 | 4015.637s |
| 工具调用 | 169 |

场景结果见 `docs/评估与验收/acceptance-core-report.md`。

## 已执行关键命令

```powershell
git fetch origin --prune
git status --short --branch
git diff --name-status
git diff --check
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_live_runner.py tests\test_intent_detection.py tests\test_planning_mode_boundary.py tests\test_tool_quality_evaluation.py tests\test_hotel_query_tool.py tests\test_transport_query_tool.py tests\test_tool_loop_guard.py tests\test_step_prompt_rendering.py -q
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario edge_transport_tool_fallback --scenario edge_hotel_tool_fallback --scenario free_weekend_nearby --scenario pricing_agency_quote_explanation --continue-on-error --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-fix-singles\20260517-four-after-transport-guard --summary-dir .runtime\acceptance-fix-singles\20260517-four-after-transport-guard --summary-prefix four-after-transport-guard --scenario-timeout 1200 --global-timeout 7200 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-smoke\20260517-transport-guard --summary-dir .runtime\acceptance-smoke\20260517-transport-guard --summary-prefix acceptance-smoke --scenario-timeout 1200 --global-timeout 1800 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --continue-on-error --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-core\20260517-transport-guard --summary-dir .runtime\acceptance-core\20260517-transport-guard --summary-prefix acceptance-core --scenario-timeout 1200 --global-timeout 14400 --json
```

历史结果：

- 相关单测：185 passed。
- 重点 4 场景：4/4 passed。
- `acceptance-smoke`：1/1 passed。
- `acceptance-core`：9 场景完整执行，9/9 passed，总状态 passed。

## 脱敏与提交边界

- 不提交 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`。
- 文档只记录状态、指标、相对路径和结论；不记录真实密钥、手机号、邮箱、JWT 或供应商私密响应。
- 通过结论来自完整 9 场景 core，不来自 1 场景 smoke。

## 下一步

当前未提交工作树已通过 `final-core-6` 完整 9 场单次统一跑批，但对外发布、部署或形成可复现演示基线前，仍应冻结干净 commit 后重新执行 smoke 和完整 core，并同时检查工具失败数、失败率、fallback 数、运行预算与报告质量。本文只能作为 2026-05-17 历史快照引用，当前结果以 `acceptance-core-report.md` 为准，生产就绪还需目标环境证据。
