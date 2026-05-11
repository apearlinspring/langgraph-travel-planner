# Live Acceptance（在线验收）Runbook（运行手册）

## 本轮结论

执行时间：2026-05-11 23:10-23:18，环境为本地 Windows PowerShell，工作树为 `D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-acceptance-runbook`，分支为 `codex/live-acceptance-runbook`。

本轮真实尝试了 preflight（预检）、后端启动、数据库初始化、RAG（检索增强生成）初始化，以及完整 `acceptance-core` 验收入口。结果是 `blocked`（环境阻塞）：当前没有 `.env`，缺真实 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、LLM（大语言模型）、MCP（模型上下文协议）上游 API（应用程序接口）密钥和可读 RAG 向量库元数据，后端也未到达健康检查端点。

因此本轮没有执行有效 live scenario（在线场景）对话调用，也没有宣称 passed（通过）。完整入口命令生成了 blocked 摘要文件，但 `.runtime/` 原始产物不提交。

## 真实验收依赖

`--acceptance-core` 当前选择 9 个核心场景，全部要求真实 LLM（大语言模型）和真实 MCP（模型上下文协议）。合并后的真实依赖如下：

- PostgreSQL（关系型数据库）：业务表、LangGraph（图式智能体编排框架）Checkpointer（执行检查点）、Store（长期存储）和审批治理表。
- Redis（内存数据结构存储）：staging（预生产）/ production（生产）会话锁和横向扩展缓存。
- LLM（大语言模型）：`DASHSCOPE_API_KEY`，通过 `app/utils/llm_factory.py` 统一创建模型。
- RAG（检索增强生成）向量库：默认 `data/vectorstore/chroma.sqlite3`，collection（集合）为 `travel_guides`；内部知识库还需要 `data/vectorstore_internal`。
- MCP（模型上下文协议）：`weather`、`search`、`amap`、`12306-mcp`、`VariFlight-Aviation`、`aigohotel-mcp`。
- 外部 API（应用程序接口）：`AMAP_API_KEY`、`TAVILY_API_KEY`、`VARIFLIGHT_API_KEY`，以及 `AIGOHOTEL_API_KEY` / `AIGOHOTEL_MCP_API` / `AIGOHOTEL_SECRET_KEY` 三者至少一个真实酒店凭据。
- Auth（认证）/ JWT（JSON Web Token，令牌认证）：staging（预生产）/ production（生产）必须使用真实 `JWT_SECRET_KEY` 和 `JWT_ALGORITHM`。

## 执行记录

所有 PowerShell 命令均先设置 UTF-8 输出：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
```

1. 初始 `.venv` 检查

   ```powershell
   .\.venv\Scripts\python scripts\check_runtime_readiness.py --target development --json
   ```

   结果：退出码 1，`.venv` 不存在，PowerShell 返回 `CommandNotFoundException`。随后使用 `uv run python ...` 创建虚拟环境，安装 191 个包。

2. development（开发）配置矩阵

   ```powershell
   uv run python scripts\check_runtime_readiness.py --target development --json
   ```

   结果：退出码 1，`status=blocked`。缺必需 `postgresql`、`llm`；可选降级包括 `redis`、`rag_vector_store`、`map`、`search`、`hotel`、`flight`、`langsmith`、`auth_jwt`。当时 `dotenv_present=false`，RAG 向量库目录不存在。

3. acceptance-core（核心验收）场景计划

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
   ```

   结果：退出码 0，列出 9 个核心场景：`free_weekend_nearby`、`free_city_three_days`、`agency_couple_relaxed`、`agency_family_parent_child`、`agency_senior_low_stress`、`edge_hotel_tool_fallback`、`pricing_agency_quote_explanation`、`risk_weather_disruption`、`edge_transport_tool_fallback`。

4. acceptance-core preflight（核心验收预检）

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
   ```

   结果：退出码 1，9 个核心场景均为 `status=blocked`，`summary_paths=null`。阻塞项包括运行配置矩阵、真实 LLM、aigohotel、高德、Tavily、VariFlight、真实 MCP 服务，以及后端 `/health/live` 和 `/health/ready` 不可达。

5. 后端启动尝试

   ```powershell
   $p = Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList 'main.py' -WorkingDirectory (Get-Location) -RedirectStandardOutput '.runtime\backend-start.out.log' -RedirectStandardError '.runtime\backend-start.err.log' -PassThru
   Start-Sleep -Seconds 25
   Invoke-WebRequest -Uri http://127.0.0.1:8000/health/live -UseBasicParsing -TimeoutSec 8
   Invoke-WebRequest -Uri http://127.0.0.1:8000/health/ready -UseBasicParsing -TimeoutSec 8
   Stop-Process -Id $p.Id -Force
   ```

   结果：服务进程进入 `Waiting for application startup`，25 秒内 `/health/live` 与 `/health/ready` 都返回“无法连接到远程服务器”。启动日志仅保存在 `.runtime/`，不提交。

6. acceptance（验收）预检带后端健康检查

   ```powershell
   .\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --base-url http://127.0.0.1:8000 --check-backend --json
   ```

   结果：退出码 1，`status=blocked`，`scenario_count=9`。`missing_required` 为 `runtime_config`、`real_llm`、`external_api:aigohotel`、`external_api:amap`、`external_api:tavily`、`external_api:variflight`、`real_mcp`、`backend_live`、`backend_ready`。

7. PostgreSQL 初始化

   ```powershell
   .\.venv\Scripts\python -m scripts.init_db
   ```

   结果：退出码 1，连接 `localhost:5432/travel_planner_db` 失败，`::1:5432` 与 `127.0.0.1:5432` 均 `Connect call failed`。没有创建业务表、Checkpointer 表、Store 表或 `pgvector` 扩展。

8. RAG 初始化

   ```powershell
   .\.venv\Scripts\python -m scripts.init_rag
   ```

   结果：退出码 1。脚本成功加载 1 个 destination guide（目的地攻略）文档和 10 个 agency internal（旅行社内部知识）文档，并切分出 3 个父文档、18 个子文档；随后在创建 DashScope Embeddings（通义千问向量模型）时因缺 `DASHSCOPE_API_KEY` 失败。`data/vectorstore` 目录被创建，但缺 `chroma.sqlite3` 元数据，不能视为可用向量库。

9. 完整 acceptance-core 入口

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json
   ```

   结果：退出码 1。脚本在 preflight（预检）阶段阻断，未调用真实聊天场景；9 个核心场景均为 `status=blocked`，生成 blocked 摘要：

   ```text
   .runtime\evaluations\20260511-151720-acceptance-summary.json
   .runtime\evaluations\20260511-151720-acceptance-summary.md
   ```

   这些文件只作为本地证据，不提交。

## 阻塞项

- `.env` 不存在，`dotenv_present=false`。
- PostgreSQL（关系型数据库）未配置真实 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`，且本机 `localhost:5432` 连接拒绝。
- Redis（内存数据结构存储）缺 `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`；staging（预生产）验收要求它是必需依赖。
- LLM（大语言模型）缺真实 `DASHSCOPE_API_KEY`。
- RAG（检索增强生成）向量库缺 `chroma.sqlite3` 元数据；`scripts.init_rag` 因缺 DashScope 密钥无法创建。
- 外部 API（应用程序接口）缺 `AMAP_API_KEY`、`TAVILY_API_KEY`、`VARIFLIGHT_API_KEY`、aigohotel 酒店凭据。
- MCP（模型上下文协议）真实服务缺上游凭据：`weather`/`amap` 需要高德，`search` 需要 Tavily，`VariFlight-Aviation` 需要 VariFlight，`aigohotel-mcp` 需要 aigohotel。
- Auth（认证）/ JWT（JSON Web Token，令牌认证）缺 staging（预生产）验收所需真实 `JWT_SECRET_KEY`、`JWT_ALGORITHM`。
- 后端未在 25 秒内进入可访问健康端点，`/health/live` 和 `/health/ready` 均不可达。

## 复现步骤

1. 准备本地 `.env`，只从 `.env.example` 复制变量名，不提交真实值。
2. 配置并确认 PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）可连通。
3. 初始化数据库：

   ```powershell
   .\.venv\Scripts\python -m scripts.init_db
   ```

4. 配置真实 `DASHSCOPE_API_KEY` 后初始化 RAG（检索增强生成）向量库：

   ```powershell
   .\.venv\Scripts\python -m scripts.init_rag
   ```

5. 启动后端：

   ```powershell
   .\.venv\Scripts\python main.py
   ```

6. 先跑预检：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
   .\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --base-url http://127.0.0.1:8000 --check-backend --json
   ```

7. 只有预检为 `passed`（通过）或经确认可接受的 `degraded`（降级）时，才运行真实验收：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json
   ```

8. 如果仍为 `blocked`（环境阻塞），只提交脱敏文档摘要，不提交 `.runtime/`、真实密钥、手机号、身份证、客户资料或供应商私密数据。

## 下一步

下一次推进应先补齐真实 staging（预生产）配置和服务连通性，再复跑 preflight（预检）。只有后端健康检查和真实依赖全部满足后，才有资格把 full acceptance（完整验收）结果判定为 `passed`、`degraded` 或 `failed`。
