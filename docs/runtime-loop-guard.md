# Runtime Loop Guard（运行期循环保护）

## 背景

`acceptance-core`（核心验收）里的 `free_weekend_nearby` 和 `agency_senior_low_stress` 曾暴露真实 Agent（智能体）链路里的重复工具调用、长回合等待和 `conversation_busy` / `session_busy`（会话繁忙）问题。修复原则是不放宽 runtime budget（运行预算）掩盖失败，而是在同一 turn（轮次）内阻断等价工具循环，并把上游慢调用转成可解释、可恢复结果。

## 本轮保护点

- `query_hotel_options`、`query_transport_options`、`query_destination_info` 同一轮只允许一次真实查询。重复调用会返回 `duplicate_tool_call_same_turn`，提示模型基于已有结果总结，下一轮再刷新。
- RAG（检索增强生成）工具按工具名和参数 fingerprint（指纹）去重。同一轮重复读取同一证据会快速返回可恢复说明，不继续消耗检索预算。
- 酒店查询增加整轮总运行上限；候选地逐个超时时，不再把所有候选都等满导致长时间占用会话锁。
- `record_requirement_tool`、`select_destination_tool`、`select_transport_tool`、`select_accommodation_tool`、`select_food_tool` 对已经写入的等价状态执行 no-op（无操作）返回，避免重复写同一状态或把流程回退到旧阶段。
- duplicate skip（重复跳过）通过 `tool_audit`（工具审计）记录为 `skipped`，不会产生 SSE `error` 事件；运行指标仍能看到一次可恢复降级。

## 运行结果预期

- 同一轮内模型即使再次尝试酒店、交通或目的地真实查询，也会快速拿到“本轮已查询”的工具结果。
- 上游酒店 MCP（模型上下文协议）慢响应时，工具会在本轮预算内停止等待，明确“不编造酒店候选”，并建议下一轮放宽条件后重试。
- acceptance snapshot（验收快照）中应看到工具调用数下降，`error_event_count` 维持 0；如触发循环保护，`tool_audit` 会出现 `duplicate_tool_call_same_turn`。

## 建议复核

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_tool_loop_guard.py tests\test_runtime_metrics.py tests\test_workflow_maintainability.py -q
.\.venv\Scripts\python -m pytest -q
```

具备真实环境时，优先单场景复跑：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario free_weekend_nearby --base-url http://127.0.0.1:8000 --json
```

复盘重点：`tool_call_count`、`tool_audit` 中的 `duplicate_tool_call_same_turn`、酒店/交通超时状态、`error_event_count` 和 `session_busy_event_count`。
