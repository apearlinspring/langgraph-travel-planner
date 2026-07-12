# 审批治理轻量版（HITL 前置骨架）

## 目标

本模块只建立敏感动作治理契约，不接真实供应链、不做真实支付、不生成真实客服或支付链接，也没有接入 LangGraph `interrupt/resume`（中断/恢复）。

当前实现提供：

- 敏感动作权限策略。
- 轻量角色边界：普通用户、审批操作者、管理员。
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
| `generate_order_id` | 记录型，不阻塞 | 生成项目内模拟订单号；不代表真实支付、真实预订、锁价、占库存或履约。 |
| `export_final_report` | 记录型，不阻塞 | 导出当前结构化旅行报告；不代表已经完成支付、预订、出票或酒店确认。 |
| `real_booking` | 强制审批 | 未来接入真实供应链、库存或订单履约前必须审批。 |
| `real_payment` | 强制审批 | 未来接入支付网关前必须审批。 |
| `send_sms` | 强制审批 | 未来向用户或供应商发送短信前必须审批。 |
| `export_customer_profile` | 强制审批 | 未来导出客户资料或行程画像前必须审批，并最小化字段。 |

`generate_order_id` 仍被视为敏感动作，但当前只是记录治理边界，不阻塞报告交付。未来只要动作会触发真实支付、真实预订、短信发送或客户资料导出，就必须先完成 `pending -> approved`，再由独立的受控执行入口校验审批和动作参数；批准记录本身不会自动恢复 Agent 或执行动作。

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

当前不引入复杂 RBAC（基于角色的访问控制）系统，也不接外部权限服务。服务端从用户对象的 `role` 属性或 `preferences.role` 中解析轻量角色，缺省为 `user`。

| 角色 | 能力边界 |
|---|---|
| `user` | 可创建敏感动作标记，可查询自己的审批记录和事件；不能批准、拒绝或手动过期审批。 |
| `approver` | 审批操作者，可查看全部审批记录，可批准、拒绝或手动过期 `pending` 审批。 |
| `admin` | 管理员，拥有审批操作者能力，预留给后续治理配置维护。 |

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

## 订单号治理边界

`generate_order_tool` 会继续生成 `ORDER-` 开头的项目内模拟订单号，不因为审批未完成而阻塞当前最终报告。但它会同步写入：

- `approval_action="generate_order_id"`。
- `approval_status="none"`。
- `approval_pending=False`。
- `approval_required=False`。
- `approval_governance.boundary`：说明当前订单号不代表真实支付、预订、锁价或履约。
- `report_data.tool_audit_summary.approval`。
- `report_data.evidence_bundle.approval_governance`。

当前工具调用路径仍保留同步内存记录，原因是本分支不做统一工具执行网关和全链路异步数据库上下文改造；聊天 API 会把流式捕获到的工具审计事件持久化到 `tool_audit_event`。未来统一工具执行网关落地后，`generate_order_tool` 可直接接入数据库审批服务。

最终报告和工具返回消息继续明确：

- 当前项目未接入真实支付服务，不生成支付链接。
- 不承诺真实库存、真实锁价或真实预订成功。
- 未来接入真实支付或真实预订时必须先完成人工审批。

## 数据与隐私边界

审批 metadata（元数据）、审批理由、审批决策备注、工具审计摘要、SSE（服务器发送事件）公开帧和验收快照统一使用 `app/utils/security.py` 中的脱敏工具处理。

当前覆盖：

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
- 不生成支付链接、客服链接、预订凭证或出票凭证。
- 不承诺锁价、余位、成团、酒店确认或订单履约。
- 不做分布式一致性和不可篡改审计日志。
- 不在本分支大规模重构所有工具执行流程；统一工具执行网关放到后续分支。

这些能力需要在未来真实业务接入前单独设计数据库表、权限模型、审计日志和失败补偿机制。
