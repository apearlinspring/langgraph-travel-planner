# Agency Customer and Transaction Domain（旅行社客户与交易域）

## 业务定位

ZhiXing 的目标产品不是面向散客的攻略生成器，而是旅行社经营与交付工作台。Agent（智能体）负责辅助旅行顾问理解客户需求、匹配产品、准备方案与报价、形成订单草稿和交付说明；当前确定性服务负责保存门店、客户生命周期、顾问分配、报价、订单、内部审核、人工取消案件、补偿结果、独立对账和幂等事实。旅行社内部订单审核已经绑定门店、订单版本与金额，但平台 Approval/HITL（审批/人类在环）、真实支付执行和供应商履约仍属于后续阶段。

当前版本处于第一阶段：已经建立旅行社门店、客户生命周期和交易域的数据与控制面骨架，但没有接入真实供应商预订、支付、退款和通知。客户认领摘要、服务端同意记录、`agency_quote` 或 `agency_order` 都只是平台内工程事实，不能单独证明真实身份、法律合规、库存已锁定、资金已收取、票务已确认或服务已履约。

## 当前已实现

| 能力 | 当前代码证据 | 当前边界 |
|---|---|---|
| 多租户经营边界 | `agency`、`agency_membership` | 保存旅行社与成员角色；每个业务 API 必须校验有效成员和租户归属。`0007` 另以数据库触发器冻结成员记录的 `id`、`agency_id`、`user_id` 和 `created_at` 身份绑定，不允许把既有成员改绑到另一账户或旅行社。 |
| 门店与岗位授权 | `agency_branch`、`agency_branch_role_grant`、`agency_branch_lifecycle_event` | 保存门店及成员在指定门店的有效岗位；`owner`、`admin` 维持旅行社全域权限，其他岗位按门店授权。门店按 `active -> inactive -> closed` 推进：`inactive` 停止新业务并保留清理动作，`closed` 是阻断项清零后的不可逆终态；停用和关闭写入门店生命周期事件。 |
| 客户生命周期 | `agency_customer`、`agency_customer_invitation`、`agency_customer_consent_record`、`agency_customer_event` | 允许线下潜客无平台用户登记，再为指定已有平台账户签发安全认领凭证，由该已登录账户认领；服务端生成规范化同意证据并保存只追加决定记录，之后才能激活。活跃客户拒绝/撤回同意或关系停用时，会原子结束当前顾问分配并收口内部交易。没有批量导入、邀请投递、真实身份核验或客户通知。 |
| 客户当前门店转移 | `agency_customer_branch_transfer` | 仅旅行社 `owner/admin` 可把客户从 `active/inactive` 来源门店即时原子转入另一个 `active` 门店；`active` 客户可选目标主顾问，`inactive/blocked` 客户可转但不新建主顾问。只修改客户当前服务门店，历史邀请、同意、事件、分配、报价、订单和取消记录保留发生时门店。待认领邀请或开放报价、订单、审核、取消案会阻断；不发送通知、不处理外部订单。 |
| 顾问分配 | `agency_customer_advisor_assignment` | 同一客户只保留一个当前有效主顾问，可更换或结束；顾问必须持有同门店有效 `travel_advisor` 授权。 |
| 供应商产品目录 | `supplier_product` | 保存旅行社可销售产品及供应商外部编号；不代表实时库存或价格同步。 |
| 报价快照 | `agency_quote` | 保存客户、产品、金额、币种、有效期、报价快照、`revision`（修订号）和 `payload_hash`（业务负载哈希）。 |
| 订单快照 | `agency_order` | 保存报价来源、客户、金额、支付状态、履约状态和外部动作开关；不自动调用外部服务。 |
| 内部订单审核 | `agency_order_review` | 绑定旅行社、门店、订单、提交时 `revision`、`payload_hash`、金额、币种和发起人；只有订单门店持有有效授权的专职 `approver` 可决定，内部通过不触发外部动作。 |
| 人工取消与对账 | `agency_order_cancellation_case`、`agency_order_cancellation_event`、`agency_order_compensation_record`、`agency_order_reconciliation_record` | 受理取消申请、分岗登记平台外人工结果并由不同审计人员核验；外部引用与证据只保存 SHA-256 摘要，绝不调用外部取消或退款接口。 |
| 状态审计 | `agency_customer_event`、`agency_branch_lifecycle_event`、`agency_order_event` | 按客户、门店或订单的事件序号记录生命周期变化；对外响应裁剪内部操作者和事件元数据。 |
| 持久化幂等 | `idempotency_record`，以及报价、订单、支付尝试、履约记录的唯一键 | 当前报价/订单服务已校验“同键同请求”，同键异请求返回冲突；未来外部动作仍需保存不可变响应快照并验证供应商侧幂等。 |
| 执行账本 | `payment_attempt`、`fulfillment_record` | 为未来支付与供应商履约保留尝试记录；当前不会执行真实支付或预订。 |
| 并发版本 | 报价和订单使用 SQLAlchemy `version_id_col` | 提供乐观并发控制基础；业务入口还必须要求并校验预期修订号。 |
| 租户角色 | `agency_membership.role` | 租户内区分旅行顾问、预订操作员、审批员、财务、审计、管理员和所有者；只有 `approver` 具有当前订单审核决定权。它与平台级 `user`、`approver`、`admin` 角色分离。 |
| 门店与客户 API | `/api/v1/agency` | 共 24 个操作、15 个 `POST`；支持门店、授权、停用/关店、关店就绪计数、客户认领邀请、认领、固定技术告知读取、服务端同意证据、客户生命周期、当前门店转移、顾问分配和事件查询，不包含邀请投递、通知、PII 档案或跨门店经理双向交接审批。 |
| 内部交易 API | `/api/v1/agency` | 交易子集共 13 个操作、6 个 `POST`；支持报价、订单和内部审核查询/决定，不包含供应商预订、支付、退款或通知执行。 |
| 人工取消 API | `/api/v1/agency` | 取消子集共 9 个操作、5 个 `POST`；支持申请、专职审批、人工结果登记、脱敏结果队列、独立对账、恢复和脱敏查询，不包含任何外部执行。 |
| 外部执行门禁 | `app/agency/transaction_policy.py`、配置样例和 Compose 模板 | 总开关、运行模式和四类动作开关默认关闭；配置门禁通过也不等于业务动作获准。 |
| 数据库迁移 | Alembic 交易域版本和 migration contract（迁移归属契约） | 证明表结构可由项目管理，不证明生产数据库已迁移或数据已验证。 |

当前能力应统一表述为“旅行社门店、客户生命周期和交易数据控制面骨架”。现有 API（应用程序接口）只能证明内部业务事实可被受控写入，不能扩写成完整 CRM、法律合规、真实供应链和资金链已经连通。

## 与 Agent 规划链路的边界

```text
客户对话
  -> 规划模式确认
  -> 自由规划 / 旅行社省心方案
  -> report_data 方案与预算
  -> 线下潜客登记 -> 为目标账户签发认领凭证 -> 已登录目标账户认领
  -> 服务端记录本人同意 -> 关系激活
  -> 门店主顾问分配
  -> 可选：owner/admin 原子转移当前服务门店与主顾问
  -> 显式进入交易域
  -> 报价草稿 -> 正式报价 -> 客户接受
  -> 订单草稿 -> 提交人工审核
  -> 专职审批员批准 / 拒绝
  -> 必要时：取消申请 -> 专职审批 -> 平台外人工结果登记 -> 独立对账
  -> 门店停止新业务 -> inactive 清理 -> 阻断项清零 -> closed
  -> 未来：真实支付 / 供应商预订 / 履约 / 退款
```

前半段是 Agent 规划与交付链路，后半段是确定性的旅行社交易链路。两者不能通过一个文本编号或模型回复隐式跨越：

- `agency_plan` 只说明当前对话使用旅行社产品化方案，不代表创建了 `agency_quote`。
- 客户登记、认领和同意记录属于确定性业务 API，不由模型文本自动推断；token 摘要和服务端同意记录也不是身份或法律合规证明。
- `report_data` 中的预算是方案表达，只有经过有效期、金额、币种和快照校验后才能形成正式报价。
- `generate_order_tool` 与 `mock_checkout` 只生成演示用 `ORDER-` 编号，不是 `agency_order`，也不是合同、收款或供应商确认凭证。
- LLM（大语言模型）不能直接决定支付成功、库存锁定、退款完成或履约完成；这些状态只能由确定性服务根据外部回执和审计规则写入。

## 最小业务 API

当前路由挂载在 `/api/v1/agency`：

### 门店与客户生命周期

| 方法与路径 | 当前职责 | 关键门禁 |
|---|---|---|
| `POST /branches`、`GET /branches` | 创建门店；按当前权限列出旅行社门店。 | 仅 `owner`、`admin` 可创建；其他成员只看有有效授权的门店。 |
| `POST /branches/{branch_id}/deactivate` | 把 `active` 门店转入停止新业务的 `inactive` 清理期。 | 仅 `owner/admin`；要求原因、`expected_revision` 和 `Idempotency-Key`。进入清理期不要求阻断项预先清零，也不表示门店已关闭。 |
| `GET /branches/{branch_id}/closure-readiness` | 返回关店阻断项聚合计数。 | `owner/admin` 或当前门店经理可读；只返回当前客户、待邀请、有效分配/授权、待审核、开放报价/订单/取消案数量，不暴露具体资源 ID。只有 `inactive` 且全部计数为零时 `ready=true`。 |
| `POST /branches/{branch_id}/close` | 把已清理完毕的 `inactive` 门店转为不可逆 `closed`。 | 仅 `owner/admin`；要求原因、`expected_revision` 和 `Idempotency-Key`。所有当前客户（不论 `invited/prospect/active/inactive/blocked`）、待认领邀请、有效顾问分配/岗位授权、待审核记录、开放报价/订单/取消案必须清零。 |
| `POST /branches/{branch_id}/role-grants`、`GET /branches/{branch_id}/role-grants` | 授予或查询成员的门店岗位。 | 仅旅行社全域管理员可授予；授权角色必须与成员角色一致，且不向 `owner`、`admin` 发门店授权。 |
| `POST /branches/{branch_id}/role-grants/{grant_id}/revoke` | 撤销门店岗位授权。 | 要求 `expected_revision`、原因和 `Idempotency-Key`；授权仍绑定当前有效顾问分配时拒绝撤销。若存在待处理订单审核或 `approval_pending` 取消案，撤权后必须逐笔业务仍有至少一名排除该业务发起人和订单客户的 eligible approver（合格审批员），不能只按门店审批员总数判断。 |
| `POST /customers`、`GET /customers`、`GET /customers/{customer_id}` | 登记未绑定账户的线下潜客并按门店/顾问范围查询。 | 创建者为全域管理员或同门店 `branch_manager`；顾问只看当前分配客户，客户认领后才按本人身份取得关系可见性。 |
| `POST /customers/{customer_id}/transfer` | 原子改变客户当前服务门店，并可为 `active` 客户选择目标主顾问。 | 仅 `owner/admin`；来源门店须为 `active/inactive`，目标门店须为同旅行社 `active` 且客户编号无冲突。待认领邀请或开放报价、订单、审核、取消案会阻断。旧主顾问在同一事务结束；`inactive/blocked` 客户可转但不得指定新主顾问。历史记录门店不改写，不通知客户、不改变外部订单。 |
| `POST /customers/{customer_id}/claim-invitations`、`GET /customers/{customer_id}/claim-invitations` | 为指定已有平台账户签发认领凭证并查询邀请元数据。 | 仅客户管理角色；凭证使用 32-byte（256-bit）高熵随机数，24 小时过期、可撤销、单次使用，数据库只保存 SHA-256 摘要。同一旅行社同一目标账户同一时刻最多一条 `pending` 邀请。原始 token 只在首次签发事务提交成功后的响应返回，幂等重放不再返回；响应丢失时必须撤销并重发。当前不投递短信、邮件或站内信。 |
| `POST /customers/{customer_id}/claim-invitations/{invitation_id}/revoke` | 撤销尚未使用的认领邀请。 | 要求客户与邀请各自的预期修订号、原因及 `Idempotency-Key`；待处理邀请必须先撤销才能重新签发。 |
| `POST /customer-claims` | 由已登录目标账户使用认领 token 绑定客户关系。 | token 必须存在、未过期、未撤销、未使用且目标账户等于当前登录账户；失败统一按不可用处理，成功后邀请进入不可逆 `claimed` 终态。 |
| `GET /customer-consent-notice` | 返回提交授权决定前必须展示的固定技术告知。 | 仅认证用户；响应包含 Markdown、`consent_version`、`consent_document_sha256`、`evidence_schema_version` 和 `channel`。 |
| `POST /customers/{customer_id}/consent` | 记录已认领客户本人的 `grant`、`deny` 或 `revoke` 决定。 | 仅客户本人；请求必须携带从告知接口读取的 `expected_notice_version` 和 `expected_notice_document_sha256`，服务端发现版本变化时返回冲突；客户端不能提交 evidence hash。服务端生成 canonical（规范化）证据并写入 append-only（只追加）记录。活跃客户 `deny/revoke` 时原子转为 `inactive`、结束当前顾问分配并执行内部交易收口。 |
| `POST /customers/{customer_id}/activate`、`POST /customers/{customer_id}/deactivate` | 激活或停用客户关系。 | 新激活要求 `secure_claim + consent_status=granted + server_canonical` 和有效门店；停用会结束当前顾问分配并执行内部交易收口，客户本人停用时同时撤回同意。 |
| `POST /customers/{customer_id}/advisor-assignments`、`POST /customers/{customer_id}/advisor-assignments/end` | 创建、更换或结束当前主顾问。 | 仅全域管理员或同门店经理；顾问必须持有同门店有效 `travel_advisor` 授权。 |
| `GET /customers/{customer_id}/advisor-assignments`、`GET /customers/{customer_id}/events` | 查询顾问分配历史和客户生命周期只追加事件。 | 按同一客户可见性授权；响应不返回客户事件原始元数据。 |

这组接口共 24 个操作，其中 15 个 `POST` 都强制 `Idempotency-Key`。状态变更要求对应 `expected_revision`，使用行锁和持久化幂等记录；客户事件、同意记录只追加，顾问分配同一时刻只允许一条 `active`。客户响应不暴露已关联 `user_id`，转店响应不返回操作者、原因或分配 ID，关店就绪只返回聚合计数；邀请列表不返回 token 或摘要，token 格式错误也不得在 `422` 中回显，签发/认领响应使用 `Cache-Control: no-store`。模型没有姓名、电话、证件或联系人等 PII（个人可识别信息）字段。普通交易写按 `customer -> branch -> quote/order` 锁定；转店按 `customer -> source/target branches（UUID 顺序） -> membership/grant -> assignment` 固定范围。授权敏感写入还对门店和成员范围持有共享行锁，使并发撤销岗位授权或改变门店状态必须等待，避免 TOCTOU（检查与使用时序差）竞态。当前这些锁序已有代码和单元测试，但目标 PostgreSQL 的并发锁等待证据仍未完成。旅行社 API 使用 function-scope（函数作用域）数据库依赖，在响应发送前完成提交和提交阶段错误映射；DEFERRABLE（提交时延迟校验）约束失败不会先返回虚假的 `2xx`。

### 报价、订单与内部审核

| 方法与路径 | 当前职责 | 关键门禁 |
|---|---|---|
| `POST /quotes` | 旅行社报价角色为指定客户创建报价草稿。 | 客户已完成 `secure_claim`、关系为 `active`、同意为 `granted`、当前同意记录来源为 `server_canonical`、门店有效、客户会话/产品同租户，以及报价管理范围和 `Idempotency-Key`。 |
| `GET /quotes`、`GET /quotes/{quote_id}` | 全域管理员、同门店经理、当前主顾问或客户本人按范围读取报价。 | 非本人、非同门店或非当前分配对象按未找到处理。 |
| `POST /quotes/{quote_id}/issue` | 将未过期草稿发布给客户。 | 同一报价管理范围、客户仍可交易、`Idempotency-Key`、`expected_revision`。 |
| `POST /quotes/{quote_id}/accept` | 报价所属客户接受有效报价。 | 客户本人、`Idempotency-Key`、`expected_revision`。 |
| `POST /orders` | 客户从本人已接受报价创建订单草稿。 | `Idempotency-Key`、`expected_quote_revision`、报价未过期。 |
| `GET /orders`、`GET /orders/{order_id}` | 全域管理员、同门店经理、当前主顾问、客户本人按范围读取；同门店专职 `approver` 只读已生成审核记录的订单。 | `approver` 看不到尚未提交审核的订单，也不能创建或发布报价；预订、财务和审计岗位仍需 purpose-specific（按职责裁剪）DTO。 |
| `GET /order-reviews` | 查询门店范围内结构化审核工作队列，支持状态和分页。 | 只允许同一 `active/inactive` 门店中持有有效授权的专职 `approver`；`inactive` 可见性只服务于清理。 |
| `GET /orders/{order_id}/review` | 读取单个订单的结构化审核记录。 | 仅订单门店的有效专职 `approver` 可读；客户通过订单 DTO 查看状态，不取得内部原因和决定人信息。 |
| `GET /orders/{order_id}/events` | 客户本人或具有该订单可见性的成员读取订单只追加事件。 | 响应只允许公开的元数据字段，不能借事件接口绕过快照权限。 |
| `POST /orders/{order_id}/submit` | 客户将订单草稿提交为 `pending_review`。 | 客户本人、`Idempotency-Key`、`expected_revision`，且订单门店至少有一名排除审核发起人和订单客户的 eligible approver；订单存在开放取消案时禁止送审。提交后每笔待审核业务都必须继续保留满足同一排除条件的替代审批员。 |
| `POST /orders/{order_id}/review` | 处理 `pending_review`。 | 仅订单门店的专职 `approver`；批准要求门店 `active` 且客户仍为 `active + granted`，门店进入 `inactive` 或客户停用后只能拒绝为 `review_rejected`。请求包含 `decision=approve\|reject`、`expected_revision`、`reason` 和 `Idempotency-Key`，拒绝时 `reason` 必填。 |

交易子集共有 13 个操作，所有六个 `POST` 都强制要求 `Idempotency-Key`。服务使用 PostgreSQL 持久化幂等记录；审核批准和拒绝共用单一 `order.review.decide` scope（作用域），同键同请求返回原审核资源，同键异请求返回 `409 Conflict`。报价、订单和审核状态变化使用 `SELECT ... FOR UPDATE`；订单提交会创建审核记录，审核决定会同时更新订单、审核记录并追加 `order_review_approved` 或 `order_review_rejected` 事件。`0004` 的 PostgreSQL mutation guard（变更门禁）会固化报价/订单的租户、门店、客户和账户绑定，复验客户同意、门店状态、报价有效期和订单/报价金额、币种、快照一致性，要求 `revision` 每次恰好加一，只允许声明过的状态迁移，并要求新订单以 `draft + not_started + external_action_enabled=false` 的惰性状态创建；`0005` 进一步要求新报价/订单所用客户为 `secure_claim + server_canonical`。订单与审核的批准/拒绝终态还会通过 DEFERRABLE（延迟到事务提交校验）约束触发器成对检查，阻止只改一侧的直接 SQL。当前 API 没有供应商预订、支付、退款或通知调用。

### 人工取消、补偿结果与独立对账

| 方法与路径 | 当前职责 | 关键门禁 |
|---|---|---|
| `POST /orders/{order_id}/cancellation-requests` | 为可取消订单创建案件。 | 客户本人、当前主顾问、同门店经理或全域管理员；服务端从锁定的订单、支付尝试和履约记录派生所需动作，客户端不能指定，数据库 INSERT 门禁还会从锁定账本独立复算。建案时必须已有排除案件发起人和订单客户的 eligible approver；原订单仍为 `pending_review` 时必须先由原审核流程拒绝，案件开放期间该订单也不能再送审。 |
| `GET /orders/{order_id}/cancellation-case`、`GET /cancellation-cases` | 读取单案或按授权范围列出案件。 | 客户、交易可见岗位、专职审批员及按职责参与的预订、财务、审计岗位只读脱敏投影。 |
| `POST /cancellation-cases/{case_id}/review` | 批准或拒绝申请。 | 仅同门店专职 `approver`，`owner/admin` 不可替代；申请人和订单客户不能审批。门店处于 `active` 或 `inactive` 清理期均可继续处理取消案件，成员与授权仍须有效且角色严格为 `approver`。存在财务核验需求时批准金额必须与订单同币种且不超过订单总额。 |
| `POST /cancellation-cases/{case_id}/manual-results` | 登记平台外人工取得的供应商取消或财务结果。 | `booking_operator` 只能登记 `supplier_cancel`，`finance` 只能登记 `refund`；只接收外部引用和证据的 SHA-256 摘要，`system_external_action_triggered=false`。 |
| `GET /cancellation-cases/{case_id}/manual-results` | 按案件列出脱敏人工结果、opaque（不透明）记录 ID 和对账状态，供独立审计岗位发现待办。 | 仅同一 `active/inactive` 门店中持有有效授权的专职 `auditor` 可读，`owner/admin` 和普通案件查看者不能替代；不返回登记人、外部引用摘要或证据摘要，供应商取消结果的存储占位金额/币种投影为 `null`。 |
| `POST /manual-results/{record_id}/reconcile` | 对最新成功结果做独立核验；退款对账由审计员独立提交观察金额、币种和证据，而不是复制财务登记值。 | 仅同门店 `auditor`，且不能核验自己登记的结果；`matched` 退款必须与财务记录一致，每条结果最多一条对账记录。 |
| `POST /cancellation-cases/{case_id}/resume` | 从 `manual_intervention` 恢复待处理动作。 | 同门店经理或全域管理员；不会自动重试外部动作。 |
| `GET /cancellation-cases/{case_id}/events` | 查询案件只追加事件。 | 与案件可见性一致；不返回负载摘要、原始备注或事件元数据。 |

审批通过后有两条路径。若服务端派生的 `supplier_cancel_required=false` 且 `refund_required=false`，符合条件的 `draft`/`approved` 订单直接走 `approval_pending -> completed` 并进入内部 `cancelled`；否则案件按 `approval_pending -> action_pending -> reconciliation_pending -> completed` 推进。审批拒绝进入终态 `rejected`，失败、未知或对账不一致进入 `manual_intervention`，恢复后回到 `action_pending`。当同时需要供应商和财务证据时，以每类动作最新一条成功记录及其 `matched` 对账为准，旧失败或旧不匹配记录保留审计但不永久阻断修复。所有写请求都要求 `Idempotency-Key` 和预期修订号，锁序为 `customer -> branch/auth -> order -> payment/fulfillment -> cancellation case`。

若客户撤回同意或关系停用先改变了订单，已有 `approval_pending` 取消案件不会被伪装成已完成：审批批准会因订单版本或暴露派生已变化而失败，专职审批员仍可拒绝该 stale（已失效）案件；若业务仍需取消，应按新订单状态重新建案。当前尚未提供 `superseded`（已被后续生命周期动作取代）终态或自动工单收口，因此运营侧仍需清理这类悬挂案件。

`refund_required` 是失败关闭的财务登记与核验门禁：它可能来自已支付、处理中、失败或已退款等投影及明细暴露，表示必须由财务说明现状并由审计核对，不是平台要求再次退款。统一响应不返回 `reason_detail`、内部审批备注、外部引用摘要、证据摘要、`payload_hash` 或 `event_metadata`。案件 `completed` 只说明订单已经在平台内进入 `cancelled`：无外部暴露时可由审批直接完成；存在服务端派生的必需动作时，还要求各类最新成功人工结果都已由不同审计人员核验为 `matched`。两种情况都不能扩写成供应商、银行或客户已经收到真实动作。

## 数据模型

### 租户、门店与产品

- `agency` 是旅行社数据隔离和授权的根边界。
- `agency_membership` 将员工关联到旅行社，并保存租户内角色和成员状态。`0007` 冻结其 `id`、`agency_id`、`user_id`、`created_at` 身份绑定；这不等于冻结受控的角色或状态生命周期。
- `agency_branch` 是门店归属与应用层权限范围；迁移为每个旧旅行社建立一个 `MAIN` 门店。`active` 接受新业务；`inactive` 表示已经停止新客户、岗位授权、认领、激活、顾问分配、报价、订单和审核批准，只保留可见性与关店清理；`closed` 在所有当前客户（含 `inactive/blocked`）、待邀请、有效分配/授权、待审核和开放报价/订单/取消案清零后进入，并且不可逆。`deactivated_at` 和 `closed_at` 分别记录进入清理期和最终关闭时间，生命周期事件按门店修订号只追加。
- `agency_branch_role_grant` 把非全域岗位授权到指定门店；`owner`、`admin` 不使用该表，其余门店岗位必须与 `agency_membership.role` 一致。
- `supplier_product` 保存旅行社可销售的供应商产品。`supplier_code` 和 `external_product_code` 只用于识别上游对象，不代表上游对象当前可售。

### 客户生命周期与顾问分配

- `agency_customer` 以 `invited`、`prospect`、`active`、`inactive`、`blocked` 表达关系状态，并用 `binding_provenance=unbound|legacy_direct|secure_claim` 明确账户绑定来源。线下潜客必须以 `user_id=NULL + unbound` 登记；只有认领成功才能形成新的账户绑定。`blocked` 不能通过普通停用再激活解除，只能由未来独立风险复核流程处理。当前没有邀请投递或通用解绑入口。
- `agency_customer_invitation` 保存目标账户、状态、过期时间和 token 的 64 位十六进制 SHA-256 摘要；不保存原始 token。`pending` 只能转为 `claimed` 或 `revoked`，终态不可修改、记录不可删除；同一客户同一时刻只允许一条待处理邀请，同一旅行社也不能同时为同一目标账户保留多条待处理邀请。
- `agency_customer_consent_record` 为每个决定保存序号、客户修订号、固定技术告知版本、文档摘要、规范化证据摘要、来源和服务端时间。新记录来源为 `server_canonical`，更新或删除由数据库触发器拒绝；[技术告知正文](customer-consent-notice-v1.md) 不替代隐私政策、合同、身份核验或法务审查。
- 新客户只有在 `secure_claim`、`consent_status=granted`、当前证据来源为 `server_canonical` 且门店有效时才能激活或进入新报价/订单。`0005` 将存量直接绑定显式标记为 `legacy_direct`，将已有客户端证据标记为 `legacy_client_hash`，不会伪造安全认领；存量账户仍可 `deny/revoke`。原账户升级认领时保留历史只追加记录，但旧同意投影会重置为 `unknown + none`；若原关系为 `active`，会先转为 `inactive`、结束当前顾问分配并收口内部交易，之后必须重新提交服务端规范化 `grant` 并激活才能新增交易。旧数据升级到 `0004` 时统一回填的 `unknown` 同意继续保持没有证据。
- `consent_version` 和 `consent_evidence_hash` 是当前决定的投影；权威审计事实是只追加同意记录。API 允许客户端回传当前告知的预期版本和文档摘要以检测 stale notice（过期告知），但不接收客户端自定义 evidence hash，也不保存原始法律材料；这些摘要不能证明条款有效、身份核验或法律合规已经完成。
- `agency_customer_event` 按客户和事件序号只追加记录生命周期变化，公开响应不返回原始 `event_metadata`。
- `agency_customer_advisor_assignment` 绑定同门店 `travel_advisor` 授权，同一客户同一时刻只允许一个 `active` 主顾问；更换时先结束旧分配，也可单独结束而不自动停用客户。
- `agency_customer_branch_transfer` 绑定旅行社、客户、来源/目标门店和客户新修订号。转店在同一事务结束旧主顾问、更新客户当前 `branch_id`，并按需为 `active` 客户建立目标主顾问；客户状态、账户/同意投影及历史邀请、同意、事件、旧分配、报价、订单和取消事实保持不变。响应不暴露操作者或原因。
- 当前客户模型没有姓名、电话、邮箱、证件、联系人或详细画像字段。内部 `user_id` 只用于账户绑定，并从客户、报价、订单和事件公开 DTO 中裁剪；`source_reference` 只能保存不含 PII 的外部系统不透明引用。这些限制仍不等于已经完成 PII 治理。

### 报价

`agency_quote` 保存一份在特定时点可复核的业务快照：

- `quote_no`：旅行社报价编号。
- `agency_id`、`branch_id`、`customer_id`、`user_id`、`product_id`：租户、门店、客户关系、关联账户和产品归属；公开 DTO 不返回 `user_id`。
- `total_amount`、`currency`：使用定点金额和三位大写币种代码。
- `quote_snapshot`、`snapshot_version`：报价内容和契约版本。
- `valid_until`：报价有效期。
- `revision`、`payload_hash`：并发修订号和内容指纹。
- `idempotency_key`：租户内报价创建幂等键。

报价表保留 `draft`、`offered`、`accepted`、`expired` 和 `cancelled` 状态；`0004` 数据库触发器当前只允许：

```text
draft -> offered
offered -> accepted
offered -> expired
draft / offered / accepted(尚无订单) -> cancelled
```

创建报价要求未来有效期，过期报价不能发布或接受，已经形成订单的 `accepted` 报价不能取消。当前最小报价 API 已覆盖 `draft -> offered -> accepted`、报价有效期、操作者权限和预期修订号，但没有独立的报价过期或报价取消管理入口；`0007` 的取消案件 API 只接受订单，不接受报价。客户关系停用收口可以在同一事务中把 `draft`、`offered` 以及尚未形成订单的 `accepted` 报价置为内部 `cancelled`；已经形成订单的 `accepted` 报价保留为订单来源快照。

### 订单

`agency_order` 从报价快照形成，并分别记录业务状态、支付状态和履约状态。表中预留 `draft`、`pending_review`、`approved`、`review_rejected`、`processing`、`completed`、`failed`、`manual_intervention`、`cancellation_pending` 和 `cancelled`；这些值不代表彼此间都可迁移。当前 `0007` 订单门禁在保留 `0004` 审核路径的基础上允许：

```text
draft -> pending_review
pending_review -> approved / review_rejected
draft / approved -> cancelled
draft / approved / processing / failed / manual_intervention -> cancellation_pending
cancellation_pending -> manual_intervention / cancelled
manual_intervention -> cancellation_pending / cancelled
```

这三个维度必须分开解释：

- `status=approved` 只代表旅行社内部审核通过，不代表已经支付或预订。
- `payment_status=paid` 未来只能由受控支付适配器及其回执驱动。
- `fulfillment_status=confirmed` 未来只能由供应商确认或受控人工核验驱动。

`external_action_enabled` 默认是 `false`。它只是单条记录的保护字段，不能替代全局配置门禁、租户权限、审批、修订号、负载哈希和幂等检查。

当前内部 API 已实现 `draft -> pending_review -> approved / review_rejected`，但开放取消案会同时在服务层和数据库层阻止订单进入 `pending_review`。客户关系停用可以执行受限的内部 `cancelled` / `cancellation_pending` 收口，`0007` 人工取消案件可以在平台外结果被分岗登记并独立核验后推进 `cancellation_pending <-> manual_intervention -> cancelled`。`approved` 只代表旅行社内部审核通过；`processing`、`completed`、`failed` 的通用履约入口仍未开放，取消状态机也不执行真实供应商或资金动作。

### 客户关系停用时的内部交易收口

当活跃客户记录 `deny` 或 `revoke`，或者客户关系被停用时，客户状态、当前顾问分配、相关报价/订单和审计事件在同一数据库事务中收口：

| 原资源状态 | 内部处理 |
|---|---|
| 报价 `draft` / `offered` | 变为 `cancelled`。 |
| 报价 `accepted` 且尚无订单 | 变为 `cancelled`；已有订单时保留报价作为来源快照。 |
| 订单 `draft` / `approved`，且 `external_action_enabled=false`、支付与履约均为 `not_started` | 变为 `cancelled`，并追加客户关系停用订单事件。 |
| 订单 `pending_review` | 保持 `pending_review`，保留给门店审批员执行 `reject`；`approve` 会重新校验客户仍为 `active + granted`，因此必须失败，且该审核拒绝前客户关系不能重新激活。 |
| 可能已有外部、支付或履约状态，或者处于异常处理中 | 转为 `cancellation_pending`，或保持 `manual_intervention` / `cancellation_pending` 并追加需要人工处理的事件。 |
| 已终结订单 | 不改写终态。 |

这个收口只改变本系统的内部状态，事件元数据明确记录 `external_actions_triggered=false`、`supplier_cancellation_confirmed=false` 和 `refund_confirmed=false`。内部 `cancelled` 或 `cancellation_pending` 绝不表示供应商侧预订已取消、资金已退款或客户已收到通知。

### 内部审核、取消事件、支付与履约记录

- `agency_order_review` 在提交审核时保存 `agency_id`、`branch_id`、`order_id`、提交时订单修订号、负载哈希、金额、币种和发起人。决定后再保存决定修订号、审批员、脱敏原因和时间。
- 同一旅行社、订单和提交修订号只能有一条审核记录；数据库约束要求决定人与发起人不同，服务层同时拒绝订单客户或审核发起人自审。PostgreSQL 触发器禁止删除审核记录、修改审核绑定字段或再次修改已终结的审核；DEFERRABLE 约束触发器会在事务提交时确认订单 `approved/review_rejected` 与审核 `approved/rejected` 成对一致，直接 SQL 只改一侧必须失败。
- `agency_order_event` 是订单关键变化的只追加事件，使用 `event_sequence` 和 `order_revision` 关联状态快照；客户关系停用的内部取消、待取消和人工处理状态也会写入该事件流。
- `payment_attempt` 是未来支付调用的尝试账本，按订单和幂等键去重；订单进入已批准的取消处理后禁止新增、修改或删除。
- `fulfillment_record` 是订单内供应商履约项账本，按 `line_item_key` 和幂等键去重；订单存在开放取消案件后同样被冻结。
- `agency_order_cancellation_case` 保存申请、服务端派生的供应商/财务核验门禁、专职审批和状态修订；同一订单同一时刻最多一条非终态案件。
- `agency_order_cancellation_event`、`agency_order_compensation_record` 和 `agency_order_reconciliation_record` 由数据库触发器强制只追加；结果登记人与对账人必须不同，退款匹配使用审计员独立提交的观察金额/币种，案件完成以每类动作最新成功记录及其匹配对账为准。取消案件创建后，支付/履约账本触发器即冻结迟到写入，服务层仍在每次推进前复核暴露投影。

这些数据库门禁提高了平台内审计可靠性，但仍不构成密码学不可篡改账本，也没有实现供应商回调验签、支付网关自动对账、退款分账或跨系统最终一致性。

## 权限与四眼原则

租户成员角色的预期职责如下：

| 角色 | 预期职责 |
|---|---|
| `travel_advisor` | 只管理持有同门店授权且当前分配给自己的客户、方案和报价。 |
| `branch_manager` | 管理同一 `active` 门店的新客户、顾问分配和报价；在 `inactive` 清理期保留范围读取与清理权限。首版不能发起或批准跨门店转移。 |
| `booking_operator` | 登记平台外人工取得的供应商取消结果；不能调用供应商接口，未来预订执行仍未实现。 |
| `approver` | 当前唯一可决定内部订单审核的岗位；必须是同一有效旅行社的有效成员，并持有订单门店的有效授权。`active` 门店可批准或拒绝，`inactive` 清理期只能拒绝订单审核；取消案件仍可继续审批。 |
| `finance` | 登记平台外人工财务结果；不能发起支付或退款，也不能替代独立审计。 |
| `auditor` | 独立核验最新人工结果且不得自我对账；可按职责读取取消案件，不能执行供应商或财务动作。 |
| `admin` / `owner` | 旅行社全域管理角色，可管理门店、授权和客户，也是首版唯一可执行客户转店、门店停用与最终关闭的角色；高风险审核仍遵循职责分离，不能代替专职审批员。 |

当前授权由应用服务和 SQL 查询过滤器执行，属于门店范围的应用层行级授权，不是 PostgreSQL RLS（Row-Level Security，行级安全策略）。`owner`、`admin` 具有旅行社全域可见性；`branch_manager` 需要同门店有效授权；`travel_advisor` 还需要客户当前有效分配；`approver` 只可查看自己授权门店的已提交订单。列表和单资源可见性覆盖 `active/inactive`，以便关店清理；所有普通新增业务仍要求门店 `active`。订单审核批准也要求 `active`，拒绝及取消收口允许 `inactive`。客户完成安全认领后可读取本人客户关系及历史报价/订单。报价写入还会重新校验客户为 `secure_claim`、`active`、同意为 `granted`、证据为 `server_canonical` 且门店有效。越权访问具体对象统一按未找到处理，列表查询使用相同范围过滤。

这套应用层授权不能被表述为数据库强制隔离：绕过服务层直接执行 SQL、遗漏可见性过滤器或使用高权限数据库账号，均可能绕过它。生产化仍需最小权限数据库账号、系统化越权测试，并评估是否引入 PostgreSQL RLS 或独立策略引擎。

内部订单审核当前保证：

1. 决定人属于目标 `agency_id`，旅行社、成员和门店岗位授权均有效，角色必须严格为 `approver`；订单批准要求门店为 `active`，`inactive` 清理期只允许拒绝。
2. 订单处于 `pending_review`，审核记录处于 `pending`，且两者通过旅行社、门店、订单、提交修订号、`payload_hash`、金额和币种绑定。
3. 决定请求校验当前订单 `expected_revision`，并锁定客户、门店、订单行和审核行；批准还会重新校验客户仍为 `active + granted`，客户停用后只能拒绝保留中的审核，且旧审核拒绝前不能重新激活客户关系。
4. 订单客户或审核发起人不能决定自己的审核。
5. 跨租户或越权资源不暴露存在性。

这套内部审核不等于平台 Approval/HITL。未来真实外部动作仍需把平台审批记录绑定动作、租户、资源、金额、币种、`revision`、`payload_hash`、过期时间和供应商适配器版本。

## 幂等、并发与审计

当前最小内部 API 已落实：

- 所有写请求要求稳定的 `Idempotency-Key`（幂等键）。
- 同一作用域的同一幂等键只能重放相同请求；负载哈希不同必须返回冲突。
- 当前报价/订单幂等记录按永久唯一处理，不设置过期复用；`expires_at` 仍是预留字段，尚无自动清理策略。
- 认领邀请首次签发且事务提交成功后的响应是原始 token 的唯一返回点；相同幂等请求重放只返回邀请元数据且 `claim_token=null`。token 丢失时必须显式撤销原邀请后重新签发，不能从数据库摘要恢复。
- 报价和订单状态修改必须携带预期 `revision`；修订号不一致时拒绝覆盖。
- 状态变化与 `agency_order_event` 在同一数据库事务中提交。
- 审核决定把 `decision`、订单、操作者、`expected_revision` 和原因纳入请求哈希；批准/拒绝共用 `order.review.decide` scope，不能用同一键切换决定。

未来外部交易入口还必须满足：

- 外部调用前先落本地意图和幂等记录，回执以可重放方式落账。
- timeout（超时）不能直接推断为失败或成功，必须进入查询、重试或人工介入。

现有测试已加入客户生命周期和交易 API 契约、客户停用时的内部交易收口、门店授权矩阵、顾问分配、禁止自审、审核绑定、幂等重放/冲突、行锁和外部动作关闭，以及 `0005` 安全认领、`0006` 触发器修正和 `0007` 取消模型/API/服务/迁移契约。`0008` 另有客户转店、门店清理/关闭、状态分层授权、响应裁剪和迁移契约测试。[`c574649`](https://github.com/apearlinspring/langgraph-travel-planner/commit/c5746496203f628fe9a93a91ebb998c910c2a920) / [运行 30606856484](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30606856484) 已验证默认 `1878 passed, 58 deselected`、PostgreSQL 17 六文件 `34 passed`（3+5+5+2+10+9），证明一次性 CI 数据库中的 `0008` 迁移、触发器和六文件覆盖路径。目标环境迁移/恢复、复杂事务故障和并发锁等待证据仍待完成。

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

1. 一次性 PostgreSQL 17 CI 已覆盖 `0001 -> ... -> 0008` 基础全链、legacy upgrade、历史门店保留、转店/关店守卫和六文件业务场景；仍需在隔离数据库补复杂非空旧数据、业务数据失败关闭降级、跨租户/跨门店越权、并发锁等待和事务回滚，并评估数据库 RLS 或独立策略引擎。
2. 补批量客户导入、认领邀请投递与客户通知、真实身份核验、PII 档案及分级、法律级同意证据与撤回通知流程、跨门店经理双向交接审批和 `blocked` 风险复核入口。首版 owner/admin 即时转店不能扩写成完整门店交接流程。
3. 在现有人工取消记录与独立对账之上接入经过平台 Approval/HITL 绑定的供应商取消、退款和通知适配器，并补回调验签、查询补偿和跨系统最终一致性；当前入口仍只记录平台外结果。
4. 将平台 `approval_request` 强绑定到未来外部动作、订单、金额、币种、修订号和负载哈希；内部订单审核不能代替平台 Approval/HITL。
5. 在 sandbox（沙箱）环境实现供应商预订和支付适配器，包括回调验签、查询补偿、限流、熔断和故障注入。
6. 增加退款、改签、部分履约和 Saga（分布式事务补偿流程）状态机。
7. 建立供应商对账、财务清分、发票/合同、客服工单、通知偏好和服务质量反馈。
8. 完成 PII 分级、保留与删除、操作审计、商户权限、同意合法性验证、支付合规和正式用户条款。
9. 在目标环境绑定 commit，真实执行 `0001 -> ... -> 0008` 迁移、备份恢复、转店/关店并发、回调重放、故障恢复和小流量验收，再评估是否放行单个真实动作。
10. 明确幂等记录的长期保留、归档和删除策略；真实支付或预订重放还需保存首次响应快照，不能只返回资源当前状态。

在这些缺口补齐前，统一对外口径是：“项目的目标业务是旅行社；当前已具备 Agent 规划交付、目标账户安全认领、服务端同意记录、门店清理/关闭、owner/admin 客户转店、顾问分配、交易数据控制面以及平台外人工取消结果的分岗登记与独立对账，仍不是完整 CRM；跨门店经理双向交接、邀请通知、真实身份与法律合规链路、真实供应商、支付、退款和通知动作尚未接入且默认关闭。”
