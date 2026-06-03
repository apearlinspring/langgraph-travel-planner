# Docs Index（文档索引）

This directory contains formal project documentation for the public repository. Local handoff notes, raw issue logs, historical run evidence, prompt drafts, chat records and personal preparation materials are intentionally kept outside Git.

## Directory Map

| Directory | Purpose | Start Here |
|---|---|---|
| `项目总览/` | Capability map and high-level project positioning. | `项目总览/project-capability-map.md` |
| `架构与流程/` | Architecture, workflow state, planning boundaries, model switching and session consistency. | `架构与流程/architecture-overview.md` |
| `RAG与知识库/` | RAG（检索增强生成）runtime contract, vector store readiness, retrieval evaluation and demo explanation. | `RAG与知识库/rag-demo-evaluation-guide.md` |
| `评估与验收/` | Evaluation system, acceptance gates, live runner and pre-deployment validation. | `评估与验收/evaluation-system.md` |
| `部署与运行/` | Local runtime, database readiness, MCP（模型上下文协议）health and deployment templates. | `部署与运行/deployment-readiness.md` |
| `前端与演示/` | Project demo flow and frontend report experience. | `前端与演示/project-demo-pack.md` |
| `治理与可观测/` | Approval, tool governance, runtime budget, observability and loop protection. | `治理与可观测/runtime-governance.md` |

## Recommended Reading

- Project capability map: `项目总览/project-capability-map.md`
- Architecture overview: `架构与流程/architecture-overview.md`
- Planning mode boundary: `架构与流程/planning-mode-boundary.md`
- Planning guardrails: `架构与流程/planning-guardrails.md`
- RAG demo and evaluation: `RAG与知识库/rag-demo-evaluation-guide.md`
- RAG retrieval result: `RAG与知识库/rag-retrieval-evaluation.md`
- Evaluation system: `评估与验收/evaluation-system.md`
- Deployment template: `部署与运行/deployment-readiness.md`
- Frontend report experience: `前端与演示/frontend-report-experience.md`
- Stage change summary: `前端与演示/stage-change-summary-2026-06-03.md`

## Public Documentation Boundary

- Keep formal architecture, deployment, testing, frontend and evaluation documentation in Git.
- Keep private deployment coordinates, local evidence snapshots, raw logs, database dumps, generated vector stores and personal preparation materials out of Git.
- Productized RAG route templates are demo catalog data. They do not represent real inventory, guaranteed group availability or locked pricing.
