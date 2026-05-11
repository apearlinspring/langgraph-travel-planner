# 运行治理说明

## 目标

第三批运行治理补齐的是 Agent（智能体）跑批期间的确定性门禁。它不接真实计费系统，也不调用外部账单 API（应用程序接口），只使用 live snapshot（真实链路快照）里已经保存的 SSE（服务器发送事件）、turn（轮次）摘要、`turn_observability` 生产观测摘要、工具调用事件和文本长度做近似判断。

运行治理回答三个问题：

- 慢在哪里：总耗时、首 token（词元）时间、工具轮次耗时占比。
- 成本风险在哪里：估算输入 token、估算输出 token、估算总 token、工具调用次数。
- 工具是否过度调用：高成本工具同轮重复调用、总工具调用次数、工具调用预算占比。
- 兜底和降级在哪里：工具失败次数、fallback（兜底）次数、degraded（降级）轮次。

## 运行预算契约

核心契约在 `app/evaluation/runtime_metrics.py`：

- `RuntimeMetrics`：从快照收集到的事实指标。
- `RuntimeBudget`：运行预算阈值。
- `RuntimeBudgetGateResult`：预算门禁结果。
- `RuntimeQualityResult`：运行质量评分和治理摘要。

聊天 API（应用程序接口）会在每轮 `done` 前发送 `turn_observability` 安全摘要。该摘要不包含工具输入、工具输出、密钥、手机号、邮箱、身份证或异常原文，只包含 `turn_id`、阶段、规划模式、耗时、工具计数、失败计数、兜底计数、降级状态和 token 估算。

默认阈值：

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_total_elapsed_seconds` | 900 | 场景最大总耗时 |
| `max_first_token_seconds` | 60 | 首 token 最大等待时间 |
| `max_tool_call_count` | 32 | 场景最大工具调用次数 |
| `max_estimated_total_tokens` | 120000 | 估算总 token 上限 |
| `max_error_event_count` | 0 | SSE 错误事件上限 |
| `max_tool_turn_elapsed_seconds` | `null` | 可选工具轮次耗时上限 |

首 token 缺失时会记录 warning（警告），但不直接判失败，因为旧快照或纯 `report_data` 快照可能没有 token 事件。只要首 token 有观测值，就会按阈值判断。

## 场景预算

固定场景可以在 `data/evaluation/report_quality_scenarios.json` 写入 `runtime_budget` 覆盖默认阈值。长对话和工具降级场景已经放宽了总耗时、首 token、工具调用次数或估算 token 数。

`live_runner.runtime_budget_for_scenario()` 的策略：

- 默认使用 `RuntimeBudget`。
- `long-context` 或 `long_conversation` 场景放宽到 1200 秒、90 秒首 token、45 次工具调用、180000 估算 token。
- `hotel`、`transport`、`weather`、`fallback` 场景至少允许 36 次工具调用。
- 场景内 `runtime_budget` 拥有最终覆盖权。

## 质量门禁

成功跑完的快照会写入：

- `summary.quality_summary.runtime_quality.budget_gate`
- `summary.quality_summary.runtime_quality.governance_summary`
- `summary.quality_summary.runtime_governance`

`run_evaluation_scenarios.py` 现在使用综合 Agent 质量门禁作为退出码依据。也就是说，报告质量、RAG（检索增强生成）质量、工具质量或运行预算任一关键门禁失败，场景就会失败。

验收门禁还会单独检查 `runtime_metrics.turn_observability_event_count`。如果真实链路快照没有生产观测摘要，即使报告本身合格，也会暴露为 `runtime_observability` 维度失败。

`evaluate_report_snapshot.py` 为兼容旧快照，默认仍按报告质量退出。需要启用运行门禁时使用：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\evaluations\sample.json --scenario agency_couple_relaxed --enforce-runtime-budget
```

需要启用综合门禁时使用：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\evaluations\sample.json --scenario agency_couple_relaxed --enforce-agent-gate
```

## 摘要字段

`runtime_governance` 包含四个面向复盘的分组：

- `slow_path`：总耗时、首 token 时间、工具轮次耗时和慢点发现。
- `cost_risk`：估算输入、输出、总 token 和成本风险发现。
- `tool_usage`：工具调用次数、工具计数、冗余调用和过度调用发现。
- `fallbacks`：fallback 次数、降级轮次数和生产观测事件数量。
- `errors`：错误事件数和错误预算发现。

工具质量模块的 `tool_overuse` 还会补充：

- `total_call_count`
- `tracked_call_count`
- `tracked_call_ratio`
- `redundant_call_count`
- `high_frequency_tools`

这两个摘要配合使用：`tool_quality` 判断工具调用是否符合意图，`runtime_governance` 判断这些调用是否带来运行预算压力。

## 当前边界

- token 使用量是字符近似估算，不等于供应商真实计费 token。
- 工具调用次数只表示运行压力，不代表真实 API 成本。
- 没有接入真实账单、余额、计费 SKU（库存单位）或外部费用 API。
- 运行预算是回归门禁，不替代人工性能压测。
- `turn_observability` 是进程内和快照级观测，不是分布式 trace（链路追踪）。

## 本地验证注意事项

当前 runtime-governance worktree 如果没有 `.env`，直接运行测试或启动后端会缺少这些必填环境变量：

- `DASHSCOPE_API_KEY`
- `LANGSMITH_API_KEY`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

单元测试可以使用 PowerShell（Windows 命令行环境）的命令级 dummy（占位）环境变量，不需要复制或提交真实 `.env`：

```powershell
$env:DASHSCOPE_API_KEY='test-key'
$env:LANGSMITH_API_KEY='test-key'
$env:POSTGRES_DB='test_db'
$env:POSTGRES_USER='test_user'
$env:POSTGRES_PASSWORD='test_password'
$env:AIGOHOTEL_API_KEY='test-hotel-key'

D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner\.venv\Scripts\python.exe -m pytest -q
```

live 评估必须从当前 worktree 启动后端。否则 `scripts/run_evaluation_scenarios.py` 会请求已经监听在同一端口上的旧主线服务，不能验证本分支代码。建议使用不同端口，例如 `8001`，避免和主仓库服务冲突。

启动当前 worktree 后端示例：

```powershell
cd D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-agency-runtime-governance

# 仅本地可选，不提交；不要把真实 .env 或密钥写入仓库。
Copy-Item ..\langgraph-travel-planner\.env .\.env

$env:APP_PORT='8001'
D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner\.venv\Scripts\python.exe main.py
```

另一个终端运行 live 评估：

```powershell
cd D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-agency-runtime-governance

D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --base-url http://127.0.0.1:8001
```

如果 live 快照缺少 `evidence_bundle`、`tool_audit_summary` 等当前分支已经生成的字段，先确认后端进程是否从当前 worktree 启动。此前发现的 live 快照缺字段不是 `.env` 直接导致，而是 `127.0.0.1:8000` 后端服务从主仓库旧代码启动；当前分支已补 `agency_context.evidence` fallback（兜底证据），验证 live 场景时需要从当前 worktree 重启服务。

## 建议验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_metrics.py tests\test_tool_quality_evaluation.py tests\test_evaluation_live_runner.py -q
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --dry-run
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py --list-scenarios
```
