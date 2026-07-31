# 知行旅行规划器 / ZhiXing Travel Planner

知行旅行规划器的目标业务形态是旅行社经营与交付工作台：Agent（智能体）辅助旅行顾问完成需求澄清、产品匹配、方案与报价准备、订单草稿和交付说明，而不是只生成一篇旅游攻略。后端使用 FastAPI（快速应用接口框架），主执行链路以一个 Travel Agent（旅行主控智能体）和阶段中间件为核心，再按需调用目的地 Router（路由器）与交通 Coordinator（协调器）；LangGraph（图式智能体编排框架）和 LangChain（大模型应用编排框架）负责运行编排，RAG（检索增强生成）补充本地知识，MCP（模型上下文协议）接入可选外部能力。PostgreSQL（关系型数据库）保存用户、会话、消息、审批、检查点、长期记忆和第一阶段旅行社客户/交易域数据；Redis（缓存数据库）主要承担会话锁、缓存、API 限流计数和短期运行状态，不作为长期业务事实来源。

当前版本仍处于“规划交付链路 + 旅行社业务控制面”阶段。它可以持续对话、分阶段确认需求、区分自由规划和旅行社省心方案并生成结构化报告；代码也已加入旅行社、门店、成员、客户生命周期、客户认领邀请、只追加同意记录、顾问分配、供应商产品、报价、订单、内部审核、取消案件、人工补偿结果、独立对账、事件和幂等记录等持久化模型。但真实供应商预订、支付、退款和通知尚未接入，并由默认关闭的配置门禁阻断，不能把当前版本表述为已具备真实外部交易或履约能力。

## 核心能力

- 双工作流规划：自由规划按目的地、交通、住宿、餐饮、行程和预算逐步推进；省心方案按需求确认、产品匹配、方案草案、用户微调和报告交付推进。
- 编排边界：主流程不是“每个阶段一个 Agent”；交通 Coordinator 直接调用航班、高铁和自驾查询工具，不再保留一套未接入运行链路的交通方式子 Agent。
- 流式聊天接口：通过 SSE（服务器发送事件）返回模型文本、工具调用事件、结构化报告数据和超时兜底信息。
- 本地知识增强：公开目的地知识和脱敏旅行社样例知识覆盖路线模板、报价规则、风险提示、SOP（标准作业流程）和报告标准。
- 外部能力接入：MCP 工具可接入天气、搜索、地图、火车、航班和酒店等服务；可选服务不可用时按服务级别降级。
- 结构化报告：后端维护 `report_data` 报告契约，前端优先按结构化数据渲染预算、行程、地图、风险和待核验项。
- 旅行社客户控制面：持久化门店、门店角色授权、客户生命周期事件、客户认领邀请、只追加同意记录和主顾问分配；支持登记线下潜客，向指定已有平台账户签发 256-bit 高熵、24 小时过期、可撤销、单次使用的认领凭证，由该已登录账户完成认领，再记录客户本人同意、激活/停用关系以及分配、更换或结束主顾问。数据库只保存认领 token（令牌）的 SHA-256 摘要；认证后的告知接口返回固定技术告知 Markdown、版本、文档摘要、证据 schema（模式）和渠道，提交决定时客户端回传预期告知版本/文档摘要防止使用过期告知，canonical（规范化）证据仍完全由服务端生成。活跃客户拒绝/撤回同意或关系被停用时，会在同一数据库事务内结束当前顾问分配并收口内部交易状态。
- 门店范围权限：`owner`、`admin` 保持旅行社全域权限；`branch_manager`、`travel_advisor`、`approver` 等岗位必须有同门店有效授权，顾问还必须与客户存在当前有效分配。这是应用层行级授权，不是 PostgreSQL RLS（行级安全策略）。
- 旅行社交易域骨架：持久化供应商产品、报价、订单、内部审核、订单事件、幂等记录、支付尝试和履约记录；内部 API 支持报价草稿、发布、客户接受、订单草稿、提交审核及门店专职审批员批准/拒绝，创建报价前要求客户已完成 `secure_claim`（安全认领）、处于 `active`、同意状态为 `granted`、同意证据来源为 `server_canonical` 且所属门店有效，报价和订单带 `revision`（修订号）与 `payload_hash`（业务负载哈希），外部动作字段默认关闭。
- 人工取消与对账闭环：取消申请的补偿范围只由服务端根据锁定的订单、支付尝试和履约记录派生，数据库会独立复算；案件创建后即冻结原支付/履约账本，避免审批前后迟到暴露绕过既定范围。`booking_operator` 只能登记人工取得的供应商取消结果，`finance` 只能登记财务结果，另一名 `auditor` 通过仅限审计岗位的脱敏队列发现待办，再独立提交退款观察金额/币种和证据后对账。系统只保存外部引用和证据的 SHA-256 摘要，统一响应不返回内部人员账户标识，所有外部动作标记仍固定为 `false`；这里的 `refund_required` 表示财务结果与证据必须登记核验，不是平台发起退款命令。
- 交易执行门禁：`TRANSACTION_MODE`、总熔断开关和供应商预订、支付、退款、通知四类细粒度开关共同采用 fail-closed（故障或配置不全时默认拒绝）策略；即使配置门禁通过，后续仍必须校验租户权限、四眼审批、修订号、负载哈希、幂等和供应商适配器。
- 部署模板：提供 Docker（容器化平台）和 Caddy（反向代理服务器）配置示例，适合本地或自有服务器部署。

## 当前业务边界

- `agency_plan` 是旅行社顾问的方案规划分支，输出成熟路线、费用口径、服务说明和待核验项；它不会自动完成真实下单。
- `agency_quote`、`agency_order` 等表构成第一阶段交易数据与审计骨架，不等于供应商库存、支付网关、退款或履约已经连通。
- `/api/v1/agency` 的报价、订单和审核子集为 13 个操作，其中 6 个 `POST` 强制 `Idempotency-Key`（幂等键）；门店与客户生命周期子集为 24 个操作，其中 15 个 `POST` 强制该幂等键，并新增客户转店、门店停用、关店就绪计数和最终关闭；人工取消与对账子集另有 9 个操作，其中 5 个 `POST` 同样要求幂等键和预期修订号，审计岗位可从脱敏人工结果队列取得待核验记录 ID 与当前对账状态。
- 客户把订单提交为 `pending_review` 或创建取消案件前，门店必须存在至少一名排除业务发起人和订单客户后的有效专职 `approver`；开放取消案件会阻止同一订单进入审核。待处理订单审核或 `approval_pending` 取消案件存在时，撤权操作必须为每笔业务保留一名同样合格的替代审批员。只有同门店拥有有效成员身份和授权的专职 `approver` 可读取已生成审核记录的订单快照并处理审核；`active` 门店可批准或拒绝，`inactive` 清理期只允许拒绝保留中的订单审核，取消申请、审批、结果登记、对账和恢复仍可继续收口。批准还要求客户保持 `active + granted`，客户停用后保留中的审核只能拒绝为 `review_rejected`，且拒绝前客户关系不能重新激活。该只读权限不包含未提交订单或报价创建/发布，`owner`、`admin` 等角色也不能代替审批员，客户或审核发起人不能自审。
- `approved` 只代表旅行社内部审核通过，`external_action_enabled` 仍为 `false`；系统没有供应商预订、支付、退款或通知执行路由。
- 当前只支持逐条登记线下 `prospect`（潜客），再由客户管理角色为指定已有平台账户签发认领凭证；只有该已登录目标账户能用未过期且未撤销的凭证认领。同一旅行社同一目标账户同一时刻最多一条待认领邀请。原始 token 只在首次签发事务已提交的响应中返回，幂等重放不会再次返回；若首次响应丢失，必须先撤销原邀请再重新签发。当前不负责短信、邮件或站内信投递，也没有批量客户导入。
- 客户模型未引入姓名、电话、证件、联系人等 PII（个人可识别信息）字段。认证用户可通过 `GET /api/v1/agency/customer-consent-notice` 读取 [客户关系授权技术告知](docs/架构与流程/customer-consent-notice-v1.md)；同意请求必须携带预期告知版本和文档 SHA-256，若服务端版本已变化则拒绝，但客户端不能上传任意 evidence hash（证据哈希）。服务端为每次决定生成只追加同意记录；这些记录仍只是平台内审计原语，不能证明真实身份核验、告知充分或法律合规。
- 旅行社 `owner/admin` 可通过 `POST /api/v1/agency/customers/{customer_id}/transfer` 原子更新客户的当前服务门店，并可为 `active` 客户选择目标门店的主顾问；`inactive` 或 `blocked` 客户也可转店，但不能随转店新建主顾问分配。来源门店可为 `active/inactive`，目标门店必须为 `active`；待认领邀请或开放报价、订单、审核、取消案件会阻断。转店不会改写邀请、同意、事件、旧分配和交易记录的历史门店，不发送通知，也不处理任何外部订单。首版尚无来源/目标门店经理双向审批。
- `blocked` 客户不能通过“停用后再激活”绕过风险复核。门店通过 `active -> inactive -> closed` 收口：`inactive` 是停止新客户、授权、认领、分配、报价、订单和批准动作后的关店清理期，不等于已关店；只有所有当前客户（包括 `inactive/blocked`）、待认领邀请、有效顾问分配和岗位授权、待审核记录、开放报价/订单/取消案件全部清零，才能进入不可逆 `closed`。就绪接口只返回聚合计数，不暴露客户、员工或交易 ID。
- 活跃客户 `deny/revoke` 同意或客户关系停用时，内部 `draft`/`offered` 报价及没有订单的 `accepted` 报价会变为 `cancelled`；未发生外部、支付或履约进展的 `draft`/`approved` 订单会变为 `cancelled`。`pending_review` 保留给门店审批员拒绝，批准路径会因客户不再 `active + granted` 而失败，并在明确拒绝前阻止客户关系重新激活；异常或可能已有外部状态的订单进入 `cancellation_pending` 或保留人工处理标记。以上只收口本系统内部状态，不代表供应商取消、退款或通知已经发生。
- 认证用户可为可取消订单创建人工取消案件；处于原订单 `pending_review` 的请求必须先由原审核流程拒绝。专职审批员批准后有两条路径：服务端未派生出供应商取消或财务核验需求时，符合条件的 `draft`/`approved` 订单直接走 `approval_pending -> completed` 并在平台内变为 `cancelled`；存在任一需求时，案件再按 `approval_pending -> action_pending -> reconciliation_pending -> completed` 推进。失败、未知或不匹配结果进入 `manual_intervention`，由门店经理或旅行社全域管理员恢复后重新登记。发起人和订单客户不能审批，结果登记人不能对账自己的记录；响应不返回原因明细、内部审核备注、外部引用摘要、证据摘要或事件元数据。
- `0004` 的 PostgreSQL 触发器固化报价/订单的租户、门店、客户与账户绑定，复验客户同意、门店状态、报价有效期及订单/报价金额、币种和快照一致性，要求每次更新的 `revision` 恰好加一，只允许已声明的状态迁移，并保持订单外部动作关闭；订单与审核的终态还会在事务提交时成对校验。写路径统一按 `customer -> branch -> quote/order` 加锁，授权写同时持有门店/成员共享锁，避免授权撤销或门店状态变化造成 TOCTOU（检查与使用时序差）竞态。
- `0005` 新增客户认领邀请与只追加同意记录，并把绑定来源标记为 `unbound`、`legacy_direct` 或 `secure_claim`，把同意证据来源标记为 `none`、`legacy_client_hash` 或 `server_canonical`。存量直接绑定不会被伪装成安全认领：原账户仍可 `deny/revoke`；一旦升级认领，旧同意投影会重置，原 `active` 关系会先转为 `inactive` 并收口当前分配/内部交易，之后必须重新记录服务端 `grant` 并激活，才能创建新的报价或订单。
- `0006` 只修正 `0005` 共享延迟约束触发器对不同表 `NEW` 字段的访问方式；`0005` frozen 迁移保持不变。`0007` 新增取消案件、只追加案件事件、人工补偿结果和独立对账表，并以 PostgreSQL 触发器约束复合绑定、`revision + 1`、状态机、合格审批员、只追加记录、最新结果对账和外部动作恒为关闭；同时冻结 `agency_membership` 的身份绑定。案件的 `requested_at` 记录取消申请创建时间；订单的 `cancellation_requested_at` 仅在申请获批并进入订单取消处理时写入；订单的 `cancelled_at` 只在订单真正进入内部 `cancelled` 时写入。
- 当前业务迁移 head 为 `0008`：新增客户转店记录、门店生命周期事件和 `closed_at`，把客户关联外键改为稳定的旅行社/客户身份，使历史邀请、同意、事件、分配和交易继续保留发生时门店；数据库门禁约束转店绑定、门店修订号、只追加记录和 `closed` 终态。存在转店/关店业务数据或历史子记录门店已与客户当前门店不同后，降级会失败关闭。[`c574649`](https://github.com/apearlinspring/langgraph-travel-planner/commit/c5746496203f628fe9a93a91ebb998c910c2a920) / [运行 30606856484](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30606856484) 已验证默认 `1878 passed, 58 deselected` 和 PostgreSQL 17 六文件 `34 passed`；目标环境迁移/恢复和并发锁等待仍待验证。
- 旅行社领域 API 使用 function-scope（函数作用域）数据库依赖，只有事务提交及 DEFERRABLE（提交时延迟校验）数据库约束通过后才返回成功；提交失败不会先向客户端发送虚假的 `2xx`。
- `mock_checkout` 和 `generate_order_tool` 生成的 `ORDER-` 编号只用于演示规划结果确认，不是交易系统订单、合同或支付凭证。
- 当前没有邀请投递/客户通知、真实身份核验、法律级同意证据、客户 PII 档案或跨门店经理双向交接审批，也没有真实供应商预订/取消、库存锁定、收款/退款、出票、酒店确认、供应商自动对账、财务清分和跨系统完整失败补偿；现有转店/关店只处理平台内当前关系，取消闭环只记录平台外人工结果并做平台内独立核验。

详细边界见 [旅行社客户与交易域](docs/架构与流程/agency-transaction-domain.md)。

## 仓库范围

这个公开仓库只保留可运行、可复现、可维护的最小公开项目集合：

- 源码：`app/`、`frontend/`、`scripts/`。
- 测试与夹具：`tests/`。
- 依赖和运行定义：`pyproject.toml`、`uv.lock`、`requirements.runtime.txt`、`Dockerfile`、`docker-compose.yml`、`deploy/`。
- 脱敏样例知识和评估数据：`data/documents/`、`data/evaluation/`。
- 正式技术文档：`docs/`。
- 配置样例：`.env.example`。

仓库不包含真实密钥、本地运行状态、数据库备份、向量库、日志、截图、私有部署坐标、聊天记录、未整理 Prompt（提示词）或私人准备资料。

## 数据库边界

项目使用 PostgreSQL 和 pgvector（PostgreSQL 向量扩展）。仓库保存的是数据库模型、初始化脚本和配置样例，不保存真实数据库实例。

- 本地或服务器数据库应放在 Docker volume（容器数据卷）或托管数据库中。
- 真实业务数据、备份和 dump（数据库导出文件）不进入 Git（分布式版本控制系统）。
- 对外只提交 `.env.example`，真实 `.env` 文件保留在本地或服务器。

初始化数据库：

```powershell
uv run python -m scripts.init_db
```

从样例知识初始化 RAG 向量库：

```powershell
uv run python -m scripts.init_rag
```

生成的 `data/vectorstore/` 和 `data/vectorstore_internal/` 已被忽略，不应提交。

## 快速启动

前置条件：

- Python `>=3.12`
- Node.js（用于前端校验脚本）
- PostgreSQL + pgvector 和 Redis，或 Docker Compose（容器编排工具）
- `uv` Python 包管理器

安装依赖：

```powershell
uv sync
```

创建本地配置：

```powershell
Copy-Item .env.example .env
```

根据本地环境填写 `.env` 中的模型、数据库、Redis 和可选外部 API（应用程序接口）配置。

启动后端：

```powershell
uv run python main.py
```

前端可以直接打开 `frontend/zhixing.html`，也可以通过 Docker 中的 Caddy 服务托管。

## Docker 部署

先根据 `.env.example` 创建 `.env`，再启动服务：

```powershell
docker compose up -d --build
```

Compose（容器编排配置）包含：

- `backend`：后端服务。
- `postgres`：PostgreSQL 数据库。
- `redis`：Redis 缓存。
- `caddy`：静态前端和反向代理。

数据库和 Redis 数据保存在 Docker volume 中，不应提交到仓库。

## 本地验证

常用检查命令：

```powershell
uv run python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
uv run python -m pytest -q
```

RAG 召回评测：

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

旅行社交易域与客户生命周期的 PostgreSQL（关系型数据库）迁移、约束和并发测试使用专用测试库：

```powershell
$env:ZHIXING_TEST_POSTGRES_DSN = "postgresql://travel_user:change-me@127.0.0.1:5432/zhixing_test"
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_customer_claim_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py tests\test_agency_cancellation_postgres_integration.py tests\test_agency_branch_transfer_closure_postgres_integration.py
```

数据库名必须包含独立的 `test` 或 `ci` 段；测试会创建并删除随机 schema（数据库命名空间），不得连接 staging（预生产）或 production（生产）数据库。[`c574649`](https://github.com/apearlinspring/langgraph-travel-planner/commit/c5746496203f628fe9a93a91ebb998c910c2a920) 的 [GitHub Actions 运行 30606856484](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30606856484) 已双绿：默认 job 为 `1878 passed, 58 deselected`，PostgreSQL 17 六个文件为 `34 passed`（3 项交易、5 项客户生命周期、5 项客户认领、2 项门店权限、10 项取消域、9 项转店/关店）。这证明 `0001 -> ... -> 0008` 在一次性 CI 数据库中的迁移、触发器和上述集成路径；不替代目标环境迁移/恢复、并发锁等待、真实人工操作或外部依赖验证。[`e17b97d`](https://github.com/apearlinspring/langgraph-travel-planner/commit/e17b97d82c24b7f5271973cc8f18e884124b7d6b) / [运行 30602058425](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30602058425) 的默认 `1841 passed, 49 deselected` 与 PostgreSQL 17 五文件 `25 passed` 保留为 `0007` 历史基线；实现候选 [`20ff715`](https://github.com/apearlinspring/langgraph-travel-planner/commit/20ff71592096dfb4fc718cef050832a745bfe174) / [运行 30534862434](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434) 的 `1713 passed, 34 deselected` 与 PostgreSQL `10 passed` 是 `0004` 历史基线；[`b8b8bea`](https://github.com/apearlinspring/langgraph-travel-planner/commit/b8b8bea29477b472c942b7df40e8da6e9dbf05ab) / [运行 30551146157](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30551146157) 的 `1738 passed, 39 deselected` 与 PostgreSQL `15 passed` 是 `0005 -> 0006` 历史基线。需要真实 LLM（大语言模型）、MCP 服务或外部 API 的其他集成测试仍单独标记，不属于默认快速回归。

## 文档入口

先读 [docs/README.md](docs/README.md)。常用入口：

- [架构速览](docs/架构与流程/architecture-overview.md)
- [规划模式边界](docs/架构与流程/planning-mode-boundary.md)
- [旅行社客户与交易域](docs/架构与流程/agency-transaction-domain.md)
- [客户关系授权技术告知 v1](docs/架构与流程/customer-consent-notice-v1.md)
- [RAG 演示与评测指南](docs/RAG与知识库/rag-demo-evaluation-guide.md)
- [评估体系](docs/评估与验收/evaluation-system.md)
- [部署模板](docs/部署与运行/deployment-readiness.md)
- [前端报告体验](docs/前端与演示/frontend-report-experience.md)

## 安全边界

- 不提交 `.env`、生产密钥、API key（接口密钥）、数据库备份、生成的向量库或运行日志。
- 私有部署域名、IP（互联网协议地址）、SSH（安全外壳协议）信息保留在本地或私有 CI（持续集成）配置中。
- 样例路线模板只用于演示和开发验证，不代表真实库存、保证成团或锁价。
- 外部服务不可用时，系统应明确说明待核验或降级原因，不能编造车票、机票、酒店库存或真实报价。
- `TRANSACTION_MODE=disabled`、`ZHIXING_REAL_PAYMENT_ORDER_DISABLED=true` 和四类外部动作开关为默认安全口径；在供应商适配、审批绑定、幂等、补偿、对账和目标环境验收完成前不得开启真实执行。
