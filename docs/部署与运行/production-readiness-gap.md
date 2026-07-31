# Production Readiness Gap（生产化差距清单）

本文从真实旅行社生产系统视角审视 ZhiXing Travel Planner 当前版本。目标产品是旅行社经营与交付工作台；本文不是演示稿，也不是功能宣传页，而是明确哪些能力有当前代码证据、哪些只有日期化历史证据、哪些仍只是模板或离线验证，以及从当前工作树走向可控试运行和真实交易还需要补什么。

## 结论

当前项目适合作为旅行社 AI 应用工程样板和受控内部工作台：它已经具备状态机、RAG（检索增强生成）、MCP（模型上下文协议）工具、结构化 `report_data`、前端报告、readiness（就绪检查）、评估门禁、轻量观测证据，以及第一阶段旅行社门店、客户生命周期、顾问分配、报价、订单、人工取消结果、独立对账、事件和幂等控制面。

当前项目还不是完整生产系统。主要原因是：

- 交易域当前只完成数据与控制面骨架：客户拒绝/撤回同意或关系停用时可以原子收口内部报价/订单；`0007` 可分岗登记平台外人工取消/财务结果并独立对账，但不会调用供应商取消或退款。真实供应商预订、取消、支付、退款、通知、出票、库存锁定和客服履约尚未接入，并由默认关闭的配置门禁阻断。
- 门店隔离当前由应用服务和查询过滤器执行，不是 PostgreSQL RLS（行级安全策略）；客户关系虽已实现目标账户安全认领与服务端只追加同意记录，但仍不含姓名、电话、证件等 PII（个人可识别信息）档案，也没有邀请投递/通知、真实身份核验、跨门店转移或完整同意合规闭环。
- 当前版本没有一套与 commit 绑定的新鲜生产证据：2026-07-03 的私有快照记录过备份恢复、短窗口探针和事故治理，但它不能自动覆盖当前工作树；密钥托管、集中日志、指标告警和分布式 trace（链路追踪）仍不完整。
- Agent 治理仍偏轻量：Prompt（提示词）和模型版本、工具权限、回放评估、灰度发布和回滚还没有形成生产 registry（注册表）。
- 真实环境验收仍需按当前 commit 现场跑：离线评测或历史 `passed` 不能替代当前向量库 `configured`、acceptance preflight（验收预检）和 live smoke/core（真实链路冒烟/核心验收）。

## 分级定义

| 等级 | 含义 | 当前状态 |
|---|---|---|
| M0 工程样板 | 本地可运行、文档清晰、关键链路有测试和离线验收。 | 规划交付、客户生命周期和交易控制面基本达到；完整 CRM 与真实交易不在此等级结论内。 |
| M1 受控试运行 | 使用真实环境和真实依赖，但只面向内部或少量白名单用户，人工兜底强。 | 2026-07-03 目标版本有一次历史就绪快照；包含 `0007` 的当前候选仍须冻结、绑定 commit 并完整复验。 |
| M2 有限生产 | 支持有限真实用户、稳定部署、数据安全、监控告警、备份恢复和明确人工运营流程。 | 尚未达到。 |
| M3 规模化生产 | 多环境治理、容量规划、成本治理、灰度发布、SLA（服务等级协议）和完整合规闭环。 | 尚未启动。 |

## P0：试运行前阻断项

| 方向 | 当前证据 | 生产缺口 | 最低验收 |
|---|---|---|---|
| 真实环境基线 | 有 `check_runtime_readiness.py`、部署模板、RAG release checklist 和 2026-07-03 历史私有快照。 | 还没有一份绑定当前 commit 的目标环境 readiness 通过记录；真实 Chroma（向量库组件）、PostgreSQL（关系型数据库）、Redis（缓存数据库）、LLM（大语言模型）和关键 MCP 服务需要重新确认。 | 冻结当前候选后，在目标环境运行 production readiness、acceptance preflight 和 smoke，并保留 commit、时间窗和脱敏摘要；`blocked` 不得改写成 `passed`。 |
| 密钥与配置 | 有 `.env.example`、脱敏规则和公开提交边界。 | 没有接入密钥管理系统、密钥轮换、最小权限账号和配置审计。 | 真实密钥进入 CI secrets 或部署密钥系统；文档和日志只出现变量名，不出现密钥值。 |
| 数据安全 | 有 PostgreSQL/Redis 运行边界、不提交数据产物规则和一次历史恢复演练摘要；当前客户关系模型未引入姓名、电话、证件或联系人字段。 | 当前目标版本缺新鲜恢复证据；内部账户绑定和业务标识仍需访问控制，数据保留、PII 分类、访问审批、导出和删除流程仍不完整。 | 对当前候选完成一次非生产恢复演练；明确所有客户关联字段的敏感级别、保留期、访问者、导出和删除方式。 |
| 旅行社客户与交易域 | 已有租户、门店、成员、门店角色授权、客户生命周期、安全认领、只追加同意记录、主顾问分配、产品、报价、订单、内部审核、取消案件、人工补偿结果、独立对账、幂等和执行账本。`0005/0006` 固化安全认领与服务端证据；`0007` 增加平台外人工取消结果分岗登记、审计员独立观察金额、取消期账本冻结、只追加门禁和订单/案件一致性，还冻结 `agency_membership` 的账户/旅行社身份绑定，并在数据库层复验取消审批人的 active 旅行社、门店、成员和授权。旅行社 API 提交完成后才返回成功。 | 仍没有邀请投递、批量导入、客户通知、真实身份核验、PII 档案、法律级同意、客户跨门店转移和门店关闭。权限整体仍是应用层行级授权，不是 PostgreSQL RLS；`0007` 仅增加定向数据库不变量。人工取消的外部引用与证据只保存 SHA-256 摘要，不调用供应商或支付接口，也不等于自动补偿/对账；客户生命周期先改变订单时，旧 `approval_pending` 取消案件需人工拒绝后按新状态重建，尚无 `superseded` 自动收口。`e17b97d` / Actions `30602058425` 已验证默认 `1841 passed, 49 deselected` 与 PostgreSQL 17 `25 passed`，但目标环境证据仍缺失。 | CI 已验证 `0001 -> ... -> 0007`、旧时间字段回填、成员身份改绑拒绝、建案/送审的合格审批员排除规则、开放取消案阻止送审、逐业务替代审批员撤权门禁、取消审批人资格、案件/订单延迟约束、支付/履约账本冻结、只追加、自审/自对账拒绝、独立观察金额和最新结果完成语义；仍须在目标环境复验迁移、最小权限、锁等待和事务回滚。任何真实动作必须在 sandbox 通过审批绑定、回调重放、超时、重复请求和故障注入后再单项评估。 |
| Agent 高风险动作 | 内部审核要求订单提交和取消建案时存在排除业务发起人、订单客户的 eligible approver（合格审批员），开放取消案阻止订单送审；待处理订单审核和 `approval_pending` 取消案在撤权时逐业务保留合格替代审批员。客户/订单/审核行锁、修订号和业务快照绑定仍生效，授权写持有门店/成员共享锁，防止并发撤权造成 TOCTOU（检查与使用时序差）竞态。平台审批仍有持久化记录和只追加事件骨架。 | 内部 `approved` 没有绑定平台 `approval_request`，也没有 LangGraph `interrupt/resume`、checkpoint 回写或外部动作恢复。 | 所有真实支付、预订、取消、退款、通知和客户资料导出动作继续默认禁止；上线前必须另行完成平台 HITL（人类在环）绑定、权限、幂等、补偿和审计。 |
| 外部工具可靠性 | 有 MCP 服务目录、可选/降级口径、工具失败审计、故障 runbook 和一份历史韧性摘要。 | 当前版本缺新鲜供应商验证、熔断、配额监控和长窗口数据；旧验收曾出现约 67.1% 工具失败/兜底。 | 按当前失败/兜底门禁重跑；为每类外部 API 验证超时、重试、降级文案、预算上限和故障处理步骤。 |
| 可观测和告警 | 有 turn 级观测、工具审计摘要和运行预算测试。 | 没有集中日志、指标看板、告警规则、分布式 trace 或值班流程。 | 至少接入集中日志和基础指标告警：错误率、P95 耗时、外部工具失败率、队列/请求积压和 token 估算异常。 |
| 发布与回滚 | 有部署模板、本地/远端命令示例、发布候选冻结检查、发布包 manifest、服务器脚本和历史上线记录。 | 历史执行记录未绑定包含 `0007` 的当前候选；候选冻结、回滚执行、迁移前备份和版本兼容仍需按本次提交确认。 | 每次发布有候选冻结记录、变更单、archive sha256、manifest、服务器脚本 dry-run / execute 摘要、回滚路径、迁移计划、验收摘要和负责人。 |
| 法务与用户边界 | 文档已声明不承诺库存、锁价、支付、出票或履约。 | 缺正式用户协议、隐私政策、免责声明、客服流程和投诉处理。 | 对真实用户开放前必须有可见条款和人工联系渠道。 |

## P1：有限生产能力

| 方向 | 当前证据 | 生产缺口 | 最低验收 |
|---|---|---|---|
| RAG 生命周期 | 有离线召回评测、mixed-corpus safety、安全门和向量库 readiness 文档。 | 缺定期重建、增量更新、索引版本、向量库备份、漂移监控和回滚策略。 | 记录每次 RAG 发布的文档版本、embedding 模型、collection、指标、回滚方式和 safety 结果。 |
| Prompt / 模型治理 | 有阶段 Prompt 规则清单和 AgentOps 版本记录建议。 | 缺 Prompt registry、模型配置 registry、灰度实验、质量对比和一键回滚。 | 每次 Prompt/模型变更都有版本号、影响范围、对比指标、回滚记录和失败门禁。 |
| 评估体系 | 有报告质量、RAG 质量、工具质量、工具失败/兜底预算、运行预算和 acceptance 入口。 | 缺定期线上抽样、人工标注闭环、重复运行分布、失败案例归档和质量趋势看板。 | 建立周级评估批次：固定场景、线上脱敏样本、人工复核、失败原因分类和趋势报告。 |
| 前端工程化 | 有单页前端、结构化报告渲染、导出和浏览器回归。 | 缺构建链路、组件边界、权限路由、可访问性审计、浏览器兼容矩阵和错误上报。 | 建立正式前端构建、错误采集、关键页面 E2E、移动端适配和基本可访问性检查。 |
| 性能与容量 | 有运行预算和工具调用统计。 | 缺压测、容量规划、并发限制、队列削峰和成本预算。 | 对登录、聊天、报告导出、RAG 检索和地图预览做基础压测，并定义并发上限和降级策略。 |
| 安全测试 | 有密钥脱敏和公开边界。 | 缺 SAST（静态安全扫描）、依赖漏洞扫描、接口鉴权测试、SSRF（服务端请求伪造）复核和越权测试。 | CI 或发布前跑依赖漏洞和关键接口鉴权测试；公开攻略抓取等入口复查 SSRF 边界。 |
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

## 不能用演示证据替代的生产验收

| 演示证据 | 不能替代 | 生产验收应看 |
|---|---|---|
| `render_m1_resource_request.py` 输出 | 资源已经准备完成。 | 服务器、密钥系统、数据库、Redis、RAG、备份、监控和验收 smoke 的目标环境证据。 |
| `check_release_candidate_freeze.py` `blocked` 输出 | 可以直接打包或部署。 | 按 workstream 完成 include/defer 决策、提交发布候选，让 Git 工作区干净后再生成发布包。 |
| `check_release_candidate_freeze.py` `passed` 输出 | 代码审查、服务器部署或线上验收已完成。 | 发布包 manifest、服务器侧 sha256 校验、`first-deploy.sh --execute --start-services`、health/readiness 和 go/no-go 证据。 |
| `check_m1_first_deploy_dry_run.py` `passed` | SSH 已连通、发布包已上传或服务已启动。 | 真实 SSH/SCP 执行记录、远端备份/解压、容器状态、health/readiness 和 go/no-go 证据。 |
| `build_release_artifact.py` `passed` | 服务器已部署成功。 | SCP 上传记录、服务器侧 `first-deploy.sh --execute` 摘要、容器状态、health/readiness 和 go/no-go 证据。 |
| `deploy/first-deploy.sh` dry-run | 服务器已经部署完成。 | sha256 校验通过、`--execute --start-services` 执行摘要、`docker compose ps`、health/readiness、runtime readiness 和 smoke 证据。 |
| 离线 RAG 评测 `passed` | 真实向量库已配置、线上 Agent 已通过。 | `rag_vector_store=configured`、acceptance preflight、live smoke/core。 |
| 前端导出 HTML | 订单、合同、支付或履约凭证。 | 真实订单系统、支付网关、合同模板、审计流水和人工确认。 |
| 交易域模型、迁移或单元测试通过 | 真实供应商、支付和履约已经接通。 | 目标 PostgreSQL 迁移记录、租户鉴权与并发测试、sandbox 回调/补偿证据、供应商控制台状态和对账结果。 |
| 内部订单 `approved` | 已锁库存、已收款、已预订或可履约。 | 平台外部动作审批、供应商/支付适配器回执、幂等与补偿记录、对账及人工复核。 |
| 客户停用后的内部 `cancelled` / `cancellation_pending` | 供应商预订已取消、退款已到账或客户已收到通知。 | 供应商取消回执、支付退款回执、通知投递、对账结果及人工处理记录；当前事件明确记录未触发外部动作。 |
| 取消案件 `completed` | 系统已经调用供应商取消、完成银行退款或通知客户。 | 当前只证明订单已在平台内进入 `cancelled`：无外部暴露时可能是审批后直接完成；有必需动作时才额外证明各类最新成功人工结果由不同审计人员核验为 `matched`。生产仍需原始外部回执、验签、资金对账、通知投递和跨系统一致性。 |
| `mock_checkout` 或 `ORDER-` 编号 | 已创建真实 `agency_order`、已收款或已预订。 | 受控交易 API 的持久化订单、审批事件、支付/供应商回执及人工复核。 |
| 门店可见性单元测试通过 | 数据库已经启用强制行级隔离。 | 当前只是应用层查询过滤与对象授权；生产需最小权限数据库账号、系统化越权测试，并评估 PostgreSQL RLS 或策略引擎。 |
| claim token 摘要或 `server_canonical` 同意记录已保存 | 已完成真实身份核验，或已取得合法、有效且可举证的客户同意。 | 当前只证明目标平台账户持有一次性凭证并在认证会话中提交决定；生产还需邀请投递证明、真实身份核验、正式条款/隐私政策、原始证据保全、撤回通知、留存期限和法务审查。 |
| turn 级观测 | 完整 APM 或分布式 trace。 | 集中日志、指标看板、告警、trace 和事故复盘。 |
| `.env.example` | 生产密钥安全。 | 密钥管理、轮换、权限和泄露响应。 |
| 安全发布 readiness `passed` | 真实密钥有效、旧 key 已撤销、泄露演练已完成。 | 供应商控制台状态、轮换记录、撤销记录和脱敏演练摘要。 |
| readiness 模板 | 真实环境可用。 | 目标环境真实执行结果和脱敏摘要。 |
| 服务器 preflight 或 live probe `passed/degraded` | 当前版本已经可正式放量。 | `docker compose ps`、health endpoint、runtime readiness、acceptance smoke 和磁盘容量证据；磁盘高水位只能作为 `conditional_go`，不能作为正式放量。 |
| Docker 磁盘清理计划 `degraded/passed` | 已经释放磁盘空间。 | 单独批准后的清理或扩容执行记录、再次 live probe / server preflight 通过记录；计划里的镜像大小是虚拟估算，可能重复计算共享层。 |
| Docker 清理执行 dry-run `passed` | 已经删除镜像或释放空间。 | 带 `--execute` 和批准 token 的执行记录、被跳过/删除镜像摘要、执行后的磁盘复验；dry-run 只证明候选和保护逻辑可执行。 |
| 服务器容量快照 `passed/degraded` | 已完成压测或证明高并发能力。 | 低风险并发探针、真实 chat 链路压测、长时间 soak、外部 API 配额/超时证据和容量拐点记录；容量快照只证明当时主机与容器资源状态。 |
| 备份恢复证据里有最新 dump | 数据已完成恢复演练。 | 非生产库实际恢复、readiness、acceptance smoke 和脱敏演练记录。 |
| `pg_restore --list` `passed` | 数据库恢复成功。 | `pg_restore` 到非生产库、表结构检查、应用 readiness 和 smoke。 |
| 监控告警 readiness `passed` | 真实告警已送达、成本封顶已生效。 | 告警投递记录、指标看板、预算阈值和事故演练摘要。 |
| `collect_monitoring_alerting_evidence.py` 默认输出 | 告警投递和指标看板已可用。 | 显式执行告警投递演练和指标声明后的脱敏摘要。 |
| `collect_incident_rollback_evidence.py` 默认输出 | 已完成事故响应或回滚演练。 | 显式执行负责人、回滚演练、事故复盘和回滚后 smoke 的脱敏摘要。 |
| 外部 API readiness `passed` | 真实供应商已从目标服务器调用成功。 | runtime readiness、acceptance smoke、供应商控制台状态和脱敏调用摘要。 |
| `collect_m1_smoke_evidence.py` 默认输出 | 目标环境真实通过。 | 显式执行 `--check-health-url --run-gate --run-acceptance-smoke` 后的脱敏摘要。 |
| `collect_m1_go_no_go_evidence.py` 默认输出 | 上线前可以放行。 | 纳入全部声明证据、server preflight 磁盘证据和 live smoke 后的 `decision`；任一请求 section 为 `not_checked` 或 `blocked` 时必须 `no_go`，磁盘 `warning` 只能作为带清理/扩容计划的 `conditional_go`。 |
| 单页前端原型 | 完整生产前端。 | 构建、权限、错误上报、可访问性、兼容性和发布流程。 |

## 建议推进顺序

1. 先冻结当前发布候选并复验 M1：绑定 commit，审阅并执行目标数据库迁移，重跑真实环境 readiness、备份恢复、外部工具门禁、smoke/core 和基础告警；历史快照只作参考。
2. 再验证并扩展旅行社业务链路：取消域已取得默认与 PostgreSQL 17 CI 双绿，下一步到目标环境复验成员身份冻结、合格审批员排除、开放取消案送审冲突、逐业务撤权保护、审批人 active 资格、锁序、修订号、幂等、岗位分离、最新结果对账和只追加事件；并继续补批量导入、邀请投递、真实身份与法律级同意、跨门店转移和门店关闭。
3. 同步做 Agent 治理硬化：Prompt/模型 registry、RAG 发布版本、验收批次和失败案例归档。
4. 再按单一动作接入 sandbox：支付、预订、退款、通知和客户资料导出必须先完成权限、审批绑定、幂等、回调验签、补偿、对账和故障注入。
5. 最后做规模化能力：灰度、压测、成本治理、高可用、旅行社运营后台和合规审计。

M1 受控试运行所需的服务器、密钥、数据、验收和运维输入见 `docs/部署与运行/production-deployment-inputs.md`，资源申请包见 `docs/部署与运行/m1-resource-request-pack.md`，执行前私有输入缺口清单见 `docs/部署与运行/m1-execution-input-gap-checklist.md`，发布候选冻结见 `docs/部署与运行/m1-release-candidate-freeze.md`，首次部署预演见 `docs/部署与运行/m1-first-deploy-dry-run.md`，上线前总检查表见 `docs/部署与运行/m1-launch-checklist.md`，执行步骤见 `docs/部署与运行/m1-controlled-trial-runbook.md`，外部 API 故障处理见 `docs/部署与运行/external-api-failure-runbook.md`，备份和恢复演练见 `docs/部署与运行/backup-restore-runbook.md`，监控告警见 `docs/部署与运行/monitoring-alerting-runbook.md`，事故响应和回滚演练见 `docs/部署与运行/incident-response-rollback-runbook.md`，安全发布和密钥轮换见 `docs/部署与运行/security-release-key-rotation-runbook.md`，验收记录模板见 `docs/部署与运行/m1-acceptance-record-template.md`。`scripts/render_m1_resource_request.py` 只把服务器、DNS/TLS、运行配置、密钥变量、RAG 数据、外部 API、验收、备份、监控和回滚需求整理成可发送资源申请包，不证明这些资源已经存在；`docs/部署与运行/m1-execution-input-gap-checklist.md` 只把真实执行前仍需准备的 SSH 目标、公网 URL、部署目录、私有证据目录、probe 凭据、备份目录、预算、验收窗口和负责人收束成检查表，不证明这些私有输入已经齐备；`scripts/check_release_candidate_freeze.py` 只按 Git 工作区状态归类发布候选，不读取文件内容、不证明代码审查或服务器部署已经完成；`scripts/check_m1_first_deploy_dry_run.py` 只做本地部署预演和命令计划，不 SSH、不 SCP、不生成发布包、不启动服务，不能替代真实上传、远端备份、容器启动或 health 验收；`scripts/build_release_artifact.py` 只从干净 Git `HEAD` 生成 archive 和 manifest，记录 commit、tree、tracked file count 和 archive `sha256`，不证明服务器已收到发布包或服务已启动；`deploy/first-deploy.sh` 是服务器侧首部署脚本，默认只 dry-run，提供 `--archive-sha256` 时会校验上传包，显式 `--execute --start-services` 后才会解压 release、切换 `current` 并启动 Compose，但 dry-run 本身不证明服务器已部署成功；`scripts/check_m1_launch_inputs.py` 只证明 M1 非密钥输入已声明；`scripts/check_server_preflight_readiness.py` 只证明服务器、部署目录、域名、TLS、端口、反向代理和 Docker 状态已经声明，显式开启时可探测 Docker、部署目录和公开 health endpoint，不证明当前版本已经部署成功或服务依赖健康；`scripts/collect_docker_disk_cleanup_plan.py` 只通过 SSH 做只读 Docker 镜像候选清理计划，保护所有容器引用镜像，不执行删除或 prune，镜像大小只是虚拟估算；`scripts/execute_docker_disk_cleanup.py` 默认只 dry-run，真实删除必须显式传入 `--execute` 和批准 token，且再次跳过所有容器引用镜像，不 prune 容器、卷、日志、备份、`.env` 或向量库；`scripts/collect_docker_build_cache_cleanup_plan.py` 只通过 SSH 读取 `docker system df` 的 build-cache 聚合大小和可回收空间，不删除 build cache 或任何运行资源；`scripts/execute_docker_build_cache_cleanup.py` 默认只 dry-run，真实清理必须显式传入 `--execute` 和批准 token，只运行 `docker builder prune -a -f`，不运行 `docker system prune`，不删除镜像、容器、卷、日志、备份、`.env` 或向量库；`scripts/collect_server_capacity_snapshot.py` 只做 SSH 只读容量快照，记录 CPU、负载、内存、磁盘、容器状态和单次 `docker stats`，不证明真实高并发或长时间稳定性；`scripts/check_backup_restore_readiness.py` 只证明备份目标、目录、保留策略和 RAG 恢复策略已经声明，显式开启时可验证目录可写；`scripts/collect_backup_restore_drill_evidence.py` 默认只输出备份恢复演练计划，显式开启时可记录最新 dump 元数据、`pg_restore --list` catalog 可读性和恢复演练状态声明，但仍不等于非生产库完整恢复；`scripts/check_external_api_readiness.py` 只证明必需/可选外部 API、配额预算、控制台负责人、支持渠道、降级策略和 timeout/retry 策略已经声明，不证明真实供应商从目标服务器调用成功、配额实际生效或数据可用于生产履约；`scripts/check_monitoring_alerting_readiness.py` 只证明监控供应商、告警渠道和成本预算已经声明，显式开启时可探测公开 health endpoint，不证明真实告警投递、指标看板或成本封顶已生效；`scripts/collect_monitoring_alerting_evidence.py` 默认只输出监控告警证据计划，显式开启时可记录 health/readiness 投递声明和错误率、P95、工具失败、成本、备份、日志脱敏监控声明，但不会主动发送告警，也不证明完整 APM；`scripts/collect_incident_rollback_evidence.py` 默认只输出事故/回滚执行计划，显式开启时可记录负责人、回滚目标、回滚后 health/gate/smoke 和事故复盘声明，但不会执行回滚、启动服务或恢复数据；`scripts/check_security_release_readiness.py` 只证明密钥托管、轮换周期、泄露响应负责人、来源限制和高风险动作关闭声明齐备，不证明真实密钥有效、旧 key 已撤销、最小权限已在供应商控制台生效或泄露演练已完成；`scripts/check_m1_deployment_gate.py` 只聚合公开边界、发布候选冻结、M1 输入、服务器 preflight、备份前置、外部 API 前置、监控告警前置、安全发布前置、Compose 配置和 readiness；`scripts/render_m1_acceptance_record.py` 只把门禁结果整理成脱敏记录；`scripts/collect_m1_smoke_evidence.py` 默认只输出部署后 smoke 执行计划，只有显式开启 health、gate 和 acceptance smoke 后才记录目标环境脱敏摘要；`scripts/collect_m1_go_no_go_evidence.py` 只做最终证据汇总和 `decision` 判定，默认计划模式不能放行，请求 section 只要仍是 `not_checked` 或 `blocked` 就必须 `no_go`。它们都不证明真实密钥、服务器健康、备份恢复演练或在线验收通过。这些文档只记录资源类型、变量名和脱敏验收口径，不记录真实密钥或真实客户资料。

`scripts/check_docker_build_cache_cleanup_approval.py` 只读取 build cache 计划、dry-run、容量快照和私有审批记录，缺审批记录时只能输出 `ready_for_explicit_approval`；`scripts/check_docker_build_cache_post_cleanup.py` 只读取 build cache 执行报告、容量快照和恢复演练可行性，用于判断清理后是否仍需扩容或 Docker data-root 迁移。二者都不连接 SSH、不读取 `.env`、不删除缓存或运行资源。

`scripts/check_probe_auth_readiness.py` 是 live chat 前的低风险认证检查，默认只确认当前进程是否提供 probe token 或 probe 账号密码，不读取 `.env`。显式 `--execute-login` 后只验证 `/api/v1/users/login` 和 `/api/v1/users/me`，不创建会话、不调用 SSE 聊天、不调用 LLM 或外部供应商、不写聊天消息，也不回显公网 URL、token、账号、密码、user id 或响应正文。它只能证明 probe 认证路径可用，不能证明真实聊天、并发、长稳、支付、预订、库存锁定、出票或履约。

`scripts/collect_live_chat_probe.py` 是认证聊天链路的单轮 SSE 探针，默认只输出 `not_checked` 执行计划；显式 `--execute` 后才会创建探针会话、写入运行时消息并可能调用 LLM 或外部 API。它支持已有 bearer token，也支持用已有 probe 账号密码先调用登录接口换取短期 token。它不回显公网 URL、access token、账号、密码、prompt、会话 id 或模型回复正文，只能证明采样窗口内一轮认证聊天链路完成，不能证明聊天高并发、长稳、完整用户体系、真实支付、预订、库存锁定、出票或履约。

`scripts/build_m1_evidence_bundle.py` 只把私有 go/no-go JSON 重新脱敏、渲染摘要并写出 manifest 哈希清单，默认禁止输出到 Git 工作区。它不执行 live probe、不连接 SSH、不读取 `.env`、不启动服务、不做备份恢复或回滚；因此它只能证明“已有证据被归档并可复核”，不能替代真实部署、health/readiness、smoke、认证聊天或 PostgreSQL/Redis 运行验收。

生产化判断口径应保持保守：没有真实运行证据就写 `not run`，缺必需依赖就写 `blocked`，局部能力可用就写具体层级，不写笼统的“生产可用”。
