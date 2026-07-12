# Docs Index（文档索引）

This directory contains several kinds of public project documentation: current contracts and status, operational runbooks and templates, and selected dated evidence snapshots. Raw private evidence, deployment coordinates, prompt drafts, chat records, local-only preparation artifacts, and local collaboration directories such as `历史轮次/` and `问题记录/` remain outside Git.

## Current Wording Rules（当前口径规则）

- 当前代码、当前测试和重新生成的机器报告优先于历史截图、旧讲解稿和带日期的验收记录。
- 主执行链路是“单个 Travel Agent + `StepConfigMiddleware` + 状态迁移工具”；目的地 Router 和交通 Coordinator 是按需调用的嵌套能力。交通 Coordinator 直接调用航班、高铁、自驾查询工具，不存在再分发给三个交通方式子 Agent 的运行层。
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
| `架构与流程/` | Architecture, workflow state, planning boundaries, model switching and session consistency. | `架构与流程/architecture-overview.md` |
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
- Planning guardrails: `架构与流程/planning-guardrails.md`
- RAG demo and evaluation: `RAG与知识库/rag-demo-evaluation-guide.md`
- RAG release checklist: `RAG与知识库/rag-release-checklist.md`
- Travel multimodal data source plan: `RAG与知识库/travel-multimodal-data-source-plan.md`
- RAG retrieval result: `RAG与知识库/rag-retrieval-evaluation.md`
- RAG vector store readiness: `RAG与知识库/rag-vectorstore-readiness.md`
- Evaluation system: `评估与验收/evaluation-system.md`
- AgentOps replay and versioning: `治理与可观测/agentops-replay-versioning.md`
- Production readiness gap: `部署与运行/production-readiness-gap.md`
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
