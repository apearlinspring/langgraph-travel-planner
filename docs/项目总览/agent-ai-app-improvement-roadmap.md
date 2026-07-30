# Agent/AI 应用工程化改进路线图

本文记录 ZhiXing Travel Planner 在 Agent（智能体）和 AI 应用工程化方向上的改进计划。它面向公开项目维护，重点写工程短板、交付证据、验收标准和协作分工，不包含本地草稿、原始运行证据、密钥、真实用户数据或本地环境坐标。

其中带日期的“已完成”行是实施历史，不自动代表当前 commit、目标环境或线上状态仍通过。当前能力与验收结论以源码、重新执行的测试/评估和日期化证据快照为准。

## 1. 改进目标

当前项目已经具备阶段化旅行规划、RAG（检索增强生成）、MCP（模型上下文协议）工具、结构化 `report_data`（报告数据）、前端报告展示、门店与客户生命周期控制面和评估入口。下一阶段目标不是继续堆叠功能，而是把这些能力收束成更可维护、可验证、可审计的 AI 应用工程闭环。

本路线图的交付目标：

- 用明确的工程证据说明项目不是普通聊天机器人或单轮 RAG 问答。
- 把 Agent 状态、工具、RAG、报告、前端和验收之间的契约写清楚。
- 为并行改进拆分清晰写入范围，降低合并冲突。
- 保持公开边界：不承诺真实库存、真实支付、真实锁价、真实出票或履约。
- 每个方向都能落到可运行命令、可复盘文档和剩余风险。

## 2. 当前短板矩阵

| 方向 | 当前风险 | 改进目标 | 优先级 | 验收证据 |
|---|---|---|---|---|
| 架构与状态 | 部分 API、中间件、状态迁移和前端文件偏大，流程规则较集中 | 明确状态契约、阶段边界和可拆分模块 | P0 | 架构文档、状态/流程测试、无回归 |
| RAG 与评估 | 样本规模偏小，真实向量库和外部模型验收需要明确 blocked / passed 语义 | 扩大场景，记录语料规模、召回指标和真实环境前置条件 | P0 | `scripts/evaluate_rag_retrieval.py --json` 输出和文档更新 |
| 工具与安全 | 外部工具错误、密钥脱敏、未知工具策略和失败审计仍需加固 | 工具白名单、脱敏、超时、降级和审计形成统一口径 | P0 | 工具治理文档、相关单测、失败兜底样例 |
| 报告交付 | `report_data` 已是核心契约，但仍需继续统一报告、前端和评估口径 | 结构化报告成为前端、导出、评估共用事实来源 | P0 | 报告契约测试、前端渲染验证 |
| AgentOps 与可观测 | 已有轻量运行指标，但缺少更完整的 trace（链路追踪）、成本和版本治理 | 形成运行质量指标、Prompt/模型变更记录和回放思路 | P1 | 评估系统文档、快照摘要、运行指标测试 |
| 前端工程化 | 单页原型可演示，但组件化、可访问性和构建治理不足 | 保持原型定位，优先保证结构化报告体验和导出可信 | P1 | 前端验证脚本、移动端/桌面端检查说明 |
| 旅行社客户与门店权限 | 门店、角色授权、线下潜客、本人同意、激活/停用、主顾问分配和范围查询已实现；客户拒绝/撤回同意或停用会原子收口内部交易，旧 `pending_review` 明确拒绝前不能随关系重新激活，写授权持共享范围锁以防并发撤权 TOCTOU（检查与使用时序差）。当前仍是应用层行级授权，不是 PostgreSQL RLS，且缺安全邀请/认领 token、客户通知、PII 档案、法律级同意、跨门店转移和门店停用/关闭 API | 先验证 `0004` 迁移、10 项 PostgreSQL 集成测试和越权/并发矩阵，再补客户获取、转店、合规和运营闭环；同意哈希与内部取消不得冒充法律合规、供应商取消或退款证明 | P0 | 客户生命周期模型/API 单测、隔离 PostgreSQL 17 集成测试、目标环境迁移与越权复验 |
| 部署与运行 | readiness（就绪检查）、部署模板和历史 M1 受控试运行证据已存在；旧 `319ac26` 具有 PostgreSQL 17 三项交易测试绿灯，但新增 `0004` 候选尚无目标环境新鲜执行与签核证据，生产高可用、扩缩容和密钥系统仍不完整 | 保持部署模板诚实，冻结候选后在目标环境重跑 readiness、preflight、smoke/core 和运维证据链 | P1 | runtime/deployment 文档、绑定 commit 的 readiness 结果和目标环境脱敏摘要 |
| 部署后 smoke 证据 | `collect_m1_smoke_evidence.py` 已能把 health、M1 gate 和 acceptance smoke 收束为脱敏摘要；当前缺口是尚未对冻结后的候选在目标环境执行并由负责人复核 | 在目标环境显式执行后形成绑定 commit、时间窗和配置口径的可复查证据；默认计划模式不冒充通过 | P0 | `scripts/collect_m1_smoke_evidence.py --json`、目标环境 smoke 摘要和复核记录 |
| 备份恢复演练证据 | readiness 与 `collect_backup_restore_drill_evidence.py` 已覆盖备份声明、dump 元数据和 catalog 检查；当前缺少绑定当前候选的目标环境新鲜备份、实际非生产恢复、恢复后校验和负责人签核 | 在隔离环境执行恢复，记录备份新鲜度、恢复耗时、数据丢失窗口、恢复后 readiness/smoke 和签核 | P0 | `scripts/collect_backup_restore_drill_evidence.py --json`、非生产恢复演练摘要和签核记录 |
| 监控告警投递证据 | readiness 与 `collect_monitoring_alerting_evidence.py` 已能收束监控声明；当前缺少目标环境真实告警投递、指标持续留存、值班升级和成本/备份告警闭环证据 | 对冻结候选执行受控告警演练，验证 health/readiness、错误率、工具失败、成本和备份告警的投递与处置 | P0 | `scripts/collect_monitoring_alerting_evidence.py --json`、告警送达证据和负责人签核 |
| 事故响应和回滚演练 | `collect_incident_rollback_evidence.py` 已提供机器化收束入口；当前缺少冻结候选在目标环境的真实回滚执行、回滚后 health/gate/smoke、事故复盘和 owner（负责人）签核 | 受控执行 P0/P1 响应和发布回滚，记录目标版本、数据安全边界、复验结果、根因与后续负责人 | P0 | `scripts/collect_incident_rollback_evidence.py --json`、回滚演练摘要、复盘和签核记录 |
| M1 go/no-go 总判定 | `collect_m1_go_no_go_evidence.py` 已能聚合 M1 gate、smoke、备份恢复、监控告警和事故回滚，并对 `not_checked` fail-closed（缺证据即阻断）；当前缺少当前候选的完整目标环境输入与最终 release-owner（发布负责人）签核 | 为冻结 commit 收齐同一时间窗的目标环境证据，生成最终 `decision` 并完成人工风险接受或阻断 | P0 | `scripts/collect_m1_go_no_go_evidence.py --json`、目标环境最终 `decision` 和 release-owner 签核 |
| M1 资源申请包 | `render_m1_resource_request.py` 和正式资源申请文档已存在；当前缺少由实际部署、运维和安全负责人填写并确认的仓库外资源状态、目标服务器输入和密钥托管责任 | 用现有模板收齐非密钥状态与 owner，阻止缺服务器、数据、备份、监控或外部依赖输入时进入部署 | P0 | `scripts/render_m1_resource_request.py --markdown`、`docs/部署与运行/m1-resource-request-pack.md` 和已确认的私有资源记录 |
| M1 首部署 dry-run | `check_m1_first_deploy_dry_run.py` 已提供不连接服务器、不上传文件的预演入口，并会对脏工作树或缺目标输入 fail-closed；新增 `0004` 尚缺绑定最终提交和真实目标输入的通过记录 | 冻结干净 commit，补齐目标输入后执行 dry-run，复核发布工具、Compose、公开边界和远端命令计划 | P0 | `scripts/check_m1_first_deploy_dry_run.py --json`、`docs/部署与运行/m1-first-deploy-dry-run.md` 和绑定候选的通过摘要 |
| M1 发布包 manifest | `build_release_artifact.py` 已能从干净 Git `HEAD` 生成 archive 和 manifest 并记录 commit、tree、tracked file count 与 sha256；新增 `0004` 尚未生成与最终提交绑定的可复现候选发布包 | 冻结并评审干净 commit，生成不可变发布包，校验哈希并让部署记录引用同一 artifact（发布制品） | P0 | `scripts/build_release_artifact.py --execute --output-dir <release-output-dir> --json`、发布包 manifest 和哈希复核 |
| M1 服务器首部署脚本 | `deploy/first-deploy.sh` 已固化 release/current/shared 模型并默认 dry-run；当前缺少最终发布包在目标服务器的 dry-run、显式执行、切换后健康检查、回滚准备和 owner 签核 | 使用同一 manifest 发布包完成目标服务器预演与受控切换，验证运行时数据不被覆盖并留存回滚证据 | P0 | `deploy/first-deploy.sh`、目标服务器执行摘要、健康检查、回滚准备和签核记录 |
| 生产化差距 | 当前更接近工程样板和受控演示，距离真实生产系统还有密钥、数据、安全、可观测、业务履约等硬缺口 | 按 P0/P1/P2 明确真实上线前阻断项和验收标准 | P0 | `docs/部署与运行/production-readiness-gap.md` |
| 生产运行依赖范围 | runtime-only requirements（仅运行时依赖）拆分和 `check_runtime_dependency_scope.py` 静态门禁已实现；当前缺少基于冻结候选的完整镜像重建、体积/时长记录、目标运行时启动与回归证据 | 保持默认 API 镜像与开发/测试、多模态深门禁、本地 embedding、GPU/model 重依赖解耦，并用实际镜像验证门禁结果 | P0 | `scripts/check_runtime_dependency_scope.py --json`、依赖范围测试、镜像 manifest、体积和健康探针记录 |
| 生产镜像构建策略 | 静态策略门禁、构建执行记录门禁和 approval-gated（需批准）远程后台 build 启动器已实现；当前未针对冻结候选获得执行批准，也没有远程构建、镜像 ID/大小、健康探针和失败回滚的当前证据 | 在不影响现有 release 的前提下受控执行远程后台构建，固定镜像源、超时、日志/PID、磁盘保护和回滚边界，并完成执行记录签核 | P0 | `scripts/check_production_image_build_policy.py --json`、`scripts/prepare_production_image_build_execution.py --markdown`、`scripts/check_production_image_build_execution_record.py --record-json ... --json`、构建摘要和签核 |

## 3. 子Agent分工

每个方向可以由独立子Agent处理，但必须遵守写入范围，避免多个方向同时修改同一批共享文件。共享文档和最终口径由 Coordinator 统一合并。

| Workstream | 写入范围 | 交付物 | 不做事项 |
|---|---|---|---|
| Coordinator | `docs/README.md`、`docs/项目总览/`、最终验收摘要 | 总路线图、入口文档、合并记录、最终公开口径 | 不直接代替各方向做深改 |
| RAG/Evaluation Agent | `app/rag/`、`app/evaluation/`、`data/evaluation/`、`docs/RAG与知识库/` | 召回场景扩展、RAG 评测报告、真实环境前置条件 | 不提交向量库、原始 `.runtime` 证据或密钥 |
| Agent State/Architecture Agent | `app/core/`、`app/agents/handoffs/`、`docs/架构与流程/` | 状态 schema、流程边界、大文件拆分建议、Prompt 规则外移方案 | 不一次性重写主链路 |
| Tool/Security Agent | `app/mcp_core/`、`app/tools/`、`app/utils/security.py`、`docs/治理与可观测/` | 密钥脱敏、工具策略、schema/version、失败审计 | 不新增真实支付、短信或预订动作 |
| Agency Domain Agent | `app/agency/`、`app/api/v1/agency_*`、`app/models/agency_*`、`alembic/versions/` | 门店、客户生命周期、顾问分配、交易权限、迁移与专项测试 | 不把应用层授权表述为 PostgreSQL RLS，不接真实供应商、支付、退款或通知 |
| Report/Frontend Agent | `app/reports/`、`frontend/`、`docs/前端与演示/` | `report_data` 交付证据、结构化报告渲染、导出验证 | 不把单页原型包装成完整生产后台 |
| Docs/Release Agent | `docs/评估与验收/`、`docs/部署与运行/`、正式公开说明 | 公开发布口径、验收矩阵、风险边界 | 不写本地草稿资料或本地敏感路径 |

## 4. 合并顺序

建议按风险依赖合并：

1. Coordinator 建立路线图和基线记录。
2. RAG/Evaluation 先明确评测规模和真实环境语义。
3. Agent State/Architecture 明确状态、流程和 Prompt 规则边界。
4. Tool/Security 收敛工具白名单、脱敏和失败审计。
5. Report/Frontend 对齐 `report_data`、前端展示和导出。
6. Docs/Release 更新公开文档入口、演示包和部署说明。
7. Coordinator 复核全部口径、测试结果和剩余风险。

## 5. 接口变更记录

后续如果引入或调整公开契约，必须先在这里记录，再落到代码和测试。

| 日期 | 变更类型 | 契约 | 影响范围 | 状态 |
|---|---|---|---|---|
| 2026-06-23 | 文档计划 | 本路线图只新增文档，不改运行时 API、数据库、前端交互或测试契约 | 文档入口、协作分工、验收口径 | 已记录 |
| 2026-06-23 | 评估输出 | RAG 召回评测 JSON / Markdown 增加 `coverage_summary`、`visibility_recall` 和 `safety_pass_rate` | `app/evaluation/rag_retrieval.py`、RAG 评测文档、RAG 评测测试 | 已完成 |
| 2026-06-23 | 安全脱敏 | `redact_sensitive_text()` 覆盖 URL query 中的 `key`、`api_key`、`access_token` 等敏感参数 | MCP 错误格式化、工具审计摘要、治理文档和相关测试 | 已完成 |
| 2026-06-23 | 状态契约 | 明确 `TravelState`、`current_step`、`agency_step`、`STEP_STATE_FIELDS` 和报告交付字段边界 | 状态契约文档、工作流维护性测试 | 已完成 |
| 2026-06-23 | Prompt 规则 | 把阶段 Prompt 硬规则、工具开放边界、报告/报价/库存红线整理为规则清单 | Prompt 规则清单、阶段配置渲染测试 | 已完成 |
| 2026-06-23 | 报告交付 | 明确 `report_data` 到前端渲染、复制摘要和导出 HTML 的交付契约 | 前端交付契约文档、报告渲染脚本、浏览器回归脚本 | 已完成 |
| 2026-06-23 | RAG readiness | 明确离线召回、安全门、真实 Chroma 向量库、acceptance preflight 和 live smoke/core 的证据层级 | 向量库 readiness 文档、RAG 发布 checklist | 已完成 |
| 2026-06-23 | AgentOps 证据链 | 明确 turn 级观测、工具审计、readiness/preflight/acceptance 摘要和版本记录建议 | AgentOps 轻量回放文档、观测文档入口 | 已完成 |
| 2026-06-23 | 生产化差距 | 从真实生产系统视角拆分 M0/M1/M2/M3 和 P0/P1/P2 缺口，并补充 M1 上线总清单、受控试运行输入清单、执行手册、外部 API 故障手册、备份恢复手册、监控告警手册、安全发布/密钥轮换手册和验收记录模板 | 生产化差距清单、M1 上线总清单、生产部署输入清单、M1 runbook、外部 API runbook、备份恢复 runbook、监控告警 runbook、安全发布 runbook、验收记录模板、公开文档入口 | 已完成 |
| 2026-06-23 | M1 输入门禁 | 新增非密钥上线输入检查脚本，覆盖范围、服务器、部署模式、密钥负责人、外部 API、数据、验收、备份、监控、成本和事故负责人；脚本不读取 `.env`，不回显变量值 | `scripts/check_m1_launch_inputs.py`、`.env.example`、`docker-compose.yml`、M1 checklist、M1 runbook、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 部署总门禁 | 新增聚合检查脚本，串起公开发布边界、M1 非密钥输入、Compose 配置和 runtime readiness；默认不读取 `.env`、不启动服务、不回显密钥 | `scripts/check_m1_deployment_gate.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 验收记录 | 新增脱敏记录生成器，把 deployment gate 输出整理成 Markdown 验收记录；默认只打印，不写文件，不保存真实密钥、日志或目标 URL 原文 | `scripts/render_m1_acceptance_record.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 备份恢复前置 | 新增备份/恢复 readiness 脚本，检查备份目标、绝对目录、仓库外路径、保留策略和 RAG 恢复策略；显式开启时验证备份目录可写 | `scripts/check_backup_restore_readiness.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 监控告警前置 | 新增监控/告警/cost readiness 脚本，检查监控供应商、告警渠道和每日成本预算；显式开启时探测公开 health endpoint；接入 M1 deployment gate | `scripts/check_monitoring_alerting_readiness.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 安全发布前置 | 新增安全发布 readiness 脚本，检查密钥托管、轮换周期、泄露响应、凭据状态、浏览器 key 来源限制和高风险动作关闭声明；接入 M1 deployment gate | `scripts/check_security_release_readiness.py`、`.env.example`、`docker-compose.yml`、security runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 外部 API 前置 | 新增外部 API readiness 脚本，检查必需供应商、可选供应商状态、配额预算、控制台负责人、支持渠道、降级策略和 timeout/retry 策略；接入 M1 deployment gate | `scripts/check_external_api_readiness.py`、`.env.example`、`docker-compose.yml`、external API runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 服务器 preflight | 新增目标服务器 preflight 脚本，检查服务器基线、部署目录、公网 URL、站点地址、域名、出口 IP、端口、TLS、反向代理和 Docker 状态；目标环境可显式探测 Docker、部署目录和 health URL | `scripts/check_server_preflight_readiness.py`、`.env.example`、`docker-compose.yml`、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 smoke 证据 | 新增部署后 smoke 证据收集器，默认只输出执行计划；显式开启时汇总公开 health、M1 deployment gate 和 acceptance smoke 的脱敏摘要，不回显真实 URL、密钥或原始日志 | `scripts/collect_m1_smoke_evidence.py`、M1 checklist、M1 runbook、部署输入文档、验收记录模板、部署模板和测试 | 已完成 |
| 2026-06-23 | 备份恢复演练证据 | 新增备份恢复演练证据收集器，默认只输出执行计划；显式开启时检查备份目录、最新 dump 元数据、`pg_restore --list` catalog 可读性和恢复演练声明，不回显真实路径或 dump 文件名 | `scripts/collect_backup_restore_drill_evidence.py`、`.env.example`、`docker-compose.yml`、backup runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 监控告警证据 | 新增监控告警证据收集器，默认只输出执行计划；显式开启时收集 health/readiness 投递声明、核心指标监控、成本、备份和日志脱敏状态，不发送真实告警或回显通知内容 | `scripts/collect_monitoring_alerting_evidence.py`、`.env.example`、`docker-compose.yml`、monitoring runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | 事故/回滚证据 | 新增事故响应和回滚演练证据收集器，默认只输出执行计划；显式开启时收集负责人、回滚目标、回滚后 health/gate/smoke 和事故复盘状态，不执行回滚或删除数据 | `scripts/collect_incident_rollback_evidence.py`、`.env.example`、`docker-compose.yml`、incident runbook、M1 checklist、M1 runbook、部署输入文档、验收记录模板和测试 | 已完成 |
| 2026-06-23 | M1 go/no-go 总判定 | 新增最终证据汇总器，默认只输出计划态；显式纳入证据后按生产口径判定 `go_for_m1_controlled_trial`、`conditional_go`、`no_go` 或 `not_checked`，其中请求 section 的 `not_checked` 直接 `no_go` | `scripts/collect_m1_go_no_go_evidence.py`、M1 checklist、M1 runbook、部署输入文档、生产差距清单、验收记录模板、部署模板、能力地图和测试 | 已完成 |
| 2026-06-23 | M1 资源申请包 | 新增资源申请包生成器和正式文档，汇总服务器、DNS/TLS、运行配置、密钥变量、RAG 数据、外部 API、验收、备份、监控和回滚准备项；脚本不读取 `.env`，不回显变量值 | `scripts/render_m1_resource_request.py`、`docs/部署与运行/m1-resource-request-pack.md`、README、M1 checklist、M1 runbook、部署输入文档、部署模板、生产差距清单和测试 | 已完成 |
| 2026-06-23 | M1 首部署 dry-run | 新增首次部署预演脚本和正式文档，本地检查目标输入、git/ssh/scp/docker 工具、git 工作区、Compose 模板和公开边界，并输出远端部署命令计划 | `scripts/check_m1_first_deploy_dry_run.py`、`docs/部署与运行/m1-first-deploy-dry-run.md`、README、deployment readiness、M1 checklist、runbook、验收模板、生产差距清单和测试 | 已完成 |
| 2026-06-23 | M1 服务器首部署脚本 | 新增 `deploy/first-deploy.sh`，在服务器侧执行 release/current/shared 发布模型；默认 dry-run，显式 `--execute --start-services` 才解压、切换 current 和启动 Compose | `deploy/first-deploy.sh`、deployment readiness、M1 runbook、M1 checklist、资源申请包、验收模板、生产差距清单和测试 | 已完成 |
| 2026-06-23 | M1 发布包 manifest | 新增 `scripts/build_release_artifact.py`，默认 dry-run，显式执行时从干净 Git `HEAD` 生成 archive 和 manifest，记录 commit、tree、tracked file count 和 archive `sha256` | `scripts/build_release_artifact.py`、deployment readiness、M1 runbook、M1 checklist、资源申请包、验收模板、生产差距清单和测试 | 已完成 |
| 2026-07-03 | 生产运行依赖门禁 | 新增 `scripts/check_runtime_dependency_scope.py`，静态检查 `pyproject.toml`、`requirements.runtime.txt` 和 `Dockerfile`，把测试框架、多模态深门禁、本地 embedding、GPU/model 重依赖混入生产镜像定义为 blocked | `scripts/check_runtime_dependency_scope.py`、`tests/test_runtime_dependency_scope.py`、deployment readiness、runtime environment 和脚本入口测试 | 已完成门禁和首次依赖拆分；仍需在下一次镜像构建后记录体积、构建时长和线上滚动验证 |
| 2026-07-03 | 生产 runtime 依赖拆分 | 将 `pytest` / `pytest-asyncio` 移入 dev dependency group，将 `faster-whisper` / `imageio-ffmpeg` / `sentence-transformers` 移入 optional profile，新增 `requirements.runtime.txt`，生产 Dockerfile 不再安装完整 `requirements.txt` | `pyproject.toml`、`uv.lock`、`requirements.runtime.txt`、`Dockerfile`、`scripts/check_release_candidate_freeze.py` | 代码侧完成；尚未重建并切换线上瘦身镜像 |
| 2026-07-03 | 生产镜像构建策略门禁 | 新增 `scripts/check_production_image_build_policy.py`，静态检查镜像源、远程后台构建、超时、日志/PID、镜像 ID/大小、健康探针和禁止清理边界，并检查 `deploy/update-runtime-image.sh` 与 Dockerfile 契约 | `scripts/check_production_image_build_policy.py`、`tests/test_production_image_build_policy.py`、脚本入口测试、deployment readiness 和 runtime environment | 已完成策略门禁；尚未执行远程后台 build 和镜像体积验收 |
| 2026-07-03 | 生产镜像构建执行记录门禁 | 新增 `scripts/check_production_image_build_execution_record.py`，校验真实远程后台 build 后的私有记录：后台 wrapper、PID/log、runtime-only 输入、镜像 ID/大小、磁盘与运行时数据安全、`compose ps` 和 health 探针 | `scripts/check_production_image_build_execution_record.py`、`tests/test_production_image_build_execution_record.py`、M1 checklist、deployment readiness 和 runtime environment | 已完成执行记录门禁；真实远程 build 仍待单独执行并填入私有记录 |
| 2026-07-03 | 生产镜像远程后台构建启动器 | 新增 `scripts/prepare_production_image_build_execution.py`，默认 dry-run 生成脱敏执行计划；显式 `--execute --approval-token APPROVE_PRODUCTION_IMAGE_BUILD_EXECUTION` 才通过 SSH 启动远程后台 `deploy/update-runtime-image.sh` | `scripts/prepare_production_image_build_execution.py`、`tests/test_production_image_build_execution_preparer.py`、M1 checklist、deployment readiness 和 runtime environment | 已完成 dry-run/execute 封装；尚未获得单独批准执行真实远程 build |
| 2026-07-03 | Compose project 固定 | 根据 M1 正式切换中暴露的固定容器名冲突，把 `first-deploy.sh` 和 `update-runtime-image.sh` 默认 Compose project 固定为 `langgraph-travel-planner`，并允许通过 `ZHIXING_COMPOSE_PROJECT_NAME` 覆盖 | `deploy/first-deploy.sh`、`deploy/update-runtime-image.sh`、生产镜像策略门禁、首部署脚本契约测试、运维复盘记录和部署文档 | 已完成脚本与文档修复；真实服务器已用最小修复完成本轮 backend/caddy 切换，并补齐 rollout、health smoke、capacity、operations review 和 rerun go/no-go 证据；下一次发布应直接走脚本固定 project |
| 2026-07-03 | 限流 burst 探针 | 将 `collect_rate_limit_live_probe.py` 从串行短窗口采样扩展为可配置并发 burst，避免慢串行请求跨过限流窗口而漏采 429；M1 go/no-go 和私有证据 workflow 透传 `--rate-limit-concurrency` | `scripts/collect_rate_limit_live_probe.py`、`scripts/collect_m1_go_no_go_evidence.py`、`scripts/run_m1_private_live_evidence_workflow.py`、限流探针测试和部署文档 | 已完成；线上低风险 workflow 采用 160 次 / 16 并发采到 Redis rate-limit 的 200+429 证据并通过 |

## 6. 推进记录

第一轮先推进两个 P0 方向，原因是它们最容易形成可复跑证据，也最能暴露 Agent 应用工程底线。

| 日期 | 方向 | 子Agent任务 | 当前状态 | Coordinator关注点 |
|---|---|---|---|---|
| 2026-06-23 | RAG/Evaluation | 统一 RAG 评测规模、blocked / passed 语义、真实向量库验收口径和场景覆盖说明 | 已完成第一轮 | 第一轮快照为 19 场景、21 文档和 3 个公开安全场景；截至 2026-06-23 第二轮扩到 25 场景、24 文档和 9 个公开安全场景，两轮都不能解释为真实向量库或在线 Agent 验收通过 |
| 2026-06-23 | Tool/Security | 检查 URL query key 脱敏、MCP 错误输出脱敏、未知工具策略和失败审计口径 | 已完成第一轮 | 已补 URL query 参数脱敏、MCP 错误脱敏和测试；未知工具全局默认策略本轮不收紧，保留为后续有回归保护的改进项 |
| 2026-06-23 | RAG/Evaluation 第二轮 | 扩充公开目的地样例，把公开安全负样本从西安扩到更多目的地 | 已完成 | 公开目的地扩到西安、杭州、厦门、桂林；离线评测为 25 场景、24 文档、9 个公开安全场景，仍不代表真实向量库或在线 Agent 验收 |
| 2026-07-11 | RAG/Evaluation 南京样例校准（历史快照） | 新增南京公开目的地样例和精确目的地消歧场景，重新生成离线召回报告并校准旧口径 | 已完成离线校准 | 该轮历史快照为 26 场景、25 文档、5 个公开目的地和 10 个 mixed-corpus safety 场景；当时离线脚本通过不代表真实向量库、在线 Agent 或生产环境验收通过 |
| 2026-07-12 | RAG/Evaluation 北京银发样例校准 | 新增北京公开低强度、午休、无障碍/电梯和天气 Plan B 安全样例，补精确召回场景并复跑离线门禁 | 已完成离线校准 | 当前为 27 场景、26 文档、6 个公开目的地和 11 个 mixed-corpus safety 场景；2026-07-11 的 26/25/5/10 保留为历史快照；离线通过不代表真实向量库或在线 Agent 通过 |
| 2026-07-26 | 旅行社客户生命周期与门店权限 | 新增 `0004` 门店、门店岗位授权、线下潜客关联、客户本人同意、激活/停用、主顾问分配和应用层范围查询；把报价、订单和内部审核绑定门店/客户关系，并增加客户停用内部交易收口、报价/订单数据库变更门禁、统一锁序与撤权并发保护 | 代码与专项测试已落地，3 个 PostgreSQL 测试文件的 10 项测试待新提交 CI 确认 | 旧 `319ac26` 的 PostgreSQL 17 三项交易测试已通过但早于 `0004`；本轮必须重新确认 3 项交易、5 项客户生命周期和 2 项门店权限测试，且内部 `cancelled` 不代表供应商取消/退款，整轮结果也不代表目标环境、RLS、完整 CRM、法律合规或真实履约 |
| 2026-06-23 | Tool/Security 第二轮 | 补外部 MCP 服务目录、required / optional / degraded 策略表，并与 `SERVICE_DEFINITIONS` 口径对齐 | 已完成 | MCP 目录只写变量名和状态语义；`required_when_declared` 只在被选中验收场景声明必需时阻塞 |
| 2026-06-23 | Agent State/Architecture 第三轮 | 新增状态契约和 Prompt 规则清单，补双工作流轴、阶段字段、工具白名单和报告红线维护性测试 | 已完成 | `active_workflow` 决定读 `current_step` 或 `agency_step`；`step_config.py` 仍是静态配置来源，运行态还要依赖中间件和工具守卫 |
| 2026-06-23 | Report/Frontend 第四轮 | 新增 `report_data` 交付契约文档，补前端渲染、复制摘要、导出 HTML 和浏览器回归边界断言 | 已完成 | 前端演示证明结构化报告可渲染、可复制摘要、可导出，不证明真实支付、预订、库存、锁价或履约 |
| 2026-06-23 | RAG/AgentOps 第五轮 | 补真实向量库 readiness 发布矩阵、RAG release checklist 和 AgentOps 轻量回放/版本记录口径 | 已完成 | 离线召回 `passed` 不能代表真实向量库或线上 Agent；当前 AgentOps 是 turn 级安全摘要复盘，不是完整分布式 trace 或 APM |
| 2026-06-23 | Production Gap 第六轮 | 新增生产化差距清单、M1 上线总清单、生产部署输入清单、M1 受控试运行 runbook、外部 API 故障 runbook、备份恢复 runbook、监控告警 runbook、安全发布/密钥轮换 runbook 和验收记录模板，明确当前项目不是完整生产系统，以及受控试运行前的 P0 阻断项 | 已完成 | 真实上线必须补密钥管理、备份恢复、集中观测、发布回滚、外部工具 runbook、法务用户边界和高风险动作 HITL；真实密钥只进服务器环境或密钥系统 |
| 2026-06-23 | Production Gap 第七轮 | 把 M1 非密钥输入从文档表格升级成 `check_m1_launch_inputs.py` 机器门禁，并接入 `.env.example`、Compose、上线清单、runbook 和验收记录模板 | 已完成 | 该脚本只证明上线输入已声明，不证明真实密钥、服务器健康、备份恢复或 acceptance smoke 已通过 |
| 2026-06-23 | Production Gap 第八轮 | 新增 `check_m1_deployment_gate.py` 聚合门禁，汇总公开边界、M1 输入、Compose 配置和 runtime readiness，并支持目标环境内追加 acceptance backend 检查 | 已完成 | 聚合门禁默认不读取 `.env`、不启动服务；本地缺真实环境时 `blocked` 是正确结果 |
| 2026-06-23 | Production Gap 第九轮 | 新增 `render_m1_acceptance_record.py`，把聚合门禁结果转换为脱敏 M1 验收 Markdown，服务真实发布后的证据留档 | 已完成 | 记录生成器不是验收本身；gate 不是 `passed` 时记录只能写 `blocked` 或 `degraded` |
| 2026-06-23 | Production Gap 第十轮 | 新增 `check_backup_restore_readiness.py`，把备份目标、备份目录、保留策略和 RAG 恢复策略纳入机器门禁，并接入 M1 deployment gate | 已完成 | 该脚本不连接数据库；`--check-filesystem` 只证明目录可写，不等于 `pg_restore` 恢复演练通过 |
| 2026-06-23 | Production Gap 第十一轮 | 新增 `check_monitoring_alerting_readiness.py`，把监控供应商、告警渠道、成本预算和可选 health URL 探测纳入机器门禁，并接入 M1 deployment gate | 已完成 | 该脚本不读取 `.env`，默认不触网；`--check-health-url` 只证明 endpoint 可达，不等于真实告警投递、指标看板或成本封顶已生效 |
| 2026-06-23 | Production Gap 第十二轮 | 新增 `check_security_release_readiness.py`，把密钥托管、轮换、泄露响应、凭据状态、来源限制和高风险动作关闭纳入机器门禁，并接入 M1 deployment gate | 已完成 | 该脚本不读取真实密钥；`passed` 不等于密钥真实有效、旧 key 已撤销、供应商最小权限或泄露演练已完成 |
| 2026-06-23 | Production Gap 第十三轮 | 新增 `check_external_api_readiness.py`，把必需/可选外部 API、配额预算、负责人、支持渠道、降级策略和 timeout/retry 策略纳入机器门禁，并接入 M1 deployment gate | 已完成 | 该脚本不读取真实密钥、不调用供应商；`passed` 不等于真实 API 从目标服务器调用成功、配额生效或数据可用于生产履约 |
| 2026-06-23 | Production Gap 第十四轮 | 新增 `check_server_preflight_readiness.py`，把目标服务器、部署目录、Docker、端口、TLS、反向代理和公网 health URL 纳入机器门禁，并接入 M1 deployment gate | 已完成 | 默认只检查声明；显式探测也不启动服务、不写文件，`passed` 不等于当前版本已部署、数据库/Redis/RAG/外部 API 全部健康 |
| 2026-06-23 | Production Gap 第十五轮 | 新增 `collect_m1_smoke_evidence.py`，把部署后 health、M1 gate 和 acceptance smoke 汇总成脱敏证据记录 | 已完成 | 默认 `not_checked` 只代表执行计划；显式跑 smoke 会触网并可能消耗 LLM/外部 API 预算，仍不证明支付、预订、锁价、出票或履约 |
| 2026-06-23 | Production Gap 第十六轮 | 新增 `collect_backup_restore_drill_evidence.py`，把备份目录、最新 PostgreSQL dump、`pg_restore --list` 和恢复演练声明收束成脱敏证据 | 已完成 | 默认 `not_checked`；最新 dump 和 catalog 可读性不等于完整恢复，必须另做非生产库恢复、readiness 和 smoke |
| 2026-06-23 | Production Gap 第十七轮 | 新增 `collect_monitoring_alerting_evidence.py`，把 health/readiness 告警投递、错误率/P95/工具失败/成本/备份/日志脱敏监控声明收束成脱敏证据 | 已完成 | 默认 `not_checked`；脚本不发送真实告警，声明不等于完整 APM、指标长期留存或值班升级闭环 |
| 2026-06-23 | Production Gap 第十八轮 | 新增 `collect_incident_rollback_evidence.py`，把事故负责人、回滚目标、回滚后复验和事故复盘声明收束成脱敏证据 | 已完成 | 默认 `not_checked`；脚本不执行回滚、不启动服务、不恢复数据，回滚后 smoke 需要显式开启 |
| 2026-06-23 | Production Gap 第十九轮 | 新增 `collect_m1_go_no_go_evidence.py`，把 M1 gate、smoke、备份恢复、监控告警、事故回滚证据汇总为最终 `decision` | 已完成 | 默认 `not_checked`；只要请求的证据 section 仍是 `not_checked` 或 `blocked`，最终就是 `no_go`，不能包装成生产可用 |
| 2026-06-23 | Production Gap 第二十轮 | 新增 `render_m1_resource_request.py` 和 `m1-resource-request-pack.md`，把用户需要准备的服务器、env、数据、密钥托管、验收、备份、监控和回滚资源汇总成可发送清单 | 已完成 | 资源申请包只收变量名和状态，不证明资源已存在，也不能填写真实密钥、账号口令或客户资料 |
| 2026-06-23 | Production Gap 第二十一轮 | 新增 `check_m1_first_deploy_dry_run.py` 和 `m1-first-deploy-dry-run.md`，把首次部署前的本地工具、目标输入、工作区、Compose 和公开边界检查收束成 dry-run gate | 已完成 | dry-run 不 SSH、不 SCP、不生成发布包、不启动服务；当前本机因缺目标输入和工作区未提交改动正确输出 `blocked` |
| 2026-07-03 | Production Gap 第二十二轮 | 根据 M1 正式切换中暴露的 RAG shared mount 缺失问题，补首部署脚本 legacy 向量库只补缺迁移和 live server probe 的 shared Chroma 文件级阻断 | 已完成 | 脚本只在服务器执行时复制已有 legacy 运行时向量库到空 shared 目录，不把向量库纳入 Git；probe 只证明文件存在，不证明召回质量或语料新鲜度 |
| 2026-07-03 | Production Gap 第二十三轮 | 新增 `converge_server_shared_env.py`，把 root `.env` 到 `shared/.env` 的布局收敛做成 dry-run 默认、审批 token 才执行的受控流程 | 已完成 | dry-run 不复制、不打印值；执行模式不覆盖已有 `shared/.env`、不重启服务，仍需后续 live probe 验证 compose 实际使用 shared env |

Coordinator 每轮合并后回填改动范围、验证结果和剩余风险。后续真实环境可用时，先用 `render_m1_resource_request.py` 收齐服务器、env、数据和运维资源状态，再用 `check_m1_first_deploy_dry_run.py` 确认本地发布前置和目标输入，然后用 `build_release_artifact.py` 生成带 manifest 和 sha256 的发布包，上传并先 dry-run `deploy/first-deploy.sh`，确认无误后显式 `--execute --start-services`，再按 release checklist 记录真实向量库 `configured`、acceptance preflight、live smoke/core、`collect_m1_smoke_evidence.py` 目标环境摘要、`collect_backup_restore_drill_evidence.py` 恢复演练摘要、`collect_monitoring_alerting_evidence.py` 告警投递摘要、`collect_incident_rollback_evidence.py` 回滚演练摘要、`collect_m1_go_no_go_evidence.py` 最终总判定和真实告警投递的实际状态；更完整的持久化 trace、指标库、告警演练、备份恢复、密钥系统和真实业务履约仍属于后续生产化方向。

## 7. 验收命令

计划文件阶段：

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
uv run python -m pytest -q tests\test_agency_customer_lifecycle_models.py tests\test_agency_customer_lifecycle_api.py tests\test_agency_customer_transaction_settlement.py tests\test_agency_transaction_models.py tests\test_agency_transaction_api.py
$env:ZHIXING_TEST_POSTGRES_DSN = "postgresql://travel_user:change-me@127.0.0.1:5432/zhixing_test"
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py
```

验收说明：

- `dry-run` 只能证明场景和入口存在，不能证明真实链路通过。
- `blocked` 表示真实环境、密钥、外部服务或依赖不满足，不能写成业务通过。
- 旧 `319ac26` 的 3 项 PostgreSQL 通过只适用于旧基线；当前 3 个文件共 10 项测试仍须等待包含 `0004` 的新提交触发数据库 job，且 CI 不能替代目标环境迁移。
- 涉及真实外部 API（应用程序接口）时，结果只提交脱敏摘要，不提交原始日志、`.runtime` 快照或密钥。

## 8. 公开边界

公开仓库允许保留：

- 源码、依赖声明、配置样例、数据库结构或初始化脚本。
- 必要测试、正式 README、技术文档、部署模板和安全样例数据。
- 可复跑命令、脱敏评估摘要、公开知识样例和风险说明。

公开仓库不得提交：

- `.env`、`.env.production`、`.runtime/`、`.venv/`、真实向量库、数据库备份、原始日志或密钥。
- 真实客户资料、真实订单、真实联系人、真实支付或库存信息。
- 原始聊天记录、未整理 Prompt 草稿、本地证据快照或本地草稿资料。

用户可见和公开文档必须保持以下红线：

- 不承诺真实库存、锁价、支付、出票、酒店确认或客服履约。
- 外部工具失败时必须标记待核验，不能编造真实班次、酒店、价格或预约状态。
- 产品化路线样板是演示目录和规则依据，不代表真实可售产品。

## 9. 每个方向的完成定义

每个子Agent方向合并前必须提交：

- 改动范围说明。
- 测试和验收结果。
- 新增或变更的契约。
- 未解决风险。
- 是否影响公开讲解口径。

Coordinator 最终验收：

- `docs/README.md` 能找到本路线图。
- `docs/项目总览/project-capability-map.md` 能说明当前边界和改进路线。
- 公开文档不含本地敏感路径或非公开运行证据。
- 本地草稿资料不进入 Git 仓库。
- 验收命令结果和未运行原因如实记录。
