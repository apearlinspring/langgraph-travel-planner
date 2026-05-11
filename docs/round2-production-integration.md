# 第二轮生产级集成验收记录

记录时间：2026-05-11

集成分支：`codex/round2-production-integration`

## 集成结论

第二轮生产级集成已按指定顺序完成四个分支合并，并补齐聊天层的手工冲突处理。当前本地默认回归通过；真实链路验收被 Runtime Config Readiness（运行配置就绪）预检阻塞，原因是当前环境没有真实数据库、模型、RAG（检索增强生成）向量库和外部 API（应用程序接口）密钥。该阻塞符合生产门禁预期，没有使用真实密钥或真实个人信息。

## 合并顺序

| 顺序 | 分支 | 结果 | 集成提交 |
|---:|---|---|---|
| 1 | `origin/codex/runtime-config-readiness` | 自动合并，保留运行配置、JWT（JSON Web Token，令牌认证）、RAG 向量库、真实密钥和生产阻塞规则检查 | `3257516` |
| 2 | `origin/codex/tool-execution-guard` | 自动合并，接入工具执行网关、工具审计事件和工具失败/降级契约 | `bce5714` |
| 3 | `codex/production-observability` | `app/api/v1/chat.py` 手工解决冲突，合并 turn observability（轮次观测）与工具审计 | `82eba69` |
| 4 | `origin/codex/report-domain-decoupling` | 自动合并，保留报告领域拆分和路线对齐逻辑 | `0431fec` |

## 冲突处理

唯一冲突文件：

- `app/api/v1/chat.py`

解决方式：

- 保留工具网关分支的 `_extract_embedded_tool_audit_events` 和去重逻辑，聊天层优先读取工具返回的 `tool_audit_events`。
- 保留生产观测分支的 `TurnObservation`、`turn_id`、`turn_observability` SSE（服务器发送事件）摘要和安全错误响应。
- 对工具返回内嵌审计事件时，不再用聊天层结果校验重新构造 `success` 事件，避免把 `skipped`、`timeout`、`degraded` 误记为成功。
- SSE `tool_audit` 只发送 `public_tool_audit_event`，不暴露工具输入、工具输出、密钥、异常原文或 PII（个人身份信息）。
- 完整审计事件仍写入助手消息 `extra_info.tool_audit_events`，并尝试持久化到 `tool_audit_event` 表；持久化失败时写入降级状态。
- 嵌入式审计事件和聊天层兜底审计事件都会进入 `TurnObservation.record_tool_audit_event`，保证运行指标能看到工具失败、超时、跳过和降级。

## 保留的关键契约

- Runtime Config Readiness 继续区分 development、test、acceptance、production 环境，并对生产真实密钥、JWT/Auth（认证）、PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG 向量库和后端健康检查做阻塞式判断。
- 工具执行网关保留权限、参数校验、超时、降级、审批和审计事件结构。
- 聊天层优先消费工具自身产生的 `tool_audit_events`；只有没有内嵌事件时，才用聊天层结果校验器生成兜底审计。
- 运行指标消费真实工具审计事件，`runtime_metrics` 与验收门禁会检查 `turn_observability` 和工具失败/降级。
- 最终 `report_data` 由报告模块构建和校验，`normalize_report_route_alignment` 会补齐每日行程与地图路线，`validate_report_data` 会拒绝行程数量、地图路线数量或摘要不一致。
- 报告继续声明不支持真实支付、真实锁价、真实库存和真实预订成功，不写入真实密钥或真实个人信息。

## 实际验证

已通过：

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
```

结果：通过。

```powershell
.\.venv\Scripts\python -m pytest tests\test_runtime_readiness.py tests\test_tool_audit_governance.py tests\test_runtime_metrics.py tests\test_chat_report_metadata.py tests\test_report_contract_module.py tests\test_report_quality_evaluation.py -q
```

结果：`54 passed in 17.53s`。

```powershell
.\.venv\Scripts\python -m pytest -q
```

结果：`299 passed, 24 deselected in 12.02s`。

已运行但按预期阻塞：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json
```

结果：返回非 0；9 个核心场景均为 `skipped`，验收状态为环境阻塞。生成摘要：

- `.runtime\evaluations\20260511-061745-acceptance-summary.json`
- `.runtime\evaluations\20260511-061745-acceptance-summary.md`

主要阻塞项：

- 缺少 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`。
- 缺少 `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`。
- 缺少 `DASHSCOPE_API_KEY`。
- RAG 向量库目录不存在。
- 缺少 `AMAP_API_KEY`、`TAVILY_API_KEY`、`VARIFLIGHT_API_KEY`、酒店相关真实密钥。
- 缺少 `JWT_SECRET_KEY`、`JWT_ALGORITHM`。

## 未解决风险

- 未运行真实 live acceptance（真实链路验收），因为当前环境缺少真实模型、外部服务密钥、数据库配置和 RAG 向量库。
- 未启动后端做浏览器端 SSE 实测；本轮通过单元测试、流式生成测试和验收预检覆盖主要契约。
- `uv run python -m pytest tests\test_runtime_readiness.py -q` 首次创建环境时曾超时，后续 `.venv` 可用后已改用 `.\.venv\Scripts\python` 完成全部验证。

## 后续计划

1. 在具备真实 acceptance 环境变量、数据库、Redis、RAG 向量库和外部 API 密钥的环境中运行完整 `--acceptance-core`。
2. 重点复核生成快照中的 `events`、`summary.quality_summary.runtime_metrics`、`report_data.tool_audit_summary` 和 `report_data.evidence_bundle.route_alignment_findings`。
3. 推送当前集成分支后创建 base 为 `main`、head 为 `codex/round2-production-integration` 的 draft PR（草稿拉取请求）。
