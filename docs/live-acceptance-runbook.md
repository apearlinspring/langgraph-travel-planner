# Live Acceptance（在线验收）Runbook（运行手册）

本手册用于复跑 S2 `acceptance-smoke`（验收烟测）和后续 `acceptance-core`（核心验收）。所有 Windows PowerShell 命令先启用 UTF-8，避免中文输出损坏。

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
```

## 当前分支

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-acceptance-runner-resilience`
- 分支：`codex/acceptance-runner-resilience`
- 日期：2026-05-14

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
   RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS=25
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
   .\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200
   ```

## acceptance-core 复跑步骤

先确认当前分支以最新主线为基准：

```powershell
git fetch origin
git merge --ff-only origin/main
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
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200
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

## acceptance-core 当前真实结果

2026-05-13 在 `codex/core-preflight-readiness` 分支完成一次 acceptance-core preflight（核心验收预检）复核；本轮没有运行 9 个 acceptance-core 场景。

- `.env` 存在：`true`
- runtime readiness：`passed`
- live health（存活检查）：`alive`
- ready health（就绪检查）：`ready`
- MCP（模型上下文协议）服务：6 healthy，0 unavailable，37 tools
- core preflight（预检）：退出码 `0`，`preflight.status=passed`，`backend_live=passed`，`backend_ready=passed`
- 9 个核心场景：未运行

当前不把 core preflight 结论替代 core 9 场景结论。preflight 已通过，下一步可以在同一真实环境下运行 9 个核心场景。

## 当前 smoke 真实结果

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

## 本轮验证记录

```powershell
.\.venv\Scripts\python.exe -m compileall app tests scripts
```

结果：退出码 `0`。

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_live_runner.py tests\test_transport_query_tool.py tests\test_workflow_maintainability.py -q
```

结果：退出码 `0`，`70 passed`。测试结束后 LangSmith（LangChain 可观测平台）上报返回 `403 Forbidden`，不影响 pytest（测试框架）退出码。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：退出码 `0`，`387 passed, 24 deselected`。结束后 LangSmith（LangChain 可观测平台）上报返回 `403 Forbidden`，但 pytest（测试框架）退出码为 `0`。

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
```

结果：退出码 `0`，`preflight.status=passed`，`backend_live=passed`，`backend_ready=passed`。

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

结果：退出码 `0`，`preflight.status=passed`，`backend_live=passed`，`backend_ready=passed`。首次默认 8 秒 MCP 启动探测会导致 `amap`、`12306-mcp` 和 `VariFlight-Aviation` degraded；把 `RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS` 调整为 25 秒后复测通过，并已把 25 秒同步为默认值。

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果：退出码 `0`，`status=passed`，`passed=true`，场景数 `1`。`runtime_budget=passed`，`total_elapsed_seconds=556.393`，`first_token_seconds=84.103`，`tool_call_count=21`。

本地证据：

- `.runtime\acceptance-smoke\20260513-150047-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260513-150047-acceptance-summary.md`
- `.runtime\evaluations\20260513-230047-pricing_agency_quote_explanation.json`

这些 `.runtime/` 文件不提交。

## 脱敏与提交规则

- 不提交 `.runtime/`。
- 不提交 `.env`、真实密钥、手机号、邮箱、证件号、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- JSON（JavaScript 对象表示法）和 Markdown（标记文本）摘要写入前必须经过脱敏。
- 可提交文档只记录状态、场景、阻塞项、命令结果和 `.runtime/` 相对路径。

提交前只对可提交文档记录脱敏摘要；`.runtime/` 原始 summary（摘要）和 snapshot（快照）不提交。

## 下一步

如果后续改动影响模型、RAG（检索增强生成）、MCP（模型上下文协议）或报告结构，先复跑 `acceptance-smoke`。当前 smoke 和 core preflight 均已通过；下一步运行 9 个 acceptance-core 场景，并继续只提交脱敏摘要，不提交 `.runtime/` 原始产物。
