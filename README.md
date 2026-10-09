# 知行旅行规划器 / ZhiXing Travel Planner

知行是一套面向旅行顾问的 AI 旅行规划应用，支持需求澄清、路线匹配、交通与住宿查询、预算整理和报告交付，并提供旅行社客户、门店、报价与内部订单管理 API。

后端使用 FastAPI、LangChain 和 LangGraph，以单个 Travel Agent 配合阶段中间件推进对话，按需调用目的地 Router 和交通 Coordinator。RAG 提供公开目的地知识与旅行社样例知识，MCP 接入天气、搜索、地图、铁路、航班和酒店等外部服务。PostgreSQL 保存业务数据、会话、检查点和长期记忆；Redis 用于会话锁、缓存、限流和短期运行状态。

## 功能

- **双工作流规划**：自由规划按目的地、交通、住宿、餐饮、行程和预算逐项确认；省心方案按需求确认、产品匹配、方案草案、用户微调和报告交付推进。
- **流式对话**：SSE 返回模型文本、工具事件、结构化报告和超时提示；首轮通过本地快路径完成规划方式分流。
- **知识与工具查询**：公开知识和旅行社样例包含路线模板、报价规则、风险、SOP 和报告标准；MCP 服务支持独立降级。
- **结构化报告**：后端生成 `report_data`，前端展示行程、预算、地图、方案依据及待核验项，支持复制摘要和导出 HTML。
- **客户与门店管理**：支持潜客登记、指定账户认领、客户同意记录、激活与停用、主顾问分配、客户转店和门店停业清场。权限按旅行社、门店、岗位与当前顾问关系校验。
- **内部交易管理**：支持报价草稿、发布与接受，订单草稿、提交审核和专职审批员决定；人工取消案件支持分岗结果登记、独立对账与异常恢复。
- **工程验证与部署**：提供专项测试、RAG 评测、运行验收和发布检查脚本，以及 Docker Compose、Caddy 部署配置。

当前已实现规划交付及旅行社内部业务管理，业务迁移 head 为 `0008`。真实供应商预订、支付、退款和通知尚未接入；订单 `approved` 表示内部审核通过。规划演示中的 `ORDER-` 编号和 `mock_checkout` 用于方案确认，正式内部订单由交易 API 创建。样例路线与估算预算需在实际业务中核验。权限、状态机、认领与同意、幂等及数据库约束见 [旅行社客户与交易域](docs/架构与流程/agency-transaction-domain.md)。

## 目录

| 路径 | 内容 |
|---|---|
| `app/` | API、Agent、业务服务、RAG、报告与评估 |
| `frontend/` | 对话与报告页面 |
| `scripts/` | 初始化、评测、验证和发布工具 |
| `tests/` | 测试与夹具 |
| `alembic/` | 业务数据库迁移 |
| `data/documents/`、`data/evaluation/` | 脱敏样例知识与评估数据 |
| `docs/` | 技术文档与运行手册 |
| `deploy/` | 服务器部署脚本 |

依赖由 `pyproject.toml`、`uv.lock` 和 `requirements.runtime.txt` 管理。仓库提供 `.env.example`；真实配置、业务数据、数据库备份、生成的向量库和运行日志保留在本地或服务器。

## 快速启动

需要 Python `>=3.12`、`uv`、PostgreSQL + pgvector 和 Redis。Node.js 用于前端验证；也可用 Docker Compose 启动依赖服务。

安装依赖并创建配置：

```powershell
uv sync
Copy-Item .env.example .env
```

在 `.env` 中填写模型、数据库、Redis 和可选外部 API 配置。真实交易默认使用 `TRANSACTION_MODE=disabled`、`ZHIXING_REAL_PAYMENT_ORDER_DISABLED=true`，供应商预订、支付、退款和通知开关保持关闭。

初始化业务数据库、检查点与记忆存储，并从样例知识建立 RAG 向量库：

```powershell
uv run python -m scripts.init_db
uv run python -m scripts.init_rag
```

生成的 `data/vectorstore/` 和 `data/vectorstore_internal/` 已加入忽略规则。数据库放在 Docker volume 或托管数据库中。

启动后端：

```powershell
uv run python main.py
```

前端可直接打开 `frontend/zhixing.html`，也可由 Docker 中的 Caddy 托管。

## Docker 部署

准备好 `.env` 后执行：

```powershell
docker compose up -d --build
```

Compose 包含 `backend`、`postgres`、`redis` 和 `caddy`，数据库与 Redis 数据保存在 Docker volume 中。服务器发布、迁移、备份和回滚步骤见 [部署指南](docs/部署与运行/deployment-readiness.md)。

## 验证

常用本地检查：

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

旅行社业务域的迁移、约束与并发集成测试使用专用 PostgreSQL 测试库：

```powershell
$env:ZHIXING_TEST_POSTGRES_DSN = "postgresql://travel_user:change-me@127.0.0.1:5432/zhixing_test"
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_customer_claim_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py tests\test_agency_cancellation_postgres_integration.py tests\test_agency_branch_transfer_closure_postgres_integration.py
```

数据库名须含独立的 `test` 或 `ci` 段。测试会创建并删除随机 schema，请使用隔离测试库。需要真实 LLM、MCP 或外部 API 的集成测试单独标记，不纳入默认快速回归。

已记录的 CI 基线：

| 迁移版本 | 提交与运行 | 默认测试 | PostgreSQL 17 集成测试 |
|---|---|---|---|
| `0008` | [`c574649`](https://github.com/apearlinspring/langgraph-travel-planner/commit/c5746496203f628fe9a93a91ebb998c910c2a920) · [30606856484](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30606856484) | `1878 passed, 58 deselected` | 六文件 `34 passed`：交易 3、客户生命周期 5、认领 5、门店权限 2、取消 10、转店/关店 9 |
| `0007` | [`e17b97d`](https://github.com/apearlinspring/langgraph-travel-planner/commit/e17b97d82c24b7f5271973cc8f18e884124b7d6b) · [30602058425](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30602058425) | `1841 passed, 49 deselected` | 五文件 `25 passed` |
| `0005 -> 0006` | [`b8b8bea`](https://github.com/apearlinspring/langgraph-travel-planner/commit/b8b8bea29477b472c942b7df40e8da6e9dbf05ab) · [30551146157](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30551146157) | `1738 passed, 39 deselected` | 四文件 `15 passed` |
| `0004` | [`20ff715`](https://github.com/apearlinspring/langgraph-travel-planner/commit/20ff71592096dfb4fc718cef050832a745bfe174) · [30534862434](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434) | `1713 passed, 34 deselected` | `10 passed` |

这些运行覆盖一次性 CI 数据库中的迁移与集成路径。目标环境仍需复验迁移、恢复、并发锁等待及外部依赖。完整验收要求见 [评估体系](docs/评估与验收/evaluation-system.md) 和 [改进路线图](docs/项目总览/agent-ai-app-improvement-roadmap.md)。

## 文档

[文档索引](docs/README.md) 按主题列出完整入口，常用文档包括：

- [架构速览](docs/架构与流程/architecture-overview.md)
- [规划模式](docs/架构与流程/planning-mode-boundary.md)
- [旅行社客户与交易域](docs/架构与流程/agency-transaction-domain.md)
- [客户关系授权技术告知 v1](docs/架构与流程/customer-consent-notice-v1.md)
- [RAG 演示与评测指南](docs/RAG与知识库/rag-demo-evaluation-guide.md)
- [前端报告体验](docs/前端与演示/frontend-report-experience.md)
- [部署指南](docs/部署与运行/deployment-readiness.md)
