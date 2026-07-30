# Docs Index（文档索引）

This directory contains several kinds of public project documentation: current contracts and status, operational runbooks and templates, and selected dated evidence snapshots. Raw private evidence, deployment coordinates, prompt drafts, chat records, local-only preparation artifacts, and local collaboration directories such as `历史轮次/` and `问题记录/` remain outside Git.

## Current Wording Rules（当前口径规则）

- 当前代码、当前测试和重新生成的机器报告优先于历史截图、旧讲解稿和带日期的验收记录。
- 产品目标业务形态是“旅行社经营与交付工作台”。当前代码完成的是规划交付链路、门店与客户生命周期控制面及第一阶段交易数据/控制面骨架，不得把目标定位扩写成当前已经具备完整 CRM、真实供应链或资金交易能力。
- 主执行链路是“单个 Travel Agent + `StepConfigMiddleware` + 状态迁移工具”；目的地 Router 和交通 Coordinator 是按需调用的嵌套能力。交通 Coordinator 直接调用航班、高铁、自驾查询工具，不存在再分发给三个交通方式子 Agent 的运行层。
- `agency_plan` 是旅行社方案规划分支，不是交易状态；`agency_quote`、`agency_order` 等持久化模型也不等于真实预订、支付、退款或履约已经接通。`mock_checkout` 与 `generate_order_tool` 只提供演示编号和确认流程，不是订单系统。
- `/api/v1/agency` 的交易子集覆盖报价草稿、发布、客户接受、订单草稿、提交审核和旅行社内部批准/拒绝，共 13 个操作、6 个 `POST`；门店与客户生命周期子集另有 20 个操作、12 个 `POST`，覆盖门店、门店角色授权、线下潜客登记、目标账户认领邀请、客户认领、固定技术告知读取、本人同意、激活/停用、顾问分配和客户事件。
- 门店权限是应用层行级授权，不是 PostgreSQL RLS（行级安全策略）。`owner`、`admin` 为旅行社全域角色；门店经理、顾问和审批员必须持有同一有效门店的有效授权，顾问还必须是客户当前主顾问。门店至少有一名有效专职 `approver` 才能提交订单，提交后不得撤掉最后一名审批员；只有该角色可以处理本门店审核。批准还要求客户保持 `active + granted`，客户停用后保留中的审核只能拒绝，且拒绝前不能重新激活客户关系；`owner`、`admin` 等角色不能代替，客户或审核发起人不能自审。
- 内部 `approved` 只表示订单通过旅行社审核，不能扩写成供应商预订、支付、退款、通知或履约已执行；`external_action_enabled` 仍为 `false`。交易域审核也没有绑定平台 `/api/v1/approvals` 或 LangGraph HITL（人类在环）恢复链路。
- 创建报价要求 `agency_customer` 已完成 `secure_claim`（安全认领）、关系为 `active`、同意为 `granted`、同意证据来源为 `server_canonical` 且所属门店有效。客户管理角色可为指定已有平台账户签发 256-bit 高熵、24 小时过期、可撤销、单次使用的认领凭证，数据库只保存 token（令牌）的 SHA-256 摘要，只有该已登录目标账户能完成认领；同一旅行社同一目标账户同一时刻最多一条待认领邀请。原始 token 只在首次签发事务已提交的响应返回，幂等重放不再返回；丢失时必须撤销并重新签发。当前仍没有批量导入、邀请投递或客户通知。
- 认证用户通过 `GET /api/v1/agency/customer-consent-notice` 读取固定 [客户关系授权技术告知 v1](架构与流程/customer-consent-notice-v1.md) 的 Markdown、版本、文档摘要、证据 schema（模式）和渠道；提交决定时必须回传预期版本/文档摘要，服务端发现告知已变化则拒绝，但客户端不能上传任意 evidence hash（证据哈希）。服务端为每次决定生成 append-only（只追加）同意记录。存量直接绑定和旧客户端哈希分别明确标记为 `legacy_direct`、`legacy_client_hash`，不会冒充安全认领或服务端证据；原账户仍可拒绝/撤回，升级认领时旧同意投影会重置，原 `active` 关系会先停用并收口分配/内部交易，再由客户重新 `grant` 和激活。客户关系模型未引入姓名、电话、证件和联系人等 PII（个人可识别信息）字段；这些技术记录也不能证明真实身份核验、告知充分或法律合规。客户跨门店转移及门店停用/关闭 API 尚未实现。
- `blocked` 客户保持失败关闭，不能经普通停用/激活接口解除；门店状态数据库门禁要求先结束有效授权、分配、客户关系和未终结交易，正式门店关闭工作流仍待实现。
- 活跃客户拒绝/撤回同意或关系停用时，会在同一数据库事务中结束当前顾问分配并收口内部交易：`draft`/`offered` 和无订单的 `accepted` 报价内部取消；未执行的 `draft`/`approved` 订单内部取消；`pending_review` 保留给审批员拒绝且不能再批准，拒绝前客户关系也不能重新激活；异常或可能已有外部状态的订单进入 `cancellation_pending` 或保留人工处理标记。这不代表供应商取消、退款或通知已经完成。
- `0004` 数据库触发器固化报价/订单绑定，复验客户/门店、报价有效期和订单/报价金额、币种、快照一致性，强制 `revision` 每次恰好加一、状态只按白名单迁移并保持外部动作关闭；订单与审核终态在事务提交时成对校验。写路径采用 `customer -> branch -> quote/order` 锁序，授权写持有门店/成员共享锁以防撤权 TOCTOU（检查与使用时序差）竞态。
- `0005` 新增客户认领邀请、只追加同意记录和 provenance（来源）字段，并用数据库门禁保护认领终态、同意记录不可修改及新交易的安全客户前置条件；`0006` 是当前 Alembic（数据库迁移工具）业务 head，只修正共享延迟约束触发器对不同表 `NEW` 字段的访问。实现提交 [`b8b8bea`](https://github.com/apearlinspring/langgraph-travel-planner/commit/b8b8bea29477b472c942b7df40e8da6e9dbf05ab) 的 [运行 30551146157](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30551146157) 已得到默认 `1738 passed, 39 deselected` 和 PostgreSQL 17 `15 passed`；这是 CI-only（仅持续集成环境）证据，仍不能替代目标环境迁移结论。
- 旅行社领域 API 只有在事务提交和 DEFERRABLE（提交时延迟校验）数据库约束通过后才发送成功响应；提交失败不会先返回虚假的 `2xx`。
- 真实供应商预订、支付、退款和通知当前尚未接入，并由 `TRANSACTION_MODE=disabled`、总熔断开关和细粒度动作开关默认阻断。任何未来放行都必须同时满足租户权限、四眼审批、`revision`（修订号）、`payload_hash`（业务负载哈希）、幂等、补偿和供应商适配器检查。
- 审批模块当前提供策略、持久化请求、只追加事件、角色权限和 readiness（就绪状态）语义；尚未实现 LangGraph `interrupt/resume`（中断/恢复）执行闭环。`approval_persistence_ready` 只表示审批与审计可持久化，`hitl_closed_loop` 当前始终为 `false`，不能扩写成“审批后自动恢复原 Agent 动作”。
- acceptance（验收）门禁主要检查报告、证据、工具治理、可观测摘要和运行预算；普通场景默认还要求工具失败数、失败率和 fallback 数为 0，只有专门降级场景可显式放宽。历史 `passed` 只代表当时单次场景门禁结果；它不等于最优工具轨迹、稳定成功率、当前工作树通过或完整生产就绪。
- 带日期、commit（提交）或仓库外私有证据的文档都是快照。代码、模型、配置、知识库或部署环境变化后，必须重新验证才能使用“当前通过”“当前就绪”等表述。

## Document Classes and Precedence（文档分类与优先级）

1. **Current contract / status（当前契约或状态）**：以当前代码、测试和明确标注最后复核时间及适用 commit 的状态文档为准。
2. **Runbook / template（运行手册或模板）**：描述如何检查和记录结果；模板里的 `passed` 示例不代表当前环境已经通过。
3. **Dated evidence snapshot（日期化证据快照）**：只证明文档所写日期、commit、模型、配置和环境下的一次运行，不能自动代表当前工作树。
4. **Historical archive / problem record（历史归档或问题记录）**：用于追溯设计和故障，不作为当前架构、生产就绪或安全能力的依据。

发生冲突时，当前源码与重新执行的测试结果优先；当前状态文档必须绑定适用版本和证据摘要。通用 runbook、旧验收报告、阶段总结和历史讲解稿不得覆盖当前事实。

## Directory Map

| Directory | Purpose | Start Here |
|---|---|---|
| `项目总览/` | Capability map, high-level project positioning and engineering improvement roadmap. | `项目总览/project-capability-map.md` |
| `架构与流程/` | Architecture, workflow state, planning boundaries, agency customer/transaction domain, model switching and session consistency. | `架构与流程/architecture-overview.md` |
| `RAG与知识库/` | RAG（检索增强生成）runtime contract, vector store readiness, retrieval evaluation and demo explanation. | `RAG与知识库/rag-demo-evaluation-guide.md` |
| `评估与验收/` | Evaluation system, acceptance gates, live runner and pre-deployment validation. | `评估与验收/evaluation-system.md` |
| `部署与运行/` | Local runtime, database readiness, MCP（模型上下文协议）health and deployment templates. | `部署与运行/deployment-readiness.md` |
| `前端与演示/` | Project demo flow and frontend report experience. | `前端与演示/project-demo-pack.md` |
| `治理与可观测/` | Approval, tool governance, runtime budget, observability and loop protection. | `治理与可观测/runtime-governance.md` |

Local workspaces may contain ignored `历史轮次/` and `问题记录/` directories for collaboration and traceability. They are not part of the public directory map or the minimum public project set; any dated fact reused in public documentation must be re-verified and rewritten as a sanitized snapshot.

## Recommended Reading

- Project capability map: `项目总览/project-capability-map.md`
- Agent / AI app improvement roadmap: `项目总览/agent-ai-app-improvement-roadmap.md`
- Architecture overview: `架构与流程/architecture-overview.md`
- TravelState contract: `架构与流程/state-schema-contract.md`
- Step prompt rule inventory: `架构与流程/step-prompt-rule-inventory.md`
- Planning mode boundary: `架构与流程/planning-mode-boundary.md`
- Agency customer and transaction domain: `架构与流程/agency-transaction-domain.md`
- Customer consent technical notice v1: `架构与流程/customer-consent-notice-v1.md`
- Planning guardrails: `架构与流程/planning-guardrails.md`
- RAG demo and evaluation: `RAG与知识库/rag-demo-evaluation-guide.md`
- RAG release checklist: `RAG与知识库/rag-release-checklist.md`
- Travel multimodal data source plan: `RAG与知识库/travel-multimodal-data-source-plan.md`
- RAG retrieval result: `RAG与知识库/rag-retrieval-evaluation.md`
- RAG vector store readiness: `RAG与知识库/rag-vectorstore-readiness.md`
- Evaluation system: `评估与验收/evaluation-system.md`
- AgentOps replay and versioning: `治理与可观测/agentops-replay-versioning.md`
- Production readiness gap: `部署与运行/production-readiness-gap.md`
- DB migration readiness: `部署与运行/db-migration-readiness.md`
- M1 controlled trial status: `部署与运行/m1-controlled-trial-status.md`
- M1 resource request pack: `部署与运行/m1-resource-request-pack.md`
- M1 execution input gap checklist: `部署与运行/m1-execution-input-gap-checklist.md`
- M1 private execution workspace preparer: `../scripts/prepare_m1_private_execution_workspace.py`
- M1 execution input gap checker: `../scripts/check_m1_execution_input_gap.py`
- PostgreSQL / Redis operations runbook: `部署与运行/postgres-redis-ops-runbook.md`
- Live server probe collector: `../scripts/collect_live_server_probe.py`
- Server env checklist renderer: `../scripts/render_server_env_checklist.py`
- Server env file checker: `../scripts/check_server_env_file.py`
- M1 release candidate freeze: `部署与运行/m1-release-candidate-freeze.md`
- M1 public release closure: `部署与运行/m1-public-release-closure.md`
- Release candidate freeze record renderer: `../scripts/render_release_candidate_freeze_record.py`
- Release candidate freeze signoff checker: `../scripts/check_release_candidate_freeze_signoff.py`
- M1 first deploy dry run: `部署与运行/m1-first-deploy-dry-run.md`
- Release artifact manifest builder: `../scripts/build_release_artifact.py`
- M1 server first deploy script: `../deploy/first-deploy.sh`
- Production deployment inputs: `部署与运行/production-deployment-inputs.md`
- M1 launch checklist: `部署与运行/m1-launch-checklist.md`
- M1 controlled trial runbook: `部署与运行/m1-controlled-trial-runbook.md`
- External API failure runbook: `部署与运行/external-api-failure-runbook.md`
- Backup and restore runbook: `部署与运行/backup-restore-runbook.md`
- Monitoring and alerting runbook: `部署与运行/monitoring-alerting-runbook.md`
- Incident response and rollback runbook: `部署与运行/incident-response-rollback-runbook.md`
- Security release and key rotation runbook: `部署与运行/security-release-key-rotation-runbook.md`
- M1 acceptance record template: `部署与运行/m1-acceptance-record-template.md`
- Deployment template: `部署与运行/deployment-readiness.md`
- Frontend report experience: `前端与演示/frontend-report-experience.md`
- Structured report delivery contract: `前端与演示/report-data-delivery-contract.md`
- Dated stage change snapshot: `前端与演示/stage-change-summary-2026-06-03.md`

## Public Documentation Boundary

- Keep current architecture, deployment, testing, frontend and evaluation contracts in Git, and label public templates, dated evidence and historical archives explicitly.
- Keep restricted deployment coordinates, local evidence snapshots, raw logs, database dumps, generated vector stores and local-only drafts out of Git.
- Productized RAG route templates are demo catalog data. They do not represent real inventory, guaranteed group availability or locked pricing.
- Branch/customer records, claim-token digests, server-canonical consent records, transaction tables, mock checkout and generated references are engineering evidence only. They do not prove real-world identity or legal consent, supplier booking, payment, refund, notification, ticket, hotel confirmation, contract or completed fulfillment.
