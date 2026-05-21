# Docs Index（文档索引）

本目录按功能拆分，便于新对话或新人先读索引，再进入对应专题。历史验收和历史方案保留在 `历史轮次/`，当前结论优先看 `评估与验收/` 和 `RAG与知识库/`。

## 目录说明

| 目录 | 用途 | 建议先读 |
|---|---|---|
| `项目总览/` | 项目能力地图、新会话知识库、文档说明。 | `项目总览/project-capability-map.md` |
| `架构与流程/` | 主链路、状态机、模型切换、规划边界和会话一致性。 | `架构与流程/architecture-overview.md` |
| `RAG与知识库/` | RAG（检索增强生成）运行契约、向量库 readiness（就绪检查）、召回评测和演示说明。 | `RAG与知识库/rag-demo-evaluation-guide.md` |
| `评估与验收/` | acceptance-core（核心验收）、acceptance-smoke（验收冒烟测试）、真实链路 runbook（运行手册）和评估体系。 | `评估与验收/acceptance-core-report.md` |
| `部署与运行/` | 本地、Docker（容器化平台）和线上服务更新指南。 | `部署与运行/deployment-readiness.md` |
| `前端与演示/` | 面试演示脚本、演示包、前端报告体验。 | `前端与演示/project-demo-pack.md` |
| `治理与可观测/` | 审批、工具治理、运行预算、观测指标和循环防护。 | `治理与可观测/runtime-governance.md` |
| `问题记录/` | 已知问题和补充问题日志。 | `问题记录/problem-log.md` |
| `历史轮次/` | 历史方案、历史验收和历史集成记录，仅作追溯参考。 | `历史轮次/round3-live-acceptance.md` |

## 当前优先入口

- 面试演示：`前端与演示/demo-script.md`
- 双工作流和模式边界：`架构与流程/planning-mode-boundary.md`
- 规划守卫与快路径边界：`架构与流程/planning-guardrails.md`
- RAG 演示解释：`RAG与知识库/rag-demo-evaluation-guide.md`
- RAG 召回结果：`RAG与知识库/rag-retrieval-evaluation.md`
- 景点票价与预约供应商接入：`RAG与知识库/scenic-ticket-supplier-integration.md`
- 线上更新：`部署与运行/deployment-readiness.md`
- 核心验收证据：`评估与验收/acceptance-core-report.md`

## 文档边界

- 不提交 `.env`、`.runtime/`、`.venv/`、真实向量库、真实密钥或个人信息。
- 历史文档中的结论如果和当前验收文档冲突，以 `评估与验收/acceptance-core-report.md` 和最新分支说明为准。
- 产品化 RAG 目录中的路线样板只用于演示和未来库存服务接入前的能力验证，不代表真实库存、成团或锁价。
