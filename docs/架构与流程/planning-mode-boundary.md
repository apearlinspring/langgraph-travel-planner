# Planning Mode Boundary

规划模式决定需求收集和方案生成流程。对话先确认方式，再在 `report_data.agency_context.mode` 输出以下两个最终值；报价、订单与履约由交易域状态管理：

- `free_planning`：个性化旅游规划。用户自己决策和预订，系统提供路线、预算、住宿区域、风险和核验建议。
- `agency_plan`：省心方案。用户明确需要现成省心方案、旅行社产品、报价、合同规则或服务标准时，系统使用产品化方案表达。

模式未确认时，运行态使用 `pending_confirmation`；最终 `agency_context.mode` 在确认后填写。

## 判定原则

- 明确自由行信号优先：自由行、自助游、自己订、不跟团、不需要旅行社、只要攻略等，均保持 `free_planning`。
- 明确旅行社信号才切换：省心方案、旅行社方案、旅行社顾问方案、成熟路线、定制游、小包团、私家团、一站式托管等，进入 `agency_plan`。
- 报价和服务边界信号进入旅行社表达：报价、报价单、费用包含、费用不含、合同规则、服务标准、SOP 等，进入 `agency_plan`。
- 弱偏好不触发旅行社模式：亲子、老人、银发、少走路、轻松、不想太赶、酒店干净、交通稳妥、交通省心、住宿兜底等，只是路线和服务偏好，默认不改变模式。
- 用户首轮已经给出完整旅行需求，但没有明确选择模式时，优先只问“您想要现成省心方案，还是个性化旅游规划？”，不先进入交通、酒店或预算推理。

## 工作流边界

`active_workflow` 选择工作流，各分支使用自己的阶段字段：

- `free_planning` 使用 `current_step`，走 `requirement_collection -> destination_recommendation -> transport_planning -> accommodation_planning -> food_planning -> itinerary_generation -> budget_summarization -> order_generation`。
- `agency_plan` 使用 `agency_step`，走 `agency_requirement -> agency_product_match -> agency_plan_draft -> agency_feedback -> agency_report`。

省心方案默认不进入 `transport_planning` 或 `accommodation_planning`。省心方案通过交通方式、住宿商圈和档次说明产品安排。只有用户明确要求查实时交通或酒店时，才临时开放对应工具。

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

个性化旅游规划使用公开 RAG 和通用交付标准，按用户自主选择组织报告，重点说明：

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

这些证据用于说明方案依据、服务节点、费用规则和风险控制。

省心方案面向用户的主输出应是成熟路线样板和可评价方案，默认包含：

- 交通口径。
- 住宿商圈/档次与示例酒店。
- 景点门票或预约参考。
- 餐饮安排。
- 费用说明和分项拆分。
- 涵盖服务。
- 待核验项与服务范围。

## 与旅行社交易域的关系

规划工作流和交易域是两个相邻但独立的状态机：

| 层级 | 职责 |
|---|---|
| `agency_plan` / `free_planning` | 收集需求、形成方案、估算预算和交付报告。 |
| `agency_quote` | 保存旅行社、客户、产品、金额、有效期和报价快照，用 `revision` 与 `payload_hash` 标识版本和内容。 |
| `agency_order` | 保存报价转成的内部订单，以及支付和履约状态快照。 |
| `agency_order_event` | 只追加记录订单关键状态和负载版本变化。 |

交易 API 覆盖客户认领与同意、顾问分配、报价/订单审核、人工取消结果登记和独立对账，以及客户原子转店、门店 `active → inactive → closed` 清场。API 在数据库提交与延迟约束通过后返回成功；转店保留历史业务门店。停业期处理存量业务，所有当前客户、邀请、分配、授权、待审核及开放交易清空后才可不可逆关闭。取消 `completed` 包含无外部暴露订单审批后直接内部取消，以及最新所需人工结果独立匹配两条路径。模型、迁移和完整状态规则见 [旅行社客户与交易域](agency-transaction-domain.md)。

正式报价与内部订单由交易 API 创建，`approved` 表示内部审核通过。`mock_checkout` 和 `generate_order_tool` 生成的 `ORDER-` 编号用于方案确认演示。真实预订、支付、退款与通知尚未接入；后续执行需校验租户、成员、四眼审批、预期 `revision`、`payload_hash`、幂等键与供应商适配器。批量导入、邀请投递、客户 PII 档案、身份核验、法律合规与双门店经理审批也需补充。

## 验收关注点

`acceptance-core` 检查输出模式与 `expected_mode` 是否一致。自由规划场景输出 `agency_context.mode=agency_plan` 时需修正规划分流；省心方案和报价场景还需检查内部产品、SOP、报价规则和风险依据是否完整。
