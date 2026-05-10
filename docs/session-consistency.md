# 会话一致性与并发治理

## 范围

本机制保护聊天流式 API（应用程序接口）中的同会话并发：同一个 `conversation_id` 在同一时刻只允许运行一轮 Travel Agent（旅行规划智能体），避免并发写入消息、checkpoint（检查点）和 LangGraph（图式智能体编排框架）状态。

本轮已从单进程锁升级为租约式会话锁：

- 默认优先使用 Redis（内存数据结构存储）保存会话锁，可覆盖多 worker（工作进程）或多实例部署。
- 锁粒度是 `conversation_id`，同一用户的不同会话仍可并行。
- 锁包含 owner（持有者）、TTL（过期时间）、获取、续租、释放和异常兜底释放。
- Redis 不可用且允许降级时，回退到本地进程锁；该模式只保护当前进程，不能保证多实例全局串行。
- 冲突策略保持快速失败，不排队。后到请求不会保存用户消息，也不会启动 Agent。

## 配置

`.env.example` 提供以下配置：

```env
SESSION_LOCK_BACKEND=auto
SESSION_LOCK_KEY_PREFIX=zhixing:session_lock
SESSION_LOCK_TTL_SECONDS=300
SESSION_LOCK_RENEW_INTERVAL_SECONDS=30
SESSION_LOCK_ACQUIRE_WAIT_SECONDS=0
SESSION_LOCK_BUSY_RETRY_AFTER_SECONDS=3
SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS=0.5
SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=true
SESSION_LOCK_REDIS_RETRY_INTERVAL_SECONDS=5
```

推荐部署：

- 单进程本地开发可使用 `local` 或默认 `auto`。
- 多 worker 或多实例部署应使用 `auto` 或 `redis`，并确保所有实例连接同一个 Redis。
- 如果不能接受 Redis 故障时的多实例一致性风险，应设置 `SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false`，让锁服务异常显式暴露。

## Redis 锁契约

Redis 后端使用 `SET key value NX PX ttl` 原子获取锁：

- `key`：`SESSION_LOCK_KEY_PREFIX:<conversation_id>`。
- `value`：当前进程生成的 owner token（持有者令牌），包含主机名、进程 ID（进程标识）和随机 UUID（通用唯一识别码）。
- `PX`：毫秒级 TTL，来自 `SESSION_LOCK_TTL_SECONDS`。

释放和续租都使用 Lua（Redis 脚本语言）脚本先比较 owner：

- 释放：只有 Redis 中的 value 等于当前 lease（租约）的 owner 时才删除 key。
- 续租：只有 owner 仍匹配时才刷新 TTL。
- 如果旧请求的锁已过期，而新请求已经拿到同一会话锁，旧请求的兜底释放不会删除新 owner 的锁。

聊天流式生成期间，`generate_sse_stream` 获取锁后会启动后台续租任务，间隔由 `SESSION_LOCK_RENEW_INTERVAL_SECONDS` 控制。正常完成、工具异常、模型异常或客户端断开时，`finally` 都会调用 release；如果释放失败，锁会依赖 TTL 自动过期。

## 降级策略

`SESSION_LOCK_BACKEND=auto` 时，系统优先尝试 Redis。出现连接失败、超时或 Redis 操作异常，且 `SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=true` 时，会进入本地锁降级：

- 当前进程内仍会按 `conversation_id` 串行化。
- 同一实例内的并发请求仍会收到 `session_busy`。
- 多实例之间不共享本地锁，因此同一会话若被负载均衡到不同实例，仍可能发生并发写入。

降级后会有短暂重试冷却时间，避免每次请求都阻塞在 Redis 连接失败上；冷却时间由 `SESSION_LOCK_REDIS_RETRY_INTERVAL_SECONDS` 控制。文档和部署配置需要明确：本地降级是可用性优先，不是强一致方案。

## 忙碌响应契约

并发请求命中同一会话锁时，后到请求会收到：

```json
{
  "type": "session_busy",
  "content": "当前会话正在处理上一轮消息，请稍后再试。",
  "conversation_id": "<conversation_id>",
  "retry_after_seconds": 3,
  "lock_backend": "redis",
  "active_seconds": 1.25,
  "expires_in_seconds": 298.75
}
```

随后会发送：

```json
{"type": "done"}
```

`lock_backend`、`active_seconds` 和 `expires_in_seconds` 是观测字段；前端只需要继续按 `content` 展示提示即可。忙碌请求不会保存用户消息，用户可等待当前轮完成后重新发送。

## 设计取舍

- 当前选择快速失败，而不是排队。这样能避免用户快速连点导致旧输入排队过久，也让消息顺序更容易解释。
- 锁不写入 `TravelState`，也不进入 PostgreSQL（关系型数据库）。它只保护运行时进入 Agent 主链路的临界区。
- TTL 是崩溃兜底，不是正常释放路径。正常路径仍依赖 owner 匹配释放。
- 续租间隔应小于 TTL。建议 TTL 至少是续租间隔的 3 倍，给网络抖动留余量。
- 如果 Redis 不可用且禁止本地降级，请求会暴露错误；这是强一致优先的部署策略。

## 验证

重点测试覆盖：

- 同一会话重复获取锁会被拒绝。
- 不同会话可并行获取锁。
- 本地锁释放后同一会话可再次获取。
- 本地锁 TTL 过期后允许新 owner 获取。
- 本地锁自动续租能保持长流式请求的 lease。
- Redis 锁会拒绝同会话第二个 owner。
- Redis 锁 TTL 过期后允许新 owner 获取。
- 旧 owner 的异常释放不会删除新 owner 的 Redis 锁。
- Redis 续租只在 owner 匹配时刷新 TTL。
- Redis 不可用时可降级到本地锁，并保留同进程冲突保护。
- SSE 忙碌请求不会保存用户消息。
- SSE 生成器关闭时释放锁。
- 运行指标能统计 `session_busy` 事件。

建议命令：

```powershell
.\.venv\Scripts\python -m compileall app tests
.\.venv\Scripts\python -m pytest tests\test_session_consistency.py tests\test_system_resilience.py -q
.\.venv\Scripts\python -m pytest -q
```
