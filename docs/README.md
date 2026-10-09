# 文档索引

这里按项目能力、架构、知识库、验收和部署整理技术文档。初次阅读可先看 [项目能力](项目总览/project-capability-map.md) 和 [架构速览](架构与流程/architecture-overview.md)，运行项目时从 [部署指南](部署与运行/deployment-readiness.md) 开始。

当前主链路为单个 Travel Agent、阶段中间件和状态迁移工具，支持自由规划与省心方案。旅行社 API 已覆盖客户与门店生命周期、报价、内部订单审核、人工取消结果登记和独立对账；真实预订、支付、退款和通知尚未接入。业务状态和权限的详细定义集中在 [旅行社客户与交易域](架构与流程/agency-transaction-domain.md)。

## 按主题阅读

| 主题 | 内容 | 入口 |
|---|---|---|
| 项目总览 | 功能、代码定位、验证入口与工程计划 | [项目能力](项目总览/project-capability-map.md)、[改进路线图](项目总览/agent-ai-app-improvement-roadmap.md) |
| 架构与流程 | Agent 编排、状态、规划模式、旅行社业务域及会话一致性 | [架构速览](架构与流程/architecture-overview.md) |
| RAG 与知识库 | 检索、样例知识、向量库初始化及召回评测 | [演示与评测指南](RAG与知识库/rag-demo-evaluation-guide.md) |
| 评估与验收 | 报告质量、工具治理、运行预算和真实链路验收 | [评估体系](评估与验收/evaluation-system.md) |
| 部署与运行 | 运行配置、迁移、发布、备份、监控与回滚 | [部署指南](部署与运行/deployment-readiness.md) |
| 前端与演示 | 演示流程、报告展示及导出契约 | [演示包](前端与演示/project-demo-pack.md) |
| 治理与可观测 | 审批、工具审计、运行指标与循环保护 | [运行治理](治理与可观测/runtime-governance.md) |

## 架构与业务

- [TravelState 状态契约](架构与流程/state-schema-contract.md)
- [阶段 Prompt 规则](架构与流程/step-prompt-rule-inventory.md)
- [规划模式](架构与流程/planning-mode-boundary.md)
- [规划约束](架构与流程/planning-guardrails.md)
- [旅行社客户与交易域](架构与流程/agency-transaction-domain.md)
- [客户关系授权技术告知 v1](架构与流程/customer-consent-notice-v1.md)

## 知识库与评估

- [RAG 演示与评测](RAG与知识库/rag-demo-evaluation-guide.md)
- [召回评测结果](RAG与知识库/rag-retrieval-evaluation.md)
- [向量库就绪检查](RAG与知识库/rag-vectorstore-readiness.md)
- [RAG 发布清单](RAG与知识库/rag-release-checklist.md)
- [多模态数据源计划](RAG与知识库/travel-multimodal-data-source-plan.md)
- [评估体系](评估与验收/evaluation-system.md)
- [AgentOps 回放与版本记录](治理与可观测/agentops-replay-versioning.md)

## 部署、发布与运维

- [生产化差距](部署与运行/production-readiness-gap.md)
- [数据库迁移检查](部署与运行/db-migration-readiness.md)
- [M1 受控试运行状态](部署与运行/m1-controlled-trial-status.md)
- [M1 资源申请包](部署与运行/m1-resource-request-pack.md)
- [M1 执行输入清单](部署与运行/m1-execution-input-gap-checklist.md)
- [发布候选冻结](部署与运行/m1-release-candidate-freeze.md)
- [公开发布检查](部署与运行/m1-public-release-closure.md)
- [首次部署预演](部署与运行/m1-first-deploy-dry-run.md)
- [生产部署输入](部署与运行/production-deployment-inputs.md)
- [M1 上线清单](部署与运行/m1-launch-checklist.md)
- [M1 受控试运行手册](部署与运行/m1-controlled-trial-runbook.md)
- [PostgreSQL / Redis 运维](部署与运行/postgres-redis-ops-runbook.md)
- [外部 API 故障处理](部署与运行/external-api-failure-runbook.md)
- [备份与恢复](部署与运行/backup-restore-runbook.md)
- [监控与告警](部署与运行/monitoring-alerting-runbook.md)
- [事故响应与回滚](部署与运行/incident-response-rollback-runbook.md)
- [安全发布与密钥轮换](部署与运行/security-release-key-rotation-runbook.md)
- [M1 验收记录模板](部署与运行/m1-acceptance-record-template.md)

相关工具：

- [私有执行工作目录准备](../scripts/prepare_m1_private_execution_workspace.py)
- [执行输入检查](../scripts/check_m1_execution_input_gap.py)
- [服务器只读探测](../scripts/collect_live_server_probe.py)
- [服务器环境变量清单](../scripts/render_server_env_checklist.py)
- [服务器配置文件检查](../scripts/check_server_env_file.py)
- [发布冻结记录生成](../scripts/render_release_candidate_freeze_record.py)
- [发布冻结签核检查](../scripts/check_release_candidate_freeze_signoff.py)
- [发布包与 manifest 构建](../scripts/build_release_artifact.py)
- [服务器首次部署](../deploy/first-deploy.sh)

## 前端与演示

- [前端报告体验](前端与演示/frontend-report-experience.md)
- [结构化报告交付契约](前端与演示/report-data-delivery-contract.md)
- [2026-06-03 阶段变更记录](前端与演示/stage-change-summary-2026-06-03.md)

## 文档与验证记录

| 类型 | 用途 |
|---|---|
| 当前契约与状态 | 描述当前实现；状态结论注明适用 commit 和复核时间 |
| 运行手册与模板 | 说明执行步骤、检查项与记录格式 |
| 带日期的验证记录 | 保存指定版本、模型、配置和环境下的结果 |
| 历史归档与问题记录 | 追溯设计和故障过程 |

出现差异时，以当前源码和重新执行的测试为准。离线检索、向量库就绪、真实 Agent 验收及目标环境发布分别记录结果；`dry-run` 记录执行计划，`blocked` 记录未满足的前置条件。默认测试与 PostgreSQL 集成测试的历史数字见 [README 验证记录](../README.md#验证)。

公开文档保留正式契约、手册和脱敏摘要。真实密钥、部署坐标、业务数据、原始运行记录及本地草稿保留在仓库外；本地 `历史轮次/` 和 `问题记录/` 不属于公开文档目录。
