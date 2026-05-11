# 模块 E：工具调用治理与审计交付说明

## 范围

本轮改造聚焦真实旅行社智能顾问 Agent（智能体）里的高风险工具调用治理：Tool Execution Guard（工具执行网关）、交通、酒店、内部 RAG（检索增强生成）、MCP（模型上下文协议）外部查询和流式聊天 API（应用程序接口）工具事件。

已完成内容：

- 新增统一工具审计契约：`ToolAuditEvent`。
- 新增统一执行网关：`app/tools/execution_guard.py`，集中处理调用前权限判断、HITL（人类在环）审批阻断、参数预检、超时、结果校验、失败分类和审计事件生成。
- 新增工具执行策略：`ToolExecutionPolicy`，对酒店、交通、内部 RAG、公开 RAG、MCP 外部查询和未来真实支付/预订占位动作做风险分级。
- 新增调用前参数校验：酒店目的地、日期、人数、预算等级；交通出发地、目的地、日期、交通枚举。
- 新增调用后结果校验：空结果、失败文本、超时、RAG 空证据和待核验信号会被归类。
- 酒店与交通真实查询工具会把审计事件写入 `tool_audit_events`。
- 内部 RAG 工具通过统一网关执行，失败时仍返回空证据契约，不把异常静默吞掉。
- MCP 工具获取后会被 `guard_mcp_tool` 包装，统一加超时、占位参数拦截和诚实兜底。
- 工具失败、超时或跳过会进入预算待核验项，并在最终 `report_data.evidence_bundle` 与 `report_data.tool_audit_summary` 中体现。
- SSE（服务器发送事件）流式聊天会优先读取工具返回的内嵌审计事件；没有内嵌事件时按统一结果校验器生成 `tool_audit` 事件，并把本轮工具运行事件写入助手消息 `extra_info` 与持久化审计表。

## 设计取舍

- 第一阶段先治理最容易误导用户的真实查询入口：`query_hotel_options` 和 `query_transport_options`，并把共性能力迁入统一执行网关。
- MCP 原始工具通过轻包装保留原工具名、描述和参数 schema（结构契约），失败时返回清晰兜底文本，不继续冒充真实结果。
- 审计事件只保存摘要，不保存密钥、认证 token（令牌）或完整大结果。
- 失败时不生成虚假的酒店、车次、航班、价格、库存、锁价、支付或预订成功状态。
- 未来真实预订和真实支付仍只是占位敏感动作；网关会先生成审批状态并阻断执行，不接真实支付、真实下单或短信发送。

## 验证

本轮已通过：

```powershell
.\.venv\Scripts\python -m compileall app\tools app\core app\api\v1\chat.py
```

结果：

```text
编译通过
```

```powershell
.\.venv\Scripts\python -m pytest tests\test_tool_audit_governance.py tests\test_tool_quality_evaluation.py tests\test_hotel_query_tool.py tests\test_transport_query_tool.py tests\test_internal_rag_businessization.py -q
```

结果：

```text
52 passed
```

```powershell
.\.venv\Scripts\python -m pytest -q
```

结果：

```text
280 passed, 24 deselected
```

## 自审

- 未写入 `.env` 真实密钥，测试只使用虚拟环境变量。
- 未新增真实支付、真实下单、真实库存、真实锁价或客服承诺。
- 酒店和交通失败路径都会给出诚实兜底，并进入待核验链路。
- 审批未通过的敏感占位动作会返回 `skipped` 审计状态和审批字段，不会继续执行真实外部动作。
- 默认回归分层未新增真实网络依赖；新增测试均为本地 fake（模拟对象）测试。
- 报告继续由结构化 `report_data` 渲染，审计摘要不会依赖自然语言正则解析。

## 剩余风险

- MCP 第三方工具的包装保持原参数 schema，但不同上游工具的返回结构差异很大；当前结果校验仍以空结果、错误词和超时信号为主。
- 工具重复调用治理仍主要依赖中间件提示和最近工具名检测，后续可把审计事件接入更严格的重复调用限流。
- 工具成本统计目前只有耗时和结果摘要，还没有 token（令牌）成本或外部 API 计费估算。
- 工具内嵌审计事件通过聊天流持久化；如果调用链不经过聊天 API，需要调用方显式持久化 `tool_audit_events`。
