# Agent / AI 应用工程化改进路线图

本文记录知行的工程改进计划、模块分工、接口变更和实施历史。当前已具备阶段化规划、RAG、MCP、结构化报告、前端交付，以及旅行社客户、门店和内部交易管理。下一阶段重点是维护性、运行稳定性和目标环境验收。

带日期的实施记录对应当时版本与环境。当前状态以源码、复跑结果和注明 commit 的验收记录为准。

## 1. 改进目标

- 明确状态、工具、知识库、报告与前端之间的契约。
- 扩充评测场景，补充重复运行、失败归因与成本观测。
- 按模块划分改动范围，降低并行维护和合并成本。
- 完成冻结候选的迁移、发布、备份、告警和回滚复验。
- 在接入真实业务适配器前补齐审批绑定、幂等、回调和补偿。

## 2. 当前工作项

| 方向 | 已有基础与待办 | 优先级 | 验证入口 |
|---|---|---|---|
| 架构与状态 | API、中间件、状态迁移及部分前端文件较大；按状态契约评估职责拆分，并同步阶段、Prompt、工具和进度展示 | P0 | 架构文档、状态与流程测试 |
| RAG 与评估 | 离线样本规模仍小；扩展语料与场景，分别记录离线召回、真实向量库和在线 Agent 结果 | P0 | `scripts/evaluate_rag_retrieval.py --json` |
| 工具治理 | 已有白名单、错误脱敏和失败审计；继续统一未知工具策略、超时、重试与降级 | P0 | 工具治理文档、专项测试与故障样例 |
| 报告与前端 | `report_data` 已用于渲染和导出；统一前端与评估契约，补充组件化、构建治理和可访问性验证 | P0 / P1 | 报告契约测试、前端验证脚本 |
| AgentOps | 已有轮次指标和工具审计；补充 trace、成本、Prompt/模型版本记录及回放 | P1 | 运行指标测试、评估摘要与版本记录 |
| 客户与门店 | `0008` 已覆盖认领、服务端同意、分配、转店、停业清场与关闭；补目标环境迁移/恢复、存量数据和并发锁复验，后续设计跨门店双边审批 | P0 | `c574649` / Actions `30606856484`：默认 `1878 passed, 58 deselected`；PostgreSQL 17 六文件 `34 passed` |
| 取消与对账 | 已有取消案件、分岗人工结果、独立审计及最新结果核验；补目标环境复验，真实适配器需要平台审批绑定、回调验签、幂等、补偿和自动对账 | P0 | 取消域专项测试、PostgreSQL 17 集成测试 |
| 部署与运行 | 已有 readiness、发布模板及历史 M1 记录；为冻结候选重新执行 preflight、smoke/core 和运维验证 | P1 | [运行状态](../部署与运行/m1-controlled-trial-status.md)、部署文档与目标环境摘要 |
| Smoke 验收 | 收集器已汇总 health、M1 gate 与 acceptance smoke；待目标环境执行及负责人复核 | P0 | `scripts/collect_m1_smoke_evidence.py --json` |
| 备份恢复 | 已检查备份声明、dump 元数据和 catalog；待新鲜备份、隔离恢复、恢复后校验及签核 | P0 | `scripts/collect_backup_restore_drill_evidence.py --json` |
| 监控告警 | 已有监控声明检查；待真实投递、指标留存、值班升级、成本和备份告警演练 | P0 | `scripts/collect_monitoring_alerting_evidence.py --json` |
| 事故与回滚 | 已有响应/回滚记录入口；待目标环境实际回滚、health/gate/smoke 复验与复盘 | P0 | `scripts/collect_incident_rollback_evidence.py --json` |
| 最终发布判定 | 已聚合 M1 gate、smoke、恢复、告警和回滚；为同一 commit 和时间窗收齐输入及发布负责人签核，必需项 `not_checked` 会阻断 | P0 | `scripts/collect_m1_go_no_go_evidence.py --json` |
| 资源与首部署 | 已有申请模板、本地 dry-run、manifest 和服务器脚本；待负责人确认服务器/数据/运维输入，生成冻结发布包并执行服务器预演和切换 | P0 | `render_m1_resource_request.py`、`check_m1_first_deploy_dry_run.py`、`build_release_artifact.py`、`deploy/first-deploy.sh` |
| 运行依赖与镜像 | runtime 依赖已拆分，策略与执行记录检查已实现；待镜像重建、体积/时长记录、启动回归、目标环境构建与签核 | P0 | `check_runtime_dependency_scope.py`、`check_production_image_build_policy.py`、`prepare_production_image_build_execution.py`、`check_production_image_build_execution_record.py` |
| 生产化 | 密钥、数据、安全、可观测、高可用与业务履约仍有待办 | P0 | [生产化差距](../部署与运行/production-readiness-gap.md) |

业务状态和数据库约束集中在 [旅行社客户与交易域](../架构与流程/agency-transaction-domain.md)。客户转店保留历史业务门店，门店按 `active -> inactive -> closed` 收口；权限在应用层实现。当前取消流程记录平台外人工结果，真实预订、支付、退款与通知尚未接入。

## 3. 模块分工

并行维护时先确定写入范围，共享入口文档与验收摘要在合并时统一更新。

| 模块 | 主要范围 | 交付物 |
|---|---|---|
| 项目总览 | `docs/README.md`、`docs/项目总览/`、验收摘要 | 路线图、导航、合并记录 |
| RAG 与评估 | `app/rag/`、`app/evaluation/`、`data/evaluation/`、`docs/RAG与知识库/` | 场景、评测结果和环境前置条件 |
| Agent 与状态 | `app/core/`、`app/agents/handoffs/`、`docs/架构与流程/` | 状态契约、流程规则和职责拆分 |
| 工具治理 | `app/mcp_core/`、`app/tools/`、`app/utils/security.py`、`docs/治理与可观测/` | 白名单、脱敏、schema/version 与失败审计 |
| 旅行社业务 | `app/agency/`、`app/api/v1/agency_*`、`app/models/agency_*`、`alembic/versions/` | 门店、客户、交易权限、迁移及专项测试 |
| 报告与前端 | `app/reports/`、`frontend/`、`docs/前端与演示/` | 报告契约、渲染与导出验证 |
| 验收与发布 | `docs/评估与验收/`、`docs/部署与运行/` | 验收矩阵、发布记录和运行手册 |

## 4. 合并顺序

1. 记录基线与各模块改动范围。
2. 明确 RAG 评测规模和真实环境前置条件。
3. 对齐状态、流程、Prompt 与阶段工具。
4. 更新工具白名单、脱敏和失败审计。
5. 对齐 `report_data`、前端展示与导出。
6. 更新验收、演示和部署文档。
7. 复核测试结果、契约变更和剩余问题。

## 5. 接口变更记录

新增或调整接口、状态和输出契约时，在这里记录影响范围，并同步代码与测试。

| 日期 | 变更类型 | 契约 | 影响范围 | 状态 |
|---|---|---|---|---|
| 2026-06-23 | 文档计划 | 本路线图只新增文档，不改运行时 API、数据库、前端交互或测试契约 | 文档入口、协作分工、验收定义 | 已记录 |
| 2026-06-23 | 评估输出 | RAG 召回评测 JSON / Markdown 增加 `coverage_summary`、`visibility_recall` 和 `safety_pass_rate` | `app/evaluation/rag_retrieval.py`、RAG 评测文档、RAG 评测测试 | 已完成 |
| 2026-06-23 | 安全脱敏 | `redact_sensitive_text()` 覆盖 URL query 中的 `key`、`api_key`、`access_token` 等敏感参数 | MCP 错误格式化、工具审计摘要、治理文档和相关测试 | 已完成 |
| 2026-06-23 | 状态契约 | 明确 `TravelState`、`current_step`、`agency_step`、`STEP_STATE_FIELDS` 和报告交付字段边界 | 状态契约文档、工作流维护性测试 | 已完成 |
| 2026-06-23 | Prompt 规则 | 把阶段 Prompt 规则、工具开放边界、报告、报价和库存约束整理为规则清单 | Prompt 规则清单、阶段配置渲染测试 | 已完成 |
| 2026-06-23 | 报告交付 | 明确 `report_data` 到前端渲染、复制摘要和导出 HTML 的交付契约 | 前端交付契约文档、报告渲染脚本、浏览器回归脚本 | 已完成 |
| 2026-06-23 | RAG readiness | 明确离线召回、安全门、真实 Chroma 向量库、acceptance preflight 和 live smoke/core 的证据层级 | 向量库 readiness 文档、RAG 发布 checklist | 已完成 |
| 2026-06-23 | AgentOps 证据链 | 明确 turn 级观测、工具审计、readiness/preflight/acceptance 摘要和版本记录建议 | AgentOps 轻量回放文档、观测文档入口 | 已完成 |
| 2026-06-23 | 生产化差距 | 从真实生产系统视角拆分 M0/M1/M2/M3 和 P0/P1/P2 缺口，并补充 M1 上线总清单、受控试运行输入清单、执行手册、外部 API 故障手册、备份恢复手册、监控告警手册、安全发布/密钥轮换手册和验收记录模板 | 生产化差距清单、M1 上线总清单、生产部署输入清单、M1 runbook、外部 API runbook、备份恢复 runbook、监控告警 runbook、安全发布 runbook、验收记录模板、公开文档入口 | 已完成 |
| 2026-06-23 | M1 输入门禁 | 新增非密钥上线输入检查脚本，覆盖范围、服务器、部署模式、密钥负责人、外部 API、数据、验收、备份、监控、成本和事故负责人；输出变量名与检查状态 | `scripts/check_m1_launch_inputs.py`、`.env.example`、`docker-compose.yml`、M1 checklist、M1 runbook、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 部署总门禁 | 新增聚合检查脚本，串起公开发布边界、M1 非密钥输入、Compose 配置和 runtime readiness；默认执行静态检查 | `scripts/check_m1_deployment_gate.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 验收记录 | 新增脱敏记录生成器，把 deployment gate 输出整理成 Markdown 验收记录；默认打印脱敏记录 | `scripts/render_m1_acceptance_record.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 备份恢复前置 | 新增备份/恢复 readiness 脚本，检查备份目标、绝对目录、仓库外路径、保留策略和 RAG 恢复策略；显式开启时验证备份目录可写 | `scripts/check_backup_restore_readiness.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 监控告警前置 | 新增监控/告警/cost readiness 脚本，检查监控供应商、告警渠道和每日成本预算；显式开启时探测公开 health endpoint；接入 M1 deployment gate | `scripts/check_monitoring_alerting_readiness.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 安全发布前置 | 新增安全发布 readiness 脚本，检查密钥托管、轮换周期、泄露响应、凭据状态、浏览器 key 来源限制和高风险动作关闭声明；接入 M1 deployment gate | `scripts/check_security_release_readiness.py`、`.env.example`、`docker-compose.yml`、security runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 外部 API 前置 | 新增外部 API readiness 脚本，检查必需供应商、可选供应商状态、配额预算、控制台负责人、支持渠道、降级策略和 timeout/retry 策略；接入 M1 deployment gate | `scripts/check_external_api_readiness.py`、`.env.example`、`docker-compose.yml`、external API runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 服务器 preflight | 新增目标服务器 preflight 脚本，检查服务器基线、部署目录、公网 URL、站点地址、域名、出口 IP、端口、TLS、反向代理和 Docker 状态；目标环境可显式探测 Docker、部署目录和 health URL | `scripts/check_server_preflight_readiness.py`、`.env.example`、`docker-compose.yml`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 smoke 证据 | 新增部署后 smoke 证据收集器，默认只输出执行计划；显式开启时汇总公开 health、M1 deployment gate 和 acceptance smoke 的脱敏摘要，输出脱敏结果 | `scripts/collect_m1_smoke_evidence.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板、部署模板和测试 | 已完成 |
| 2026-06-23 | 备份恢复演练证据 | 新增备份恢复演练证据收集器，默认只输出执行计划；显式开启时检查备份目录、最新 dump 元数据、`pg_restore --list` catalog 可读性和恢复演练声明，输出脱敏元数据 | `scripts/collect_backup_restore_drill_evidence.py`、`.env.example`、`docker-compose.yml`、backup runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 监控告警证据 | 新增监控告警证据收集器，默认只输出执行计划；显式开启时收集 health/readiness 投递声明、核心指标监控、成本、备份和日志脱敏状态，实际告警投递由运维验证 | `scripts/collect_monitoring_alerting_evidence.py`、`.env.example`、`docker-compose.yml`、monitoring runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 事故/回滚证据 | 新增事故响应和回滚演练证据收集器，默认只输出执行计划；显式开启时收集负责人、回滚目标、回滚后 health/gate/smoke 和事故复盘状态，实际回滚由运维执行 | `scripts/collect_incident_rollback_evidence.py`、`.env.example`、`docker-compose.yml`、incident runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 go/no-go 总判定 | 新增最终证据汇总器，默认只输出计划态；显式纳入证据后按发布规则判定 `go_for_m1_controlled_trial`、`conditional_go`、`no_go` 或 `not_checked`，其中请求 section 的 `not_checked` 直接 `no_go` | `scripts/collect_m1_go_no_go_evidence.py`、M1 checklist、M1 runbook、部署输入文档、生产差距清单、验收记录模板、部署模板、能力地图和测试 | 已完成 |
| 2026-06-23 | M1 资源申请包 | 新增资源申请包生成器和正式文档，汇总服务器、DNS/TLS、运行配置、密钥变量、RAG 数据、外部 API、验收、备份、监控和回滚准备项；输出变量名与检查状态 | `scripts/render_m1_resource_request.py`、`docs/部署与运行/m1-resource-request-pack.md`、README、M1 checklist、M1 runbook、部署输入文档、部署模板、生产差距清单和测试 | 已完成 |
| 2026-06-23 | M1 首部署 dry-run | 新增首次部署预演脚本和正式文档，本地检查目标输入、git/ssh/scp/docker 工具、git 工作区、Compose 模板和公开边界，并输出远端部署命令计划 | `scripts/check_m1_first_deploy_dry_run.py`、`docs/部署与运行/m1-first-deploy-dry-run.md`、README、deployment readiness、M1 checklist、runbook、验收模板、生产差距清单和测试 | 已完成 |
| 2026-06-23 | M1 服务器首部署脚本 | 新增 `deploy/first-deploy.sh`，在服务器侧执行 release/current/shared 发布模型；默认 dry-run，显式 `--execute --start-services` 才解压、切换 current 和启动 Compose | `deploy/first-deploy.sh`、deployment readiness、M1 runbook、M1 checklist、资源申请包、验收模板、生产差距清单和测试 | 已完成 |
| 2026-06-23 | M1 发布包 manifest | 新增 `scripts/build_release_artifact.py`，默认 dry-run，显式执行时从干净 Git `HEAD` 生成 archive 和 manifest，记录 commit、tree、tracked file count 和 archive `sha256` | `scripts/build_release_artifact.py`、deployment readiness、M1 runbook、M1 checklist、资源申请包、验收模板、生产差距清单和测试 | 已完成 |
| 2026-07-03 | 生产运行依赖门禁 | 新增 `scripts/check_runtime_dependency_scope.py`，静态检查 `pyproject.toml`、`requirements.runtime.txt` 和 `Dockerfile`，检测生产镜像中的测试框架、多模态深度校验、本地 embedding 和 GPU/model 重依赖，发现混入时返回 `blocked` | `scripts/check_runtime_dependency_scope.py`、`tests/test_runtime_dependency_scope.py`、deployment readiness、runtime environment 和脚本入口测试 | 已完成门禁和首次依赖拆分；仍需在下一次镜像构建后记录体积、构建时长和线上滚动验证 |
| 2026-07-03 | 生产 runtime 依赖拆分 | 将 `pytest` / `pytest-asyncio` 移入 dev dependency group，将 `faster-whisper` / `imageio-ffmpeg` / `sentence-transformers` 移入 optional profile，新增 `requirements.runtime.txt`，生产 Dockerfile 不再安装完整 `requirements.txt` | `pyproject.toml`、`uv.lock`、`requirements.runtime.txt`、`Dockerfile`、`scripts/check_release_candidate_freeze.py` | 依赖拆分已完成；镜像重建与切换待执行 |
| 2026-07-03 | 生产镜像构建策略门禁 | 新增 `scripts/check_production_image_build_policy.py`，静态检查镜像源、远程后台构建、超时、日志/PID、镜像 ID/大小、健康探针和禁止清理边界，并检查 `deploy/update-runtime-image.sh` 与 Dockerfile 契约 | `scripts/check_production_image_build_policy.py`、`tests/test_production_image_build_policy.py`、脚本入口测试、deployment readiness 和 runtime environment | 已完成策略门禁；尚未执行远程后台 build 和镜像体积验收 |
| 2026-07-03 | 生产镜像构建执行记录门禁 | 新增 `scripts/check_production_image_build_execution_record.py`，校验真实远程后台 build 后的私有记录：后台 wrapper、PID/log、runtime-only 输入、镜像 ID/大小、磁盘与运行时数据安全、`compose ps` 和 health 探针 | `scripts/check_production_image_build_execution_record.py`、`tests/test_production_image_build_execution_record.py`、M1 checklist、deployment readiness 和 runtime environment | 已完成执行记录门禁；真实远程 build 仍待单独执行并填入私有记录 |
| 2026-07-03 | 生产镜像远程后台构建启动器 | 新增 `scripts/prepare_production_image_build_execution.py`，默认 dry-run 生成脱敏执行计划；显式 `--execute --approval-token APPROVE_PRODUCTION_IMAGE_BUILD_EXECUTION` 才通过 SSH 启动远程后台 `deploy/update-runtime-image.sh` | `scripts/prepare_production_image_build_execution.py`、`tests/test_production_image_build_execution_preparer.py`、M1 checklist、deployment readiness 和 runtime environment | 已完成 dry-run/execute 封装；远程构建待执行审批 |
| 2026-07-03 | Compose project 固定 | 根据 M1 正式切换中暴露的固定容器名冲突，把 `first-deploy.sh` 和 `update-runtime-image.sh` 默认 Compose project 固定为 `langgraph-travel-planner`，并允许通过 `ZHIXING_COMPOSE_PROJECT_NAME` 覆盖 | `deploy/first-deploy.sh`、`deploy/update-runtime-image.sh`、生产镜像策略门禁、首部署脚本契约测试、运维复盘记录和部署文档 | 已完成脚本与文档修复；真实服务器已用最小修复完成本轮 backend/caddy 切换，并补齐 rollout、health smoke、capacity、operations review 和 rerun go/no-go 证据；下一次发布应直接走脚本固定 project |
| 2026-07-03 | 限流 burst 探针 | 将 `collect_rate_limit_live_probe.py` 从串行短窗口采样扩展为可配置并发 burst，避免慢串行请求跨过限流窗口而漏采 429；M1 go/no-go 和私有证据 workflow 透传 `--rate-limit-concurrency` | `scripts/collect_rate_limit_live_probe.py`、`scripts/collect_m1_go_no_go_evidence.py`、`scripts/run_m1_private_live_evidence_workflow.py`、限流探针测试和部署文档 | 已完成；线上低风险 workflow 采用 160 次 / 16 并发采到 Redis rate-limit 的 200+429 证据并通过 |
| 2026-07-30 | 客户安全认领与服务端同意证据 | 移除公开直接绑定入口，新增面向指定已有账户的认领邀请签发/查询/撤销与已登录目标账户认领；原始 token 仅在首次签发提交成功后返回，幂等重放不返回，同一旅行社同 target 待邀请唯一。新增认证 notice GET，consent POST 回传预期版本/文档摘要，规范化 evidence 仍由服务端生成；`0005` 增加来源标记、legacy 升级重置与数据库不可变门禁，agency API 提交完成后才返回成功 | 客户生命周期 API、认领/同意服务、客户身份模型、`20260730_0005` 迁移、技术告知和专项测试 | 后续 `0006` 修正与 `0007` 候选已通过一次性 PostgreSQL 17 CI；目标环境迁移待验证 |
| 2026-07-30 | 客户一致性触发器修正 | 首次包含 `0005` 的 PostgreSQL 17 CI 暴露共享触发器在错误表行类型上访问 `NEW.target_user_id` / `NEW.status`；不修改 frozen `0005`，新增 `0006` 按 `TG_TABLE_NAME` 分支后再访问表专属字段 | `20260730_0006` 迁移、revision-frozen helper 和迁移契约测试 | [`b8b8bea`](https://github.com/apearlinspring/langgraph-travel-planner/commit/b8b8bea29477b472c942b7df40e8da6e9dbf05ab) / [Actions 30551146157](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30551146157) 已通过：默认 `1738 passed, 39 deselected`，PostgreSQL 17 `15 passed`；目标环境迁移仍待验证 |
| 2026-07-30 | 人工取消、补偿结果与独立对账 | 新增 9 个取消域操作、4 张强绑定表和 `0007` 门禁；服务端派生所需证据，专职审批，`booking_operator`/`finance` 分岗登记，脱敏结果队列向不同 `auditor` 暴露待办记录 ID 与对账状态，失败/未知/不匹配进入人工介入，最新结果可重做。外部动作开关保持关闭 | `app/agency/cancellation_service.py`、`cancellation_support.py`、取消 API/模型、`20260730_0007` 和专项测试 | [`e17b97d`](https://github.com/apearlinspring/langgraph-travel-planner/commit/e17b97d82c24b7f5271973cc8f18e884124b7d6b) / [Actions 30602058425](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30602058425) 已通过：默认 `1841 passed, 49 deselected`、PostgreSQL 17 `25 passed`；目标环境待验证；当前为人工结果登记流程 |
| 2026-07-31 | 客户转店与门店关闭 | 新增 owner/admin 专属的即时原子客户转店，可选目标门店主顾问，客户状态保持不变且历史业务记录不改门店；新增 `active -> inactive -> closed` 门店生命周期、聚合关闭 readiness 和清场授权。`inactive` 停止新业务但允许拒绝待审核订单和完成取消清场；`closed` 不可逆并要求全部关闭阻断项归零 | `app/agency/customer_branch_transfer.py`、`app/agency/branch_administration.py`、客户生命周期 API、`20260731_0008` 迁移和专项测试 | `c574649` / Actions `30606856484` 已验证默认 `1878 passed, 58 deselected` 与 PostgreSQL 17 六文件 `34 passed`；跨门店经理双边审批待设计；目标环境迁移/恢复与并发锁待复验 |


## 6. 推进记录

实施记录保留原日期、测试数字和版本引用，便于追溯改动。

| 日期 | 方向 | 实施内容 | 状态 | 结果与后续 |
|---|---|---|---|---|
| 2026-06-23 | RAG/Evaluation | 统一 RAG 评测规模、blocked / passed 语义、真实向量库验收要求和场景覆盖说明 | 已完成第一轮 | 第一轮 19 场景、21 文档、3 个公开安全场景；第二轮扩至 25 场景、24 文档、9 个公开安全场景。 |
| 2026-06-23 | Tool/Security | 检查 URL query key 脱敏、MCP 错误输出脱敏、未知工具策略和失败审计 | 已完成第一轮 | 已补 URL query 脱敏、MCP 错误脱敏与测试；未知工具全局默认策略留待专项回归后调整。 |
| 2026-06-23 | RAG/Evaluation 第二轮 | 扩充公开目的地样例，把公开安全负样本从西安扩到更多目的地 | 已完成 | 西安、杭州、厦门、桂林四个公开目的地；离线评测 25 场景、24 文档、9 个公开安全场景。 |
| 2026-07-11 | RAG/Evaluation 南京样例校准（历史快照） | 新增南京公开目的地样例和精确目的地消歧场景，更新离线召回报告与规模记录 | 已完成离线校准 | 该轮离线快照为 26 场景、25 文档、5 个公开目的地、10 个混合库安全场景。 |
| 2026-07-12 | RAG/Evaluation 北京银发样例校准 | 新增北京公开低强度、午休、无障碍/电梯和天气 Plan B 安全样例，补精确召回场景并复跑离线门禁 | 已完成离线校准 | 截至 2026-07-12 为 27 场景、26 文档、6 个公开目的地、11 个混合库安全场景；上一轮 26/25/5/10 保留为历史。 |
| 2026-07-26 | 旅行社客户生命周期与门店权限 | 新增 `0004` 门店、门店岗位授权、线下潜客关联、客户本人同意、激活/停用、主顾问分配和应用层范围查询；把报价、订单和内部审核绑定门店/客户关系，并增加客户停用内部交易收口、报价/订单数据库变更门禁、统一锁序与撤权并发保护 | 实现候选 [`20ff715`](https://github.com/apearlinspring/langgraph-travel-planner/commit/20ff71592096dfb4fc718cef050832a745bfe174) 已在 [Actions 30534862434](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434) 通过默认 `1713 passed, 34 deselected` 和 PostgreSQL 17 `10 passed`（3+5+2） | 一次性 CI 结果；目标环境迁移与恢复待验证。 |
| 2026-07-30 | 旅行社客户安全认领与同意证据 | 新增 256-bit 高熵、24 小时过期、可撤销、单次使用且只存 SHA-256 摘要的目标账户认领；同一旅行社同 target 待邀请唯一。认证客户端先读取固定告知再回传预期版本/摘要；服务端生成只追加规范化证据。legacy 认领会重置旧同意并先停用原 active 关系；新激活/报价/订单要求 `secure_claim + server_canonical`，提交失败不得先返回 `2xx` | `0005` 功能与 `0006` 触发器修正已由运行 `30551146157` 通过默认与 PostgreSQL 17 job 验证 | 认领和同意记录用于平台内审计；邀请投递、身份核验及目标环境迁移待补。 |
| 2026-07-30 | 旅行社人工取消与独立对账 | 为订单增加取消申请、专职审批、平台外人工供应商/财务结果登记、不同审计人员核验和人工介入恢复；`0007` 强制只追加、四眼制、最新结果匹配、订单/案件一致和外部动作关闭。案件 `requested_at` 记录申请创建，订单 `cancellation_requested_at` 仅在批准后进入取消处理时写入，订单 `cancelled_at` 只记录真正完成内部取消 | `e17b97d` / Actions `30602058425` 已验证默认 `1841 passed, 49 deselected` 与 PostgreSQL 17 `25 passed`；目标环境迁移仍待验证 | `completed` 包括无外部暴露订单审批后直接内部取消，以及所需最新人工结果独立匹配完成两条路径。 |
| 2026-07-31 | 旅行社客户转店与门店清场/关闭 | owner/admin 可把客户当前归属即时原子转到同旅行社 active 目标门店；`active`、`inactive`、`blocked` 客户可转移，历史分支记录保持不变，`active` 客户可选目标主顾问。门店先从 `active` 进入 `inactive` 清场期，停止新业务但保留拒绝待审核订单和取消收口能力；只有当前客户（含 `inactive`/`blocked`）、待邀请、有效分配/授权、待审核、开放报价/订单/取消案全部归零后才能不可逆 `closed` | `0008` 实现、API、服务、迁移和授权专项测试已完成一次性 CI 验证：`c574649` / Actions `30606856484`，默认 `1878 passed, 58 deselected`，PostgreSQL 17 六文件 `34 passed` | 转店保留历史业务门店；双边审批及目标环境迁移、恢复、并发锁验证待补。 |
| 2026-06-23 | Tool/Security 第二轮 | 补外部 MCP 服务目录、required / optional / degraded 策略表，并与 `SERVICE_DEFINITIONS` 对齐 | 已完成 | `required_when_declared` 只在所选验收场景声明必需时阻塞；服务目录记录变量名和状态。 |
| 2026-06-23 | Agent State/Architecture 第三轮 | 新增状态契约和 Prompt 规则清单，补双工作流轴、阶段字段、工具白名单和报告约束维护性测试 | 已完成 | `active_workflow` 决定读取 `current_step` 或 `agency_step`；静态配置、运行中间件与工具守卫共同约束阶段。 |
| 2026-06-23 | Report/Frontend 第四轮 | 新增 `report_data` 交付契约文档，补前端渲染、复制摘要、导出 HTML 和浏览器回归边界断言 | 已完成 | 完成结构化报告渲染、复制摘要与导出回归；前端保持单页原型。 |
| 2026-06-23 | RAG/AgentOps 第五轮 | 补真实向量库 readiness 发布矩阵、RAG release checklist 和 AgentOps 轻量回放与版本记录规范 | 已完成 | 分别记录离线召回、向量库和在线 Agent 结果；AgentOps 目前为轮次摘要复盘。 |
| 2026-06-23 | Production Gap 第六轮 | 新增生产化差距清单、M1 上线总清单、生产部署输入清单、M1 受控试运行 runbook、外部 API 故障 runbook、备份恢复 runbook、监控告警 runbook、安全发布/密钥轮换 runbook 和验收记录模板，列出受控试运行前的 P0 待办 | 已完成 | 上线待办涵盖密钥管理、备份恢复、集中观测、发布回滚、外部服务故障、用户告知及高风险动作审批。 |
| 2026-06-23 | Production Gap 第七轮 | 把 M1 非密钥输入从文档表格升级成 `check_m1_launch_inputs.py` 机器门禁，并接入 `.env.example`、Compose、上线清单、runbook 和验收记录模板 | 已完成 | 校验上线输入声明；资源可用性与真实链路由后续执行验证。 |
| 2026-06-23 | Production Gap 第八轮 | 新增 `check_m1_deployment_gate.py` 聚合门禁，汇总公开边界、M1 输入、Compose 配置和 runtime readiness，并支持目标环境后端验收检查 | 已完成 | 默认检查配置与声明；环境缺失时返回 `blocked`。 |
| 2026-06-23 | Production Gap 第九轮 | 新增 `render_m1_acceptance_record.py`，把聚合门禁结果转换为脱敏 M1 验收 Markdown，服务真实发布后的证据留档 | 已完成 | 把 gate 结果整理为记录，保留 `passed`、`blocked` 或 `degraded` 的实际状态。 |
| 2026-06-23 | Production Gap 第十轮 | 新增 `check_backup_restore_readiness.py`，把备份目标、备份目录、保留策略和 RAG 恢复策略纳入机器门禁，并接入 M1 deployment gate | 已完成 | 备份目标与策略检查；`--check-filesystem` 验证目录可写，恢复演练单独执行。 |
| 2026-06-23 | Production Gap 第十一轮 | 新增 `check_monitoring_alerting_readiness.py`，把监控供应商、告警渠道、成本预算和可选 health URL 探测纳入机器门禁，并接入 M1 deployment gate | 已完成 | 默认检查监控声明；`--check-health-url` 可探测 endpoint，告警投递另做演练。 |
| 2026-06-23 | Production Gap 第十二轮 | 新增 `check_security_release_readiness.py`，把密钥托管、轮换、泄露响应、凭据状态、来源限制和高风险动作关闭纳入机器门禁，并接入 M1 deployment gate | 已完成 | 校验密钥托管、轮换与动作关闭声明；有效性、撤销和供应商权限需现场核验。 |
| 2026-06-23 | Production Gap 第十三轮 | 新增 `check_external_api_readiness.py`，把必需/可选外部 API、配额预算、负责人、支持渠道、降级策略和 timeout/retry 策略纳入机器门禁，并接入 M1 deployment gate | 已完成 | 校验供应商、配额、负责人和失败策略声明；目标服务器实际调用另行验收。 |
| 2026-06-23 | Production Gap 第十四轮 | 新增 `check_server_preflight_readiness.py`，把目标服务器、部署目录、Docker、端口、TLS、反向代理和公网 health URL 纳入机器门禁，并接入 M1 deployment gate | 已完成 | 默认检查服务器声明，显式探测 Docker、目录和 health。 |
| 2026-06-23 | Production Gap 第十五轮 | 新增 `collect_m1_smoke_evidence.py`，把部署后 health、M1 gate 和 acceptance smoke 汇总成脱敏证据记录 | 已完成 | 默认 `not_checked`；显式 smoke 会调用网络服务并可能消耗模型或外部 API 预算。 |
| 2026-06-23 | Production Gap 第十六轮 | 新增 `collect_backup_restore_drill_evidence.py`，把备份目录、最新 PostgreSQL dump、`pg_restore --list` 和恢复演练声明收束成脱敏证据 | 已完成 | 默认 `not_checked`；检查 dump 与 catalog，隔离库恢复及恢复后 smoke 单独执行。 |
| 2026-06-23 | Production Gap 第十七轮 | 新增 `collect_monitoring_alerting_evidence.py`，把 health/readiness 告警投递、错误率/P95/工具失败/成本/备份/日志脱敏监控声明收束成脱敏证据 | 已完成 | 默认 `not_checked`；收集告警和监控声明，实际投递与长期留存另行验收。 |
| 2026-06-23 | Production Gap 第十八轮 | 新增 `collect_incident_rollback_evidence.py`，把事故负责人、回滚目标、回滚后复验和事故复盘声明收束成脱敏证据 | 已完成 | 默认 `not_checked`；整理回滚与复盘声明，实际回滚由运维执行，复验 smoke 显式开启。 |
| 2026-06-23 | Production Gap 第十九轮 | 新增 `collect_m1_go_no_go_evidence.py`，把 M1 gate、smoke、备份恢复、监控告警、事故回滚证据汇总为最终 `decision` | 已完成 | 默认 `not_checked`；必需 section 为 `not_checked` 或 `blocked` 时，总判定为 `no_go`。 |
| 2026-06-23 | Production Gap 第二十轮 | 新增 `render_m1_resource_request.py` 和 `m1-resource-request-pack.md`，汇总服务器、配置、数据、密钥托管、验收、备份、监控与回滚资源清单 | 已完成 | 清单填写变量名和资源状态；密钥由指定渠道交付。 |
| 2026-06-23 | Production Gap 第二十一轮 | 新增 `check_m1_first_deploy_dry_run.py` 和 `m1-first-deploy-dry-run.md`，把首次部署前的本地工具、目标输入、工作区、Compose 和公开边界检查收束成 dry-run gate | 已完成 | 只做本地预演；该轮因缺目标输入和未提交改动返回 `blocked`。 |
| 2026-07-03 | Production Gap 第二十二轮 | 根据 M1 正式切换中暴露的 RAG shared mount 缺失问题，补首部署脚本 legacy 向量库只补缺迁移和 live server probe 的 shared Chroma 文件级阻断 | 已完成 | 服务器执行时只向空 shared 目录补已有 legacy 向量库；probe 检查文件，召回质量另行验收。 |
| 2026-07-03 | Production Gap 第二十三轮 | 新增 `converge_server_shared_env.py`，把 root `.env` 到 `shared/.env` 的布局收敛做成 dry-run 默认、审批 token 才执行的受控流程 | 已完成 | 默认 dry-run；执行时只补缺 shared 配置且保留现有文件，之后用 live probe 确认 Compose 使用的配置。 |

发布顺序为资源确认、本地预演、冻结打包、服务器预演与切换，再执行目标环境验收。对应工具依次为 `render_m1_resource_request.py`、`check_m1_first_deploy_dry_run.py`、`build_release_artifact.py` 和 `deploy/first-deploy.sh`。切换后记录向量库 `configured`、acceptance preflight、live smoke/core、smoke、恢复、告警与回滚摘要，最后由 `collect_m1_go_no_go_evidence.py` 汇总判定并签核。详细步骤见 [M1 运行手册](../部署与运行/m1-controlled-trial-runbook.md)。

## 7. 验收命令

文档检查：

```powershell
git diff --check
```

默认回归：

```powershell
uv run python -m compileall app tests scripts
uv run python -m pytest -q
uv run python scripts\render_m1_resource_request.py --json
uv run python scripts\check_m1_first_deploy_dry_run.py --json
uv run python scripts\build_release_artifact.py --json
uv run python scripts\collect_m1_smoke_evidence.py --json
uv run python scripts\collect_backup_restore_drill_evidence.py --json
uv run python scripts\collect_monitoring_alerting_evidence.py --json
uv run python scripts\collect_incident_rollback_evidence.py --json
uv run python scripts\collect_m1_go_no_go_evidence.py --json
```

RAG 方向：

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

前端和报告方向：

```powershell
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
```

旅行社客户与交易域：

```powershell
uv run python -m pytest -q tests\test_customer_claim_tokens.py tests\test_agency_customer_claim_service.py tests\test_agency_customer_lifecycle_models.py tests\test_agency_customer_lifecycle_api.py tests\test_agency_customer_transaction_settlement.py tests\test_agency_transaction_models.py tests\test_agency_transaction_api.py
uv run python -m pytest -q tests\test_agency_branch_transfer_closure_api.py tests\test_agency_branch_transfer_closure_service.py tests\test_agency_branch_transfer_closure_migration.py tests\test_branch_drain_authorization.py
$env:ZHIXING_TEST_POSTGRES_DSN = "postgresql://travel_user:change-me@127.0.0.1:5432/zhixing_test"
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_customer_claim_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py tests\test_agency_cancellation_postgres_integration.py tests\test_agency_branch_transfer_closure_postgres_integration.py
```

## 8. 验证记录与发布要求

`dry-run` 记录执行计划，`blocked` 记录缺失的环境、密钥、服务或依赖。离线 RAG 结果、真实向量库、在线 Agent 和目标环境发布分别验收。验证记录注明 commit、时间窗、配置及环境；外部 API 结果保存脱敏摘要，原始日志和 `.runtime` 记录保留在仓库外。

数据库 CI 历史：

| 迁移阶段 | 提交与运行 | 结果 |
|---|---|---|
| `0004` | [`20ff71592096dfb4fc718cef050832a745bfe174`](https://github.com/apearlinspring/langgraph-travel-planner/commit/20ff71592096dfb4fc718cef050832a745bfe174) · [30534862434](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434) | 默认 `1713 passed, 34 deselected`；PostgreSQL 17 `10 passed`（3+5+2） |
| 首次 `0005` | [30542366036](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30542366036) | 失败：共享触发器访问不适用的 `NEW.target_user_id` / `NEW.status`；后由 `0006` 修正 |
| `0006` | [`b8b8bea29477b472c942b7df40e8da6e9dbf05ab`](https://github.com/apearlinspring/langgraph-travel-planner/commit/b8b8bea29477b472c942b7df40e8da6e9dbf05ab) · [30551146157](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30551146157) | 默认 `1738 passed, 39 deselected`；PostgreSQL 17 四文件 `15 passed` |
| `0007` | [`e17b97d82c24b7f5271973cc8f18e884124b7d6b`](https://github.com/apearlinspring/langgraph-travel-planner/commit/e17b97d82c24b7f5271973cc8f18e884124b7d6b) · [30602058425](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30602058425) | 默认 `1841 passed, 49 deselected`；PostgreSQL 17 五文件 `25 passed` |
| `0008` | [`c5746496203f628fe9a93a91ebb998c910c2a920`](https://github.com/apearlinspring/langgraph-travel-planner/commit/c5746496203f628fe9a93a91ebb998c910c2a920) · [30606856484](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30606856484) | 默认 `1878 passed, 58 deselected`；PostgreSQL 17 六文件 `34 passed` |

上述运行使用一次性 CI 数据库，目标环境迁移、恢复和并发锁复验仍待完成。PostgreSQL 集成测试请使用隔离库；库名须含独立的 `test` 或 `ci` 段，测试会创建并删除随机 schema。

发布包包含源码、依赖、配置样例、数据库结构/迁移、必要测试、正式文档、部署工具及脱敏样例。真实配置、业务数据、向量库、备份、原始日志、聊天记录和草稿保留在仓库外。路线样例用于演示和规则验证；外部查询失败时报告保留待核验项。

## 9. 完成要求

各模块合并前记录改动范围、测试与验收结果、契约变更、未解决问题及受影响文档。合并复核包括：

- 文档索引、能力地图和路线图导航有效。
- 新增状态、API 和配置有对应契约与验证。
- 公开材料完成脱敏，本地草稿与运行产物未进入 Git。
- 已执行命令的结果和未执行的原因记录完整。
