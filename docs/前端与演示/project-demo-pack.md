# Project Demo Pack

## 目标

演示包汇总知行的架构、能力索引、演示流程和复跑命令。项目用阶段状态组织旅行咨询，由主控 Agent 调用目的地 Router、交通 Coordinator、RAG 与 MCP，最终交付结构化 `report_data`，并通过 HITL 治理和验收脚本检查运行过程。

## 如何生成演示包目录

PowerShell 先启用 UTF-8，避免中文输出损坏：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python scripts\build_project_demo_pack.py --output .runtime\project-demo-pack
```

生成目录只包含：

- `README.md`：演示包目录说明。
- `project-demo-pack.md`：本文。
- `project-capability-map.md`：项目能力答疑地图。
- `demo-script.md`：现场讲述脚本。
- `commands.ps1`：可复跑命令。
- `manifest.json`：来源、演示路径和安全策略清单。
- `redaction-check.txt`：脱敏扫描结果。

生成器不会读取 `.env`，不会复制 `.runtime` 原始快照，也不会保存真实密钥、手机号、邮箱或 JWT。

## 能力映射

| 能力点 | 实现位置 | 职责与状态 | 可运行入口 |
|---|---|---|---|
| Agent 能力编排 | `app/agents/handoffs/travel_agent.py`、`app/agents/routers/destination_router.py`、`app/agents/subagents/transport_coordinator.py` | 主控 Agent 负责旅行流程，目的地 Router 负责攻略和天气分流，交通 Coordinator 直接调用航班、高铁、自驾查询工具。阶段由中间件与状态迁移工具管理。 | `.\.venv\Scripts\python -m pytest tests\test_travel_agent_tool_registry.py -q` |
| 状态机 | `app/core/state.py`、`app/core/workflow.py`、`app/agents/handoffs/step_config.py`、`app/tools/state_transition.py` | `current_step` 驱动需求收集、目的地推荐、交通、住宿、餐饮、行程、预算和报告生成。 | `.\.venv\Scripts\python -m pytest tests\test_workflow_maintainability.py tests\test_step_prompt_rendering.py -q` |
| 工具调用 | `app/tools/transport_query.py`、`app/tools/hotel_query.py`、`app/tools/mcp_tools.py` | Agent 可调用交通、酒店、地图、搜索、天气等工具；失败时写入错误分类和待核验项。 | `.\.venv\Scripts\python -m pytest tests\test_hotel_query_tool.py tests\test_driving_query_tool.py -q` |
| RAG 知识增强 | `app/rag/`、`app/tools/rag_tools.py`、`app/evaluation/rag_retrieval.py`、`data/documents/internal/products/`、`docs/RAG与知识库/rag-demo-evaluation-guide.md` | RAG 为顾问方案提供目的地知识、成熟路线样板、SOP、报价、风险和报告标准证据；产品化场景允许目的地级弱匹配。 | `.\.venv\Scripts\python scripts\validate_rag_knowledge.py`；`.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --json` |
| MCP 外部能力 | `app/mcp_core/client.py`、`app/mcp_core/servers/` | MCP 把天气、搜索、地图、铁路、航班、酒店等外部能力标准化为 Agent 工具，并支持服务级降级。 | `.\.venv\Scripts\python -m pytest tests\test_mcp_client_config_unit.py tests\test_mcp\test_weather_server_unit.py -q` |
| HITL 治理骨架 | `app/core/approval.py`、`app/core/permissions.py`、`app/api/v1/approvals.py`、`docs/治理与可观测/approval-governance.md` | 已有审批策略、事件账本与 readiness；LangGraph `interrupt/resume` 执行闭环待接通。 | `.\.venv\Scripts\python -m pytest tests\test_approval_governance.py -q` |
| 可观测性 | `app/core/observability.py`、`app/evaluation/runtime_metrics.py`、`docs/治理与可观测/observability.md` | 每轮对话输出 `first_token_seconds`、`total_elapsed_seconds`、工具调用数、失败数、fallback 数和 token 估算；首个助手片段可能为固定 ACK，分析时同时查看总耗时。 | `.\.venv\Scripts\python -m pytest tests\test_runtime_metrics.py -q` |
| 验收门禁 | `app/evaluation/acceptance_gate.py`、`scripts/run_evaluation_scenarios.py`、`docs/评估与验收/evaluation-system.md` | 确定性场景门禁检查 `report_data`、RAG 证据、工具治理、失败/兜底预算、运行预算和旅行社业务证据；轨迹质量、长期稳定性与用户体验另行评估。 | `.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run` |
| CI/CD | `.github/workflows/ci.yml`、`.github/workflows/staging-smoke.yml` | 默认 CI 跑本地回归和前端验证；staging smoke 用 workflow_dispatch 跑真实链路。 | `.\.venv\Scripts\python -m pytest tests\test_ci_workflows.py -q` |
| 前端报告 | `frontend/app.js`、`frontend/zhixing.html`、`docs/前端与演示/frontend-report-experience.md`、`docs/前端与演示/report-data-delivery-contract.md` | 前端优先消费结构化 `report_data`，展示预算明细、待核验项、地图路线，支持 HTML 导出。 | `node scripts\verify_frontend_report_renderer.js`；`node scripts\verify_frontend_browser_regression.js` |
| 核心验收证据 | `docs/评估与验收/acceptance-core-report.md`、`docs/评估与验收/live-acceptance-runbook.md`、`app/evaluation/acceptance_gate.py` | 2026-07-12 的 `final-core-6` 在同一后端代码快照和同一组真实本地依赖上完整执行 9 个场景，9/9 同时通过报告质量、Agent 工业指标和运行预算门禁；该次使用未提交工作树，冻结 commit 后需复跑并补重复运行与目标环境验证。 | `.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary` |

## 当前可展示状态

- 部署实例配合健康检查、验收摘要与代码定位展示，地址从本地或 CI 私有配置读取。
- 截至 2026-07-12，当前未提交工作树已有 `final-core-6` 完整 9 场统一运行结论：9/9 通过，且 9 个场景的报告质量分、Agent 工业指标分均为 100，运行预算均通过。该结论不是分批结果拼接，但仍只代表同一代码快照和同一组本地依赖上的一次运行。
- `docs/评估与验收/acceptance-core-report.md` 保存 2026-07-12 单次统一跑批与 2026-05-17 旧门禁记录。发布验收需绑定干净 commit，重新执行 smoke 和完整 core。
- `docs/RAG与知识库/rag-demo-evaluation-guide.md` 可用于回答“RAG 怎么验证”：重点看是否召回正确产品样板、知识类别和依据来源。
- `docs/RAG与知识库/rag-retrieval-evaluation.md` 记录当前轻量标注查询和本地知识文档规模；实际指标以重新运行 `scripts/evaluate_rag_retrieval.py --json` 的输出为准。
- `docs/前端与演示/report-data-delivery-contract.md` 记录 `report_data` 到前端报告、复制摘要和导出 HTML 的交付契约；导出件保存结构化报告的静态快照。
- 前端展示旅行顾问工作台、服务治理、审批记录与脱敏运行摘要。

## 三条演示路径

### 路径一：本地纯讲解路径

适用场景：没有真实 DashScope、高德、Tavily 或酒店密钥，只能讲架构和跑本地检查。

建议顺序：

```powershell
.\.venv\Scripts\python scripts\build_project_demo_pack.py --output .runtime\project-demo-pack
.\.venv\Scripts\python -m pytest tests\test_project_demo_pack.py -q
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
```

检查重点：

- `--dry-run` 只列出验收场景，不调用真实后端。
- 检查代码定位、专项测试、场景目录与演示包脱敏结果。
- 真实后端与外部服务通过下一条路径验收。

### 路径二：acceptance-smoke 真实链路

适用场景：本地 `.env` 已配置真实 LLM、PostgreSQL、Redis 和相关 MCP 外部能力。

建议顺序：

```powershell
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

检查重点：

- preflight 检查依赖，缺失时返回 blocked 并列出待补项。
- smoke 最小场景覆盖旅行社报价解释，要求真实链路产出 `report_data`。
- 结果只提交脱敏摘要，不提交 `.runtime` 原始产物。

### 路径三：前端报告路径

适用场景：已经跑出最终报告，想展示从 SSE 到前端可视化报告的产品闭环。

建议顺序：

```powershell
.\.venv\Scripts\python main.py
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
```

现场操作：

1. 打开 `frontend/zhixing.html`。
2. 登录或注册测试用户。
3. 创建会话，输入旅行社省心方案需求。
4. 等待最终报告生成。
5. 展示报告卡片、预算置信度、待核验项、地图路线和导出按钮。

检查重点：

- 前端优先消费 `report_data`。
- `report_data` 能被评估、前端和导出共同使用，是 Agent 交付契约。
- 浏览器回归会覆盖桌面与移动视口、复制摘要和导出 HTML，并确认导出件保留待核验边界、不保留交互按钮或内部治理标签。

### 核心验收证据入口

适用场景：检查完整 acceptance-core 的场景覆盖、历史结果与当前复跑要求。

建议顺序：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

检查重点：

- `docs/评估与验收/acceptance-core-report.md` 顶部记录 2026-07-12 当前未提交工作树的 `final-core-6` 统一 9/9 状态地图，后文保留 2026-05-17 旧门禁历史证据；前者为一次本地完整跑批，按该日期的工作树与依赖记录。
- 没有真实 `.env`、LLM、RAG 向量库、MCP 和后端 ready 时，结果必须是 blocked。
- 待依赖补齐后重新执行真实链路验收。

## 项目讲解主线

1. 业务流程：需求澄清、方案准备与报告交付。
2. 编排方式：主控 Agent + 目的地 StateGraph Router+ 交通 Coordinator + 状态迁移工具。
3. 证据来源：公开 RAG、内部 RAG、产品化路线样板、MCP 真实查询、用户长期记忆和规则估算。
4. 交付物：结构化 `report_data` 与可导出的报告。
5. 治理：展示审批策略与记录；敏感动作适配需补齐 HITL 执行绑定、幂等与补偿。
6. 验收方式：用确定性场景门禁判断报告、证据、工具失败/兜底预算、运行预算和前端导出准备度，并用人工 badcase 复核补足轨迹质量判断。

## 风险边界

- 当前演示使用路线样例、工具候选与估算，真实库存锁定、支付、预订、出票和酒店确认尚未接入。外部查询失败时保留待核验项。
- 指定 fallback 场景可以在明确预算内验证降级；普通场景或高比例工具失败不能只因“诚实兜底”而通过。
- `.env` 和 `.runtime` 原始产物只留在本地或 CI artifact，不进入演示包提交。
- acceptance-smoke 需要真实环境；没有真实依赖时只能讲本地路径和 blocked 语义。

## 自审清单

- 三条路径注明演示内容、依赖和结果范围。
- 每个能力点都有代码定位和至少一个验证命令。
- 文档只引用脱敏摘要、命令和相对路径。
- 没有复制真实密钥、手机号、邮箱、JWT 或 `.runtime` 原始快照。
