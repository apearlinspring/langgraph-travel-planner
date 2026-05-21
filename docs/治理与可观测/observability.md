# 运行观测说明

## 目标

本项目当前的运行观测是轻量雏形：不接 Prometheus（监控指标系统）或 OpenTelemetry（开放遥测标准），先用结构化日志、消息 `extra_info` 和内存最近快照追踪每轮 Agent（智能体）对话。

它回答这些问题：

- 本轮对话的 `turn_id`、`conversation_id`、`user_id`、阶段和规划模式是什么；公开展示时阶段默认是 `requirement_collection`，模式默认是 `pending_confirmation`，不再展示 `unknown`。
- 首 token（文本令牌）等待了多久，总耗时多久。
- 实际工具启动了几次，失败几次，是否触发 fallback（兜底）或 degraded（降级）状态。
- 输入、输出和总 token 是否有稳定近似估算。
- 这些指标能否被运行时评分和验收门禁消费。
- 本轮是否走了轻量快路径，没有创建完整 Travel Agent（旅行智能体）或加载 MCP（模型上下文协议）工具。
- 完整 Agent 流是否触发事件空闲超时，避免前端无限等待。

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

## SSE 安全边界

SSE 只返回安全摘要，不返回完整工具参数、工具输出、错误原文、真实密钥或个人隐私信息。

允许返回：

- `turn_id`
- 工具名
- 用户可理解服务名和原始工具名
- 工具状态
- 工具展示语义，如成功、需核验、未查到、参数不足、服务异常、已跳过
- 粗粒度耗时
- 是否降级
- token 估算
- 规划阶段和规划模式

不允许返回：

- API（应用程序接口）密钥、token、cookie、密码等凭据。
- 手机号、邮箱、身份证、护照等 PII（个人身份信息）。
- 完整工具输入、完整工具输出或内部审计原文。
- 未脱敏的异常字符串。

用户侧错误事件使用通用文案；真实异常类型和堆栈只进入后端日志。

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
- `tool_failure_count`、`fallback_count` 和 `degraded_event_count` 会进入 `runtime_governance`。
- 缺少 `turn_observability` 会让运行时观测维度扣分，避免评估体系和真实链路脱节。

`app/evaluation/acceptance_gate.py` 继续通过 `runtime_quality` 和 `runtime_budget` 消费运行时结果，不改变 `/health/ready` 的核心依赖判定。

## 当前边界

- token 使用量仍是字符近似估算，不等于供应商真实账单。
- 内存快照只适合本地排查和单进程验证，重启后会丢失。
- 还没有接入分布式 trace（链路追踪）或指标数据库。
- 工具执行统一治理不在本分支实现，后续由 `codex/tool-execution-guard` 负责。
