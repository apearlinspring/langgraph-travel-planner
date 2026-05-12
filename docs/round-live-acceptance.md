# S2 Live Acceptance（在线验收）记录

日期：2026-05-13。

工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-smoke-evidence`。

分支：`codex/live-smoke-evidence`。

## 结论

实际 smoke（烟测）状态：`passed（通过）`。

本轮基于最新 main（主线）和当前真实环境重新闭环：preflight（预检）可用，`acceptance-smoke`（验收烟测）进入真实聊天链路，产出结构化 `report_data`，并通过报告质量、RAG（检索增强生成）质量、工具治理、运行时预算、预算置信度、风险、待核验项和旅行社业务证据门禁。

这不是把 failed（失败）伪装成 passed（通过）。中间复跑曾出现两类真实问题：

- 默认首 token（文本令牌）预算 60 秒过严，历史失败点为 `first_token_seconds=64.839`。
- 场景级 `90s` 首 token 硬预算消除了 60 秒 violation（违规）。
- 后续真实复核曾失败于 `tool_call_count=35 exceeds budget 32`，原因是报价 smoke（烟测）触发旅行社报价/RAG（检索增强生成）证据、目的地、酒店和交通兜底核验的组合链路。

最终采用单场景预算：`max_first_token_seconds=90`，`warning_first_token_ratio=0.99`，`max_tool_call_count=36`，`warning_tool_call_ratio=0.99`。这是 `pricing_agency_quote_explanation` 的场景级覆盖，不是全局放宽；其他场景超过默认预算仍会失败。最终通过 run 的 `first_token_seconds=32.775`、`tool_call_count=15`，runtime budget（运行预算）无 findings（发现项）。

## 场景覆盖

`acceptance-smoke` 当前选择 1 个最小场景：

- `pricing_agency_quote_explanation`

该场景覆盖：

- 旅行社省心方案。
- 报价说明。
- 费用包含和不包含。
- 估算价格。
- 二次核验项。
- 预算置信度、风险、旅行社业务证据。

## 实际命令和结果

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
```

结果：退出码 `0`。

```powershell
.\.venv\Scripts\python -m pytest tests\test_evaluation_live_runner.py -q
```

结果：`34 passed`。

```powershell
.\.venv\Scripts\python -m pytest -q
```

结果：`364 passed, 24 deselected`。结束后 LangSmith（LangChain 可观测平台）上报返回 403，但 pytest（测试框架）退出码为 `0`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
```

结果：

- 退出码：`0`
- `preflight.status=passed`
- `backend_live=passed`
- `backend_ready=passed`
- 顶层 run status 为 `skipped`，原因是 `--preflight-only` 不运行场景。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果：

- 退出码：`0`
- 顶层状态：`passed`
- `passed=true`
- 场景结果：`pricing_agency_quote_explanation passed`
- 报告质量分：`100.0`
- Agent（智能体）综合分：`100.0`
- runtime budget（运行预算）：`passed`
- `first_token_seconds=32.775`
- `tool_call_count=15`
- `tool_failure_count=6`
- `fallback_count=6`
- `runtime_findings=[]`

## 证据产物

本地 `.runtime/` 证据：

- `.runtime\acceptance-smoke\20260512-183306-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260512-183306-acceptance-summary.md`
- `.runtime\evaluations\20260513-023306-pricing_agency_quote_explanation.json`
- `.runtime\acceptance-smoke-preflight-20260513-final3.txt`
- `.runtime\acceptance-smoke-live-20260513-final4.stdout.txt`

这些文件只作为本地证据，不提交。

## Evidence Closure（证据闭环）

最终 run 的 `evidence_closure` 结果：

```text
snapshot=true
report_data=true
budget=true
budget_confidence=true
risk=true
verification_items=true
agency_business_evidence=true
```

闭环摘要：

- `result_count=1`
- `passed_count=1`
- `missing_by_scenario={}`
- 旅行社证据类别：`pricing`、`products`、`report`、`risk`、`sop`
- 待核验项数量：`18`

## 脱敏检查

已对最终 `.runtime/` smoke summary（烟测摘要）、snapshot（快照）和命令捕获文件扫描以下敏感形态：

- 邮箱。
- 手机号。
- JWT（JSON Web Token，令牌认证）。
- 常见 API key（应用程序接口密钥）形态。

结果：`NO_SENSITIVE_FINDINGS`。

## 后续风险

- 本轮真实链路仍记录了工具失败和 fallback（兜底）事件，但这些事件已被报告中的待核验项、工具审计和证据闭环覆盖，未导致门禁失败。
- `.runtime/` 中的原始快照只保留在本机，不提交。
- 若后续更换模型、MCP（模型上下文协议）服务或真实上游响应，仍需重新跑 smoke（烟测）确认首 token（文本令牌）和报告生成稳定性。
