# 审批治理轻量版（旅行社交易执行前置骨架）

## 目标

本模块只建立敏感动作治理契约。项目的目标业务是旅行社经营与交付工作台，但当前不接真实供应链、不做真实支付或退款、不发送真实通知、不生成真实客服或支付链接，也没有接入 LangGraph `interrupt/resume`（中断/恢复）。

当前实现提供：

- 敏感动作权限策略。
- 轻量平台审批角色边界：普通用户、审批操作者、管理员。
- 独立的旅行社内部订单审核：门店至少有一名有效专职 `approver` 才能提交订单，提交后不能撤掉最后一名审批员；该角色可处理本门店 `pending_review`，且不能自审。批准还要求客户保持 `active + granted`，客户停用后保留中的审核只能拒绝，且拒绝前客户关系不能重新激活。这不是平台 Approval/HITL。
- 独立的门店与客户权限控制：旅行社全域管理员、门店经理、当前主顾问、门店审批员和已安全认领的客户本人按应用层范围访问；这不是 PostgreSQL RLS（行级安全策略）。
- PostgreSQL（关系型数据库）持久化审批请求、审批事件和工具审计事件。
- 审批事件采用 append-only（只追加）方式记录状态流转。
- TravelState（旅行规划状态）审批字段。
- API（应用程序接口）契约：标记、查询、批准、拒绝、过期。
- 最终报告中的治理边界说明。
- `/health/ready` 会暴露审批持久化 readiness（就绪状态）；该状态只证明审批请求、事件和工具审计可持久化，不代表 Agent HITL（人类在环）闭环完成。

## 敏感动作策略

策略定义在 `app/core/permissions.py`。

| 动作 | 当前策略 | 说明 |
|---|---|---|
| `generate_order_id` | 记录型，不阻塞 | 生成规划演示用模拟编号；不是 `agency_order`，不代表真实支付、真实预订、锁价、占库存或履约。 |
| `export_final_report` | 记录型，不阻塞 | 导出当前结构化旅行报告；不代表已经完成支付、预订、出票或酒店确认。 |
| `real_booking` | 强制审批 | 未来接入真实供应链、库存或订单履约前必须审批。 |
| `real_payment` | 强制审批 | 未来接入支付网关前必须审批。 |
| `send_sms` | 强制审批 | 未来向用户或供应商发送短信前必须审批。 |
| `export_customer_profile` | 强制审批 | 未来导出客户资料或行程画像前必须审批，并最小化字段。 |

`generate_order_id` 仍被视为敏感动作，但当前只是记录治理边界，不阻塞报告交付。未来只要动作会触发真实支付、真实预订、短信发送或客户资料导出，就必须先完成 `pending -> approved`，再由独立的受控执行入口校验审批和动作参数；批准记录本身不会自动恢复 Agent 或执行动作。

## 与旅行社交易域的关系

旅行社业务域已增加 `agency`、`agency_membership`、`agency_branch`、`agency_branch_role_grant`、`agency_customer`、`agency_customer_invitation`、`agency_customer_consent_record`、`agency_customer_event`、`agency_customer_advisor_assignment`、`agency_quote`、`agency_order`、`agency_order_review`、`agency_order_event`、`idempotency_record`、`payment_attempt` 和 `fulfillment_record` 等持久化模型。`agency_order_review` 已实现旅行社内部审核闭环：记录绑定旅行社、门店、订单、提交时修订号、`payload_hash`、金额、币种和发起人，由订单门店专职审批员决定。

旅行社内部审核与平台 `/api/v1/approvals` 是两个独立契约：

- 内部订单审核在客户仍为 `secure_claim + active + granted + server_canonical` 时可决定 `pending_review -> approved`；客户停用后仍可由原门店审批员决定 `pending_review -> review_rejected`，但不能批准。
- 平台 Approval 记录未来高风险外部动作是否经过治理审批。
- 内部 `approved` 不会创建或批准 `approval_request`，平台 `approved` 也不会自动改变 `agency_order`。
- 两者当前都不会调用供应商预订、支付、退款或通知服务，也不会恢复 LangGraph run（运行）。

当前平台 `approval_request` 尚未形成以下外部动作绑定闭环：

- 旅行社 `agency_id` 和租户内有效成员。
- 报价或订单资源 ID、动作类型和操作者。
- 金额、币种、预期 `revision`（修订号）和 `payload_hash`（业务负载哈希）。
- 审批过期时间、幂等键和供应商适配器版本。
- 发起人与审批人的 four-eyes（四眼原则）职责分离。

因此，平台审批 `approved` 只能表示一条治理记录被平台审批员或管理员批准；交易域订单 `approved` 只能表示旅行社内部审核通过。二者都不能直接作为真实预订、支付、退款或通知的执行凭证。未来交易执行入口必须在数据库事务中重新读取并锁定相关业务对象，验证平台审批与交易对象的全部绑定字段后才能调用外部适配器。

### 旅行社内部订单审核

交易路由挂载在 `/api/v1/agency`：

- `GET /api/v1/agency/order-reviews`：仅同一有效旅行社、有效成员且持有有效门店授权的 `role=approver` 可读取其门店结构化审核工作队列。
- `GET /api/v1/agency/orders/{order_id}/review`：只有订单门店的有效专职 `approver` 可读取结构化审核记录；客户仍可通过订单 DTO 查看订单审核状态，但不会取得内部审核原因和决定人信息。
- `POST /api/v1/agency/orders/{order_id}/review`：仅订单门店专职 `approver` 可决定；`owner`、`admin`、`branch_manager`、`travel_advisor`、`booking_operator`、`finance` 和 `auditor` 不能代替。

专职 `approver` 还可以通过订单读取接口查看自己有效授权门店内、已生成审核记录的完整订单快照，但不能读取其他门店或尚未提交审核的订单，也不能创建、修改或发布报价。提交服务和数据库延迟约束都会确认门店至少存在一名有效审批员；决定请求包含 `decision=approve|reject`、`expected_revision`、可选 `reason` 和必需的 `Idempotency-Key`（幂等键），拒绝时 `reason` 必填。批准与拒绝共用 `order.review.decide` 幂等 scope（作用域）。服务按 `customer -> branch/member scope -> order -> review` 的顺序锁定资源，校验旅行社、门店、订单/审核状态、修订号、负载哈希、金额和币种绑定，拒绝订单客户或审核发起人自审，并追加 `order_review_approved` 或 `order_review_rejected` 事件；批准会重新锁定并校验客户仍为 `secure_claim + active + granted + server_canonical`，而拒绝允许对已停用客户保留的 `pending_review` 做失败关闭。数据库 DEFERRABLE（延迟到事务提交校验）约束触发器还会确认订单与审核的批准/拒绝终态成对一致，阻止直接 SQL 只改一侧。审核原因写入前会脱敏。

客户生命周期与交易审核保持同一失败关闭语义：活跃客户 `deny/revoke` 同意或关系被停用时，会在同一数据库事务中结束当前顾问分配，内部取消 `draft`/`offered` 和无订单的 `accepted` 报价，取消未发生外部/支付/履约进展的 `draft`/`approved` 订单，并把异常或可能已有外部状态的订单置为 `cancellation_pending` 或保留人工处理标记。`pending_review` 不被静默取消，必须由门店审批员明确拒绝，且该旧审核解决前客户关系不能重新激活。事件会标记未触发外部动作；这些内部状态绝不代表供应商取消、退款或通知已经完成。

以上闭环是确定性的旅行社业务审核，不是 Agent HITL：它不写 `TravelState.approval_*`，不调用 `Command(resume=...)`，也不放行任何外部副作用。

## 状态字段

`TravelState` 新增或补齐以下字段：

```python
approval_pending: bool
approval_reason: str
approval_action: str
approval_expires_at: float | None
approval_status: Literal["none", "pending", "approved", "rejected", "expired"]
approval_record_id: str
approval_required: bool
approval_governance: dict
```

状态含义：

- `none`：当前动作无需审批或只是记录型治理边界。
- `pending`：等待人工审批，过期前可批准或拒绝。
- `approved`：审批记录已通过；当前不会自动恢复原 Agent 运行，也不会触发真实动作。
- `rejected`：审批拒绝，不应继续执行对应真实动作。
- `expired`：审批超时，不应继续执行对应真实动作。

## API 契约

路由挂载在 `/api/v1/approvals`，当前复用登录用户鉴权。

- `GET /api/v1/approvals/policies`：查看敏感动作策略。
- `POST /api/v1/approvals`：标记敏感动作；强制审批动作会生成 `pending` 记录，记录型动作会生成 `none` 记录。
- `GET /api/v1/approvals`：查询当前用户审批记录，支持 `status`、`action`、`conversation_id` 过滤。
- `GET /api/v1/approvals/{approval_id}`：查询单条审批记录。
- `POST /api/v1/approvals/{approval_id}/approve`：批准 `pending` 记录。
- `POST /api/v1/approvals/{approval_id}/reject`：拒绝 `pending` 记录。
- `POST /api/v1/approvals/{approval_id}/expire`：手动过期 `pending` 记录。
- `GET /api/v1/approvals/{approval_id}/events`：查询单条审批记录的只追加事件。

这些 API 只读写审批记录和事件。当前没有暂停中的 LangGraph run（运行）可供恢复，也不会把审批结果自动回写到 conversation checkpoint（会话检查点）或调用 `Command(resume=...)`。

## 前端治理台展示

单页前端 `frontend/zhixing.html` 已增加轻量治理台，作为人工确认边界的演示入口：

- 登录后读取 `GET /api/v1/approvals`，普通用户默认查看自己的人工确认记录；审批操作者或管理员账号可按后端权限查看全部记录。
- 选择人工确认记录后读取 `GET /api/v1/approvals/{approval_id}/events`，展示 append-only（只追加）审批事件，不覆盖历史。
- `pending` 记录提供批准、拒绝、手动过期入口；服务端仍按角色校验权限，普通用户不能自审。
- “演示记录”按钮只调用 `POST /api/v1/approvals` 创建 `real_payment` 占位记录，用于说明未来真实支付、短信通知或客户资料导出前必须人工确认；它不接真实支付、真实预订、短信、客服或供应链。
- 前端只展示审批理由和事件理由的脱敏短摘要，不展示密钥、完整工具输入输出或客户原始资料。

这个治理台不是独立后台系统，也不是正式审批工作流的最终形态；它用于把当前轻量审批治理契约可视化，便于验收和演示。当前订单号、报告导出和演示记录都不会触发真实下单，也不会恢复 Agent 执行。

### 角色与权限

当前不引入完整企业级 RBAC（基于角色的访问控制）系统，也不接外部权限服务。审批 API 从用户对象的 `role` 属性或 `preferences.role` 中解析平台级 `user`、`approver`、`admin`，缺省为 `user`；旅行社业务域用 `agency_membership` 表达租户岗位，并由 `agency_branch_role_grant` 将非全域岗位授权到门店。两套角色不能互相替代。平台 `approver` 不自动获得旅行社审核权，旅行社 `approver` 也不自动获得平台审批全量权限。

| 角色作用域 | 角色 | 当前能力边界 |
|---|---|---|
| 平台审批 | `user` | 可创建敏感动作标记，可查询自己的审批记录和事件；不能批准、拒绝或手动过期审批。 |
| 平台审批 | `approver` | 可查看全部审批记录，可决定其他用户发起的 `pending` 审批；不能自审。 |
| 平台审批 | `admin` | 拥有审批操作者能力并预留治理配置维护；同样不能自审。 |
| 旅行社租户 | `travel_advisor` | 仅管理有同门店有效授权且当前分配给自己的客户、方案和报价；不因此获得平台审批或真实预订执行权。 |
| 旅行社租户 | `branch_manager` | 管理同一有效门店的客户、顾问分配和业务可见性；不能决定内部订单审核。 |
| 旅行社租户 | `booking_operator` | 预订操作员骨架；当前没有供应商执行入口。 |
| 旅行社租户 | `approver` | 当前唯一可读取自己有效授权门店的审核工作队列并决定内部订单审核；必须是同一有效旅行社的有效成员，且不能审核本人订单或本人发起的审核。不能据此调用平台审批全量接口。 |
| 旅行社租户 | `finance`、`auditor` | 预留财务和审计职责；当前不能决定订单审核，也没有真实支付、退款或对账入口。 |
| 旅行社租户 | `admin`、`owner` | 旅行社全域管理角色，可管理门店、门店授权和客户；高风险动作仍需职责分离，不能代替专职审批员。 |

旅行社门店/客户授权由应用服务的对象检查和 SQL 可见性过滤器实现，不是 PostgreSQL RLS。授权敏感写入会对门店和成员范围持有共享行锁，使并发撤销岗位授权或改变门店状态必须等待，避免 TOCTOU（检查与使用时序差）竞态；这只保护受控服务写路径。生产数据库账号一旦绕过服务层，这些过滤器和锁顺序不会自动生效；因此还需要最小权限数据库账号、系统化越权测试，并评估数据库 RLS 或独立策略引擎。

`GET /api/v1/approvals` 默认只返回当前用户记录；审批操作者或管理员可以通过 `scope=all` 查看全部审批记录。无权限响应使用稳定错误契约：

```json
{
  "detail": {
    "code": "approval_decision_denied",
    "message": "只有审批操作者或管理员可以批准、拒绝或手动过期审批记录",
    "required_roles": ["approver", "admin"],
    "current_role": "user"
  }
}
```

普通用户即使是审批发起人，也不能自审未来真实支付、真实预订、短信发送或客户资料导出这类敏感动作。

审批 API 默认使用 `DatabaseApprovalStore` 写入数据库；测试可以注入同接口的 `ApprovalStore` 内存替身，以保持本地快速回归。这个替身不作为生产审计账本。

生产环境必须使用 PostgreSQL 持久化审批请求、审批事件和工具审计事件，不允许回退到进程内内存存储。开发、测试和本地环境可以启用内存审批存储作为调试替身，但治理状态仍会标记为 `not_ready`。无论使用 PostgreSQL 还是内存存储，当前都保持 `hitl_closed_loop=false`；数据库就绪只会令 `approval_persistence_ready=true`。

## 持久化数据模型

治理表定义在 `app/models/approval.py`，由 `scripts/init_db.py` 的业务表初始化流程创建。

| 表 | 用途 | 关键点 |
|---|---|---|
| `approval_request` | 当前审批请求快照 | 保存当前 `status`、动作、用户、会话、过期时间、治理边界和脱敏 metadata。 |
| `approval_event` | 审批状态事件 | 记录 `created`、`approved`、`rejected`、`expired` 等事件；历史事件只追加，不覆盖。 |
| `tool_audit_event` | 工具调用审计事件 | 保存工具名、输入摘要、输出摘要、状态、耗时、错误类型、重试次数和证据类型。 |

`approval_request.status` 是为了查询当前状态的派生快照；可信历史以 `approval_event` 为准。审批自动过期和手动过期都会追加 `expired` 事件。

旅行社内部审核另存于 `agency_order_review`，不属于上述平台审批表。它保存审核快照和决定结果，并通过 `agency_order_event` 记录订单状态变化；不能用它推断 `approval_persistence_ready` 或 `hitl_closed_loop`。

## Readiness 语义

`/health/ready` 的 `services.approval_governance` 字段用于判断审批记录和审计事件能否可靠持久化：

- `status="ready"`：审批请求、审批事件和工具审计事件均可访问 PostgreSQL，`persistent=true`，`approval_persistence_ready=true`，但 `hitl_closed_loop=false`。
- `status="not_ready"`：数据库不可用、治理表缺失或工具审计写入失败，`persistent=false`，`approval_persistence_ready=false`，`hitl_closed_loop=false`。
- `storage="memory"` 且 `fallback_mode="dev_memory"`：仅表示开发环境允许继续用内存替身调试 API，不代表生产审批持久化或 HITL 闭环完成。

当审批治理不是 `ready` 时，整体 readiness 返回 `not_ready`，避免核心依赖已经启动但治理审计能力缺失时被误判为可生产使用。

第 1.5 批统一集成后，审批治理与会话锁共同参与 `/health/ready` 核心契约：

- `services` 必须同时暴露 `checkpointer`、`store`、`mcp`、`session_lock` 和 `approval_governance`。
- `approval_governance.ready=true` 是 `core_ready` 成立条件；生产环境 PostgreSQL 不可持久化时，整体状态必须是 `not_ready`。
- `session_lock.status="degraded"` 可以让整体状态变为 `degraded`，但不替代审批治理持久化要求。
- MCP（模型上下文协议）为 `degraded` 或 `unavailable` 时，若核心依赖全部就绪，整体状态返回 `degraded` 而不是 `not_ready`。

## 模拟编号与交易订单边界

`generate_order_tool` 会继续生成 `ORDER-` 开头的规划演示编号，不因为审批未完成而阻塞当前最终报告。该编号不是 `agency_order.order_no`，不能用于收款、供应商预订、合同或履约。但工具会同步写入：

- `approval_action="generate_order_id"`。
- `approval_status="none"`。
- `approval_pending=False`。
- `approval_required=False`。
- `approval_governance.boundary`：说明当前订单号不代表真实支付、预订、锁价或履约。
- `report_data.tool_audit_summary.approval`。
- `report_data.evidence_bundle.approval_governance`。

当前工具调用路径仍保留同步内存记录，原因是当前尚未完成统一工具执行网关和全链路异步数据库上下文改造；聊天 API 会把流式捕获到的工具审计事件持久化到 `tool_audit_event`。未来统一工具执行网关落地后，应直接调用旅行社交易服务，而不是把 `generate_order_tool` 的演示编号升级解释为真实订单。

最终报告和工具返回消息继续明确：

- 当前项目未接入真实支付服务，不生成支付链接。
- 不承诺真实库存、真实锁价或真实预订成功。
- 未来接入真实支付或真实预订时必须先完成人工审批。

## 数据与隐私边界

审批 metadata（元数据）、审批理由、审批决策备注、工具审计摘要、SSE（服务器发送事件）公开帧和验收快照统一使用 `app/utils/security.py` 中的脱敏工具处理。

当前覆盖：

- 客户关系模型不保存姓名、电话、证件、联系人等 PII（个人可识别信息）档案；客户、报价、订单和事件公开 DTO 不返回内部账户标识。认领邀请列表也不返回原始 token 或数据库摘要。
- 认领 token 使用 256-bit 高熵随机数，24 小时过期、可撤销且单次使用，数据库只保存 SHA-256 摘要；只有已登录目标账户能认领，同一旅行社同一目标账户同一时刻最多一条待处理邀请。原始 token 仅在首次签发事务提交成功后的响应返回，幂等重放不再返回，丢失时需撤销并重新签发；token 不得被格式校验错误回显，签发/认领响应使用 `no-store`。当前不投递邀请通知。
- 认证告知接口返回固定 Markdown、版本、文档摘要、证据 schema（模式）和渠道；客户同意请求必须回传预期版本/文档摘要，告知已更新时失败关闭，但客户端不能上传任意 evidence hash（证据哈希）。服务端生成 canonical（规范化）证据并写入 append-only（只追加）记录。存量 `legacy_direct` / `legacy_client_hash` 明确保持旧来源，原账户可 `deny/revoke`；升级认领会重置旧同意，原 active 关系会先停用并收口分配/内部交易，再要求新的 `grant` 与激活。新激活、报价和订单要求 `secure_claim + server_canonical`。这些摘要和记录仍不能证明真实身份核验、告知充分、条款有效或法律合规。
- 字段名命中 `token`、`secret`、`api_key`、`authorization`、`password`、`phone`、`email`、`id_card`、`passport` 等敏感含义时，字段值替换为 `[REDACTED]`。
- 文本中疑似手机号、邮箱、身份证号、JWT（JSON Web Token，令牌认证）、Bearer token（持有者令牌）和常见 API Key（应用程序接口密钥）形态时，替换为 `[REDACTED]`。
- 工具审计只保存输入和输出摘要；即使上游错误消息携带敏感串，也会在写入审计事件前脱敏。
- SSE 公开事件会在序列化前脱敏，`tool_audit` 事件仍只暴露工具名、状态、耗时、证据类型和错误类型。
- 评估 live snapshot（真实链路快照）写盘前会递归脱敏，避免验收产物保留真实密钥或真实个人信息。

当前文档、测试和提交说明不写入真实密钥、真实手机号、真实身份证号或真实客户资料。

工具审计事件只保存摘要，不保存完整外部 API（应用程序接口）请求、认证头、密钥或原始大段结果；上游工具返回失败时，审计事件用于报告待核验项，不用于编造真实价格、库存或预订状态。

如果工具审计事件写入 PostgreSQL 失败，系统会：

- 将审批治理状态标记为 `not_ready`。
- 在消息 `extra_info.tool_audit_persistence` 中记录 `status="degraded"`、错误类型和降级说明。
- 写入服务日志，明确说明审计事件未能完成持久化。

这类失败不会被静默吞掉；后续真实支付、短信、客户资料导出或供应链下单接入前，必须把这类写入失败作为阻断条件处理。

## 未覆盖范围

- 不提供 LangGraph `interrupt/resume`、审批结果回写 checkpoint 或审批后自动恢复工具调用。
- 不提供独立后台审批 UI（用户界面）；当前只有现有单页前端里的轻量治理台演示入口。
- 不接真实库存、支付、短信、客服或供应链。
- 平台 `approval_request` 仍不绑定旅行社报价/订单的金额、币种、修订号和负载哈希；交易域内部订单审核虽已完成四眼约束和业务快照绑定，但不能替代平台外部动作审批。
- 不生成支付链接、客服链接、预订凭证或出票凭证。
- 不承诺锁价、余位、成团、酒店确认或订单履约。
- 不做分布式一致性和不可篡改审计日志。
- 不在本分支大规模重构所有工具执行流程；统一工具执行网关放到后续分支。
- 不提供批量客户导入、邀请投递/客户通知、真实身份核验、客户 PII 档案与法律级同意流程、客户跨门店转移或门店停用/关闭 API。

安全客户认领、服务端同意记录、门店、客户生命周期、顾问分配、客户停用时的内部交易收口、内部报价/订单 API 和订单审核闭环已经存在，但真实业务接入前仍需补齐邀请投递与通知、真实身份核验、PII/同意合规、转店与门店状态管理、供应商取消/退款、`cancellation_pending` / `manual_intervention` 人工处理、平台审批绑定、外部适配器、回调验签、失败补偿和对账机制。真实供应商预订、取消、支付、退款和通知继续 fail-closed（默认拒绝）。
