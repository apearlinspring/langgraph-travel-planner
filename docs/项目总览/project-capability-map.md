# Project Capability Map（项目能力答疑地图）

这份文档把 AI-Agent（人工智能智能体）项目常见问题映射到项目回答、代码定位、可运行命令和风险边界。回答时优先讲“设计取舍”和“可验证证据”，避免只说概念。

## 快速总览

| 常见问题 | 一句话回答 | 代码定位 | 验证命令 | 风险边界 |
|---|---|---|---|---|
| 这是不是普通 RAG 问答？ | 不是。RAG（检索增强生成）只是证据来源之一，主链路由状态机、工具调用、MCP（模型上下文协议）和最终 `report_data`（结构化报告数据）交付组成。 | `app/core/workflow.py`、`app/tools/state_transition.py`、`app/reports/` | `.\.venv\Scripts\python -m pytest tests\test_report_contract_module.py -q` | 不把检索片段直接当成最终事实。 |
| 多智能体怎么编排？ | 主控 Travel Agent（旅行智能体）负责阶段推进；目的地 Router（路由器）处理攻略和天气；交通 Coordinator（协调器）分发航班、高铁、自驾。 | `app/agents/handoffs/travel_agent.py`、`app/agents/routers/destination_router.py`、`app/agents/subagents/transport_coordinator.py` | `.\.venv\Scripts\python -m pytest tests\test_destination_router.py tests\test_flight_query_tool.py -q` | 子 Agent 不是越多越好，必须有清晰职责和工具边界。 |
| 状态机在哪里？ | `TravelState` 保存结构化状态，`current_step` 控制八个规划阶段，状态迁移工具用 `Command(update=...)` 推进。 | `app/core/state.py`、`app/core/workflow.py`、`app/agents/handoffs/step_config.py`、`app/tools/state_transition.py` | `.\.venv\Scripts\python -m pytest tests\test_workflow_maintainability.py tests\test_step_prompt_rendering.py -q` | 改阶段必须同步状态、prompt（提示词）、工具和测试。 |
| 工具怎么避免乱调？ | `StepConfigMiddleware` 按阶段注入工具，跨阶段查询只在明确意图下临时开放，并对重复酒店或交通查询做抑制。 | `app/core/middleware.py`、`app/agents/handoffs/step_config.py` | `.\.venv\Scripts\python -m pytest tests\test_step_prompt_rendering.py -q` | 当前还不是统一工具执行网关，后续可继续收敛。 |
| 外部能力为什么用 MCP？ | MCP 把天气、搜索、地图、铁路、航班和酒店能力统一为 Agent 可调用工具，并通过服务级缓存、重试和降级避免单点拖垮主链路。 | `app/mcp_core/client.py`、`app/tools/mcp_tools.py` | `.\.venv\Scripts\python -m pytest tests\test_mcp_client_config_unit.py -q` | 外部服务不可用时不能伪造真实查询结果。 |
| RAG 怎么保证旅行社业务感？ | 内部知识库按产品、SOP（标准作业流程）、报价、风险和报告标准组织；产品化样板支持目的地级弱匹配，例如只说“想去新疆”也能召回新疆省心路线候选。 | `data/documents/internal/`、`app/tools/rag_tools.py`、`app/evaluation/rag_quality.py`、`app/evaluation/rag_retrieval.py`、`docs/RAG与知识库/rag-demo-evaluation-guide.md` | `.\.venv\Scripts\python scripts\validate_rag_knowledge.py`；`.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --json` | 小型召回评估不是线上全量指标，产品样板不能说成真实库存或锁价。 |
| 报价怎么讲清楚？ | 报告区分真实工具价、规则估算、兜底估算和待核验项，避免锁价或库存承诺。 | `app/agency/pricing_rules.py`、`app/reports/builder.py` | `.\.venv\Scripts\python -m pytest tests\test_report_quality_evaluation.py -q` | 不接真实支付和供应链履约。 |
| HITL 如何体现？ | 敏感动作有策略、审批请求、审批事件和 readiness 语义；当前订单号只是模拟编号，不代表真实预订。 | `app/core/approval.py`、`app/core/permissions.py`、`app/api/v1/approvals.py`、`docs/治理与可观测/approval-governance.md` | `.\.venv\Scripts\python -m pytest tests\test_approval_governance.py -q` | 普通用户不能自审未来真实支付或预订动作。 |
| 可观测性有什么？ | 聊天链路记录 turn（轮次）级观测：首 token（文本令牌）、总耗时、工具调用、失败、fallback（兜底）和 token 估算。 | `app/core/observability.py`、`app/api/v1/chat.py`、`app/evaluation/runtime_metrics.py` | `.\.venv\Scripts\python -m pytest tests\test_runtime_metrics.py -q` | 当前是轻量观测，不是分布式 trace（链路追踪）。 |
| 验收门禁怎么做？ | `acceptance_gate` 聚合报告质量、RAG 质量、工具质量、运行预算和内部证据，失败时输出维度化原因。 | `app/evaluation/acceptance_gate.py`、`scripts/run_evaluation_scenarios.py` | `.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run` | 无真实环境时只能 blocked 或 dry-run，不能声明通过。 |
| CI/CD（持续集成/持续交付） 如何覆盖？ | 默认 CI 跑编译、知识库校验、测试收集、本地回归和前端验证；staging smoke（预生产烟测）手动触发真实链路。 | `.github/workflows/ci.yml`、`.github/workflows/staging-smoke.yml` | `.\.venv\Scripts\python -m pytest tests\test_ci_workflows.py -q` | 默认 CI 不消耗真实外部 API（应用程序接口）额度。 |
| 前端怎么证明报告可交付？ | 前端优先消费 `report_data`，展示规划模式、预算置信度、待核验、方案依据、地图路线和导出 HTML（超文本标记语言）。 | `frontend/app.js`、`frontend/zhixing.html`、`docs/前端与演示/frontend-report-experience.md` | `node scripts\verify_frontend_report_renderer.js` | 前端是单页原型，不是完整工程化后台。 |

## 推荐回答结构

### 1. “请介绍你的项目”

回答模板：

> 知行是一个旅行社智能顾问 Agent。后端用 FastAPI（快速应用接口框架）提供 API，主对话由 LangGraph（图式智能体编排框架）和 LangChain（大模型应用编排框架）编排，状态机分八个旅行规划阶段。它通过 RAG 补充公开和内部知识，通过 MCP 接入天气、搜索、地图、铁路、航班、酒店等外部能力，最终生成结构化 `report_data`，前端按这个契约渲染和导出报告。

代码定位：

- `app/main.py`：FastAPI 应用和生命周期。
- `app/api/v1/chat.py`：SSE（服务器发送事件）聊天入口。
- `app/core/state.py`：旅行状态。
- `app/agents/handoffs/travel_agent.py`：主控 Agent。
- `app/reports/builder.py`：结构化报告构建。

### 2. “为什么不是普通 RAG？”

回答模板：

> 普通 RAG 通常是“检索几段文本，然后生成答案”。这个项目的 RAG 只负责提供证据，真正的控制面是状态机和工具编排。系统会先收集需求，再推荐目的地、查交通、查住宿、生成行程、汇总预算、生成报告。每一步都有允许工具和前置依赖，最终验收看 `report_data` 是否满足结构、预算、风险、证据和前端导出契约。

产品化演示时可以补一句：

> 如果用户没有拒绝省心方案，RAG 可以召回成熟路线样板作为候选；如果用户明确说自由行或自己订，中间件会切回自由规划，不继续推产品。

可指代码：

- `app/agents/handoffs/step_config.py`：每阶段 prompt 和工具白名单。
- `app/tools/state_transition.py`：状态迁移工具。
- `app/evaluation/report_quality.py`：报告质量评分。
- `app/evaluation/rag_quality.py`：RAG 证据质量评分。

### 3. “Agent 工具失败怎么办？”

回答模板：

> 工具失败不能编造真实结果。酒店和交通查询失败时，系统会给出诚实兜底，并在报告中保留待核验项。MCP 客户端按服务降级，避免单个外部服务拖垮核心对话。验收门禁也会检查失败兜底和工具审计，而不是只看回复是否流畅。

可指代码：

- `app/tools/hotel_query.py`
- `app/tools/transport_query.py`
- `app/mcp_core/client.py`
- `app/evaluation/tool_quality.py`

### 4. “怎么做生产治理？”

回答模板：

> 当前项目不接真实供应链，但已经有轻量治理边界：审批策略、审批请求和事件、工具审计、运行时观测、readiness 检查、CI 门禁和手动 staging smoke。也就是说，未来接真实支付、短信、真实预订前，已有敏感动作和审计模型可以承接，不会让 Agent 直接执行高风险动作。

可指代码：

- `app/core/permissions.py`
- `app/models/approval.py`
- `app/core/observability.py`
- `.github/workflows/staging-smoke.yml`

### 5. “如何证明能复跑？”

回答模板：

> 复跑分三层。第一层是本地讲解路径，只跑文档生成、专项测试和 dry-run，不需要密钥。第二层是 acceptance-smoke，需要真实后端和真实环境，先 preflight 再跑最小真实链路。第三层是前端报告路径，用同一份 `report_data` 验证渲染和导出。每层都明确依赖和不能证明的边界。

可运行命令：

```powershell
.\.venv\Scripts\python scripts\build_project_demo_pack.py --output .runtime\project-demo-pack
.\.venv\Scripts\python -m pytest tests\test_project_demo_pack.py -q
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
```

真实环境命令：

```powershell
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

## 常见追问与边界回答

| 追问 | 建议回答 |
|---|---|
| 现在能真实下单吗？ | 不能。当前只生成项目内模拟订单号，不代表支付、锁价、库存或履约；真实支付和预订必须先补 HITL 和供应链治理。 |
| 真实价格准确吗？ | 工具返回的价格可以标记为可追溯；缺失时只能做规则估算或兜底估算，并进入待核验项。 |
| 为什么不直接让模型一次性写报告？ | 一次性写报告不可控，难以追踪证据和阶段状态；现在的状态机可以把需求、工具结果、预算和风险沉淀为结构化状态。 |
| 为什么不用更多 Agent？ | Agent 数量不是目标。当前只在目的地路由和交通模式分发处拆分，因为这些地方有明确任务边界。 |
| 评估是不是太规则化？ | 确定性门禁负责底线，例如结构、证据、工具和运行预算；可选 LLM-as-Judge（大模型评审）只做补充，不覆盖确定性结论。 |
| 前端是否生产可用？ | 目前是单页原型，用来证明结构化报告体验；完整生产前端还需要工程化构建、权限后台和更完整的可访问性验证。 |

## 最后收束

讲解结束前可以这样总结：

> 我把这个项目当作 Agent 工程问题，而不是 prompt 工程问题来做。它的核心价值在于：有阶段状态、有工具边界、有证据契约、有结构化交付、有可观测和验收门禁，也知道哪些真实业务动作现在不能做。
