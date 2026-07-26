# Agency Transaction Domain（旅行社交易域）

## 业务定位

ZhiXing 的目标产品不是面向散客的攻略生成器，而是旅行社经营与交付工作台。Agent（智能体）负责辅助旅行顾问理解客户需求、匹配产品、准备方案与报价、形成订单草稿和交付说明；当前确定性交易服务负责保存报价、订单、内部审核、订单事件和幂等事实。旅行社内部订单审核已经绑定订单版本与金额，但平台 Approval/HITL（审批/人类在环）、支付尝试执行和供应商履约仍属于后续阶段。

当前版本处于第一阶段：已经建立旅行社交易域的数据与控制面骨架，但没有接入真实供应商预订、支付、退款和通知。任何 `agency_quote` 或 `agency_order` 记录都不能单独证明库存已锁定、资金已收取、票务已确认或服务已履约。

## 当前已实现

| 能力 | 当前代码证据 | 当前边界 |
|---|---|---|
| 多租户经营边界 | `agency`、`agency_membership` | 保存旅行社与成员角色；每个业务 API 必须校验有效成员和租户归属。 |
| 租户客户关系 | `agency_customer` | 把全局用户登记为某旅行社的潜客或有效客户；创建报价只接受 `active` 客户。当前没有客户导入、同意或关系激活/停用 API。 |
| 供应商产品目录 | `supplier_product` | 保存旅行社可销售产品及供应商外部编号；不代表实时库存或价格同步。 |
| 报价快照 | `agency_quote` | 保存客户、产品、金额、币种、有效期、报价快照、`revision`（修订号）和 `payload_hash`（业务负载哈希）。 |
| 订单快照 | `agency_order` | 保存报价来源、客户、金额、支付状态、履约状态和外部动作开关；不自动调用外部服务。 |
| 内部订单审核 | `agency_order_review` | 绑定旅行社、订单、提交时 `revision`、`payload_hash`、金额、币种和发起人；只有同租户专职 `approver` 可决定，内部通过不触发外部动作。 |
| 状态审计 | `agency_order_event` | 按订单和事件序号只追加记录状态变化及对应负载哈希。 |
| 持久化幂等 | `idempotency_record`，以及报价、订单、支付尝试、履约记录的唯一键 | 当前报价/订单服务已校验“同键同请求”，同键异请求返回冲突；未来外部动作仍需保存不可变响应快照并验证供应商侧幂等。 |
| 执行账本 | `payment_attempt`、`fulfillment_record` | 为未来支付与供应商履约保留尝试记录；当前不会执行真实支付或预订。 |
| 并发版本 | 报价和订单使用 SQLAlchemy `version_id_col` | 提供乐观并发控制基础；业务入口还必须要求并校验预期修订号。 |
| 租户角色 | `agency_membership.role` | 租户内区分旅行顾问、预订操作员、审批员、财务、审计、管理员和所有者；只有 `approver` 具有当前订单审核决定权。它与平台级 `user`、`approver`、`admin` 角色分离。 |
| 内部交易 API | `/api/v1/agency` | 共 13 个操作；支持报价、订单和内部审核查询/决定，不包含供应商预订、支付、退款或通知执行。 |
| 外部执行门禁 | `app/agency/transaction_policy.py`、配置样例和 Compose 模板 | 总开关、运行模式和四类动作开关默认关闭；配置门禁通过也不等于业务动作获准。 |
| 数据库迁移 | Alembic 交易域版本和 migration contract（迁移归属契约） | 证明表结构可由项目管理，不证明生产数据库已迁移或数据已验证。 |

当前能力应统一表述为“旅行社交易数据与控制面骨架”。现有报价和订单 API（应用程序接口）只能证明内部业务事实可被受控写入，不能扩写成真实供应链和资金链已经连通。

## 与 Agent 规划链路的边界

```text
客户对话
  -> 规划模式确认
  -> 自由规划 / 旅行社省心方案
  -> report_data 方案与预算
  -> 显式进入交易域
  -> 报价草稿 -> 正式报价 -> 客户接受
  -> 订单草稿 -> 提交人工审核
  -> 专职审批员批准 / 拒绝
  -> 未来：支付 / 供应商预订 / 履约 / 退款
```

前半段是 Agent 规划与交付链路，后半段是确定性的旅行社交易链路。两者不能通过一个文本编号或模型回复隐式跨越：

- `agency_plan` 只说明当前对话使用旅行社产品化方案，不代表创建了 `agency_quote`。
- `report_data` 中的预算是方案表达，只有经过有效期、金额、币种和快照校验后才能形成正式报价。
- `generate_order_tool` 与 `mock_checkout` 只生成演示用 `ORDER-` 编号，不是 `agency_order`，也不是合同、收款或供应商确认凭证。
- LLM（大语言模型）不能直接决定支付成功、库存锁定、退款完成或履约完成；这些状态只能由确定性服务根据外部回执和审计规则写入。

## 最小内部 API

当前路由挂载在 `/api/v1/agency`：

| 方法与路径 | 当前职责 | 关键门禁 |
|---|---|---|
| `POST /quotes` | 旅行社报价角色为指定客户创建报价草稿。 | 有效旅行社与成员、`active` 租户客户关系、客户会话/产品归属、`Idempotency-Key`。 |
| `GET /quotes`、`GET /quotes/{quote_id}` | `owner`、`admin`、`travel_advisor` 读取本租户完整报价；客户只读本人报价。 | 其他岗位暂不开放完整快照；非本人、非授权对象按未找到处理。 |
| `POST /quotes/{quote_id}/issue` | 将未过期草稿发布给客户。 | 报价管理角色、`Idempotency-Key`、`expected_revision`。 |
| `POST /quotes/{quote_id}/accept` | 报价所属客户接受有效报价。 | 客户本人、`Idempotency-Key`、`expected_revision`。 |
| `POST /orders` | 客户从本人已接受报价创建订单草稿。 | `Idempotency-Key`、`expected_quote_revision`、报价未过期。 |
| `GET /orders`、`GET /orders/{order_id}` | `owner`、`admin`、`travel_advisor` 读取本租户完整订单；专职 `approver` 只读已生成审核记录的订单；客户只读本人订单。 | `approver` 看不到尚未提交审核的订单，也不能创建或发布报价；预订、财务和审计岗位仍需 purpose-specific（按职责裁剪）DTO。 |
| `GET /order-reviews` | 查询本旅行社结构化审核工作队列，支持状态和分页。 | 只允许同一 `active` 旅行社中 `active role=approver`。 |
| `GET /orders/{order_id}/review` | 读取单个订单的结构化审核记录。 | 仅同一旅行社的有效专职 `approver` 可读；客户通过订单 DTO 查看状态，不取得内部原因和决定人信息。 |
| `GET /orders/{order_id}/events` | 客户本人或租户内有效成员读取订单只追加事件。 | 响应会剔除 `event_metadata.quote_snapshot`，避免借事件接口绕过完整快照权限。 |
| `POST /orders/{order_id}/submit` | 客户将订单草稿提交为 `pending_review`。 | 客户本人、`Idempotency-Key`、`expected_revision`。 |
| `POST /orders/{order_id}/review` | 将 `pending_review` 决定为 `approved` 或 `review_rejected`。 | 仅租户 `approver`；请求包含 `decision=approve\|reject`、`expected_revision`、`reason` 和 `Idempotency-Key`，拒绝时 `reason` 必填。 |

当前共有 13 个操作，所有六个 `POST` 都强制要求 `Idempotency-Key`。服务使用 PostgreSQL 持久化幂等记录；审核批准和拒绝共用单一 `order.review.decide` scope（作用域），同键同请求返回原审核资源，同键异请求返回 `409 Conflict`。报价、订单和审核状态变化使用 `SELECT ... FOR UPDATE`；订单提交会创建审核记录，审核决定会同时更新订单、审核记录并追加 `order_review_approved` 或 `order_review_rejected` 事件。当前 API 的 `external_action_enabled` 始终为 `false`，没有供应商预订、支付、退款或通知调用。

## 数据模型

### 租户与产品

- `agency` 是旅行社数据隔离和授权的根边界。
- `agency_membership` 将员工关联到旅行社，并保存租户内角色和成员状态。
- `agency_customer` 将全局用户关联到旅行社，并用 `prospect`、`active`、`inactive`、`blocked` 表达客户关系状态。当前报价服务只接受 `active` 客户。
- `supplier_product` 保存旅行社可销售的供应商产品。`supplier_code` 和 `external_product_code` 只用于识别上游对象，不代表上游对象当前可售。

### 报价

`agency_quote` 保存一份在特定时点可复核的业务快照：

- `quote_no`：旅行社报价编号。
- `agency_id`、`user_id`、`product_id`：租户、客户和产品归属。
- `total_amount`、`currency`：使用定点金额和三位大写币种代码。
- `quote_snapshot`、`snapshot_version`：报价内容和契约版本。
- `valid_until`：报价有效期。
- `revision`、`payload_hash`：并发修订号和内容指纹。
- `idempotency_key`：租户内报价创建幂等键。

当前报价状态：

```text
draft -> offered -> accepted
                  -> expired
                  -> cancelled
```

状态集合只定义允许保存的值。当前最小 API 已覆盖 `draft -> offered -> accepted`、报价有效期、操作者权限和预期修订号；`expired`、`cancelled` 等管理入口尚未开放。

### 订单

`agency_order` 从报价快照形成，并分别记录业务状态、支付状态和履约状态。当前业务状态集合为：

```text
draft
  -> pending_review
  -> approved / review_rejected
  -> processing
  -> completed / failed / manual_intervention
  -> cancellation_pending -> cancelled
```

这三个维度必须分开解释：

- `status=approved` 只代表旅行社内部审核通过，不代表已经支付或预订。
- `payment_status=paid` 未来只能由受控支付适配器及其回执驱动。
- `fulfillment_status=confirmed` 未来只能由供应商确认或受控人工核验驱动。

`external_action_enabled` 默认是 `false`。它只是单条记录的保护字段，不能替代全局配置门禁、租户权限、审批、修订号、负载哈希和幂等检查。

当前内部 API 已实现 `draft -> pending_review -> approved / review_rejected`。`approved` 只代表旅行社内部审核通过；处理、取消、失败、人工介入或完成入口仍未开放。

### 内部审核、事件、支付与履约记录

- `agency_order_review` 在提交审核时保存 `agency_id`、`order_id`、提交时订单修订号、负载哈希、金额、币种和发起人。决定后再保存决定修订号、审批员、脱敏原因和时间。
- 同一旅行社、订单和提交修订号只能有一条审核记录；数据库约束要求决定人与发起人不同，服务层同时拒绝订单客户或审核发起人自审。PostgreSQL 触发器禁止删除审核记录、修改审核绑定字段或再次修改已终结的审核。
- `agency_order_event` 是订单关键变化的只追加事件，使用 `event_sequence` 和 `order_revision` 关联状态快照。
- `payment_attempt` 是未来支付调用的尝试账本，按订单和幂等键去重。
- `fulfillment_record` 是订单内供应商履约项账本，按 `line_item_key` 和幂等键去重。

这些记录当前不构成不可篡改账本，也没有实现供应商回调验签、支付对账、退款分账或跨系统最终一致性。

## 权限与四眼原则

租户成员角色的预期职责如下：

| 角色 | 预期职责 |
|---|---|
| `travel_advisor` | 管理客户需求、方案和报价草稿。 |
| `booking_operator` | 在审批通过后执行供应商预订。 |
| `approver` | 当前唯一可决定内部订单审核的租户岗位；必须属于同一 `active` 旅行社且成员状态为 `active`。 |
| `finance` | 执行或复核支付、退款和对账。 |
| `auditor` | 只读审计业务事件和执行记录。 |
| `admin` / `owner` | 管理旅行社成员和配置；高风险动作仍应遵循职责分离。 |

当前报价、订单和审核 API 已校验有效旅行社、租户内 `active` 成员、`active` 旅行社客户关系、客户本人归属，以及客户会话和供应商产品的同租户关系；完整报价 DTO（数据传输对象）只开放给客户本人或 `owner`、`admin`、`travel_advisor`，完整订单 DTO 额外允许专职 `approver` 只读已经生成审核记录的订单，审核队列和审核详情也只开放给租户 `approver`，事件接口则允许租户内有效成员访问但剔除报价快照。`approver` 看不到未提交审核的订单，不能创建或发布报价；`owner`、`admin`、`travel_advisor`、`booking_operator`、`finance` 和 `auditor` 也不能代替 `approver` 作决定。越权访问具体对象统一按未找到处理。

内部订单审核当前保证：

1. 决定人属于目标 `agency_id`，旅行社和成员状态均为 `active`，租户岗位必须严格为 `approver`。
2. 订单处于 `pending_review`，审核记录处于 `pending`，且两者通过旅行社、订单、提交修订号、`payload_hash`、金额和币种绑定。
3. 决定请求校验当前订单 `expected_revision`，并锁定订单行和审核行。
4. 订单客户或审核发起人不能决定自己的审核。
5. 跨租户或越权资源不暴露存在性。

这套内部审核不等于平台 Approval/HITL。未来真实外部动作仍需把平台审批记录绑定动作、租户、资源、金额、币种、`revision`、`payload_hash`、过期时间和供应商适配器版本。

## 幂等、并发与审计

当前最小内部 API 已落实：

- 所有写请求要求稳定的 `Idempotency-Key`（幂等键）。
- 同一作用域的同一幂等键只能重放相同请求；负载哈希不同必须返回冲突。
- 当前报价/订单幂等记录按永久唯一处理，不设置过期复用；`expires_at` 仍是预留字段，尚无自动清理策略。
- 报价和订单状态修改必须携带预期 `revision`；修订号不一致时拒绝覆盖。
- 状态变化与 `agency_order_event` 在同一数据库事务中提交。
- 审核决定把 `decision`、订单、操作者、`expected_revision` 和原因纳入请求哈希；批准/拒绝共用 `order.review.decide` scope，不能用同一键切换决定。

未来外部交易入口还必须满足：

- 外部调用前先落本地意图和幂等记录，回执以可重放方式落账。
- timeout（超时）不能直接推断为失败或成功，必须进入查询、重试或人工介入。

当前单元测试覆盖 API 契约、租户岗位、禁止自审、审核绑定、幂等重放/冲突、订单/审核行锁和外部动作关闭。仓库已增加 PostgreSQL 集成测试与独立 CI job，使用一次性 PostgreSQL 17 service 覆盖 `upgrade -> downgrade -> legacy upgrade`、租户复合外键、只追加触发器、并发幂等、修订号冲突和审核竞争。本机没有可用 PostgreSQL，因此本地仍是 `not run`；CI 配置落库也不等于远端 job 已通过，更不能代替目标环境、事务故障和供应商故障注入测试。

## 外部执行的默认关闭策略

当前配置默认值：

```dotenv
TRANSACTION_MODE=disabled
ZHIXING_REAL_PAYMENT_ORDER_DISABLED=true
LIVE_SUPPLIER_BOOKING_ENABLED=false
LIVE_PAYMENT_ENABLED=false
LIVE_REFUND_ENABLED=false
LIVE_NOTIFICATION_ENABLED=false
```

门禁按以下顺序 fail-closed（故障时默认拒绝）：

1. 总熔断开关仍为关闭真实动作时，所有外部交易拒绝。
2. `TRANSACTION_MODE=disabled` 时，只允许保存内部草稿和业务事实。
3. 对应细粒度动作开关未开启时，拒绝该类外部动作。
4. 即使配置门禁通过，仍必须校验租户权限、四眼审批、资源修订号、负载哈希、幂等记录、供应商凭据和适配器安全检查。

当前仓库没有完成第 4 步所需的真实适配器与端到端证据，因此不得开启 live（真实执行）模式。

`/health/ready` 会在 `services.transaction_execution` 中输出不含密钥的门禁快照。`configuration_gate_passed=true` 只表示配置层通过，不是最终执行许可；默认关闭也不会让报价/订单草稿 API 被判为未就绪。

## 下一阶段缺口

1. 增加客户导入、客户同意、关系激活/停用、顾问分配和来源审计 API；当前 `travel_advisor` 仍是旅行社级报价权限，不是按门店或客户分配的行级权限。
2. 扩展取消、人工介入和后续处理入口，并在真实 PostgreSQL 覆盖跨租户越权、并发冲突、报价过期和事务回滚。
3. 将平台 `approval_request` 强绑定到未来外部动作、订单、金额、币种、修订号和负载哈希；内部订单审核不能代替平台 Approval/HITL。
4. 在 sandbox（沙箱）环境实现供应商预订和支付适配器，包括回调验签、查询补偿、限流、熔断和故障注入。
5. 增加退款、改签、部分履约和 Saga（分布式事务补偿流程）状态机。
6. 建立供应商对账、财务清分、发票/合同、客服工单、通知偏好和服务质量反馈。
7. 完成 PII（个人可识别信息）分级、保留与删除、操作审计、商户权限、支付合规和正式用户条款。
8. 在目标环境绑定 commit，真实执行 `0001 -> 0002 -> 0003` 迁移、备份恢复、并发、回调重放、故障恢复和小流量验收，再评估是否放行单个真实动作。
9. 明确幂等记录的长期保留、归档和删除策略；真实支付或预订重放还需保存首次响应快照，不能只返回资源当前状态。

在这些缺口补齐前，统一对外口径是：“项目的目标业务是旅行社；当前已具备 Agent 规划交付能力和交易数据/控制面骨架，真实供应商与资金动作尚未接入且默认关闭。”
