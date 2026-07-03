# Docs Index（文档索引）

This directory contains formal project documentation for the public repository. Local handoff notes, raw issue logs, historical run evidence, prompt drafts, chat records and local-only preparation artifacts are intentionally kept outside Git.

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
- Stage change summary: `前端与演示/stage-change-summary-2026-06-03.md`

## Public Documentation Boundary

- Keep formal architecture, deployment, testing, frontend and evaluation documentation in Git.
- Keep restricted deployment coordinates, local evidence snapshots, raw logs, database dumps, generated vector stores and local-only drafts out of Git.
- Productized RAG route templates are demo catalog data. They do not represent real inventory, guaranteed group availability or locked pricing.
