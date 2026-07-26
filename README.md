# 知行旅行规划器 / ZhiXing Travel Planner

知行旅行规划器的目标业务形态是旅行社经营与交付工作台：Agent（智能体）辅助旅行顾问完成需求澄清、产品匹配、方案与报价准备、订单草稿和交付说明，而不是只生成一篇旅游攻略。后端使用 FastAPI（快速应用接口框架），主执行链路以一个 Travel Agent（旅行主控智能体）和阶段中间件为核心，再按需调用目的地 Router（路由器）与交通 Coordinator（协调器）；LangGraph（图式智能体编排框架）和 LangChain（大模型应用编排框架）负责运行编排，RAG（检索增强生成）补充本地知识，MCP（模型上下文协议）接入可选外部能力。PostgreSQL（关系型数据库）保存用户、会话、消息、审批、检查点、长期记忆和第一阶段旅行社交易域数据；Redis（缓存数据库）主要承担会话锁、缓存、API 限流计数和短期运行状态，不作为长期业务事实来源。

当前版本仍处于“规划交付链路 + 交易控制面骨架”阶段。它可以持续对话、分阶段确认需求、区分自由规划和旅行社省心方案并生成结构化报告；代码也已加入旅行社租户、成员、客户关系、供应商产品、报价、订单、内部审核、事件和幂等记录等持久化模型。但真实供应商预订、支付、退款和通知尚未接入，并由默认关闭的配置门禁阻断，不能把当前版本表述为已具备真实外部交易或履约能力。

## 核心能力

- 双工作流规划：自由规划按目的地、交通、住宿、餐饮、行程和预算逐步推进；省心方案按需求确认、产品匹配、方案草案、用户微调和报告交付推进。
- 编排边界：主流程不是“每个阶段一个 Agent”；交通 Coordinator 直接调用航班、高铁和自驾查询工具，不再保留一套未接入运行链路的交通方式子 Agent。
- 流式聊天接口：通过 SSE（服务器发送事件）返回模型文本、工具调用事件、结构化报告数据和超时兜底信息。
- 本地知识增强：公开目的地知识和脱敏旅行社样例知识覆盖路线模板、报价规则、风险提示、SOP（标准作业流程）和报告标准。
- 外部能力接入：MCP 工具可接入天气、搜索、地图、火车、航班和酒店等服务；可选服务不可用时按服务级别降级。
- 结构化报告：后端维护 `report_data` 报告契约，前端优先按结构化数据渲染预算、行程、地图、风险和待核验项。
- 旅行社交易域骨架：持久化旅行社租户、成员、客户关系、供应商产品、报价、订单、内部审核、订单事件、幂等记录、支付尝试和履约记录；内部 API 支持报价草稿、发布、客户接受、订单草稿、提交审核及专职审批员批准/拒绝，创建报价前要求客户与旅行社存在 `active` 关系，报价和订单带 `revision`（修订号）与 `payload_hash`（业务负载哈希），外部动作字段默认关闭。
- 交易执行门禁：`TRANSACTION_MODE`、总熔断开关和供应商预订、支付、退款、通知四类细粒度开关共同采用 fail-closed（故障或配置不全时默认拒绝）策略；即使配置门禁通过，后续仍必须校验租户权限、四眼审批、修订号、负载哈希、幂等和供应商适配器。
- 部署模板：提供 Docker（容器化平台）和 Caddy（反向代理服务器）配置示例，适合本地或自有服务器部署。

## 当前业务边界

- `agency_plan` 是旅行社顾问的方案规划分支，输出成熟路线、费用口径、服务说明和待核验项；它不会自动完成真实下单。
- `agency_quote`、`agency_order` 等表构成第一阶段交易数据与审计骨架，不等于供应商库存、支付网关、退款或履约已经连通。
- `/api/v1/agency` 当前提供 13 个内部操作，其中 6 个 `POST` 强制 `Idempotency-Key`（幂等键）。只有同一有效旅行社中 `active` 的 `approver` 岗位可读取已生成审核记录的订单快照，并将订单从 `pending_review` 决定为 `approved` 或 `review_rejected`；该只读权限不包含未提交订单或报价创建/发布，`owner`、`admin` 等角色也不能代替审批员，客户或审核发起人不能自审。
- `approved` 只代表旅行社内部审核通过，`external_action_enabled` 仍为 `false`；系统没有供应商预订、支付、退款或通知执行路由。
- 客户导入、客户同意和旅行社客户关系激活/停用 API 尚未实现；`agency_customer` 当前是持久化与校验边界，不是完整 CRM（客户关系管理）模块。
- `mock_checkout` 和 `generate_order_tool` 生成的 `ORDER-` 编号只用于演示规划结果确认，不是交易系统订单、合同或支付凭证。
- 当前没有真实供应商预订、库存锁定、收款、退款、出票、酒店确认或消息通知闭环，也没有供应商对账、财务清分和完整失败补偿。

详细边界见 [旅行社交易域](docs/架构与流程/agency-transaction-domain.md)。

## 仓库范围

这个公开仓库只保留可运行、可复现、可维护的最小公开项目集合：

- 源码：`app/`、`frontend/`、`scripts/`。
- 测试与夹具：`tests/`。
- 依赖和运行定义：`pyproject.toml`、`uv.lock`、`requirements.runtime.txt`、`Dockerfile`、`docker-compose.yml`、`deploy/`。
- 脱敏样例知识和评估数据：`data/documents/`、`data/evaluation/`。
- 正式技术文档：`docs/`。
- 配置样例：`.env.example`。

仓库不包含真实密钥、本地运行状态、数据库备份、向量库、日志、截图、私有部署坐标、聊天记录、未整理 Prompt（提示词）或私人准备资料。

## 数据库边界

项目使用 PostgreSQL 和 pgvector（PostgreSQL 向量扩展）。仓库保存的是数据库模型、初始化脚本和配置样例，不保存真实数据库实例。

- 本地或服务器数据库应放在 Docker volume（容器数据卷）或托管数据库中。
- 真实业务数据、备份和 dump（数据库导出文件）不进入 Git（分布式版本控制系统）。
- 对外只提交 `.env.example`，真实 `.env` 文件保留在本地或服务器。

初始化数据库：

```powershell
uv run python -m scripts.init_db
```

从样例知识初始化 RAG 向量库：

```powershell
uv run python -m scripts.init_rag
```

生成的 `data/vectorstore/` 和 `data/vectorstore_internal/` 已被忽略，不应提交。

## 快速启动

前置条件：

- Python `>=3.12`
- Node.js（用于前端校验脚本）
- PostgreSQL + pgvector 和 Redis，或 Docker Compose（容器编排工具）
- `uv` Python 包管理器

安装依赖：

```powershell
uv sync
```

创建本地配置：

```powershell
Copy-Item .env.example .env
```

根据本地环境填写 `.env` 中的模型、数据库、Redis 和可选外部 API（应用程序接口）配置。

启动后端：

```powershell
uv run python main.py
```

前端可以直接打开 `frontend/zhixing.html`，也可以通过 Docker 中的 Caddy 服务托管。

## Docker 部署

先根据 `.env.example` 创建 `.env`，再启动服务：

```powershell
docker compose up -d --build
```

Compose（容器编排配置）包含：

- `backend`：后端服务。
- `postgres`：PostgreSQL 数据库。
- `redis`：Redis 缓存。
- `caddy`：静态前端和反向代理。

数据库和 Redis 数据保存在 Docker volume 中，不应提交到仓库。

## 本地验证

常用检查命令：

```powershell
uv run python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
uv run python -m pytest -q
```

RAG 召回评测：

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

旅行社交易域的 PostgreSQL（关系型数据库）迁移、约束和并发测试使用专用测试库：

```powershell
$env:ZHIXING_TEST_POSTGRES_DSN = "postgresql://travel_user:change-me@127.0.0.1:5432/zhixing_test"
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py
```

数据库名必须包含独立的 `test` 或 `ci` 段；测试会创建并删除随机 schema（数据库命名空间），不得连接 staging（预生产）或 production（生产）数据库。GitHub Actions（GitHub 自动化流水线）的 `PostgreSQL Transaction Integration` job 使用一次性 PostgreSQL 17 service（服务容器）执行这组测试。需要真实 LLM（大语言模型）、MCP 服务或外部 API 的其他集成测试仍单独标记，不属于默认快速回归。

## 文档入口

先读 [docs/README.md](docs/README.md)。常用入口：

- [架构速览](docs/架构与流程/architecture-overview.md)
- [规划模式边界](docs/架构与流程/planning-mode-boundary.md)
- [旅行社交易域](docs/架构与流程/agency-transaction-domain.md)
- [RAG 演示与评测指南](docs/RAG与知识库/rag-demo-evaluation-guide.md)
- [评估体系](docs/评估与验收/evaluation-system.md)
- [部署模板](docs/部署与运行/deployment-readiness.md)
- [前端报告体验](docs/前端与演示/frontend-report-experience.md)

## 安全边界

- 不提交 `.env`、生产密钥、API key（接口密钥）、数据库备份、生成的向量库或运行日志。
- 私有部署域名、IP（互联网协议地址）、SSH（安全外壳协议）信息保留在本地或私有 CI（持续集成）配置中。
- 样例路线模板只用于演示和开发验证，不代表真实库存、保证成团或锁价。
- 外部服务不可用时，系统应明确说明待核验或降级原因，不能编造车票、机票、酒店库存或真实报价。
- `TRANSACTION_MODE=disabled`、`ZHIXING_REAL_PAYMENT_ORDER_DISABLED=true` 和四类外部动作开关为默认安全口径；在供应商适配、审批绑定、幂等、补偿、对账和目标环境验收完成前不得开启真实执行。
