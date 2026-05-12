# 第一阶段总体验收报告

## 结论

本阶段已建立可重复运行、可审计的总体验收质量门禁。门禁不改核心 Agent（智能体）业务逻辑，只聚合真实链路快照中的结构化报告、RAG（检索增强生成）证据、工具调用事件和运行时指标，把“是否达成阶段目标”转成确定性评分和失败维度。

已新增可选 LLM-as-Judge（大模型评审）补充层。它只提供人工质感反馈，不参与确定性门禁通过或失败判断。

当前环境结论：blocked（环境阻塞）。当前没有真实 LLM（大语言模型）和外部 API（应用程序接口）密钥，不能生成“有效验收通过”的结论；只能生成环境阻塞报告。

核心验收命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000
```

该命令会运行 `acceptance-core` 标记的 9 个核心场景，并生成 JSON（JavaScript 对象表示法）和 Markdown（标记文本）两种摘要。摘要默认写入 `.runtime/evaluations/`。

## 验收范围

核心场景覆盖：

- 自由行近郊两日。
- 自由行城市三日。
- 旅行社省心情侣方案。
- 旅行社亲子方案。
- 旅行社银发低压力方案。
- 酒店工具失败兜底。
- 旅行社报价解释。
- 天气和 Plan B 风险。
- 交通工具失败兜底。

每个场景都会输出：

- 报告质量评分。
- RAG（检索增强生成）质量评分。
- 工具治理质量评分。
- 运行时指标评分。
- 预算置信度契约检查。
- 旅行社内部证据引用检查。
- 工具审计表面检查。
- 可选 LLM-as-Judge（大模型评审）补充记录，只有显式 `--llm-judge` 时运行。

每个核心场景都显式声明 `requirements`：

- `real_llm`：是否需要真实 LLM（大语言模型）。
- `real_mcp`：是否需要真实 MCP（模型上下文协议）服务。
- `mcp_servers`：需要的 MCP（模型上下文协议）服务清单。
- `external_apis`：需要的外部 API（应用程序接口）清单。

本批 9 个核心场景都需要真实 LLM（大语言模型）和真实 MCP（模型上下文协议）。核心场景合计需要的外部 API（应用程序接口）包括 `amap`、`tavily`、`variflight`、`aigohotel`。

## 门禁阈值

当前默认阈值：

- 综合 Agent（智能体）分：不低于场景最低分，且全局最低 82 分。
- 报告质量：不低于 80 分。
- RAG（检索增强生成）质量：不低于 80 分。
- 工具治理质量：不低于 80 分。
- 运行时质量：不低于 80 分。
- 运行预算：必须通过。
- 预算置信度：必须有等级、已确认或估算项、待核验项。
- 旅行社省心方案：至少 3 类内部证据。
- 工具审计：必须有使用来源、待核验项和不支持承诺。

LLM-as-Judge（大模型评审）默认阈值为 80 分，但属于 `supplemental_dimensions.llm_judge`。它不能覆盖上述确定性门禁：低分不会把确定性通过改为失败，高分也不会把确定性失败改为通过。

补充评审 rubric（评分规程）为五个 20 分维度：

- 业务贴合。
- 事实忠实。
- 可交付性。
- 风险表达。
- 旅行社专业度。

## 失败输出

失败摘要会明确指出：

- 失败场景。
- 失败维度。
- 实际分数和阈值。
- 关键失败发现。
- 建议排查方向。

常见排查方向：

- 报告失败：检查 `report_data` 顶层字段、每日行程、地图路线、预算明细和风险章节。
- RAG（检索增强生成）失败：检查 `agency_context.evidence` 和 `evidence_bundle` 的类别覆盖。
- 工具失败：检查 SSE（服务器发送事件）里的 `tool_call`、重复高成本工具调用和待核验兜底。
- 运行时失败：检查首 token（令牌）时间、总耗时、工具调用次数、错误事件和估算 token（令牌）数量。
- 预算置信度失败：检查 `budget_confidence` 是否区分已确认、估算和待核验。
- LLM-as-Judge（大模型评审）补充提示：检查 `supplemental_dimensions.llm_judge`，它只用于人工复盘，不作为门禁失败维度。

启用补充评审示例：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --llm-judge
```

真实模型创建统一通过 `app/utils/llm_factory.py`。缺少真实 `DASHSCOPE_API_KEY` 时，显式启用的 LLM-as-Judge（大模型评审）会 blocked（环境阻塞），不会用 mock（模拟）结果冒充通过。评审输入和输出都会脱敏，避免保存真实密钥、手机号、邮箱、证件号、JWT（JSON Web Token，令牌认证）或其他 PII（个人可识别信息）。`manual_review` 字段已预留给后续人工评审数据集。

## 当前验证记录

已完成轻量验证：

```powershell
uv run --frozen pytest tests\test_evaluation_scenarios.py tests\test_evaluation_live_runner.py tests\test_report_quality_evaluation.py tests\test_rag_quality_evaluation.py tests\test_tool_quality_evaluation.py tests\test_runtime_metrics.py -q
```

结果：`50 passed`。

已完成验收核心场景空跑：

```powershell
uv run --frozen python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
```

结果：列出 9 个核心验收场景和每个场景的阶段推进消息。

2026-05-11 追加真实链路环境检查：

- Docker Desktop 已启动，宿主机 `5432` 和 `6379` 端口上的 PostgreSQL（关系型数据库）与 Redis（内存缓存服务）可连通。
- 已用当前进程环境变量完成 `scripts.init_db`，业务表、LangGraph（图式智能体编排框架）Checkpointer（执行检查点）、Store（长期存储）和 `pgvector` 扩展初始化成功。
- 当前没有 `.env`，进程环境中也没有真实 DashScope（阿里云灵积模型服务）、高德、搜索、航班、酒店等外部 API（应用程序接口）密钥。
- 使用占位模型密钥尝试启动后端时，应用卡在 MCP（模型上下文协议）外部服务初始化阶段；日志显示外部服务因缺 API（应用程序接口）密钥返回非 MCP JSON（JavaScript 对象表示法）响应，导致后端未监听 `8000` 端口。
- 因此真实 `--acceptance-core` 验收仍未运行；当前阻塞点是缺真实模型和外部 API（应用程序接口）凭据，或需要调整本地 MCP（模型上下文协议）启动配置让无密钥服务降级后不阻塞启动。

2026-05-11 追加 preflight（预检）结果：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --summary-dir .runtime\preflight-check --summary-prefix preflight-check --json
```

结果：blocked（环境阻塞），当时 9 个核心场景均为 skipped（跳过）。生成了环境阻塞摘要：

- `.runtime\preflight-check\20260511-015126-preflight-check.json`
- `.runtime\preflight-check\20260511-015126-preflight-check.md`

本次缺失依赖：

- 后端启动必需环境变量：`DASHSCOPE_API_KEY`、`LANGSMITH_API_KEY`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`。
- 真实 LLM（大语言模型）：`DASHSCOPE_API_KEY`。
- 高德 API（应用程序接口）：`AMAP_API_KEY`。
- Tavily 搜索 API（应用程序接口）：`TAVILY_API_KEY`。
- 航班 API（应用程序接口）：`VARIFLIGHT_API_KEY`。
- 酒店 API（应用程序接口）：`AIGOHOTEL_API_KEY`、`AIGOHOTEL_MCP_API` 或 `AIGOHOTEL_SECRET_KEY`。
- 后端健康检查：`GET /health/live` 不可达。

本次不可判定指标：

- 报告质量。
- RAG（检索增强生成）质量。
- 工具治理质量。
- 运行时质量。
- 预算置信度。
- 旅行社内部证据引用。
- 工具审计表面。

2026-05-11 追加第 1.5 批集成结论：

- 已统一 `/health/ready` 运行时契约，`services` 同时包含 `checkpointer`、`store`、`mcp`、`session_lock` 和 `approval_governance`。
- `core_ready` 同时要求启动完成、Checkpointer（执行检查点）初始化、Store（长期存储）初始化、会话锁不是 `unavailable`、审批治理 `ready=true`。
- MCP（模型上下文协议）降级或开发环境会话锁降级会返回 `degraded`；生产 Redis（内存数据结构存储）会话锁不可用或审批治理不能持久化到 PostgreSQL（关系型数据库）会返回 `not_ready`。
- `tests/test_system_resilience.py` 已覆盖 ready、MCP 降级、会话锁不可用、审批治理不可用，以及 payload（载荷）同时暴露会话锁和审批治理。

## 后续使用建议

每次合并影响报告、RAG（检索增强生成）、工具治理或运行时行为的改动前，至少运行一次 `--acceptance-core`。如果失败，优先查看 Markdown（标记文本）摘要中的失败维度，再打开对应 JSON（JavaScript 对象表示法）快照复盘原始事件。

## 2026-05-11 第三批生产化收口追加

本分支继续收口真实 live acceptance（在线验收）语义，详见 `docs/round3-live-acceptance.md`。

新增结论：

- `--acceptance-core` 当前稳定选择 9 个核心场景，满足至少 8 个核心场景要求。
- blocked（环境阻塞）不再只表现为 skipped（跳过）；真实依赖缺失时，每个受影响核心场景和整批摘要都会输出 blocked（环境阻塞）。
- 只做 preflight（预检）且预检不是 blocked（环境阻塞）时，场景才会保持 skipped（跳过）。
- 成功 live snapshot（真实链路快照）新增顶层 `quality_summary` 和 `turn_observability`，并继续保留 `report_data`、`tool_events`、`summary.quality_summary` 和 `observability_events`。
- 汇总报告新增 `environment_dependencies` 失败维度，用于指向真实密钥、后端健康检查、RAG（检索增强生成）向量库和场景外部 API（应用程序接口）依赖。
- 运行预算 warning（警告）会使门禁进入 degraded（降级），不会被当作 passed（通过）。

本次实际验证：

```powershell
.\.venv\Scripts\python -m pytest tests/test_evaluation_live_runner.py tests/test_runtime_readiness.py tests/test_runtime_metrics.py -q
```

结果：`39 passed`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
```

结果：退出码 0，列出 9 个核心验收场景。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

结果：非零退出，整体 blocked（环境阻塞），9 个核心场景均为 blocked（环境阻塞），没有写出有效 passed（通过）结论。

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --json
```

结果：非零退出，`status=blocked`，`scenario_count=9`。

## 2026-05-11 live acceptance（在线验收）runbook（运行手册）复跑

本轮继续在本地真实执行验收入口，详见 `docs/live-acceptance-runbook.md`。结论仍为 `blocked（环境阻塞）`，但阻塞证据更完整：

- 实际尝试启动后端：进程进入 application startup（应用启动）阶段，25 秒内 `/health/live` 和 `/health/ready` 都不可达。
- 实际跑了 preflight（预检）：`--acceptance-core --preflight-only --json --no-summary` 返回非零退出，9 个核心场景均为 `blocked`。
- 实际尝试完整入口：`--acceptance-core --base-url http://127.0.0.1:8000 --json` 返回非零退出，在 preflight（预检）阶段阻断，没有进入真实对话场景调用。
- 实际尝试 `scripts.init_db`：本机 `localhost:5432` PostgreSQL（关系型数据库）连接拒绝。
- 实际尝试 `scripts.init_rag`：文档加载和切分成功，但缺 `DASHSCOPE_API_KEY`，无法创建 DashScope Embeddings（通义千问向量模型），当前 RAG（检索增强生成）向量库缺 `chroma.sqlite3` 元数据。

完整入口生成了 `.runtime\evaluations\20260511-151720-acceptance-summary.json` 和 `.runtime\evaluations\20260511-151720-acceptance-summary.md` blocked 摘要。`.runtime/` 产物不提交，只把脱敏结论写入文档。
