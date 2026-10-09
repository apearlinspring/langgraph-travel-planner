# Production Readiness Gap

本文整理当前版本的运行条件和待完成事项，按受控试运行、有限生产和规模化运行分级。

## 结论

当前项目适合作为旅行社 AI 应用工程样板和受控内部工作台：它已经具备状态机、RAG、MCP 工具、结构化 `report_data`、前端报告、readiness、评估门禁、轻量观测证据，以及第一阶段旅行社门店、客户生命周期、顾问分配、报价、订单、人工取消结果、独立对账、事件和幂等控制面。

上线前仍需完成：

- 交易域当前只完成数据与控制面骨架：客户拒绝/撤回同意或关系停用时可以原子收口内部报价/订单；`0007` 可分岗登记平台外人工取消/财务结果并独立对账，但不会调用供应商取消或退款。真实供应商预订、取消、支付、退款、通知、出票、库存锁定和客服履约尚未接入，并由默认关闭的配置门禁阻断。
- 门店隔离当前由应用服务和查询过滤器执行，不是 PostgreSQL RLS；`0008` 已增加 owner/admin 客户当前门店转移，以及 `active -> inactive -> closed` 的门店清理/关闭控制，但仍不含跨门店经理双向交接审批。客户关系虽已实现目标账户安全认领与服务端只追加同意记录，仍不含姓名、电话、证件等 PII 档案，也没有邀请投递/通知、真实身份核验或完整同意合规闭环。
- 当前版本没有一套与 commit 绑定的新鲜生产证据：2026-07-03 的私有快照记录过备份恢复、短窗口探针和事故治理，但它不能自动覆盖当前工作树；密钥托管、集中日志、指标告警和分布式 trace 仍不完整。
- Agent 治理仍偏轻量：Prompt 和模型版本、工具权限、回放评估、灰度发布和回滚还没有形成生产 registry。
- 真实环境验收仍需按当前 commit 现场跑：离线评测或历史 `passed` 不能替代当前向量库 `configured`、acceptance preflight 和 live smoke/core。

## 分级定义

| 等级 | 含义 | 当前状态 |
|---|---|---|
| M0 工程样板 | 本地可运行、文档清晰、关键链路有测试和离线验收。 | 规划交付、客户生命周期和交易控制面基本达到；完整 CRM 与真实交易不在此等级结论内。 |
| M1 受控试运行 | 使用真实环境和真实依赖，但只面向内部或少量白名单用户，人工兜底强。 | 2026-07-03 目标版本有一次历史就绪快照；包含 `0008` 的当前候选仍须冻结、绑定 commit 并完整复验。 |
| M2 有限生产 | 支持有限真实用户、稳定部署、数据安全、监控告警、备份恢复和明确人工运营流程。 | 尚未达到。 |
| M3 规模化生产 | 多环境治理、容量规划、成本治理、灰度发布、SLA 和完整合规闭环。 | 尚未启动。 |

## P0：试运行前阻断项

| 方向 | 当前证据 | 生产缺口 | 最低验收 |
|---|---|---|---|
| 真实环境基线 | 有 `check_runtime_readiness.py`、部署模板、RAG release checklist 和 2026-07-03 历史私有快照。 | 还没有一份绑定当前 commit 的目标环境 readiness 通过记录；真实 Chroma、PostgreSQL、Redis、LLM 和关键 MCP 服务需要重新确认。 | 冻结当前候选后，在目标环境运行 production readiness、acceptance preflight 和 smoke，并保留 commit、时间窗和脱敏摘要；`blocked` 不得改写成 `passed`。 |
| 密钥与配置 | 有 `.env.example`、脱敏规则和公开提交边界。 | 没有接入密钥管理系统、密钥轮换、最小权限账号和配置审计。 | 真实密钥进入 CI secrets 或部署密钥系统；文档和日志只出现变量名，不出现密钥值。 |
| 数据安全 | 有 PostgreSQL/Redis 运行边界、不提交数据产物规则和一次历史恢复演练摘要；当前客户关系模型未引入姓名、电话、证件或联系人字段。 | 当前目标版本缺新鲜恢复证据；内部账户绑定和业务标识仍需访问控制，数据保留、PII 分类、访问审批、导出和删除流程仍不完整。 | 对当前候选完成一次非生产恢复演练；明确所有客户关联字段的敏感级别、保留期、访问者、导出和删除方式。 |
| 旅行社客户与交易域 | 已有租户、门店、成员、门店角色授权、客户生命周期、安全认领、只追加同意记录、主顾问分配、owner/admin 客户转店、门店清理/关闭、产品、报价、订单、内部审核、取消案件、人工补偿结果、独立对账、幂等和执行账本。`0008` 只更新客户当前服务门店，历史邀请、同意、事件、分配和交易保留发生时门店；`inactive` 停止新业务但允许转出、清理、订单审核拒绝和取消收口，全部当前客户（含 `inactive/blocked`）、待邀请、有效分配/授权、待审核和开放业务清零后才可进入不可逆 `closed`。 | 仍没有邀请投递、批量导入、客户通知、真实身份核验、PII 档案、法律级同意或跨门店经理双向交接审批。权限整体仍是应用层行级授权，不是 PostgreSQL RLS。转店不通知客户、不改变外部订单；人工取消也不调用供应商或支付接口。`c574649` / Actions `30606856484` 已验证一次性 PostgreSQL 17 六文件 `34 passed`，但目标环境迁移/恢复、复杂存量数据、并发锁等待和最小权限仍无证据。 | 在目标环境复验 `0001 -> ... -> 0008` 迁移、备份恢复与最小权限，并在隔离 PostgreSQL 补复杂业务数据 downgrade、并发锁等待和事务回滚。任何真实动作必须在 sandbox 通过审批绑定、回调重放、超时、重复请求和故障注入后再单项评估。 |
| Agent 高风险动作 | 内部审核要求订单提交和取消建案时存在排除业务发起人、订单客户的 eligible approver，开放取消案阻止订单送审；待处理订单审核和 `approval_pending` 取消案在撤权时逐业务保留合格替代审批员。客户/订单/审核行锁、修订号和业务快照绑定仍生效，授权写持有门店/成员共享锁，防止并发撤权造成 TOCTOU 竞态。平台审批仍有持久化记录和只追加事件骨架。 | 内部 `approved` 没有绑定平台 `approval_request`，也没有 LangGraph `interrupt/resume`、checkpoint 回写或外部动作恢复。 | 所有真实支付、预订、取消、退款、通知和客户资料导出动作继续默认禁止；上线前必须另行完成平台 HITL 绑定、权限、幂等、补偿和审计。 |
| 外部工具可靠性 | 有 MCP 服务目录、可选/降级口径、工具失败审计、故障 runbook 和一份历史韧性摘要。 | 当前版本缺新鲜供应商验证、熔断、配额监控和长窗口数据；旧验收曾出现约 67.1% 工具失败/兜底。 | 按当前失败/兜底门禁重跑；为每类外部 API 验证超时、重试、降级文案、预算上限和故障处理步骤。 |
| 可观测和告警 | 有 turn 级观测、工具审计摘要和运行预算测试。 | 没有集中日志、指标看板、告警规则、分布式 trace 或值班流程。 | 至少接入集中日志和基础指标告警：错误率、P95 耗时、外部工具失败率、队列/请求积压和 token 估算异常。 |
| 发布与回滚 | 有部署模板、本地/远端命令示例、发布候选冻结检查、发布包 manifest、服务器脚本和历史上线记录。 | 历史执行记录未绑定包含 `0008` 的当前候选；候选冻结、回滚执行、迁移前备份和版本兼容仍需按本次提交确认。 | 每次发布有候选冻结记录、变更单、archive sha256、manifest、服务器脚本 dry-run / execute 摘要、回滚路径、迁移计划、验收摘要和负责人。 |
| 法务与用户边界 | 文档已声明不承诺库存、锁价、支付、出票或履约。 | 缺正式用户协议、隐私政策、免责声明、客服流程和投诉处理。 | 对真实用户开放前必须有可见条款和人工联系渠道。 |

## P1：有限生产能力

| 方向 | 当前证据 | 生产缺口 | 最低验收 |
|---|---|---|---|
| RAG 生命周期 | 有离线召回评测、mixed-corpus safety、安全门和向量库 readiness 文档。 | 缺定期重建、增量更新、索引版本、向量库备份、漂移监控和回滚策略。 | 记录每次 RAG 发布的文档版本、embedding 模型、collection、指标、回滚方式和 safety 结果。 |
| Prompt / 模型治理 | 有阶段 Prompt 规则清单和 AgentOps 版本记录建议。 | 缺 Prompt registry、模型配置 registry、灰度实验、质量对比和一键回滚。 | 每次 Prompt/模型变更都有版本号、影响范围、对比指标、回滚记录和失败门禁。 |
| 评估体系 | 有报告质量、RAG 质量、工具质量、工具失败/兜底预算、运行预算和 acceptance 入口。 | 缺定期线上抽样、人工标注闭环、重复运行分布、失败案例归档和质量趋势看板。 | 建立周级评估批次：固定场景、线上脱敏样本、人工复核、失败原因分类和趋势报告。 |
| 前端工程化 | 有单页前端、结构化报告渲染、导出和浏览器回归。 | 缺构建链路、组件边界、权限路由、可访问性审计、浏览器兼容矩阵和错误上报。 | 建立正式前端构建、错误采集、关键页面 E2E、移动端适配和基本可访问性检查。 |
| 性能与容量 | 有运行预算和工具调用统计。 | 缺压测、容量规划、并发限制、队列削峰和成本预算。 | 对登录、聊天、报告导出、RAG 检索和地图预览做基础压测，并定义并发上限和降级策略。 |
| 安全测试 | 有密钥脱敏和公开边界。 | 缺 SAST、依赖漏洞扫描、接口鉴权测试、SSRF 复核和越权测试。 | CI 或发布前跑依赖漏洞和关键接口鉴权测试；公开攻略抓取等入口复查 SSRF 边界。 |
| 交易运营闭环 | 有支付尝试、履约记录、订单事件，以及平台外人工取消结果和独立对账结构。 | 缺真实供应商/支付适配器、自动对账、财务清分、改签、部分履约、合同/发票、客服工单和服务质量反馈。 | 选一个受控产品完成从报价、审核、沙箱支付、沙箱预订到取消/补偿和对账的可重放验收。 |

## P2：规模化生产能力

| 方向 | 需要补齐的能力 |
|---|---|
| 多环境治理 | development、staging、production 配置完全隔离，环境差异可审计。 |
| 灰度与实验 | 支持按用户、场景、模型版本或 Prompt 版本灰度，不影响全量用户。 |
| 成本治理 | LLM、embedding、外部 API、地图和搜索服务有预算、配额、告警和账单归因。 |
| 业务运营 | 客服后台、人工接管、订单跟进、供应商对账和服务质量反馈。 |
| 合规审计 | 数据处理记录、访问审计、权限审批、合规留痕和删除证明。 |
| 高可用 | 多实例、健康探针、自动恢复、数据库高可用、缓存高可用和灾备演练。 |

## 发布验证清单

发布时分别记录计划、执行和验收结果，并关联 commit 与 release。

| 环节 | 所需记录 |
|---|---|
| 发布候选 | include/defer 决策、代码审查、干净工作区、archive 与 manifest。 |
| 部署执行 | SSH/SCP、sha256 校验、`first-deploy.sh --execute --start-services`、容器状态和 health/readiness。 |
| RAG 与聊天 | `rag_vector_store=configured`、acceptance preflight、live smoke/core。 |
| 业务数据 | 目标 PostgreSQL 迁移、权限、并发、幂等及事务回滚测试。 |
| 交易接入 | sandbox 回调、审批绑定、供应商/支付回执、补偿、资金对账和通知投递。 |
| 备份恢复 | 最新 dump、非生产库恢复、表结构、readiness 和 smoke。 |
| 容量与限流 | 主机快照、采样窗口、并发数、P95、429、供应商配额和长窗口结果。 |
| 密钥与告警 | 轮换及撤销记录、告警投递、预算阈值、事故和回滚演练。 |

当前订单 `approved` 表示内部审核通过；取消 `completed` 表示内部取消流程收口。报告、模拟 `ORDER-` 编号、客户转店及技术同意记录的含义见 [交易域说明](../架构与流程/agency-transaction-domain.md)。

## 建议推进顺序

1. 先冻结当前发布候选并复验 M1：绑定 commit，审阅并执行目标数据库迁移，重跑真实环境 readiness、备份恢复、外部工具门禁、smoke/core 和基础告警；历史快照只作参考。
2. 再验证并扩展旅行社业务链路：`0008` 客户转店和门店清理/关闭已有一次性 PostgreSQL 17 六文件 CI 绿灯；下一步在目标环境复验迁移/恢复、历史门店保留、权限和幂等，并在隔离环境补复杂业务数据失败关闭降级、锁序、并发锁等待和事务回滚。后续继续补批量导入、邀请投递、真实身份与法律级同意，以及来源/目标门店经理双向交接审批。
3. 同步做 Agent 治理硬化：Prompt/模型 registry、RAG 发布版本、验收批次和失败案例归档。
4. 再按单一动作接入 sandbox：支付、预订、退款、通知和客户资料导出必须先完成权限、审批绑定、幂等、回调验签、补偿、对账和故障注入。
5. 最后做规模化能力：灰度、压测、成本治理、高可用、旅行社运营后台和合规审计。

## 相关文档与工具

- [部署输入](production-deployment-inputs.md)、[资源申请](m1-resource-request-pack.md)、[执行输入](m1-execution-input-gap-checklist.md)。
- [候选冻结](m1-release-candidate-freeze.md)、[部署预演](m1-first-deploy-dry-run.md)、[上线清单](m1-launch-checklist.md)、[试运行手册](m1-controlled-trial-runbook.md)。
- [外部 API 故障处理](external-api-failure-runbook.md)、[备份恢复](backup-restore-runbook.md)、[监控告警](monitoring-alerting-runbook.md)、[事故与回滚](incident-response-rollback-runbook.md)。
- [密钥轮换](security-release-key-rotation-runbook.md)、[验收记录](m1-acceptance-record-template.md)。

工具按用途分组：

| 用途 | 入口与执行方式 |
|---|---|
| 资源与发布计划 | `render_m1_resource_request.py`、`check_m1_launch_inputs.py`、`check_release_candidate_freeze.py`、`check_m1_first_deploy_dry_run.py`。 |
| 发布包与首部署 | `build_release_artifact.py` 从干净 HEAD 生成包与 manifest；`deploy/first-deploy.sh` 默认预演，部署使用 `--execute --start-services`。 |
| 运行前置检查 | `check_server_preflight_readiness.py`、`check_backup_restore_readiness.py`、`check_external_api_readiness.py`、`check_monitoring_alerting_readiness.py`、`check_security_release_readiness.py`。 |
| 容量与磁盘 | `collect_server_capacity_snapshot.py`、`collect_docker_disk_cleanup_plan.py`、`collect_docker_build_cache_cleanup_plan.py` 采集状态或计划。清理使用对应 execute 脚本、`--execute` 和批准 token，并复验磁盘。 |
| 备份、告警与回滚证据 | `collect_backup_restore_drill_evidence.py`、`collect_monitoring_alerting_evidence.py`、`collect_incident_rollback_evidence.py` 默认生成计划，执行结果单独归档。 |
| 认证与聊天探针 | `check_probe_auth_readiness.py --execute-login` 验证登录；`collect_live_chat_probe.py --execute` 创建探针会话并运行一轮 SSE，可调用模型和外部 API。 |
| 验收与归档 | `check_m1_deployment_gate.py`、`render_m1_acceptance_record.py`、`collect_m1_smoke_evidence.py`、`collect_m1_go_no_go_evidence.py`、`build_m1_evidence_bundle.py` 汇总结果与签核。 |

执行及原始证据保存在私有目录。`not run` 记录未执行项，`blocked` 记录缺失依赖；go/no-go 汇总中仍有必需项未检查或受阻时，结果为 `no_go`。
