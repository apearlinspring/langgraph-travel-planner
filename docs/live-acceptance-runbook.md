# Live Acceptance（在线验收）Runbook（运行手册）

本手册用于复跑 S2 `acceptance-smoke`（验收烟测）和后续 `acceptance-core`（核心验收）。所有 Windows PowerShell 命令先启用 UTF-8，避免中文输出损坏。

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
```

## 当前分支

- 工作树：当前本地验收工作区（不记录绝对路径）
- 分支：`codex/acceptance-core-rerun-closeout`
- 基准：`origin/main@620947b`
- 日期：2026-05-16

## 状态判定

- `blocked（环境阻塞）`：真实依赖、凭据、后端健康检查或配置缺失，不能运行真实链路。
- `degraded（降级）`：核心链路可运行，但可选依赖、MCP（模型上下文协议）服务或运行预算 warning（警告）触发，不能作为完全通过。
- `failed（失败）`：真实链路已运行，但确定性门禁失败。
- `passed（通过）`：真实链路已运行，产出 `report_data`，并通过报告、预算、风险、待核验项、旅行社证据、工具审计和运行时门禁。

失败分类补充：

- `timeout（超时）`：单场景或底层 SSE（服务器发送事件）读取超时。
- `global_timeout（全局超时）`：整批运行预算耗尽。
- `conversation_busy（会话占用）`：后端返回 `session_busy`，说明同一会话仍被占用。
- `runtime_budget（运行预算）`：场景完成但运行预算门禁失败。
- `evidence_closure（证据闭环）`：缺少快照、报告数据、预算、风险、待核验项或旅行社证据。

缺真实依赖或缺 `report_data` 时，任何命令都不能返回 `passed`。

## 2026-05-16 当前真实复跑记录

- `.env`：存在且未被 Git 跟踪；未打印真实值。
- readiness（就绪检查）：PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG（检索增强生成）、LLM（大语言模型）和 MCP（模型上下文协议）均可用；`/health/ready=ready`，MCP 6 healthy / 37 tools。
- `acceptance-smoke`（冒烟验收）：`.runtime/acceptance-smoke/20260516-092127-acceptance-summary.json`，1/1 passed（通过），`report_data=true`，证据闭环通过。
- `acceptance-core`（核心验收）：`.runtime/acceptance-core/20260516-102402-acceptance-summary.json`，完整运行 9 场景，6/9 passed（通过），总状态 failed（失败）。
- 失败分类：`free_weekend_nearby` 为 evidence_closure（证据闭环）失败，未产出结构化 `report_data`，缺少预算、预算置信度、风险和待核验项；`edge_hotel_tool_fallback` 和 `edge_transport_tool_fallback` 为 acceptance_gate（验收门禁）/工具覆盖失败，分别缺少预期 `query_hotel_options` 与 `query_transport_options`。
- 补充：`risk_weather_disruption` 本轮已 passed（通过），不再记录为 timeout（超时）失败。
- 结论：本轮 smoke 通过但 core 未通过，不能声明部署通过；详见 `docs/acceptance-core-report.md` 与 `docs/predeploy-runtime-acceptance.md`。

Windows 本地后端建议用以下方式启动，避免 direct `uvicorn app.main:app` 在 Windows 事件循环和开发 reload（热重载）上引入干扰：

```powershell
$env:DEBUG = 'false'
$env:RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS = '45'
$env:RUNTIME_MCP_OPTIONAL_STARTUP_TIMEOUT_SECONDS = '45'
.\.venv\Scripts\python.exe main.py
```

## 2026-05-14 历史部署前真实环境结果

该轮部署前 readiness（就绪检查）和 `acceptance-smoke`（验收冒烟测试）只证明当时的最小报价说明链路 `pricing_agency_quote_explanation` 1/1 passed（通过），不能替代当前 `docs/acceptance-core-report.md` 的最新 9 场景 acceptance-core（核心验收）结论。

生产发布前若模型、RAG（检索增强生成）、MCP（模型上下文协议）、报告契约或外部 API（应用程序接口）配置变化，应重跑完整 acceptance-core。所有真实本机 `.env` 只在本地运行时使用，不写入手册、摘要或提交。

## 部署验收三层入口

本手册不写真实服务器地址、真实密钥或真实个人信息；`<staging-base-url>` 和 `<production-base-url>` 只表示由部署平台注入或人工临时传入的地址。

### Local 本地

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target local --json
docker compose up -d postgres redis
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --base-url http://127.0.0.1:8000 --json --no-summary
```

### Staging 预生产

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <staging-base-url> --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --base-url <staging-base-url> --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url <staging-base-url> --json --summary-dir .runtime\acceptance-smoke --summary-prefix staging-smoke
```

### Production 生产

```powershell
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <production-base-url> --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url <production-base-url> --json --no-summary
```

`check_runtime_readiness.py` 输出里要同时看 `readiness_status` 和 `component_readiness`。PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG（检索增强生成）和 LLM（大语言模型）在 staging/production 缺真实配置时必须是 `not_ready`；MCP（模型上下文协议）在配置静态检查中可显示 `degraded`，但只要所选 smoke 场景要求的 MCP 服务不 healthy（健康），acceptance preflight（验收预检）必须 blocked（环境阻塞）。

smoke（冒烟测试）失败时先看 JSON（JavaScript Object Notation，结构化数据格式）里的 `repair_suggestions`：

- `blocked`：补齐真实环境变量、RAG 向量库或后端 `/health/ready`，然后重跑 preflight。
- `timeout` / `global_timeout`：查后端日志、MCP 服务健康和模型延迟，不要直接把 timeout（超时限制）调大当作修复。
- `conversation_busy`：确认没有旧验收仍在运行，等待会话锁过期或重启后端。
- `runtime_budget`：先看 runtime metrics（运行指标）和工具调用数，排查重复工具调用或慢依赖。
- `evidence_closure` / `acceptance_gate`：打开 `.runtime/acceptance-smoke` 摘要，补齐 `report_data`、预算、风险、RAG、工具审计等缺口。

## 推荐复跑顺序

1. 确认 `.env` 存在但不要打印真实值；确认 `.env`、`.runtime/` 已被忽略。

2. 启动或确认 PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）。

   ```powershell
   docker compose up -d postgres redis
   ```

   如果遇到同名容器冲突，先复核现有 `zhixing-postgres` 和 `zhixing-redis` 是否 `healthy`，不要为了复跑验收直接删除未知来源容器。

3. 初始化数据库和 RAG（检索增强生成）向量库。

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
   .\.venv\Scripts\python.exe -m scripts.init_rag
   ```

4. 跑 runtime readiness（运行时就绪检查）。

   ```powershell
   .\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
   ```

5. 启动后端。

   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

   远端 MCP（模型上下文协议）服务冷启动可能超过 8 秒；当前默认非密钥配置为：

   ```text
   RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS=45
   ```

   修改该值后需重启后端，再确认 `/health/ready`。core（核心验收）前应看到所需 MCP 服务均为 healthy。

6. 确认最小 smoke（烟测）场景选择。

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
   ```

   预期包含 `pricing_agency_quote_explanation`。

7. 跑 smoke preflight（预检）。

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
   ```

   注意：`--preflight-only` 不运行场景，因此 run status（运行状态）可能是 `skipped（跳过）`；应查看 JSON（JavaScript 对象表示法）里的 `preflight.status`。当前真实环境下应为 `passed`。

8. 跑 smoke 真实入口。

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke --scenario-timeout 900 --global-timeout 1200
   ```

9. smoke 通过或有明确可接受的 degraded（降级）解释后，再扩展到 core（核心验收）。

   ```powershell
   .\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200 --continue-on-error
   ```

## acceptance-core 复跑步骤

先确认当前分支和远端状态。若任务要求以最新 `origin/main` 为基准，先 fetch（获取远端引用）并执行 fast-forward merge（快进合并）：

```powershell
git fetch origin --prune
git merge --ff-only origin/main
git status --short --branch
git log --oneline -5
```

如果当前工作树没有 `.venv`，使用锁文件恢复本地环境：

```powershell
uv sync --frozen
```

先跑 preflight（预检），不要跳过 blocked（环境阻塞）判定：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

再启动后端并跑完整入口：

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200 --continue-on-error
```

如果需要缩小排查范围，可以显式指定一个场景或重复 `--scenario` 运行子集：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-subset --scenario-timeout 900
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --scenario risk_weather_disruption --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-subset --scenario-timeout 900 --global-timeout 1800
```

每完成一个场景，运行器都会刷新 JSON（JavaScript 对象表示法）和 Markdown（标记文本）summary（摘要）。如果发生 Ctrl+C 中断、timeout（超时）或 `global_timeout`，最新 summary 的 `run_context.partial=true`，并列出已完成场景、待运行场景和失败分类计数；敏感值会在写入前脱敏。

验收解释规则：

- `passed（通过）`：preflight 通过，9 个核心场景真实运行并通过门禁。
- `failed（失败）`：真实场景已运行，但报告、RAG、MCP、工具审计或运行预算门禁失败。
- `degraded（降级）`：真实场景可运行，但存在可解释的可选依赖或 warning（警告）。
- `blocked（环境阻塞）`：真实依赖、后端 ready、凭据、向量库或配置缺失，不能声称核心验收通过。

`.runtime/` 下的 JSON（JavaScript 对象表示法）、Markdown（标记文本）、stdout 和 stderr 原始产物只留本地。提交文档时只写相对路径、状态计数、关键阻塞项和脱敏指标。

## acceptance-core 历史真实结果（仅供参考）

2026-05-14 在 `codex/round-core-fixes-integration-review` 分支完成新一轮完整 9 场景真实验收。

- `.env` 存在：`true`，未打印真实值，未提交。
- runtime readiness：`passed`
- live health（存活检查）：`alive`
- ready health（就绪检查）：`ready`
- MCP（模型上下文协议）服务：6 healthy，0 unavailable，37 tools
- core preflight（预检）：退出码 `0`，`preflight.status=passed`，`backend_live=passed`，`backend_ready=passed`
- 完整 9 场景摘要：`.runtime\acceptance-core-full\20260514-134448-acceptance-summary.json`
- 总状态：`passed`
- 完成情况：`completed=9`，`pending=0`
- 场景统计：`passed=9`，`degraded=0`，`failed=0`
- 所有场景：`report_data=true`，`evidence_closure.missing=[]`，`runtime_budget=passed`，`error_event_count=0`，`session_busy_event_count=0`
- 按每个快照的同轮同名工具事件复核，`duplicate_tool_call_same_turn=0`

场景指标摘要：

| 场景 | 状态 | first_token_seconds | tool_call_count | mode |
|---|---:|---:|---:|---|
| `free_weekend_nearby` | passed | 12.565 | 14 | `free_planning` |
| `free_city_three_days` | passed | 9.681 | 13 | `free_planning` |
| `agency_couple_relaxed` | passed | 20.547 | 17 | `agency_plan` |
| `agency_family_parent_child` | passed | 33.636 | 21 | `agency_plan` |
| `agency_senior_low_stress` | passed | 17.513 | 18 | `agency_plan` |
| `edge_hotel_tool_fallback` | passed | 29.511 | 19 | `free_planning` |
| `pricing_agency_quote_explanation` | passed | 74.391 | 26 | `agency_plan` |
| `risk_weather_disruption` | passed | 15.614 | 13 | `agency_plan` |
| `edge_transport_tool_fallback` | passed | 40.417 | 15 | `free_planning` |

本轮闭环的历史问题：

- 首轮复杂慢请求不再先等待酒店、交通、天气或风险工具，先轻量确认，再在后续推进轮核验证据。
- `pricing_agency_quote_explanation` 最终报告轮收窄到 `generate_order_tool` 后已稳定生成 `report_data`。
- `agency_couple_relaxed` 不再因首轮内部产品检索导致工具预算 warning。
- `edge_transport_tool_fallback` 保持 `agency_context.mode=free_planning`，没有回到 `agency_plan`。

该段是历史验收记录；完整 9 场景证据保留在 `docs/acceptance-core-report.md`。合入或发布前仍要在目标环境复跑 `/health/ready`、preflight（预检）和完整 acceptance-core。

## smoke 历史真实结果（仅供参考）

2026-05-13 在当前真实环境完成一次新的 smoke 闭环：

- `preflight.status=passed`
- live smoke status（在线烟测状态）：`passed`
- 生成 `report_data`：是
- evidence closure（证据闭环）：通过
- `report_quality=passed`
- `rag_quality=passed`
- `tool_quality=passed`
- `runtime_budget=passed`
- `total_elapsed_seconds=556.393`，预算 `900.0`
- `first_token_seconds=84.103`，场景预算 `90.0`
- `tool_call_count=21`，场景预算 `36`
- `tool_failure_count=13`
- `fallback_count=13`
- `error_event_count=0`

本地证据：

- `.runtime\acceptance-smoke\20260513-150047-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260513-150047-acceptance-summary.md`
- `.runtime\evaluations\20260513-230047-pricing_agency_quote_explanation.json`

结论：smoke 已经证明最小旅行社报价说明链路可进入真实聊天 API（应用程序接口）、生成 `report_data` 并通过确定性门禁。下一步应运行 9 个核心场景，不要用 smoke 通过结果直接代表核心验收通过。

## 2026-05-14 历史验证记录

该轮详细脱敏结果曾集中记录在 `docs/predeploy-runtime-acceptance.md`。以下命令和指标仅作为历史参考，当前 2026-05-16 结论以本文前部的“当前真实复跑记录”和 `docs/acceptance-core-report.md` 为准。实际执行的关键命令包括：

```powershell
git fetch origin main
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果摘要：RAG public/internal 向量库分别为 18/61 个 embedding（嵌入向量），staging/acceptance readiness 均 ready，MCP（模型上下文协议）6 healthy/37 tools，`acceptance-smoke` 1/1 passed（通过）。本轮 smoke 是部署前最小链路验收，不能替代完整 9 场景 acceptance-core。

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
```

结果：退出码 `0`。

```powershell
.\.venv\Scripts\python -m pytest tests\test_runtime_readiness.py tests\test_acceptance_evidence_pack.py tests\test_evaluation_live_runner.py -q
```

结果：退出码 `0`，`61 passed`。

```powershell
.\.venv\Scripts\python -m pytest -q
```

结果：退出码 `0`，`441 passed, 24 deselected`。

本地证据：

- `.runtime\readiness-staging.json`
- `.runtime\readiness-acceptance.json`
- `.runtime\acceptance-smoke\20260514-151605-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260514-151605-acceptance-summary.md`

这些 `.runtime/` 文件只保留本地，不提交。生产发布前若模型、RAG、MCP、报告契约或外部 API（应用程序接口）配置变化，应重跑完整 acceptance-core。

## 脱敏与提交规则

- 不提交 `.runtime/`。
- 不提交 `.env`、真实密钥、手机号、邮箱、证件号、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- JSON（JavaScript 对象表示法）和 Markdown（标记文本）摘要写入前必须经过脱敏。
- 可提交文档只记录状态、场景、阻塞项、命令结果和 `.runtime/` 相对路径。

提交前只对可提交文档记录脱敏摘要；`.runtime/` 原始 summary（摘要）和 snapshot（快照）不提交。

## 下一步

当前 2026-05-16 `acceptance-core` 未通过。后续先修复 `free_weekend_nearby` 的 `report_data` 证据闭环缺口，再修复 `edge_hotel_tool_fallback` 与 `edge_transport_tool_fallback` 的预期工具调用覆盖；修复后先复跑 `acceptance-smoke`，再复跑完整 9 场景 acceptance-core，继续只提交脱敏摘要，不提交 `.runtime/` 原始产物。
