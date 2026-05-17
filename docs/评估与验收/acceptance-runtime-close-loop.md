# Acceptance Runtime Close Loop（运行时验收闭环）

## 结论

2026-05-13 在 `codex/acceptance-runtime-close-loop` 分支完成真实环境闭环。acceptance-core（核心验收）preflight（预检）已经从 blocked（环境阻塞）推进到 `passed`，但 acceptance-smoke（验收烟测）真实场景失败在 runtime budget（运行预算），所以本轮不进入 9 个核心场景。

当前判断：环境阻塞项已关闭到足以启动真实场景；是否值得跑 9 个核心场景，取决于先处理 smoke 暴露的耗时和工具调用预算问题。

## 脱敏前提

- `.env` 存在，未打印、未复制、未提交。
- 本轮只向 `.env` 追加了非密钥运行时配置：`RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS=25`，用于避免远端 MCP（模型上下文协议）服务冷启动握手被默认 8 秒超时误判。
- `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/` 均为 ignored（忽略）状态。
- `.runtime/` 原始 JSON（JavaScript 对象表示法）、Markdown（标记文本）、stdout、stderr 仅本地保留，不提交。

## 执行命令与结果

```powershell
git fetch origin --prune
git status --short --branch
```

结果：当前分支与 `origin/codex/acceptance-runtime-close-loop` 齐平，工作树起始无未提交改动。

```powershell
docker compose up -d postgres redis
```

结果：退出码 `1`，原因是本机已有同名容器 `zhixing-postgres`、`zhixing-redis`。复核后两个容器均 `healthy`，端口分别为 `5432` 和 `6379`，可复用。

```powershell
uv sync --frozen
```

结果：退出码 `0`。当前工作树原本缺 `.venv`，已按 `uv.lock` 重建本地虚拟环境。

```powershell
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
```

结果：退出码 `0`。业务表 Alembic（数据库迁移工具）迁移完成，LangGraph（图式智能体编排框架）Checkpointer（检查点）表和 Store（存储）表创建/迁移成功，pgvector（PostgreSQL 向量扩展）启用成功。

```powershell
.\.venv\Scripts\python.exe -m scripts.init_rag
```

结果：退出码 `0`。RAG（检索增强生成）初始化完成：

- public vector store（公开向量库）：18 条 embedding（向量嵌入），路径 `data\vectorstore`
- internal vector store（内部向量库）：61 条 embedding，路径 `data\vectorstore_internal`
- Chroma（向量库组件）telemetry（遥测）输出告警，但未影响退出码。

```powershell
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
```

结果：退出码 `0`，`status=passed`，`blocked_reasons=[]`，`repair_suggestions=[]`。状态计数：`configured=10`，`service_checked=2`。

```powershell
.\.venv\Scripts\python.exe main.py
GET /health/live
GET /health/ready
```

第一次 ready 结果：`degraded`，核心依赖 ready，但 `amap`、`12306-mcp`、`VariFlight-Aviation` 因 MCP 连接超时降级。

脱敏复测显示这 3 个 MCP 服务在 25 秒工具加载超时下均 healthy：

- `amap`: 15 tools
- `12306-mcp`: 8 tools
- `VariFlight-Aviation`: 9 tools

追加非密钥超时配置并重启后：

- `/health/live`: `alive`
- `/health/ready`: `ready`
- `missing_required=[]`
- `degraded_optional=[]`
- MCP 服务：6 healthy，0 unavailable，37 tools

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

第一次结果：退出码 `1`，`preflight.status=blocked`。阻塞原因为后端 ready 中 selected MCP services 不健康：`12306-mcp`、`VariFlight-Aviation`、`amap`。

调整非密钥超时并重启后结果：退出码 `0`，`preflight.status=passed`，`backend_live=passed`，`backend_ready=passed`。`--preflight-only` 顶层 run status 为 `skipped` 属于预期，因为没有运行真实场景。

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果：退出码 `1`，`status=failed`，场景数 `1`。

本地证据路径：

- `.runtime\acceptance-smoke\20260513-072508-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260513-072508-acceptance-summary.md`
- `.runtime\evaluations\20260513-152508-pricing_agency_quote_explanation.json`

## Smoke 失败摘要

场景：`pricing_agency_quote_explanation`

- `status=failed`
- `normalized_score=100.0`
- `grade=A`
- `agent_score=97.08`
- `report_quality=passed`
- `rag_quality=passed`
- `tool_quality=passed`
- `budget_confidence=passed`
- `internal_evidence=passed`
- `tool_audit=passed`
- `evidence_closure=passed`
- `runtime_quality=failed`
- `runtime_budget=failed`

运行预算失败项：

- `total_elapsed_seconds=1223.067`，超过预算 `900.0`
- `tool_call_count=41`，超过预算 `36`
- `tool_failure_count=19`
- `fallback_count=19`
- `first_token_seconds=42.404`
- `turn_count=9`
- `report_event_count=1`
- `error_event_count=0`

状态计数：

- `passed`: 0
- `failed`: 1
- `blocked`: 0
- `degraded`: 0
- `skipped`: 0

## 是否进入 9 个核心场景

本轮不进入 acceptance-core 9 个核心场景。

原因：preflight 已经 passed，环境不再 blocked；但 smoke 已真实运行并失败在运行预算。如果此时跑 9 个核心场景，大概率会放大同类耗时和重复工具调用问题，产出成本高且结论不新。

下一轮建议先做运行预算分析，不急着改业务逻辑：

- 对 `.runtime\evaluations\20260513-152508-pricing_agency_quote_explanation.json` 做脱敏指标分析，定位 19 次 fallback（兜底）和 41 次 tool call（工具调用）的来源。
- 复核交通、地图、酒店、天气等真实工具是否有慢调用或重复调用。
- 确认是业务链路需要减少重复工具调用，还是 smoke 场景预算需要按真实冷启动重新设定。
- 修复或解释后先复跑 acceptance-smoke；smoke 通过后再跑 9 个 acceptance-core 场景。

## 验证记录

```powershell
.\.venv\Scripts\python.exe -m compileall app tests scripts
```

结果：退出码 `0`。

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_readiness.py tests\test_script_entrypoints.py tests\test_evaluation_live_runner.py -q
```

结果：退出码 `0`，`66 passed`。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：退出码 `0`，`387 passed, 24 deselected`。测试结束后 LangSmith（LangChain 可观测平台）上报返回 `403 Forbidden`，不影响 pytest（测试框架）退出码。

## 自审

- `.env` 是否存在：是。
- `.env` 是否提交：否，仍为 ignored。
- Docker / PostgreSQL / Redis 状态：已有容器复用，PostgreSQL 和 Redis 均 healthy。
- init_db 结果：通过，退出码 `0`。
- init_rag 结果：通过，退出码 `0`，仅有非阻塞 telemetry 告警。
- `/health/live` 结果：`alive`。
- `/health/ready` 结果：调整非密钥 MCP 启动超时后为 `ready`。
- acceptance-core preflight 状态：`passed`。
- 是否进入 smoke：是，因为 preflight passed。
- 是否进入 core：否，因为 smoke 真实场景 failed，失败维度为 runtime budget。
- 本轮修改：只准备提交脱敏文档；`.env` 本地非密钥配置和 `.runtime/` 原始产物不提交。
- 未解决风险：真实链路当前存在耗时超预算、工具调用超预算、fallback 偏多风险。

## 下一步

下一步先做 smoke runtime budget（运行预算）拆解和脱敏指标归因；只有 smoke 通过或存在明确可接受的 degraded 解释后，再运行 9 个 acceptance-core 场景。
