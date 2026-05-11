# 第三批生产化收口：live acceptance（在线验收）证据

## 结论

本分支把第三批第一优先级收口到可重复验收的证据链：`acceptance-core` 核心验收集可以稳定选择 9 个场景，跑批脚本会先做 preflight（预检），真实依赖缺失时输出 blocked（环境阻塞），不会把缺密钥、后端未启动或运行配置不完整误报为 passed（通过）。

当前本机环境结论是 blocked（环境阻塞），原因是缺少真实 LLM（大语言模型）、MCP（模型上下文协议）上游 API（应用程序接口）凭据、PostgreSQL（关系型数据库）/ Redis（内存数据结构存储）验收配置、RAG（检索增强生成）向量库、JWT（JSON Web Token，令牌认证）配置，并且后端健康检查不可达。因此本轮没有声明真实链路通过，只沉淀了可审计的阻塞证据。

## 核心场景

`--acceptance-core` 当前选择 9 个核心场景，满足“至少 8 个核心场景”的验收目标：

- `free_weekend_nearby`
- `free_city_three_days`
- `agency_couple_relaxed`
- `agency_family_parent_child`
- `agency_senior_low_stress`
- `edge_hotel_tool_fallback`
- `pricing_agency_quote_explanation`
- `risk_weather_disruption`
- `edge_transport_tool_fallback`

这些场景覆盖自由行、旅行社省心方案、报价解释、天气风险、酒店兜底和交通兜底。每个场景都声明了 `requirements`，包括是否需要真实 LLM（大语言模型）、真实 MCP（模型上下文协议）、具体 MCP 服务和外部 API（应用程序接口）。

## 快照证据契约

成功的 live snapshot（真实链路快照）必须包含以下顶层字段：

- `report_data`：最终结构化旅行报告。
- `tool_events`：从 SSE（服务器发送事件）归一化出的工具调用证据。
- `turn_observability`：每轮安全运行观测摘要。
- `quality_summary`：综合 Agent（智能体）质量摘要，包含报告质量、RAG（检索增强生成）质量、工具治理质量、运行时质量和综合分。

为了兼容已有消费者，`summary.quality_summary` 和 `observability_events` 仍然保留；新增顶层字段用于审计时直接定位证据，不需要从嵌套摘要里猜。

## 状态语义

验收摘要现在明确区分 5 类状态：

- `passed`（通过）：预检通过，所有核心门禁通过。
- `failed`（失败）：环境具备运行条件，但至少一个报告、RAG（检索增强生成）、工具治理或运行时质量维度失败。
- `degraded`（降级）：硬门禁未失败，但存在非阻塞运行预算 warning（警告）或可选预检降级。
- `blocked`（环境阻塞）：缺真实依赖、后端健康检查不可达或核心运行配置不足，不能执行有效在线验收。
- `skipped`（跳过）：明确只做 preflight（预检）且预检不是 blocked，或没有选择可运行场景。

blocked（环境阻塞）不再只表现为“场景 skipped（跳过）”。当 preflight（预检）发现真实依赖缺失时，每个核心场景的结果和 gate（门禁）都会是 blocked，并在 run-level summary（整批摘要）中额外写入 `environment_dependencies` 失败维度。

## 失败维度

汇总报告会把失败落到可排查维度：

- `report_quality`：报告结构、行程、地图、预算、风险和前端导出契约。
- `rag_quality`：RAG（检索增强生成）证据、内部类别覆盖、模式适配和可追溯性。
- `tool_quality`：工具意图覆盖、禁用工具规避、重复调用、失败兜底和审计表面。
- `runtime_quality` / `runtime_budget`：总耗时、首 token（词元）时间、工具调用数、错误事件和估算 token（词元）成本。
- `environment_dependencies`：真实密钥、运行配置、后端健康检查和场景声明依赖。

这次没有降低任何门禁阈值；新增的 degraded（降级）只用于标记非阻塞 warning（警告），不会把 degraded 当作 passed（通过）。

## 本轮验证记录

```powershell
.\.venv\Scripts\python -m pytest tests/test_evaluation_live_runner.py tests/test_runtime_readiness.py tests/test_runtime_metrics.py -q
```

结果：`39 passed`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
```

结果：退出码 0，列出 9 个 `acceptance-core` 核心场景及每个场景的阶段推进消息。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

结果：非零退出，整体 `acceptance_summary.status=blocked`，9 个核心场景均为 `status=blocked`，`summary_paths=null`。报告中包含 `environment_dependencies` 失败记录，且 `skipped_metrics` 明确列出报告质量、RAG（检索增强生成）、工具治理、运行时质量、预算置信度、内部证据和工具审计均不可判定。

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --json
```

结果：非零退出，`status=blocked`，`scenario_count=9`。该命令未开启 `--check-backend`，因此只验证运行配置和场景依赖矩阵。

当前缺失项只记录环境变量名，不记录真实值：

- `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`
- `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`
- `DASHSCOPE_API_KEY`
- `AMAP_API_KEY`
- `TAVILY_API_KEY`
- `VARIFLIGHT_API_KEY`
- `AIGOHOTEL_API_KEY`、`AIGOHOTEL_MCP_API` 或 `AIGOHOTEL_SECRET_KEY`
- `JWT_SECRET_KEY`、`JWT_ALGORITHM`
- RAG（检索增强生成）向量库目录
- 后端 `GET /health/live` 和 `GET /health/ready`

## 复跑步骤

1. 准备 `.env` 中的真实验收配置和 RAG（检索增强生成）向量库，不提交真实密钥。
2. 启动后端：

   ```powershell
   .\.venv\Scripts\python main.py
   ```

3. 先跑预检：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json
   ```

4. 预检通过或仅 degraded（降级）后跑真实核心验收：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000
   ```

5. 若结果不是 passed（通过），优先打开 Markdown（标记文本）摘要的失败维度，再定位对应 JSON（JavaScript 对象表示法）快照中的 `report_data`、`tool_events`、`turn_observability` 和 `quality_summary`。
