# 运行观测说明

## 目标

本项目当前的运行观测是轻量雏形：不接 Prometheus（监控指标系统）或 OpenTelemetry（开放遥测标准），先用结构化日志、消息 `extra_info` 和内存最近快照追踪每轮 Agent（智能体）对话。

它回答这些问题：

- 本轮对话的 `turn_id`、`conversation_id`、`user_id`、阶段和规划模式是什么；公开展示时阶段默认是 `requirement_collection`，模式默认是 `pending_confirmation`，不再展示 `unknown`。
- 首个助手响应片段等待了多久，总耗时多久。
- 实际工具启动了几次，失败几次，是否触发 fallback（兜底）或 degraded（降级）状态。
- 输入、输出和总 token 是否有稳定近似估算。
- 这些指标能否被运行时评分和验收门禁消费。
- 本轮是否走了轻量快路径，没有创建完整 Travel Agent（旅行智能体）或加载 MCP（模型上下文协议）工具。
- 完整 Agent 流是否触发事件空闲超时，避免前端无限等待。

相关的 AgentOps（智能体运行运营与治理）回放和版本记录口径见 [AgentOps 轻量回放与版本记录](agentops-replay-versioning.md)。该文档只把当前能力定义为 turn（单轮对话）级安全摘要复盘，不声明完整 OpenTelemetry（开放遥测标准）或分布式 trace（链路追踪）能力。

## 运行时契约

核心代码在 `app/core/observability.py`：

- `TurnObservation`：单轮对话观测收集器。
- `turn_observability`：SSE（服务器发送事件）里对前端可见的安全摘要。
- `public_tool_audit_event()`：工具审计的前端安全摘要，只暴露工具名、原始状态、展示语义、耗时、重试次数和证据类型。
- `list_recent_turn_observations()`：进程内最近快照，便于测试和本地排查。

内部快照会保留：

- `turn_id`
- `conversation_id`
- `user_id`
- `current_step`
- `planning_mode`
- `first_token_seconds`
- `total_elapsed_seconds`
- `tool_call_count`
- `tool_failure_count`
- `fallback_count`
- `degradation_status`
- `estimated_input_tokens`
- `estimated_output_tokens`
- `estimated_total_tokens`
- `progress_snapshot`
- `agency_step`
- `active_workflow`

`first_token_seconds` 的准确口径是“从本轮开始到任意首个助手 `token` SSE（服务器发送事件）片段的时间”。该片段可能只是 API 固定 ACK（确认收到），不等于 LLM 已开始输出有意义方案，更不等于完整 Agent 已处理完毕。性能复盘必须同时保留并展示 `total_elapsed_seconds`；当前尚未单独采集 time-to-first-meaningful-content（首个有意义内容耗时）。

## 工具状态统计口径

工具的原始状态会先归一化为用户可理解的 `semantic_status`（语义状态），再进入观测和验收统计。`degraded（降级）` 表示结果不能直接当作已确认事实，不等于工具执行失败。

| 典型原始状态或情形 | `semantic_status` | 计入 degraded | 计入 `tool_failure_count` | 计入 `fallback_count` |
|---|---|---:|---:|---:|
| `success` 且有可用结果 | `success` | 否 | 否 | 否 |
| 调用成功但为空，如 `empty_transport_result` | `not_found` | 是 | 否 | 是 |
| `degraded` | `needs_verification` | 是 | 否 | 否 |
| 参数缺失、占位值或无效参数导致 `skipped` | `insufficient_parameters` | 是 | 否 | 否 |
| `approval_required` 或治理规则跳过执行 | `skipped` | 是 | 否 | 否 |
| 无更具体语义的 `failed`、`failure`、`timeout`、`error` | `service_exception` | 是 | 是 | 否 |

分类优先级是显式 `semantic_status`、`error_type`、最后才是原始 `status`。因此，即使原始状态是 `failed`，只要 `error_type=empty_rag_result`、`empty_mcp_result`、`empty_transport_result` 等能明确归类为空结果，就只记 `not_found` fallback（兜底），不记 hard failure（硬失败）。只有 `service_exception` 才进入硬失败统计；`needs_verification`、`insufficient_parameters` 和治理跳过只记录降级，不增加失败数或 fallback 数。后端显式调用 `mark_fallback()` 的非工具兜底也会增加 `fallback_count`。

## SSE 观测事件的安全边界

`tool_audit` 和 `turn_observability` 这两类 SSE（服务器发送事件）观测事件只返回安全摘要，不返回完整工具参数、工具输出、错误原文或真实密钥。这里的承诺只适用于观测事件，不适用于整条 SSE：聊天流还会返回模型正文 token、结构化 `report_data` 和用户可见的降级文案。

模型正文和报告在发送前会经过脱敏处理，但这是 best-effort redaction（尽力脱敏），不能保证所有 PII（个人身份信息）都被识别，尤其不能把按流式分片处理的文本视为跨分片敏感信息检测。前端、日志和下游消费者仍应把正文与报告当作可能包含用户业务内容的数据，按鉴权、最小展示和保留周期要求处理。

观测事件允许返回：

- `turn_id`
- 工具名
- 用户可理解服务名和原始工具名
- 工具状态
- 工具展示语义，如成功、需核验、未查到、参数不足、服务异常、已跳过
- 粗粒度耗时
- 是否降级
- token 估算
- 规划阶段和规划模式

观测事件不允许返回：

- API（应用程序接口）密钥、token、cookie、密码等凭据。
- 手机号、邮箱、身份证、护照等 PII（个人身份信息）。
- 完整工具输入、完整工具输出或内部审计原文。
- 未脱敏的异常字符串。

用户侧错误事件使用通用文案；真实异常堆栈只进入受控后端日志。模型正文和 `report_data` 的脱敏属于纵深防御，不应在文档中表述为“整个 SSE 保证不含个人隐私信息”。

## 聊天链路接入

`app/api/v1/chat.py` 在每轮 `generate_sse_stream()` 开始时创建 `TurnObservation`：

1. 生成 `turn_id`。
2. 把 `turn_id` 写入 LangGraph（图式智能体编排框架）输入状态。
3. 记录首 token、总耗时、工具启动、工具结束、工具失败、兜底和降级。
4. 把内部快照写入助手消息 `extra_info.observability`。
5. 在 `done` 前发送一次 `turn_observability` 安全摘要。

聊天入口还存在两类不创建完整 Agent 的快路径：

- 规划方式确认：首轮已给旅行需求但未选模式时，直接返回“省心方案 / 个性化旅游规划”分流问题，并把解析事实写入 `extra_info.fast_mode_split`。
- 省心方案基础事实补齐：用户已选择省心方案，只是在补日期等基础事实时，直接更新 `planning_mode=agency_plan`、`active_workflow=agency_plan`、`agency_step=agency_requirement` 和进度快照。

快路径仍会发送安全的 `turn_observability`，但工具调用数应为 0，且日志里会明确标记 without creating travel agent（未创建旅行智能体）。

完整 Agent 流读取 LangGraph 事件时带有空闲超时。模型、上游或工具链长时间不返回任何事件时，后端会记录降级并返回可继续的兜底回复，避免一轮对话卡住十几分钟。

`app/core/middleware.py` 会把 `observability_context` 写回状态，包含当前阶段、规划模式、模式来源和本轮可用工具数量。这个上下文不包含用户原文。

## 前端展示

`frontend/app.js` 会消费公开 SSE（服务器发送事件）帧中的两类安全摘要，并展示在右侧治理台：

- `tool_audit`：显示用户可理解服务名、原始工具名、展示语义、粗粒度耗时、重试次数、证据类型和已转译原因；不显示完整工具输入、完整工具输出、认证头、密钥或上游原始错误。`empty_transport_result` 会显示为“未查到合适结果”，并说明这是工具调用成功但没有查到候选，不是系统崩溃。
- `turn_observability`：只显示状态、阶段、规划模式、首个响应片段等待、总耗时、工具调用数、需复查工具数、兜底次数和文本量估算；`turn_id` 弱化成“追踪码（排查用）”。

历史会话加载时，前端只从助手消息 `extra_info.tool_audit_events` 中提取同样的安全字段，忽略输入摘要和输出摘要，避免把内部审计账本当作用户可见明细。前端还会对可能出现的邮箱、手机号、身份证、Bearer token（持有者令牌）、JWT（JSON Web Token，令牌认证）和常见密钥形态做二次脱敏。

治理台中的观测信息用于演示“慢在哪里、是否降级、工具是否失败”，不用于展示客户原文、PII（个人可识别信息）或完整供应链响应。

右侧进度台使用 `progress_snapshot` 渲染当前阶段、方案类型、已确认信息、偏好记录和确认边界；偏好记录优先展示长期偏好，没有稳定偏好时展示本次已确认的风格、餐饮、住宿或特殊需求。普通用户不展示“工作流”“Day 结构”“这轮先”等内部过程词。

## 评估与验收

`app/evaluation/runtime_metrics.py` 会消费 `turn_observability`：

- 如果 SSE 工具提示为了前端体验做了去重，运行时指标仍会使用观测摘要里的真实工具启动次数。
- `tool_failure_count` 只统计 `service_exception`；仅当没有更具体语义时，原始 `failed`、`failure`、`timeout`、`error` 才回落为 `service_exception`。`not_found` 只进入 `fallback_count`，其余待核验、参数不足和治理跳过只进入降级观测。
- `tool_failure_count`、`fallback_count` 和 `degraded_event_count` 会分别进入 `runtime_governance`，三者不能互相替代。
- 工具审计写入 PostgreSQL 失败会安全地增加 `turn_observability.error_event_count`；运行时采用它与 SSE `error` 事件数的最大值防止重复计数，默认 `max_error_event_count=0` 会 fail-closed（缺失持久化证据即失败）。
- 缺少 `turn_observability` 会让运行时观测维度扣分，避免评估体系和真实链路脱节。

`app/evaluation/acceptance_gate.py` 继续通过 `runtime_quality` 和 `runtime_budget` 消费运行时结果，不改变 `/health/ready` 的核心依赖判定。

## 当前边界

- token 使用量仍是字符近似估算，不等于供应商真实账单。
- 内存快照只适合本地排查和单进程验证，重启后会丢失。
- 还没有接入分布式 trace（链路追踪）或指标数据库。
- 当前文档描述的是进程内安全摘要和验收统计口径，不等于完整的跨服务工具执行链路追踪。
