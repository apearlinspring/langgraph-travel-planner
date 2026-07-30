# Planning Mode Boundary（规划模式边界）

本项目的真实业务定位是旅行社经营与交付工作台。对话链路先通过意图分流确认规划方式，再在 `report_data`（结构化报告数据）里稳定输出 `agency_context.mode`。这里的“模式”只决定如何生成方案，不代表报价、订单、支付或履约状态。当前只允许两个最终模式值：

- `free_planning`：个性化旅游规划。用户自己决策和预订，系统提供路线、预算、住宿区域、风险和核验建议。
- `agency_plan`：省心方案。用户明确需要现成省心方案、旅行社产品、报价、合同规则或服务标准时，系统使用产品化方案表达。

模式未确认时，运行态可以使用 `pending_confirmation` 表示“待确认”，但不能写入最终 `agency_context.mode`。

## 判定原则

- 明确自由行信号优先：自由行、自助游、自己订、不跟团、不需要旅行社、只要攻略等，均保持 `free_planning`。
- 明确旅行社信号才切换：省心方案、旅行社方案、旅行社顾问方案、成熟路线、定制游、小包团、私家团、一站式托管等，进入 `agency_plan`。
- 报价和服务边界信号进入旅行社表达：报价、报价单、费用包含、费用不含、合同规则、服务标准、SOP（标准作业流程）等，进入 `agency_plan`。
- 弱偏好不触发旅行社模式：亲子、老人、银发、少走路、轻松、不想太赶、酒店干净、交通稳妥、交通省心、住宿兜底等，只是路线和服务偏好，默认不改变模式。
- 用户首轮已经给出完整旅行需求，但没有明确选择模式时，优先只问“您想要现成省心方案，还是个性化旅游规划？”，不先进入交通、酒店或预算推理。

## 工作流边界

`active_workflow` 只表示当前分支，不能直接等同于自由规划阶段：

- `free_planning` 使用 `current_step`，走 `requirement_collection -> destination_recommendation -> transport_planning -> accommodation_planning -> food_planning -> itinerary_generation -> budget_summarization -> order_generation`。
- `agency_plan` 使用 `agency_step`，走 `agency_requirement -> agency_product_match -> agency_plan_draft -> agency_feedback -> agency_report`。

省心方案默认不进入 `transport_planning` 或 `accommodation_planning`。交通和住宿在省心方案中是产品口径说明，例如“推荐高铁/飞机口径”“住宿商圈和档次”，不是逐项偏好确认或实时库存查询。只有用户明确要求查实时交通或酒店时，才临时开放对应工具。

即使外部查询返回了候选信息，也不等于旅行社已向供应商锁定库存、完成预订或取得可履约确认。

用户选择“省心方案”后，同轮必须写入：

- `planning_mode=agency_plan`
- `active_workflow=agency_plan`
- `planning_mode_confirmed=True`
- `agency_step=agency_requirement`

用户选择“个性化旅游规划”后，同轮必须写入：

- `planning_mode=free_planning`
- `active_workflow=free_planning`
- `planning_mode_confirmed=True`

## 自由规划的证据使用

个性化旅游规划可以参考公开 RAG（检索增强生成）和通用交付标准，但不能把内部旅行社产品包装成用户已选择的省心套餐。报告表达要保持中立实用，重点说明：

- 每日路线和地图节点。
- 预算估算、置信度和待核验项。
- 天气、预约、交通、住宿和体力风险。
- 用户可自主选择和调整的空间。

## 旅行社方案的证据要求

`agency_plan` 场景必须继续保留内部证据，尤其是：

- 产品或成熟路线模板。
- 服务 SOP。
- 报价规则和费用说明。
- 风险与 Plan B。
- 最终报告交付标准。

这些证据只能支撑“方案依据、服务节点、报价口径和风险控制”，不能承诺真实库存、锁价、成团、支付或预订完成。

省心方案面向用户的主输出应是成熟路线样板和可评价方案，默认包含：

- 交通口径。
- 住宿商圈/档次与示例酒店。
- 景点门票或预约参考。
- 餐饮安排。
- 费用说明和分项拆分。
- 涵盖服务。
- 待核验项和不承诺边界。

## 与旅行社交易域的关系

规划工作流和交易域是两个相邻但独立的状态机：

| 层级 | 当前职责 | 不代表 |
|---|---|---|
| `agency_plan` / `free_planning` | 收集需求、形成方案、预算估算和交付报告。 | 报价已正式发出、客户已接受、订单已审核。 |
| `agency_quote` | 保存旅行社、客户、产品、金额、有效期和报价快照；使用 `revision` 与 `payload_hash` 标识版本和内容。 | 实时库存已锁定、供应商价格已确认。 |
| `agency_order` | 保存从报价形成的订单业务事实，以及支付和履约状态快照。 | 已付款、已出票、酒店已确认或服务已完成。 |
| `agency_order_event` | 只追加记录订单关键状态和负载版本变化。 | 已形成不可篡改的外部审计或财务账本。 |

当前阶段已经增加旅行社租户、成员、门店、门店岗位授权、客户关系、客户认领邀请、只追加同意记录、客户事件、主顾问分配、供应商产品、报价、订单、内部订单审核、订单事件、幂等记录、支付尝试和履约记录的数据模型与迁移，并加入应用层门店范围和外部动作配置门禁。`/api/v1/agency` 的内部 API 已支持线下潜客登记，向指定已有平台账户签发 256-bit 高熵、24 小时过期、可撤销、单次使用且数据库只存 SHA-256 摘要的认领凭证，由该已登录目标账户认领；同一旅行社同一目标账户同一时刻最多一条待处理邀请。认证客户端先读取固定技术告知的 Markdown、版本、文档摘要、证据 schema（模式）和渠道，提交决定时回传预期版本/摘要防止使用过期告知，规范化 evidence（证据）仍由服务端生成。原始 token 只在首次签发事务提交成功后的响应返回，幂等重放不再返回；丢失时必须撤销并重新签发。创建报价要求客户已完成 `secure_claim` 并保持 `active + granted + server_canonical`。存量 `legacy_direct` 账户仍可拒绝或撤回；升级认领会重置旧同意投影，原 `active` 关系先转为 `inactive` 并收口分配/内部交易，之后必须重新 `grant` 和激活。旅行社 API 在数据库提交及提交时延迟约束通过后才发送成功响应。批量导入、邀请投递、客户通知、真实身份核验、法律合规闭环、PII（个人可识别信息）档案、跨门店转移和门店停用/关闭 API 仍未实现。规划报告不会自动转成报价或自动通过审核；内部 `approved` 也不触发供应商、支付、退款或通知动作。真实外部执行尚未接入，相关总开关和细粒度开关默认关闭。

`mock_checkout` 与 `generate_order_tool` 仍是规划演示能力：它们生成的 `ORDER-` 编号只能帮助演示“用户确认方案”这一步，不得写成真实 `agency_order`、合同号、支付单或履约凭证。真实交易链路必须显式进入交易域，并校验旅行社租户、有效成员、四眼审批、预期 `revision`、`payload_hash`、幂等键和供应商适配器。

## 验收关注点

`acceptance-core`（核心验收）中，`expected_mode=free_planning` 的场景如果输出 `agency_context.mode=agency_plan`，属于真实模式误判，不应通过降低评分规则掩盖。`expected_mode=agency_plan` 的省心方案和报价场景仍要检查内部产品、SOP、报价规则和风险证据是否完整。
