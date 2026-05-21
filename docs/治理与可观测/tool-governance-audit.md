# 工具治理覆盖审计

## 审计范围

本分支审计所有面向 Agent（智能体）的旅行规划工具，重点证明 Tool Execution Guard（工具执行网关）不是只覆盖少数 happy path（顺利路径）。覆盖范围包括：

- Travel Agent（旅行智能体）直接注册的阶段状态工具、酒店、交通、目的地 Router（路由器）、内部 RAG（检索增强生成）、记忆工具和动态 MCP（模型上下文协议）工具。
- 交通子代理注册的航班、高铁和自驾核心查询工具。
- 目的地 Router 使用的公开 RAG 工具。
- 航班、高铁、交通协调器里的补充 MCP 工具。
- 当前不接入但需要治理边界的真实支付、真实下单、短信、客户资料导出等高风险占位动作。

## 审计状态契约

工具审计事件统一使用 `ToolAuditEvent`，至少包含工具名、开始时间、耗时、输入摘要、输出摘要、错误分类、重试次数和证据类型。

当前状态值：

- `success`：工具得到可用结果。
- `failed`：工具失败或返回不可恢复错误。
- `degraded`：工具返回可展示内容，但包含空结果、失败提示或待核验信号。
- `skipped`：参数不完整、权限不允许或治理策略要求跳过。
- `approval_required`：命中 HITL（人类在环）审批边界，审批前不得继续执行。
- `timeout`：兼容既有报告和观测链路的超时扩展状态，统一按待核验失败类处理，错误类型为 `upstream_timeout`。

前端治理台不会直接把这些原始状态当成演示文案，而是通过 SSE（服务器发送事件）公开摘要里的展示语义说明：

| 展示语义 | 典型来源 | 演示解释 |
|---|---|---|
| 成功 | `success` | 工具返回了可用结果。 |
| 需核验 | `degraded` 或带待核验信号的结果 | 有内容可参考，但出发前或交付前仍要复查。 |
| 未查到 | `empty_transport_result`、`empty_hotel_result` 等空结果 | 工具调用成功，但没有查到合适候选；这不是系统崩溃。 |
| 参数不足 | `skipped` 且错误类型为 `invalid_*` | 缺出发地、日期、目的地等必要信息，补齐后可重查。 |
| 服务异常 | `failed`、`timeout` | 外部服务或工具执行异常，需要稍后重试或人工核验。 |
| 已跳过 | 重复调用保护、未开放能力或人工确认边界 | 本轮按保护规则没有继续执行真实动作。 |

## Travel Agent 注册工具清单

| 工具 | 覆盖状态 | 理由 |
|---|---|---|
| `record_requirement_tool` | 例外 | 本地记录已确认需求和阶段状态，不触发外部查询。 |
| `set_planning_mode_tool` | 例外 | 只写入规划模式状态。 |
| `confirm_planning_mode_tool` | 例外 | 只确认当前规划模式。 |
| `record_evidence_bundle_tool` | 例外 | 只记录证据摘要；证据来源工具本身单独受治理。 |
| `select_destination_tool` | 例外 | 只保存用户确认目的地和上下文。 |
| `select_transport_tool` | 例外 | 只保存已确认交通选择；真实查询由 `query_transport_options` 治理。 |
| `select_accommodation_tool` | 例外 | 只保存已确认住宿偏好或候选；真实查询由 `query_hotel_options` 治理。 |
| `select_food_tool` | 例外 | 只保存餐饮偏好，不做真实预订。 |
| `generate_itinerary_tool` | 例外 | 基于已确认状态生成本地行程草案。 |
| `summarize_budget_tool` | 例外 | 只做估算和待核验汇总，不锁价、不支付、不下单。 |
| `generate_order_tool` | 治理边界 | 生成项目内模拟订单号，写入 `approval_governance`；不代表真实支付、预订或履约。 |
| `go_back_to_step` / `go_back_to_*` | 例外 | 只回退本地工作流状态并清理后续字段。 |
| `check_current_progress` | 例外 | 只读取当前本地状态。 |
| `query_destination_info` | 网关覆盖 | 目的地 Router 入口已做参数预检、结果校验、失败分类和审计事件。 |
| `query_hotel_options` | 网关覆盖 | 真实酒店候选查询，校验目的地、日期、人数、预算和地点类型，失败不编造酒店。 |
| `query_transport_options` | 网关覆盖 | 真实交通协调入口，校验出发地、目的地、日期和交通方式，失败不编造车次、航班或价格。 |
| `update_travel_style_tool` | 例外 | 长期记忆写入已有 `memory_scope` 过滤和记忆审计条目。 |
| `update_dietary_restriction_tool` | 例外 | 长期记忆写入已有 `memory_scope` 过滤和记忆审计条目。 |
| `update_food_preference_tool` | 例外 | 长期记忆写入已有 `memory_scope` 过滤和记忆审计条目。 |
| `update_accommodation_preference_tool` | 例外 | 长期记忆写入已有 `memory_scope` 过滤和记忆审计条目。 |
| `add_travel_record_tool` | 例外 | 长期记忆写入已有记忆审计条目。 |
| `search_agency_product_templates` | 网关覆盖 | 内部 RAG 工具通过统一网关执行。 |
| `search_agency_service_sop` | 网关覆盖 | 内部 RAG 工具通过统一网关执行。 |
| `search_agency_pricing_rules` | 网关覆盖 | 内部 RAG 工具通过统一网关执行。 |
| `search_agency_risk_playbook` | 网关覆盖 | 内部 RAG 工具通过统一网关执行。 |
| `search_agency_report_standards` | 网关覆盖 | 内部 RAG 工具通过统一网关执行。 |
| 酒店后续 MCP 工具，如 `getHotelDetail`、`getHotelSearchTags` | 元数据网关覆盖 | `guard_mcp_tool` 包装后带 `execution_guard=tool_execution_guard`。 |
| 默认 MCP 工具，如天气、搜索、地图 | 元数据网关覆盖 | `get_all_mcp_tools()` 统一返回已包装工具。 |

机器校验入口是 `describe_travel_agent_tool_governance()`，`tests/test_travel_agent_tool_registry.py` 会断言 Travel Agent 当前注册工具没有 `missing` 覆盖项。

## 双工作流工具白名单

个性化旅游规划 `free_planning` 继续按 `current_step` 使用既有阶段工具，例如交通阶段允许真实交通查询，住宿阶段允许酒店查询。

省心方案 `agency_plan` 使用独立 `agency_step`，默认工具白名单更窄：

- 基础需求：`record_requirement_tool`、`confirm_planning_mode_tool`、长期偏好读取/记录相关工具。
- 产品匹配：`search_agency_product_templates`、景点票价参考、风险和报价规则相关工具。
- 方案草案：产品模板、SOP、报价规则、风险手册、证据整理工具。
- 方案确认/报告：修改意见记录、报告标准和 `generate_order_tool`。

省心方案默认不开放：

- `query_transport_options`
- `query_hotel_options`
- `select_transport_tool`
- `select_accommodation_tool`
- 自由规划式交通、住宿、餐饮阶段切换工具

如果用户明确说“帮我查真实航班 / 高铁 / 酒店”，中间件可以在本轮临时开放对应真实查询工具；但结果仍必须进入待核验，不承诺库存、锁价或真实下单。

`record_evidence_bundle_tool` 是证据整理工具，用来把产品模板、报价规则、风险手册和报告标准等来源归并成可追溯证据摘要。它本身不访问外部服务、不查库存、不下单；真正需要治理的是它所引用的来源工具。

## 子代理与公开 RAG 覆盖

交通子代理的核心工具也纳入治理：

- `query_flight_options`：航班查询，走 `execute_guarded_call`，证据类型为 `live_transport_query`。
- `query_train_options`：12306 火车/高铁查询，走 `execute_guarded_call`，证据类型为 `live_transport_query`。
- `query_driving_route`：高德自驾路线查询，走 `execute_guarded_call`，证据类型为 `live_transport_query`。

航班、高铁和交通协调器里的补充 MCP 工具不再裸注册，统一通过 `guard_mcp_tools()` 包装。

公开 RAG 工具也纳入统一网关：

- `search_destination_guide`
- `search_food_recommendations`
- `search_accommodation_info`
- `search_travel_tips`

## 高风险动作边界

当前项目仍不接入真实支付、真实下单、短信发送、客服链接或供应链履约。

治理策略中已登记的敏感动作：

- `generate_order_tool` / `generate_order_id`：记录型动作，不阻塞，但报告必须说明订单号只用于项目内归档。
- `export_final_report`：记录型动作，报告导出不代表支付、出票或酒店确认。
- `real_booking`：未来真实预订占位，必须 HITL 审批。
- `real_payment`：未来真实支付占位，必须 HITL 审批。
- `send_sms`：未来短信发送占位，必须 HITL 审批。
- `export_customer_profile`：未来客户资料导出占位，必须 HITL 审批并最小化字段。

命中强制审批时，审计事件状态为 `approval_required`，同时写入审批状态字段；真实动作不会继续执行。前端会把这类记录讲成“已跳过 / 命中人工确认边界”，避免被误解成系统错误。

## 测试保护

新增或强化的保护点：

- `tests/test_tool_audit_governance.py`：验证审批状态、MCP 包装、目的地 Router 审计、治理分类器，以及 `empty_transport_result` 的“未查到且非崩溃”公开语义。
- `tests/test_travel_agent_tool_registry.py`：验证 Travel Agent 注册工具全量有治理分类。
- `tests/test_flight_query_tool.py`、`tests/test_train_query_tool.py`、`tests/test_driving_query_tool.py`：验证交通子查询工具保持兼容并走治理包装。
- `tests/test_hotel_query_tool.py`、`tests/test_transport_query_tool.py`：继续保护酒店和交通顶层真实查询的失败兜底与审计事件。

## 剩余风险

- 第三方 MCP 工具返回结构差异仍然较大，结果校验以空内容、失败词、待核验词和超时为主。
- 交通子代理内部工具的审计 artifact（附加产物）在直接调用子代理时可用；通过顶层 `query_transport_options` 调用时，最终持久化仍以交通协调器整体审计事件为主。
- 记忆工具暂未接入 Tool Execution Guard，因为它们依赖现有长期记忆服务和记忆审计条目；当前用注册表例外和测试防止被误认为未治理。
