# Interview Demo Pack（面试演示包）

## 目标

本包把“知行”项目整理成面试时可演示、可讲述、可复跑的 AI-Agent（人工智能智能体）材料。核心论点是：它不是普通 RAG（检索增强生成）问答，而是一个面向旅行社顾问工作流的 Agent（智能体）系统。

面试时建议用一句话开场：

> 这个项目把用户的一次旅行咨询拆成阶段化状态机，由主控 Agent 编排目的地 Router（路由器）、交通子 Agent、RAG 知识、MCP（模型上下文协议）工具、HITL（人类在环）治理和最终 `report_data`（结构化报告数据）交付，因此重点不是“回答得像不像”，而是“能不能按顾问流程稳定交付、可审计、可复跑”。

## 如何生成演示包目录

PowerShell（Windows 命令行环境）先启用 UTF-8，避免中文输出损坏：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python scripts\build_interview_demo_pack.py --output .runtime\interview-demo-pack
```

生成目录只包含：

- `README.md`：演示包目录说明。
- `interview-demo-pack.md`：本文。
- `interview-answer-map.md`：面试答题地图。
- `demo-script.md`：现场讲述脚本。
- `commands.ps1`：可复跑命令。
- `manifest.json`：来源、演示路径和安全策略清单。
- `redaction-check.txt`：脱敏扫描结果。

生成器不会读取 `.env`，不会复制 `.runtime` 原始快照，也不会保存真实密钥、手机号、邮箱或 JWT（JSON Web Token，令牌认证）。

## 能力映射

| 面试能力点 | 项目里的证据 | 面试说法 | 可运行入口 |
|---|---|---|---|
| 多智能体编排 | `app/agents/handoffs/travel_agent.py`、`app/agents/routers/destination_router.py`、`app/agents/subagents/transport_coordinator.py` | 主控 Agent 负责旅行流程，目的地 Router 负责攻略和天气分流，交通 Coordinator（协调器）再分发到航班、高铁、自驾子代理。 | `.\.venv\Scripts\python -m pytest tests\test_travel_agent_tool_registry.py -q` |
| 状态机 | `app/core/state.py`、`app/core/workflow.py`、`app/agents/handoffs/step_config.py`、`app/tools/state_transition.py` | `current_step` 驱动需求收集、目的地推荐、交通、住宿、餐饮、行程、预算和报告生成，不是单轮问答。 | `.\.venv\Scripts\python -m pytest tests\test_workflow_maintainability.py tests\test_step_prompt_rendering.py -q` |
| 工具调用 | `app/tools/transport_query.py`、`app/tools/hotel_query.py`、`app/tools/mcp_tools.py` | Agent 可调用交通、酒店、地图、搜索、天气等工具；失败时写入待核验，而不是编造库存或价格。 | `.\.venv\Scripts\python -m pytest tests\test_hotel_query_tool.py tests\test_driving_query_tool.py -q` |
| RAG 知识增强 | `app/rag/`、`app/tools/rag_tools.py`、`data/documents/internal/` | RAG 不是最终答案生成器，而是给顾问方案提供目的地知识、产品、SOP（标准作业流程）、报价、风险和报告标准证据。 | `.\.venv\Scripts\python scripts\validate_rag_knowledge.py` |
| MCP 外部能力 | `app/mcp_core/client.py`、`app/mcp_core/servers/` | MCP 把天气、搜索、地图、铁路、航班、酒店等外部能力标准化为 Agent 工具，并支持服务级降级。 | `.\.venv\Scripts\python -m pytest tests\test_mcp_client_config_unit.py tests\test_mcp\test_weather_server_unit.py -q` |
| HITL 治理 | `app/core/approval.py`、`app/core/permissions.py`、`app/api/v1/approvals.py`、`docs/approval-governance.md` | 当前不做真实支付或预订，但敏感动作已经有审批策略、事件账本和 readiness（就绪状态）语义。 | `.\.venv\Scripts\python -m pytest tests\test_approval_governance.py -q` |
| 可观测性 | `app/core/observability.py`、`app/evaluation/runtime_metrics.py`、`docs/observability.md` | 每轮对话输出首 token（文本令牌）耗时、总耗时、工具调用数、失败数、fallback（兜底）数和 token 估算。 | `.\.venv\Scripts\python -m pytest tests\test_runtime_metrics.py -q` |
| 验收门禁 | `app/evaluation/acceptance_gate.py`、`scripts/run_evaluation_scenarios.py`、`docs/evaluation-system.md` | 验收看 `report_data`、RAG 证据、工具治理、运行预算和旅行社业务证据，不靠主观聊天观感。 | `.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run` |
| CI/CD（持续集成/持续交付） | `.github/workflows/ci.yml`、`.github/workflows/staging-smoke.yml` | 默认 CI 跑本地回归和前端验证；staging smoke（预生产烟测）用 workflow_dispatch（手动触发）跑真实链路。 | `.\.venv\Scripts\python -m pytest tests\test_ci_workflows.py -q` |
| 前端报告 | `frontend/app.js`、`frontend/zhixing.html`、`docs/frontend-report-experience.md` | 前端优先消费结构化 `report_data`，展示预算置信度、待核验项、地图路线和治理边界。 | `node scripts\verify_frontend_report_renderer.js` |
| 核心验收证据 | `docs/acceptance-core-report.md`、`docs/live-acceptance-runbook.md`、`app/evaluation/acceptance_gate.py` | acceptance-core（核心验收）给出 9 个核心场景的 passed（通过）、failed（失败）、degraded（降级）、blocked（环境阻塞）地图，不把 blocked 或 failed 伪装成通过。 | `.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary` |

## 三条演示路径

### 路径一：本地纯讲解路径

适用场景：没有真实 DashScope（阿里云灵积模型服务）、高德、Tavily（搜索 API 服务）或酒店密钥，只能讲架构和跑本地检查。

建议顺序：

```powershell
.\.venv\Scripts\python scripts\build_interview_demo_pack.py --output .runtime\interview-demo-pack
.\.venv\Scripts\python -m pytest tests\test_interview_demo_pack.py -q
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
```

讲述重点：

- `--dry-run` 只列出验收场景，不调用真实后端。
- 面试官如果问“没有密钥怎么证明”，就展示代码定位、测试、场景目录和生成目录的脱敏策略。
- 这条路径证明工程结构和验收入口存在，但不宣称真实链路已经通过。

### 路径二：acceptance-smoke 真实链路

适用场景：本地 `.env` 已配置真实 LLM（大语言模型）、PostgreSQL（关系型数据库）、Redis（内存数据结构存储）和相关 MCP 外部能力。

建议顺序：

```powershell
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

讲述重点：

- preflight（预检）先判断真实依赖是否具备，不具备时返回 blocked（环境阻塞），不会假装通过。
- smoke（烟测）最小场景覆盖旅行社报价解释，要求真实链路产出 `report_data`。
- 结果只提交脱敏摘要，不提交 `.runtime` 原始产物。

### 路径三：前端报告路径

适用场景：已经跑出最终报告，想展示从 SSE（服务器发送事件）到前端可视化报告的产品闭环。

建议顺序：

```powershell
.\.venv\Scripts\python main.py
node scripts\verify_frontend_report_renderer.js
```

现场操作：

1. 打开 `frontend/zhixing.html`。
2. 登录或注册测试用户。
3. 创建会话，输入旅行社省心方案需求。
4. 等待最终报告生成。
5. 展示报告卡片、预算置信度、待核验项、地图路线和导出按钮。

讲述重点：

- 前端不是从自然语言里硬解析报告，而是优先消费 `report_data`。
- `report_data` 能被评估、前端和导出共同使用，是 Agent 交付契约。

### 核心验收证据入口

适用场景：面试官追问“如何证明不是只跑 smoke（烟测）”时，展示 acceptance-core 的可审计入口和当前状态地图。

建议顺序：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

讲述重点：

- `docs/acceptance-core-report.md` 记录 9 个核心场景的状态地图和本地证据路径。
- 没有真实 `.env`、LLM（大语言模型）、RAG（检索增强生成）向量库、MCP（模型上下文协议）和后端 ready（就绪状态）时，结果必须是 blocked。
- blocked 只能证明验收入口和门禁语义有效，不能证明业务链路已经通过。

## 面试时的主线叙事

1. 业务身份：这是旅行社智能顾问，不是攻略问答机器人。
2. 编排方式：主控 Agent + Router + 子 Agent + 状态迁移工具。
3. 证据来源：公开 RAG、内部 RAG、MCP 真实查询、用户长期记忆和规则估算。
4. 交付物：最终不是散文答案，而是结构化 `report_data` 和可导出的报告。
5. 治理边界：真实库存、锁价、支付、短信和客服不在当前能力内；涉及敏感动作必须走 HITL。
6. 验收方式：用确定性质量门禁判断报告、证据、工具、运行预算和前端导出准备度。

## 风险边界

- 不承诺真实库存、真实锁价、真实支付、真实出票或酒店确认。
- 外部工具失败时必须标记待核验，不能编造价格、班次或酒店。
- `.env` 和 `.runtime` 原始产物只留在本地或 CI artifact（构建产物），不进入演示包提交。
- acceptance-smoke 需要真实环境；没有真实依赖时只能讲本地路径和 blocked 语义。

## 自审清单

- 三条路径都能说明“演示什么、依赖什么、不能证明什么”。
- 每个能力点都有代码定位和至少一个验证命令。
- 文档只引用脱敏摘要、命令和相对路径。
- 没有复制真实密钥、手机号、邮箱、JWT 或 `.runtime` 原始快照。
