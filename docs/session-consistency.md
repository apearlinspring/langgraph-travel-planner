# 会话一致性与并发治理轻量版

## 范围

本轮治理聚焦聊天流式 API（应用程序接口）里的同会话并发保护：同一个 `conversation_id` 在同一进程内只允许同时运行一轮 Travel Agent（旅行规划智能体），避免并发写入消息、checkpoint（检查点）和 LangGraph（图式智能体编排框架）状态。

已完成内容：

- 新增 `app/core/session_lock.py`，提供单进程内的会话级异步锁。
- `POST /api/v1/chat/stream/{conversation_id}` 对应的 SSE（服务器发送事件）生成器进入主流程前先获取会话锁。
- 同一 `conversation_id` 已在处理时，不保存新的用户消息，不启动新的 Agent，直接返回 `session_busy` 事件。
- 不同 `conversation_id` 使用不同锁，仍可并行处理。
- 流式生成正常结束、工具异常、模型异常或客户端断开时，都会在 `finally` 中释放锁。
- `app/evaluation/runtime_metrics.py` 会统计 `session_busy` 事件，便于评估快照识别并发拒绝。

## 忙碌响应契约

并发请求命中同一会话锁时，后到请求会收到：

```json
{
  "type": "session_busy",
  "content": "当前会话正在处理上一轮消息，请稍后再试。",
  "conversation_id": "<conversation_id>",
  "retry_after_seconds": 3
}
```

随后会发送：

```json
{"type": "done"}
```

前端现有 SSE 解析会读取 `content` 并展示给用户；因为这类请求没有进入 Agent 主链路，所以不会破坏消息顺序，也不会写入新的 checkpoint。

## 设计取舍

- 第一版选择明确拒绝并提示重试，而不是排队。这样能避免用户快速连点导致旧输入排队过久，也不会让消息顺序变得难以解释。
- 会话锁只存在于当前 Python（编程语言）进程内，不写入 `TravelState`，也不进入 PostgreSQL（关系型数据库）或 Redis（键值缓存数据库）。
- 锁粒度是 `conversation_id`，不是用户级锁；同一用户的不同会话仍可并行。
- 锁保护覆盖从保存用户消息到保存助手消息的整个流式生成过程。
- 忙碌请求不会保存用户消息。用户看到提示后可以等待当前轮完成，再重新发送。

## 边界与后续

当前实现不是多节点分布式锁。若后续部署为多进程、多副本或多机器，同一个 `conversation_id` 可能被路由到不同进程；那时需要引入 Redis 或数据库级租约锁，并设计锁过期、续约和崩溃恢复策略。

当前实现也不做请求排队。如果产品上希望自动排队，需要补充队列长度上限、等待超时、取消语义和前端排队状态展示。

## 验证

重点测试覆盖：

- 同一会话重复获取锁会被拒绝。
- 不同会话可并行获取锁。
- 释放后同一会话可再次获取锁。
- 异常退出会释放锁。
- SSE 忙碌请求不会保存用户消息。
- SSE 生成器关闭时释放锁。
- 运行指标能统计 `session_busy` 事件。

已通过：

```powershell
.\.venv\Scripts\python -m pytest tests\test_session_consistency.py tests\test_chat_report_metadata.py -q
```

结果：

```text
10 passed
```
