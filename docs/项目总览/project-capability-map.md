# Project Capability Map（项目能力答疑地图）

这份文档把 AI-Agent（人工智能智能体）项目常见问题映射到项目回答、代码定位、可运行命令和风险边界。项目目标业务是旅行社经营与交付工作台；当前实现是“规划交付链路 + 门店/客户生命周期控制面 + 第一阶段交易数据控制面”。回答时优先讲“设计取舍”和“可验证证据”，避免只说概念，也不能把目标形态当成当前已经上线的能力。

## 快速总览

| 常见问题 | 一句话回答 | 代码定位 | 验证命令 | 风险边界 |
|---|---|---|---|---|
| 这是不是普通 RAG 问答？ | 不是。RAG（检索增强生成）只是证据来源之一，主链路由状态机、工具调用、MCP（模型上下文协议）和最终 `report_data`（结构化报告数据）交付组成。 | `app/core/workflow.py`、`app/tools/state_transition.py`、`app/reports/` | `.\.venv\Scripts\python -m pytest tests\test_report_contract_module.py -q` | 不把检索片段直接当成最终事实。 |
| Agent 能力怎么编排？ | 主控 Travel Agent（旅行智能体）负责阶段推进；目的地 Router（路由器）处理攻略和天气；交通 Coordinator（协调器）直接编排航班、高铁、自驾查询工具。 | `app/agents/handoffs/travel_agent.py`、`app/agents/routers/destination_router.py`、`app/agents/subagents/transport_coordinator.py` | `.\.venv\Scripts\python -m pytest tests\test_destination_router.py tests\test_flight_query_tool.py -q` | 主流程不是“每阶段一个 Agent”，交通也没有再分发到三个方式子 Agent。 |
| 状态机在哪里？ | `TravelState` 保存结构化状态；`free_planning` 用 `current_step` 控制八个逻辑阶段，`agency_plan` 用 `agency_step` 控制五个逻辑阶段。主链路由 `create_agent`、中间件和迁移工具推进，目的地 Router 才是显式 `StateGraph`。 | `app/core/state.py`、`app/core/workflow.py`、`app/agents/handoffs/step_config.py`、`app/tools/state_transition.py` | `.\.venv\Scripts\python -m pytest tests\test_workflow_maintainability.py tests\test_step_prompt_rendering.py -q` | 改阶段必须同步状态、prompt（提示词）、工具、前端进度台和测试。 |
| 省心方案和自由规划怎么分流？ | 首轮先问“省心方案 / 个性化旅游规划”；省心方案走产品匹配和方案草案，个性化旅游规划走交通、住宿、餐饮等逐项状态机。 | `app/api/v1/chat.py`、`app/core/intent.py`、`app/core/middleware.py`、`app/agents/handoffs/step_config.py` | `.\.venv\Scripts\python -m pytest tests\test_chat_report_metadata.py tests\test_intent_detection.py -q` | 省心方案不应漂回自由规划交通/住宿阶段。 |
| 首轮为什么能快？ | API（应用程序接口）层先走本地快路径，解析首句事实并问规划方式；不创建完整 Travel Agent，不加载 MCP（模型上下文协议）工具。 | `app/api/v1/chat.py` | `.\.venv\Scripts\python -m pytest tests\test_chat_report_metadata.py -q` | 快路径只处理分流和基础事实，复杂方案仍交给 Agent。 |
| 工具怎么避免乱调？ | `StepConfigMiddleware` 按工作流和阶段注入工具；省心方案使用独立白名单，默认移除交通/酒店实时查询和选择工具。 | `app/core/middleware.py`、`app/agents/handoffs/step_config.py` | `.\.venv\Scripts\python -m pytest tests\test_step_prompt_rendering.py tests\test_intent_detection.py -q` | 用户明确要求实时查交通或酒店时，才临时开放对应工具。 |
| 外部能力为什么用 MCP？ | MCP 把天气、搜索、地图、铁路、航班和酒店能力统一为 Agent 可调用工具，并通过服务级缓存、重试和降级避免单点拖垮主链路。 | `app/mcp_core/client.py`、`app/tools/mcp_tools.py` | `.\.venv\Scripts\python -m pytest tests\test_mcp_client_config_unit.py -q` | 外部服务不可用时不能伪造真实查询结果。 |
| RAG 怎么保证旅行社业务感？ | 内部知识库按产品、SOP（标准作业流程）、报价、风险和报告标准组织；产品化样板支持目的地级弱匹配，例如只说“想去新疆”也能召回新疆省心路线候选。 | `data/documents/internal/`、`app/tools/rag_tools.py`、`app/evaluation/rag_quality.py`、`app/evaluation/rag_retrieval.py`、`docs/RAG与知识库/rag-demo-evaluation-guide.md`、`docs/RAG与知识库/rag-vectorstore-readiness.md` | `.\.venv\Scripts\python scripts\validate_rag_knowledge.py`；`.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --json` | 离线召回 passed 不等于真实 Chroma 向量库 configured，也不等于线上 Agent passed。 |
| 方案预算和旅行社报价怎么区分？ | `report_data` 中的预算按真实工具价、规则估算、兜底估算和待核验项表达；`agency_quote` 则保存租户、客户、金额、有效期、快照、`revision` 和 `payload_hash`。二者必须显式转换，不能由模型文本自动形成正式报价。 | `app/agency/pricing_rules.py`、`app/reports/builder.py`、`app/models/agency_transaction.py`、`docs/架构与流程/agency-transaction-domain.md` | `uv run python -m pytest -q tests/test_report_quality_evaluation.py tests/test_agency_transaction_models.py` | 报价表不代表供应商库存已确认、价格已锁定或客户已付款。 |
| 旅行社客户生命周期做到哪一步？ | 20 个门店/客户操作覆盖门店授权、线下潜客、目标账户认领邀请、客户认领、固定技术告知读取、服务端同意、激活/停用、主顾问分配和只追加事件。认领凭证为 256-bit 高熵、24 小时过期、可撤销、单次使用且数据库只存 SHA-256 摘要；只有已登录目标账户能认领，同一旅行社同一目标同一时刻最多一条待处理邀请。认证客户端先读取告知 Markdown/版本/摘要/schema/渠道，提交预期版本/摘要防止 stale notice（过期告知），证据仍由服务端生成并只追加。 | `app/models/agency_customer_lifecycle.py`、`app/models/agency_customer_identity.py`、`app/agency/customer_claim_service.py`、`app/agency/customer_consent.py`、`app/agency/customer_transaction_settlement.py`、`app/api/v1/agency_customers.py`、`alembic/versions/20260730_0005_agency_customer_invitation_claim.py` | `uv run python -m pytest -q tests/test_customer_claim_tokens.py tests/test_agency_customer_claim_service.py tests/test_agency_customer_lifecycle_api.py tests/test_agency_customer_transaction_settlement.py` | 这是应用层行级授权，不是 PostgreSQL RLS；原始 token 只在首次签发提交成功的响应返回，幂等重放不返 token，丢失需撤销重发。legacy 认领会重置旧同意并先停用原 active 关系。仍没有批量导入、邀请投递/通知、真实身份核验、PII 档案、法律级同意、跨门店转移或门店停用/关闭 API。 |
| 旅行社交易域做到哪一步？ | 已加入供应商产品、报价、订单、内部审核、只追加订单事件、幂等记录和执行账本；13 个交易操作覆盖报价、订单提交和订单门店专职审批员批准/拒绝。`0004` 数据库触发器固化报价/订单绑定，复验客户/门店、有效期和订单/报价快照一致性，强制 `revision + 1`、合法状态迁移、外部动作关闭及订单/审核终态成对提交；写路径采用 `customer -> branch -> quote/order` 锁序。 | `app/models/agency_transaction.py`、`app/models/agency_order_review.py`、`app/agency/transaction_service.py`、`app/agency/order_review_service.py`、`app/agency/transaction_locking.py`、`app/api/v1/agency_transactions.py`、`alembic/versions/20260726_0004_agency_customer_lifecycle.py` | `uv run python -m pytest -q tests/test_agency_transaction_models.py tests/test_agency_transaction_policy.py tests/test_agency_transaction_api.py tests/test_agency_customer_transaction_settlement.py` | `approved` 仅为内部审核；已有客户停用的内部收口，但没有通用取消/人工处理入口，也没有供应商预订/取消、支付/退款、通知、对账和履约闭环。 |
| HITL 做到哪一步？ | 交易域已有确定性内部订单审核：门店至少有一名有效专职 `approver` 才能提交订单，提交后不能撤掉最后一名审批员；只有该角色可读写本门店审核，owner/admin 不能代替，客户或发起人不能自审。批准还会重新锁定并校验客户仍为 `secure_claim + active + granted + server_canonical`，客户停用后只能拒绝保留中的审核，且拒绝前客户关系不能重新激活。平台 Approval 仍只提供敏感动作记录、事件、角色权限和 readiness。 | `app/models/agency_order_review.py`、`app/agency/order_review_service.py`、`app/core/approval.py`、`app/api/v1/approvals.py`、`docs/治理与可观测/approval-governance.md` | `uv run python -m pytest -q tests/test_agency_order_review_service.py tests/test_agency_transaction_api.py tests/test_approval_governance.py` | 内部审核没有绑定平台 `approval_request`，也没有 LangGraph `interrupt/resume`；通过或拒绝审核都不会执行供应商、支付、退款或通知动作。 |
| 可观测性有什么？ | 聊天链路记录 turn（轮次）级观测：`first_token_seconds`、`total_elapsed_seconds`、工具调用、失败、fallback（兜底）和 token 估算；AgentOps 文档把它和工具审计、readiness/preflight/acceptance 摘要串成轻量复盘链。 | `app/core/observability.py`、`app/api/v1/chat.py`、`app/evaluation/runtime_metrics.py`、`docs/治理与可观测/agentops-replay-versioning.md` | `.\.venv\Scripts\python -m pytest tests\test_runtime_metrics.py -q` | `first_token_seconds` 只表示任意首个助手片段，可能只是固定 ACK（确认收到）；它不等于 LLM 有意义内容或完整处理完成，必须与总耗时一起解释。当前也不是完整分布式 trace 或 APM。 |
| 验收门禁怎么做？ | `acceptance_gate` 聚合报告质量、RAG 质量、工具治理、运行预算和内部证据，运行预算还会约束工具失败数、失败率和 fallback 数。 | `app/evaluation/acceptance_gate.py`、`app/evaluation/runtime_metrics.py`、`scripts/run_evaluation_scenarios.py` | `.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run` | 普通场景默认不允许工具失败/fallback，只有两个专门降级场景显式放宽；即便 `passed` 也不等于轨迹最优、重复稳定或完整过程评估。 |
| CI/CD（持续集成/持续交付） 如何覆盖？ | 默认 CI 跑编译、知识库校验、测试收集、本地回归和前端验证；独立 PostgreSQL 17 job 运行交易、客户生命周期、客户认领和门店权限场景。实现候选 [`20ff715`](https://github.com/apearlinspring/langgraph-travel-planner/commit/20ff71592096dfb4fc718cef050832a745bfe174) 的 [运行 30534862434](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434) 曾得到默认 `1713 passed, 34 deselected` 和 PostgreSQL `10 passed`（3+5+2），但只覆盖 `0004`。 | `.github/workflows/ci.yml`、`.github/workflows/staging-smoke.yml` | `.\.venv\Scripts\python -m pytest tests\test_ci_workflows.py -q` | `0005` 尚需新的 CI 结果；一次性 CI 数据库证据也不能替代目标环境迁移、恢复、锁等待和供应商故障验证。 |
| 前端怎么证明报告可交付？ | 前端优先消费 `report_data`，展示规划模式、预算、待核验、方案依据、地图路线、复制摘要和导出 HTML（超文本标记语言）。 | `frontend/app.js`、`frontend/zhixing.html`、`docs/前端与演示/frontend-report-experience.md`、`docs/前端与演示/report-data-delivery-contract.md` | `node scripts\verify_frontend_report_renderer.js`；`node scripts\verify_frontend_browser_regression.js` | 前端是单页原型；导出件不是支付、预订、锁价或履约凭证。 |
| 现在能算生产系统吗？ | 不能。截至 2026-07-03 的仓库外私有采样曾记录一次 M1 受控试运行部署、健康检查、数据库/缓存、恢复演练、短窗口探针和单轮 live chat 证据；这些是历史目标版本快照，不代表新增 `0005` 候选仍就绪。安全认领和服务端同意记录也只证明平台内控制面存在，不证明真实身份或法律合规。 | `docs/部署与运行/m1-controlled-trial-status.md`、`docs/部署与运行/production-readiness-gap.md`、`docs/架构与流程/agency-transaction-domain.md`、`docs/部署与运行/m1-controlled-trial-runbook.md` | `uv run python scripts\check_runtime_readiness.py --target production --json`；在目标版本和目标环境重新执行 migration review、release freeze、go/no-go、health/readiness 与 acceptance smoke | 当前公开状态应写成“目标业务是旅行社，客户与交易控制面已建立，历史 M1 证据可追溯，新增版本与真实交易均待验收”；不能承诺真实身份核验、法律合规、真实履约、长时间压测、多机高可用、PITR、异地灾备或供应商 SLA。 |

## 当前边界与改进路线

当前项目已经具备 Agent 应用骨架，以及旅行社门店、客户生命周期、顾问分配和交易数据控制面；仓库外留有截至 2026-07-03 的 M1 受控试运行历史证据。业务域覆盖多租户、门店授权、线下潜客、目标账户安全认领、固定告知读取、服务端规范化同意记录、关系激活/停用、主顾问分配、客户停用内部交易收口、产品、报价、订单、绑定式内部审核、事件、修订号、负载哈希和幂等；`0004` 用数据库触发器和统一锁序保护报价/订单绑定、合法迁移与并发授权，`0005` 增加认领/同意 provenance、同 target 待邀请唯一、终态不可变和新交易安全客户门禁。存量 `legacy_direct` / `legacy_client_hash` 不冒充安全认领或服务端证据：原账户仍可拒绝/撤回，升级认领会重置旧同意并先停用原 active 关系，再要求新的服务端 `grant` 和激活。旅行社 API 还会在响应发送前完成数据库提交，避免提交阶段失败却先返回 `2xx`。门店权限仍是应用层行级授权，不是 PostgreSQL RLS；批量导入、邀请投递、客户通知、真实身份核验、PII 档案与法律级同意、跨门店转移、门店停用/关闭、外部取消/退款与人工处理、平台 Approval 绑定、真实供应商预订、支付、补偿与对账尚未接入。`20ff715` / 运行 `30534862434` 的默认 `1713 passed, 34 deselected` 和 PostgreSQL `10 passed` 只是 `0004` 历史基线；`0005` 需要新的 CI 与目标环境证据。公开工程口径必须写成“目标业务是旅行社，安全认领与服务端同意控制面已建立，历史 CI/M1 证据可追溯，当前迁移、目标环境和真实外部交易仍待验收”。token 摘要、服务端同意记录、内部 `approved` 或内部 `cancelled` 都不代表真实身份、法律合规、真实库存、真实锁价、真实支付、供应商取消/退款、真实出票或供应链履约。

资源收集入口见 `docs/部署与运行/m1-resource-request-pack.md`、`scripts/render_m1_resource_request.py --markdown`、`scripts/check_m1_launch_inputs.py --template`、`scripts/check_m1_launch_inputs.py --input-json <private-workdir>/m1-launch-inputs.local.json --json`、`scripts/render_server_env_checklist.py --template` 和 `scripts/check_server_env_file.py --env-file <deploy-dir>/shared/.env --json`。它用于告诉部署/运维负责人需要准备哪些服务器、env、数据、验收、备份、监控和回滚资源，并在目标服务器或受控 shell 中校验服务器 `.env` 是否缺变量、空值、仍像占位符或重复声明；全程只收变量名、状态和脱敏摘要，不收真实密钥值。

首次部署预演见 `docs/部署与运行/m1-first-deploy-dry-run.md` 和 `scripts/check_m1_first_deploy_dry_run.py --json`。它不连接服务器、不上传文件、不启动服务，只检查目标输入、本机发布工具、git 工作区、Compose 模板和公开边界；当前工作区有未提交改动时必须 `blocked`。

服务器侧首部署入口见 `deploy/first-deploy.sh`。它默认只 dry-run，提供 `--archive-sha256` 时会在解压前校验上传包，显式 `--execute --start-services` 后才会解压 release、切换 `<deploy-dir>/current` 并启动 Compose；运行时 `.env`、向量库、日志和备份保留在 `<deploy-dir>/shared/`，不跟随代码包覆盖。

发布包 manifest 见 `scripts/build_release_artifact.py`。它默认不写文件，显式执行时从干净 Git `HEAD` 生成 archive 和 manifest，记录 commit、tree、tracked file count 和 archive `sha256`；它证明发布包可审计，不证明服务器已部署。

发布候选冻结见 `scripts/check_release_candidate_freeze.py`、`scripts/render_release_candidate_freeze_record.py`、`scripts/check_release_candidate_freeze_signoff.py --check-current-worktree` 和 `docs/部署与运行/m1-release-candidate-freeze.md`。它只读取 Git 工作区状态，把未提交路径按 workstream 归类，生成 include/defer/remove 决策记录，并校验进入候选的方向是否有验证结果、验证证据摘要、风险结论、负责人签核且记录仍匹配当前工作区路径快照；当前工作区未冻结时会阻塞 M1 聚合门禁和正式打包。

下一阶段改进路线见 `docs/项目总览/agent-ai-app-improvement-roadmap.md`。该路线图把架构与状态、RAG（检索增强生成）评测、MCP（模型上下文协议）工具安全、结构化报告、前端交付和可观测验收拆成可并行推进的方向，并要求每个方向提交改动范围、测试结果、剩余风险和公开口径影响。

截至 2026-07-12，当前 RAG 离线召回集为 27 个场景、26 份文档，公开目的地样例覆盖西安、杭州、厦门、桂林、南京和北京，mixed-corpus safety（公开+内部混合库安全）门禁覆盖 11 个公开场景。这些数字只是当前本地 BM25/metadata 确定性评测口径，不代表真实向量库、在线 Agent 或生产环境已验收。2026-07-11 的 26 场景、25 文档、5 个公开目的地和 10 个安全场景为南京样例校准后的历史快照；下段的 25 场景、24 文档和 9 个安全场景保留为 2026-06-23 前两轮实施快照，均不是当前规模。

第一轮和第二轮已补强两个 P0 方向：RAG 离线召回评测更新到 25 个场景、24 份文档，公开目的地覆盖西安、杭州、厦门、桂林，并单独标出 9 个 mixed-corpus safety（公开+内部混合库安全）场景；工具治理补充 URL query 密钥脱敏、MCP 错误脱敏和外部 MCP 服务目录。第三轮补充 `TravelState` 状态契约和阶段 Prompt 规则清单，明确双工作流进度轴、阶段字段、工具白名单和报告红线。第四轮补充 `report_data` 交付契约和前端导出回归，证明结构化报告可以渲染、复制摘要和导出 HTML。第五轮补充 RAG readiness 发布矩阵和 AgentOps 轻量回放/版本记录，明确离线评测、真实向量库、preflight、live smoke/core、turn 级观测和工具审计各自能证明什么。第六轮补充生产化差距清单、M1 上线总清单、生产部署输入清单、M1 受控试运行 runbook、外部 API 故障 runbook、备份恢复 runbook、监控告警 runbook、安全发布/密钥轮换 runbook 和验收记录模板；第七轮把 M1 非密钥输入升级为 `check_m1_launch_inputs.py` 机器门禁；第八轮新增 `check_m1_deployment_gate.py` 聚合门禁；第九轮新增 `render_m1_acceptance_record.py`，把门禁结果整理成脱敏 M1 验收记录；第十轮新增 `check_backup_restore_readiness.py`，把备份目标和恢复策略纳入机器门禁；第十一轮新增 `check_monitoring_alerting_readiness.py`，把监控告警和成本预算纳入机器门禁；第十二轮新增 `check_security_release_readiness.py`，把安全发布和密钥轮换状态纳入机器门禁；第十三轮新增 `check_external_api_readiness.py`，把外部 API 可靠性状态纳入机器门禁；第十四轮新增 `check_server_preflight_readiness.py`，把目标服务器部署基础条件纳入机器门禁；第十五轮新增 `collect_m1_smoke_evidence.py`，把部署后 health、M1 gate 和 acceptance smoke 收束成脱敏证据；第十六轮新增 `collect_backup_restore_drill_evidence.py`，把最新 PostgreSQL dump、catalog 可读性和恢复演练声明收束成脱敏证据；第十七轮新增 `collect_monitoring_alerting_evidence.py`，把告警投递和关键指标监控声明收束成脱敏证据；第十八轮新增 `collect_incident_rollback_evidence.py`，把事故响应和发布回滚演练收束成脱敏证据；第十九轮新增 `collect_m1_go_no_go_evidence.py`，把 M1 gate、smoke、备份恢复、监控告警、事故回滚证据汇总为最终 `decision`，并把请求 section 的 `not_checked` 视为 `no_go`。当前仍不是完整生产系统，受控试运行前必须补齐服务器、密钥、数据、安全、观测、发布和履约缺口；这些都是工程证据，不代表真实供应链、真实向量库、真实告警投递、真实密钥有效、真实供应商调用成功、目标版本已部署、最终 go/no-go 已放行或在线 Agent 验收已经通过。

第二十轮新增资源申请包生成器，把“需要准备什么”变成可发送清单：服务器、DNS/TLS、运行配置、密钥变量、RAG 数据、外部 API、验收、备份、监控和回滚资源都按生产口径列出，但仍不保存真实密钥、账号口令或客户资料。

第二十轮补充项新增服务器 env 清单生成器：`scripts/render_server_env_checklist.py` 只读取公开 `.env.example` 里的变量名，输出 `<deploy-dir>/shared/.env` 变量清单、密钥交付方式和占位符模板，不读取真实 `.env`，也不回显当前进程环境变量值。第二十轮补充项还新增服务器 env 文件校验器：`scripts/check_server_env_file.py` 只在显式传入 `--env-file` 时读取目标文件，默认拒绝仓库根目录本地 `.env`，只报告缺失、空值、明显占位符、重复变量和权限状态，不输出真实值或文件路径。

第二十一轮新增首次部署 dry-run，把“能不能开始真实部署”拆成目标输入、本机工具、git 工作区、Compose 模板和公开边界五个 section；它只证明本地发布前置，不证明 SSH/SCP、远端容器、真实密钥或在线验收已通过。

第二十二轮新增服务器侧首部署脚本，把远端执行从临时手工解压改为 release/current/shared 模型；它减少覆盖运行时数据的风险，但没有目标服务器和真实执行记录时仍不能证明上线完成。

第二十三轮新增发布包构建器，把 release archive 和 manifest 绑定到同一个 Git `HEAD`，用 sha256 支撑上传校验和发布审计；当前工作区未冻结时会正确阻塞，不会生成正式发布包。

第二十四轮新增发布候选冻结检查器、冻结记录生成器和签核校验器，把当前未提交改动按部署运行、RAG 评测、状态架构、工具安全、报告前端、业务 API、配置依赖、项目文档和测试验收归类，并生成 include/defer/remove 决策表；冻结记录可以用 `--with-suggestions` 生成建议方向和证据模板，也可以用 `--draft-baseline-decisions` 生成非签核的发布控制基线拟填写稿，但签核校验仍要求进入候选的方向必须有真实验证结果、验证证据摘要、风险结论和负责人签核，让“能不能打包上线”变成机器可见的 `release_candidate_freeze` 门禁，而不是人工凭印象判断。

第二十五轮新增 M1 非密钥输入 JSON 模板和文件校验入口：`scripts/check_m1_launch_inputs.py --template` 可生成服务器、域名、公网 URL、备份、监控、负责人、预算和验收窗口等可填写项，`--input-json` 用同一套规则校验填好的状态文件；`scripts/check_m1_deployment_gate.py --m1-input-json` 可以把这份文件接入 M1 聚合门禁。输出只写变量名、状态和修复建议，不回显填写值，也拒绝读取 `.env`、运行时目录和向量库路径。这个能力用于在真实服务器和密钥落地前先收齐资源状态，不代表真实密钥有效、服务器可达或服务已部署。

第二十六轮新增 PostgreSQL / Redis 运行手册：`docs/部署与运行/postgres-redis-ops-runbook.md` 把 Compose/托管数据库模式、会话锁、健康检查、备份恢复、高并发瓶颈、Caddy 故障和回滚证据写成可验收口径。它解决“上线后怎么守住状态和并发”的讨论基础，但没有目标服务器真实执行记录时仍不能写成生产放行。

第二十七轮新增 live server probe：`scripts/collect_live_server_probe.py` 通过 SSH 只读检查目标服务器的系统规格、Docker/Compose 服务、内部 health、服务器侧公网 health、向量库存在性和模拟订单路由部署状态，输出中不回显 SSH 目标、部署目录或公网 URL。这一轮也记录了 Windows 到 Linux 远端脚本的 CRLF 换行坑：如果脚本通过文本 stdin 发送，bash 可能出现 `set: -^M: invalid option`，因此探测脚本统一使用 LF 和二进制 stdin。

## 推荐回答结构

### 1. “请介绍你的项目”

回答模板：

> 知行是一个旅行社智能顾问 Agent。后端用 FastAPI（快速应用接口框架）提供 API；主对话由 LangChain `create_agent` 构建并运行在 LangGraph runtime（运行时）上，通过 `TravelState`、中间件和迁移工具推进八个逻辑规划阶段。它用 RAG 补充公开和内部知识，用 MCP 接入天气、搜索、地图、铁路、航班、酒店等外部能力，最终生成结构化 `report_data`，前端按这个契约渲染和导出报告。

代码定位：

- `app/main.py`：FastAPI 应用和生命周期。
- `app/api/v1/chat.py`：SSE（服务器发送事件）聊天入口。
- `app/core/state.py`：旅行状态。
- `app/agents/handoffs/travel_agent.py`：主控 Agent。
- `app/reports/builder.py`：结构化报告构建。

### 2. “为什么不是普通 RAG？”

回答模板：

> 普通 RAG 通常是“检索几段文本，然后生成答案”。这个项目的 RAG 只负责提供证据，真正的控制面是状态机和工具编排。系统会先收集需求，再推荐目的地、查交通、查住宿、生成行程、汇总预算、生成报告。每一步都有允许工具和前置依赖，最终验收看 `report_data` 是否满足结构、预算、风险、证据和前端导出契约。

产品化演示时可以补一句：

> 如果用户没有拒绝省心方案，RAG 可以召回成熟路线样板作为候选；如果用户明确说自由行或自己订，中间件会切回自由规划，不继续推产品。

可指代码：

- `app/agents/handoffs/step_config.py`：每阶段 prompt 和工具白名单。
- `app/tools/state_transition.py`：状态迁移工具。
- `app/evaluation/report_quality.py`：报告质量评分。
- `app/evaluation/rag_quality.py`：RAG 证据质量评分。

### 3. “Agent 工具失败怎么办？”

回答模板：

> 工具失败不能编造真实结果。酒店和交通查询失败时，系统会给出诚实兜底，并在报告中保留待核验项。MCP 客户端按服务降级，避免单个外部服务拖垮核心对话。但失败很多仍然说明工具链不可靠；当前普通场景默认要求工具失败数、失败率和 fallback 数都为 0，只有两个专门 fallback 场景允许有界失败。生产前还要补连续成功率、多次运行分布和 Badcase 归因。

可指代码：

- `app/tools/hotel_query.py`
- `app/tools/transport_query.py`
- `app/mcp_core/client.py`
- `app/evaluation/tool_quality.py`

### 4. “怎么做生产治理？”

回答模板：

> 当前项目不接真实供应链，但已经有目标账户安全认领、服务端规范化同意记录、门店范围的客户/顾问权限、客户停用时的内部交易原子收口、确定性的旅行社内部订单审核，以及平台审批策略、审批请求和事件、工具审计、运行时观测、readiness 检查、CI 门禁和手动 staging smoke。认领与同意记录不等于真实身份或法律合规，门店权限是应用层过滤而不是 PostgreSQL RLS，内部取消和内部审核也只改变业务状态。未来接真实支付、通知、预订或取消前，还要把平台审批记录与交易对象、LangGraph `interrupt/resume`、幂等、补偿和对账流程真正接通。

可指代码：

- `app/core/permissions.py`
- `app/models/approval.py`
- `app/agency/branch_authorization.py`
- `app/models/agency_transaction.py`
- `app/agency/transaction_service.py`
- `app/core/observability.py`
- `.github/workflows/staging-smoke.yml`

### 5. “如何证明能复跑？”

回答模板：

> 复跑分三层。第一层是本地讲解路径，只跑文档生成、专项测试和 dry-run，不需要密钥。第二层是 acceptance-smoke，需要真实后端和真实环境，先 preflight 再跑最小真实链路。第三层是前端报告路径，用同一份 `report_data` 验证渲染和导出。每层都明确依赖和不能证明的边界。

可运行命令：

```powershell
.\.venv\Scripts\python scripts\build_project_demo_pack.py --output .runtime\project-demo-pack
.\.venv\Scripts\python -m pytest tests\test_project_demo_pack.py -q
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
```

真实环境命令：

```powershell
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

## 常见追问与边界回答

| 追问 | 建议回答 |
|---|---|
| 现在能真实下单吗？ | 不能。当前既保留规划演示用模拟编号，也能持久化旅行社内部订单并完成专职审批员审核；但内部 `approved` 不触发支付、锁价、库存、供应商预订或履约。真实外部下单仍需平台 HITL 绑定、供应商适配器、幂等、补偿、对账和目标环境验收。 |
| 真实价格准确吗？ | 工具返回的价格可以标记为可追溯；缺失时只能做规则估算或兜底估算，并进入待核验项。 |
| 为什么不直接让模型一次性写报告？ | 一次性写报告不可控，难以追踪证据和阶段状态；现在的状态机可以把需求、工具结果、预算和风险沉淀为结构化状态。 |
| 为什么不用更多 Agent？ | Agent 数量不是目标。当前主流程是单个 Travel Agent；目的地 Router 和交通 Coordinator 只在有明确任务边界时按需调用。航班、高铁、自驾差异留在确定性查询 wrapper（包装器）中，避免为了“多 Agent”标签增加额外模型调用。 |
| 评估是不是太规则化？ | 是当前边界之一。确定性门禁负责结构、证据、诚实降级和运行预算；可选 LLM-as-Judge（大模型评审）只做补充。它还不能证明工具轨迹最优、同一场景多次运行稳定、失败可精确归因或线上用户体验提升。 |
| 前端是否生产可用？ | 目前是单页原型，用来证明结构化报告体验；完整生产前端还需要工程化构建、权限后台和更完整的可访问性验证。 |

## 最后收束

讲解结束前可以这样总结：

> 我把这个项目当作 Agent 工程问题，而不是 prompt 工程问题来做。它的核心价值在于：有阶段状态、有工具边界、有证据契约、有结构化交付、有可观测和验收门禁，也知道哪些真实业务动作现在不能做。
