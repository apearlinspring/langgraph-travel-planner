# TravelState 状态契约

本文说明 `TravelState`（旅行规划运行状态）、双工作流进度轴、阶段依赖字段和后续 schema 化路线。它面向公开工程维护，不包含本地运行证据、真实密钥或敏感业务数据。

## 1. 契约目标

`TravelState` 是 Agent、工具、中间件、报告生成和前端展示之间共享的状态边界。当前代码仍以 `TypedDict`（类型字典）承载宽状态，运行链路没有强制 runtime schema（运行时结构校验）。因此维护原则是：

- 进度字段必须显式，不依赖 prompt 口头承诺。
- 阶段产物必须落到可测试状态字段，不能只存在于自然语言回复。
- 自由规划和省心方案是两条工作流，不能把一个字段当成唯一全局进度源。
- 最终报告优先消费结构化 `report_data`，而不是从 Markdown 正文反向解析。

## 2. 双工作流

系统先确认规划方式，再进入对应工作流：

| 字段 | 含义 | 合法值 |
| --- | --- | --- |
| `planning_mode` | 当前识别到的规划模式倾向或已确认模式 | `free_planning` / `agency_plan` |
| `active_workflow` | 当前正在推进的工作流分支 | `free_planning` / `agency_plan` |
| `current_step` | 自由规划阶段进度 | `PLANNING_STEPS` |
| `agency_step` | 省心方案阶段进度 | `AGENCY_STEPS` |
| `planning_mode_confirmed` | 用户是否已确认规划模式 | `True` / `False` |

自由规划使用 `current_step` 推进：

1. `requirement_collection`
2. `destination_recommendation`
3. `transport_planning`
4. `accommodation_planning`
5. `food_planning`
6. `itinerary_generation`
7. `budget_summarization`
8. `order_generation`

省心方案使用 `agency_step` 推进：

1. `agency_requirement`
2. `agency_product_match`
3. `agency_plan_draft`
4. `agency_feedback`
5. `agency_report`

`active_workflow` 决定当前应读取哪条进度轴。`current_step` 和 `agency_step` 可以同时存在于状态中，但不能混用为同一个“唯一进度字段”。

`planning_mode` 与 `pending_initial_planning_mode` 可以保存尚未确认的倾向，但倾向不等于工作流已经切换。`set_planning_mode_tool` 只写模式倾向、原因和 pending（待确认）字段，不得覆盖 `active_workflow` 或推进 `agency_step`；只有用户确认后，`confirm_planning_mode_tool` 或等价快路径才能同时写入 `planning_mode_confirmed=True` 和新的 `active_workflow`。中间件、聊天快路径和状态迁移工具判断省心方案时，也必须同时看到已确认标记，不能仅凭一个历史 `planning_mode=agency_plan` 锁定工作流。初始状态中的 `active_workflow=free_planning` 是非销售安全默认值，不代表用户已经确认自由规划。

## 3. 关键状态字段分层

| 层级 | 字段示例 | 维护要求 |
| --- | --- | --- |
| 工作流控制层 | `planning_mode`、`active_workflow`、`current_step`、`agency_step`、`planning_mode_confirmed`、`planning_mode_reason` | 决定路由、阶段、工具白名单和报告口径，必须由工具或快路径显式写入 |
| 已确认事实层 | `confirmed_facts`、`confirmation_history`、`departure_date_confirmed`、`user_requirement` | 记录目的地、日期、天数、人数、预算等事实；相对日期和未确认日期不得直接驱动真实库存查询 |
| 自由规划产物层 | `selected_destination`、`destination_options`、`selected_transport_option`、`selected_accommodation_option`、`selected_food_types`、`itinerary`、`budget` | 对应 `STEP_STATE_FIELDS`，用于阶段回退、前置依赖检查和最终报告门禁 |
| 省心方案产物层 | `matched_product`、`scenic_price_evidence`、`evidence_bundle`、`itinerary`、`budget`、`report_data` | 支撑成熟路线样板、报价口径、服务边界和待核验项；不承诺库存、锁价、支付或真实下单 |
| 报告交付层 | `report`、`report_data`、`journey_plan`、`route_segment_preferences`、`planning_trace`、`order_id` | 面向前端和最终交付；结构化数据是主契约，文本报告是展示载体 |
| 治理观测层 | `tool_audit_events`、`tool_loop_guard`、`approval_*`、`observability_context` | 记录工具调用、循环保护、审批和可观测上下文 |
| 上下文与记忆层 | `conversation_summary`、`key_history_turns`、`context_*`、`long_term_preferences_snapshot` | 用于长对话压缩和偏好注入，不应替代阶段产物字段 |

## 4. 自由规划阶段产物

`STEP_STATE_FIELDS` 是自由规划阶段的可维护依赖表。除初始需求收集外，每个阶段都应有明确产物：

| 阶段 | 应产出的关键字段 | 说明 |
| --- | --- | --- |
| `requirement_collection` | `user_requirement` | 基础需求、规划模式线索和日期确认状态 |
| `destination_recommendation` | `selected_destination`、`destination_options` | 目的地选择与候选依据 |
| `transport_planning` | `selected_transport`、`selected_transport_option`、`transport_options` | 交通方式、候选或待核验说明 |
| `accommodation_planning` | `selected_accommodation_types`、`selected_accommodation_option`、`accommodation_options` | 住宿偏好、候选或兜底区域 |
| `food_planning` | `selected_food_types`、`food_options` | 餐饮偏好和推荐集合 |
| `itinerary_generation` | `itinerary` | 每日行程、餐食、住宿、交通备注和路线风险 |
| `budget_summarization` | `budget` | 分项预算、总额、人均、置信度和待核验项 |
| `order_generation` | `order_id`、`report`、`report_data` | 最终交付文本和结构化报告 |

新增自由规划阶段时，必须同步更新：

- `app/core/workflow.py` 中的 `PLANNING_STEPS`、`STEP_LABELS`、`STEP_STATE_FIELDS`。
- `app/agents/handoffs/step_config.py` 中的 prompt、tools 和依赖说明。
- 阶段迁移工具和回退清理逻辑。
- 相关维护性测试和正式架构文档。

## 5. 省心方案阶段产物

省心方案目前没有独立的 `AGENCY_STEP_STATE_FIELDS` 常量，因此阶段产物先以文档契约固化：

| 阶段 | 应产出的关键字段 | 说明 |
| --- | --- | --- |
| `agency_requirement` | `user_requirement`、`planning_mode`、`active_workflow`、`agency_step` | 确认目的地、天数、人数、预算、出发地和日期等基础事实 |
| `agency_product_match` | `matched_product`、`evidence_bundle`、`scenic_price_evidence` | 匹配成熟路线、内部产品、票价或风险依据 |
| `agency_plan_draft` | `itinerary`、`budget`、`evidence_bundle` | 输出产品化方案草案、费用口径、涵盖服务和待核验项 |
| `agency_feedback` | `evidence_bundle`、`planning_trace`、`itinerary`、`budget` | 记录用户修改意见并更新方案 |
| `agency_report` | `report`、`report_data`、`journey_plan` | 生成用户交付视图报告 |

省心方案可以复用 `itinerary`、`budget`、`report_data` 等交付字段，但不应把它们解释成用户已完成自由规划的交通、住宿、餐饮逐项确认。

## 6. 不能依赖 prompt 隐式保证的约束

以下约束必须通过工具、状态字段、测试或文档契约表达，不能只写在 prompt 里：

- 模式确认：用户选择省心方案时，必须写入 `planning_mode=agency_plan`、`active_workflow=agency_plan`、`planning_mode_confirmed=True`，并使用 `agency_step` 推进。
- 双轴进度：自由规划读 `current_step`，省心方案读 `agency_step`；检查进度、报告门禁和前端状态时必须同时考虑 `active_workflow`。
- 日期门禁：真实交通、酒店、票务查询必须有明确且已确认的日期；未确认日期只能进入待核验说明。
- 阶段产物：阶段完成必须写入对应状态字段，不能只输出自然语言。
- 报告门禁：正式报告必须基于 `itinerary`、`budget`、`report_data` 等结构化字段；缺关键字段时应继续补齐，而不是生成看似完整的报告。
- 省心方案边界：内部资料只能支撑方案依据、服务节点、报价口径和风险控制，不能承诺真实库存、锁价、成团、支付或预订完成。
- 回退清理：自由规划回退时，应按 `STEP_STATE_FIELDS` 清理目标阶段之后的产物，避免旧字段污染后续报告。
- 串行状态写：主 Agent 的模型调用固定使用 `parallel_tool_calls=False`，同一轮只允许一个会修改 `current_step`、`agency_step`、`planning_mode`、`active_workflow` 或阶段产物的状态工具落地 `Command`。`tool_audit_events` 和 `tool_loop_guard` 的 reducer（归并器）只用于安全合并观测记录，不表示标量工作流状态可以并行覆盖。后续如需并行查询，应把只读查询与状态迁移拆开，先汇总查询结果，再由单一状态迁移工具提交。

## 7. 后续 runtime schema 化路线

建议分四步推进，不一次性大改运行链路：

1. 文档契约和维护性测试先行：继续保护 `TravelState` 核心字段、阶段字段映射和双工作流轴。
2. 引入只读导出函数：如确需更强验收，可在 `app/core/workflow.py` 增加极小的只读 helper（辅助函数），统一返回阶段产物契约，避免测试复制常量。
3. 拆分运行态校验模型：为自由规划阶段、省心方案阶段、报告交付层分别建立轻量 schema（结构模型），先在测试和报告生成前做非阻塞校验。
4. 逐步接入运行时门禁：把日期门禁、报告门禁、模式门禁从 prompt 约束迁移到工具层和中间件层，失败时返回可读错误和待补字段。

这条路线的原则是：先把“应该是什么”公开可验收，再把“运行时必须如此”逐步收紧，避免一次性重写 Agent 编排链路。
