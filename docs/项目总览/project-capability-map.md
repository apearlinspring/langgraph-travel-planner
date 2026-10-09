# 项目能力与实现索引

知行面向旅行顾问的需求澄清、方案准备与报告交付，并逐步补充客户、门店和内部交易管理。本文列出已实现模块、代码位置、验证入口和后续工作。

## Agent 能力编排与状态机

| 模块 | 实现 | 主要代码 |
|---|---|---|
| 对话入口 | FastAPI 提供 SSE 聊天接口；首轮在本地解析基础事实、询问规划方式，后续进入 Agent | `app/main.py`、`app/api/v1/chat.py`、`app/core/intent.py` |
| 主 Agent | 单个 Travel Agent 配合 `StepConfigMiddleware` 与迁移工具推进阶段 | `app/agents/handoffs/travel_agent.py`、`app/core/middleware.py`、`app/tools/state_transition.py` |
| 双工作流 | `free_planning` 用 `current_step` 管理八个阶段；`agency_plan` 用 `agency_step` 管理五个阶段 | `app/core/state.py`、`app/core/workflow.py`、`app/agents/handoffs/step_config.py` |
| 嵌套能力 | 目的地 Router 通过 `StateGraph` 处理攻略和天气；交通 Coordinator 直接编排航班、高铁和自驾查询工具 | `app/agents/routers/destination_router.py`、`app/agents/subagents/transport_coordinator.py` |
| 阶段工具 | 按工作流与阶段开放工具；省心方案有独立白名单，实时交通或酒店查询按用户需求临时开放 | `app/core/middleware.py`、`app/agents/handoffs/step_config.py` |
| 外部查询 | MCP 接入天气、搜索、地图、铁路、航班和酒店；客户端提供服务级缓存、重试和降级 | `app/mcp_core/client.py`、`app/tools/mcp_tools.py` |
| RAG | 公开知识与内部样例分别检索；内部样例按产品、SOP、报价、风险和报告标准组织，支持目的地级路线匹配 | `app/tools/rag_tools.py`、`app/rag/`、`data/documents/internal/` |
| 报告 | 状态与工具结果汇总为 `report_data`，包含预算来源、行程、风险与待核验项 | `app/reports/builder.py`、`app/agency/pricing_rules.py` |
| 前端交付 | 消费 `report_data`，展示规划模式、预算、依据、地图，支持复制摘要与导出 HTML | `frontend/app.js`、`frontend/zhixing.html` |

自由规划逐项确认需求和交通、住宿等选择；省心方案侧重成熟路线匹配与微调。工具调用结果写入结构化状态，再由报告模块汇总。预算区分工具价格、规则估算、兜底估算和待核验项；正式报价需通过交易 API 显式创建。

外部查询失败时保留降级原因与待核验项。普通验收场景默认要求工具失败数、失败率与 fallback 数为 0，两个专门降级场景允许有界失败。前端目前为单页原型，完整业务后台、构建治理和可访问性验证仍需补充。

## 旅行社业务

| 模块 | 实现与状态 | 主要代码 |
|---|---|---|
| 客户与门店生命周期 | 24 个操作，其中 15 个 POST 要求 `Idempotency-Key`；覆盖门店授权、潜客、认领、同意、激活/停用、顾问分配、转店与关店 | `app/api/v1/agency_customers.py`、`app/models/agency_customer_lifecycle.py`、`app/models/agency_customer_identity.py` |
| 报价、订单与审核 | 13 个操作，其中 6 个 POST 要求幂等键；保存金额、有效期、快照、`revision`、`payload_hash` 与审核记录 | `app/agency/transaction_service.py`、`app/agency/order_review_service.py`、`app/models/agency_transaction.py`、`app/models/agency_order_review.py` |
| 人工取消与对账 | 9 个操作，其中 5 个 POST 要求幂等键和预期修订号；登记平台外人工结果，审计岗位从脱敏队列取得待核验记录 | `app/agency/cancellation_service.py`、`app/agency/cancellation_support.py`、`app/api/v1/agency_cancellations.py`、`app/models/agency_cancellation.py` |
| 转店与关店 | `0008` 增加原子客户转店、门店清场及关闭就绪检查，保留历史业务门店 | `app/agency/customer_branch_transfer.py`、`app/agency/branch_administration.py`、`alembic/versions/20260731_0008_agency_branch_transfer_closure.py` |
| 数据库约束 | 约束对象绑定、修订号、状态迁移、只追加记录与提交一致性；API 在事务提交成功后返回成功 | `alembic/versions/`、`app/api/v1/agency_common.py` |

客户链路为潜客登记、指定已有账户认领、客户同意、关系激活与顾问分配。认领凭证为 256-bit、24 小时有效、可撤销且单次使用；数据库只存 SHA-256 摘要，原始 token 仅在首次签发提交成功后返回。客户端读取固定技术告知并提交预期版本与摘要，服务端生成规范化同意记录。报价与订单要求 `secure_claim + server_canonical` 的有效客户关系和有效门店。客户撤回同意或停用时，同一事务结束顾问分配并收口内部交易。

`owner/admin` 有旅行社全域权限；门店岗位需有效授权，顾问还需当前客户分配。订单送审和取消建案要求存在排除发起人及订单客户的合格专职审批员；撤权时为每笔待办保留合格替代人。审批采用专职角色，owner/admin 不代替审批员。门店权限在应用层实现，尚未使用 PostgreSQL RLS。

取消范围由服务端从锁定的订单、支付和履约账本派生，建案后冻结相关账本。无外部暴露的订单可在审批后直接内部取消；有暴露时依次登记供应商/财务人工结果，再由不同审计人员核验最新结果为 `matched`。失败、未知或不匹配进入 `manual_intervention`，恢复后可重新登记。锁序为 `customer -> branch/auth -> order -> payment/fulfillment -> case`。

`owner/admin` 可将 `active`、`inactive` 或 `blocked` 客户原子转到同旅行社的 `active` 门店，保留历史邀请、同意、分配和交易的原门店；活跃客户可同时指定目标主顾问。门店按 `active -> inactive -> closed` 推进：停业期停止新业务，允许拒绝旧审核与完成取消清场；全部当前客户、待邀请、有效分配/授权、待审核及开放交易归零后才能关闭，`closed` 不可逆。

订单 `approved` 是内部审核状态。当前尚未接入真实供应商预订/取消、支付/退款或通知，也未实现平台 Approval 与业务对象绑定、LangGraph `interrupt/resume`、回调验签和跨系统补偿。批量导入、邀请投递、客户 PII 档案、真实身份核验、法律级同意及跨门店经理双边审批是后续业务工作。详细状态、权限和迁移定义见 [旅行社客户与交易域](../架构与流程/agency-transaction-domain.md)。

## 治理与可观测性

| 模块 | 已有实现 | 验证重点 |
|---|---|---|
| HITL 与平台审批 | 敏感动作记录、审批事件、角色权限与 readiness | `app/core/approval.py`、`app/api/v1/approvals.py`；与旅行社内部审核分别管理 |
| 运行观测 | `first_token_seconds`、总耗时、工具调用/失败/fallback、token 估算与审计摘要 | `app/core/observability.py`、`app/evaluation/runtime_metrics.py`；首个片段可能为固定 ACK，需结合总耗时分析 |
| 验收门禁 | `acceptance_gate` 汇总报告、RAG、工具、运行预算与内部证据 | `app/evaluation/acceptance_gate.py`、`scripts/run_evaluation_scenarios.py` |
| CI/CD | 编译、知识库校验、测试收集、本地回归、前端验证及 PostgreSQL 17 集成测试 | `.github/workflows/ci.yml`、`.github/workflows/staging-smoke.yml` |

当前观测以轮次摘要为主。完整分布式 trace、APM、多次运行稳定性、工具轨迹评估及 Badcase 归因还需完善。

截至 2026-07-03，仓库外记录过 M1 受控试运行的部署、健康检查、数据库/缓存、恢复演练、短窗口探针和单轮 live chat。该记录对应当时版本；含 `0008` 的候选仍需目标环境迁移、恢复、并发锁与发布复验。运行状态见 [M1 受控试运行](../部署与运行/m1-controlled-trial-status.md)，待办见 [生产化差距](../部署与运行/production-readiness-gap.md)。

## 验证入口

本地专项检查：

```powershell
uv run python -m pytest -q tests/test_destination_router.py tests/test_flight_query_tool.py tests/test_workflow_maintainability.py tests/test_step_prompt_rendering.py tests/test_chat_report_metadata.py tests/test_intent_detection.py
uv run python -m pytest -q tests/test_mcp_client_config_unit.py tests/test_report_contract_module.py tests/test_report_quality_evaluation.py tests/test_runtime_metrics.py tests/test_ci_workflows.py
uv run python -m pytest -q tests/test_agency_transaction_models.py tests/test_agency_order_review_service.py tests/test_agency_cancellation_api.py tests/test_agency_cancellation_service.py tests/test_agency_cancellation_models.py tests/test_agency_cancellation_migration.py tests/test_agency_branch_transfer_closure_api.py tests/test_agency_branch_transfer_closure_service.py tests/test_agency_branch_transfer_closure_migration.py tests/test_branch_drain_authorization.py tests/test_approval_governance.py
uv run python scripts/validate_rag_knowledge.py
uv run python scripts/evaluate_rag_retrieval.py --json
node scripts/verify_frontend_report_renderer.js
node scripts/verify_frontend_browser_regression.js
```

### 本地纯讲解路径

生成演示包并检查文档与计划：

```powershell
uv run python scripts/build_project_demo_pack.py --output .runtime/project-demo-pack
uv run python -m pytest tests/test_project_demo_pack.py -q
uv run python scripts/run_evaluation_scenarios.py --acceptance-smoke --dry-run
```

### acceptance-smoke

启动真实后端后执行 preflight 和 smoke：

```powershell
uv run python main.py
uv run python scripts/run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
uv run python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime/acceptance-smoke
uv run python scripts/check_runtime_readiness.py --target production --json
```

`dry-run` 输出执行计划；真实链路检查需要模型、向量库与所选外部服务。验证摘要注明 commit、模型、配置和运行时间，原始记录保留在仓库外。PostgreSQL 专用测试库命令见 [README](../../README.md#验证)。

### 前端报告路径

用同一份 `report_data` 检查展示、复制摘要与导出，命令为上方的报告渲染和浏览器回归脚本。交付契约见 [报告与前端](../前端与演示/report-data-delivery-contract.md)。

## 已记录的规模与结果

| 日期或版本 | 结果 |
|---|---|
| 2026-06-23 第一轮 RAG | 19 场景、21 文档、3 个公开安全场景 |
| 2026-06-23 第二轮 RAG | 25 场景、24 文档；公开目的地为西安、杭州、厦门、桂林；9 个混合库安全场景 |
| 2026-07-11 RAG | 26 场景、25 文档、5 个公开目的地、10 个混合库安全场景，新增南京 |
| 2026-07-12 RAG | 27 场景、26 文档、6 个公开目的地、11 个混合库安全场景，新增北京银发样例 |
| `0008` CI | [`c574649`](https://github.com/apearlinspring/langgraph-travel-planner/commit/c5746496203f628fe9a93a91ebb998c910c2a920) · [30606856484](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30606856484)：默认 `1878 passed, 58 deselected`；PostgreSQL 17 六文件 `34 passed` |

RAG 数字来自本地 BM25/metadata 离线评测；向量库与在线 Agent 另行验收。CI 使用一次性数据库。更早的数据库基线与触发器修正记录见 [改进路线图](agent-ai-app-improvement-roadmap.md)。

## 当前边界与改进路线

| 环节 | 工具与文档 |
|---|---|
| 资源与配置 | [资源申请包](../部署与运行/m1-resource-request-pack.md)；`render_m1_resource_request.py --markdown`、`check_m1_launch_inputs.py --template`、`check_m1_launch_inputs.py --input-json <private-workdir>/m1-launch-inputs.local.json --json`、`render_server_env_checklist.py --template`、`check_server_env_file.py --env-file <deploy-dir>/shared/.env --json` |
| 发布冻结 | [候选冻结](../部署与运行/m1-release-candidate-freeze.md)；`check_release_candidate_freeze.py`、`render_release_candidate_freeze_record.py`、`check_release_candidate_freeze_signoff.py --check-current-worktree`；记录 include/defer/remove、验证结果、风险与负责人签核 |
| 本地部署预演 | [首部署预演](../部署与运行/m1-first-deploy-dry-run.md)；`check_m1_first_deploy_dry_run.py --json` 检查目标输入、本机工具、工作区、Compose 与发布范围，未提交改动会阻断 |
| 发布制品 | `build_release_artifact.py` 从干净 `HEAD` 生成 archive 与 manifest，记录 commit、tree、tracked file count 和 sha256 |
| 服务器发布 | `deploy/first-deploy.sh` 默认 dry-run，`--archive-sha256` 校验上传包，`--execute --start-services` 解压 release、切换 current 并启动 Compose；运行数据保存在 shared |
| 运维检查 | [PostgreSQL / Redis 手册](../部署与运行/postgres-redis-ops-runbook.md)；`collect_live_server_probe.py` 通过 SSH 只读采样系统、容器、health、向量库文件与模拟订单路由 |

环境检查只报告变量名、状态及脱敏摘要。服务器探测脚本使用 LF 和二进制 stdin，避免 Windows CRLF 导致 bash 的 `set: -^M: invalid option`。

工程计划与实施历史见 [改进路线图](agent-ai-app-improvement-roadmap.md)。既有工作包括工具 URL query 脱敏、MCP 服务目录、状态与 Prompt 契约、报告与前端回归、RAG readiness、AgentOps 记录，以及资源申请、发布冻结、部署、备份、监控、回滚和最终 go/no-go 工具。下一阶段重点是目标环境复验、运行稳定性、前端工程化及真实业务适配。
