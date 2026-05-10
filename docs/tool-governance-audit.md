# 模块 E：工具调用治理与审计交付说明

## 范围

本轮改造聚焦真实旅行社智能顾问 Agent（智能体）里的高风险工具调用治理：交通、酒店和流式聊天 API（应用程序接口）工具事件。

已完成内容：

- 新增统一工具审计契约：`ToolAuditEvent`。
- 新增调用前参数校验：酒店目的地、日期、人数、预算等级；交通出发地、目的地、日期、交通枚举。
- 新增调用后结果校验：空结果、失败文本、超时和待核验信号会被归类。
- 酒店与交通真实查询工具会把审计事件写入 `tool_audit_events`。
- 工具失败、超时或跳过会进入预算待核验项，并在最终 `report_data.evidence_bundle` 与 `report_data.tool_audit_summary` 中体现。
- SSE（服务器发送事件）流式聊天会额外发送 `tool_audit` 事件，并把本轮工具运行事件写入助手消息 `extra_info`。

## 设计取舍

- 第一阶段先治理最容易误导用户的真实查询入口：`query_hotel_options` 和 `query_transport_options`。
- 对 MCP（模型上下文协议）原始工具，当前先在 SSE 事件层记录运行审计，不强行包裹所有第三方工具对象，避免破坏工具 schema（结构契约）。
- 审计事件只保存摘要，不保存密钥、认证 token（令牌）或完整大结果。
- 失败时不生成虚假的酒店、车次、航班、价格、库存、锁价、支付或预订成功状态。

## 验证

已通过：

```powershell
$env:DASHSCOPE_API_KEY='test-key'
$env:LANGSMITH_API_KEY='test-key'
$env:POSTGRES_DB='test_db'
$env:POSTGRES_USER='test_user'
$env:POSTGRES_PASSWORD='test_password'
$env:AIGOHOTEL_API_KEY='test-hotel-key'
uv run python -m pytest tests\test_hotel_query_tool.py tests\test_transport_query_tool.py tests\test_system_resilience.py -q
```

结果：

```text
24 passed
```

补充验证：

```powershell
uv run python -m pytest tests\test_tool_audit_governance.py tests\test_hotel_query_tool.py tests\test_transport_query_tool.py -q
```

结果：

```text
21 passed
```

## 自审

- 未写入 `.env` 真实密钥，测试只使用虚拟环境变量。
- 未新增真实支付、真实下单、真实库存、真实锁价或客服承诺。
- 酒店和交通失败路径都会给出诚实兜底，并进入待核验链路。
- 默认回归分层未新增真实网络依赖；新增测试均为本地 fake（模拟对象）测试。
- 报告继续由结构化 `report_data` 渲染，审计摘要不会依赖自然语言正则解析。

## 剩余风险

- 原始 MCP 第三方工具目前主要在 SSE 层审计，尚未全部写回 LangGraph（图式智能体编排框架）状态。
- 工具重复调用治理仍主要依赖中间件提示和最近工具名检测，后续可把审计事件接入更严格的重复调用限流。
- 工具成本统计目前只有耗时和结果摘要，还没有 token（令牌）成本或外部 API 计费估算。
