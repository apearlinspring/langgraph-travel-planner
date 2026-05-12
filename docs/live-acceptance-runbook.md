# Live Acceptance（在线验收）Runbook（运行手册）

本手册用于复跑 S2 `acceptance-smoke`（验收烟测）和后续 `acceptance-core`（核心验收）。所有 Windows PowerShell 命令先启用 UTF-8，避免中文输出损坏。

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
```

## 当前分支

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-smoke-evidence`
- 分支：`codex/live-smoke-evidence`
- 日期：2026-05-13

## 状态判定

- `blocked（环境阻塞）`：真实依赖、凭据、后端健康检查或配置缺失，不能运行真实链路。
- `degraded（降级）`：核心链路可运行，但可选依赖、MCP（模型上下文协议）服务或运行预算 warning（警告）触发，不能作为完全通过。
- `failed（失败）`：真实链路已运行，但确定性门禁失败。
- `passed（通过）`：真实链路已运行，产出 `report_data`，并通过报告、预算、风险、待核验项、旅行社证据、工具审计和运行时门禁。

缺真实依赖或缺 `report_data` 时，任何命令都不能返回 `passed`。

## 推荐复跑顺序

1. 启动依赖和后端。

   ```powershell
   .\.venv\Scripts\python main.py
   ```

2. 确认最小 smoke（烟测）场景选择。

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
   ```

   预期包含 `pricing_agency_quote_explanation`。

3. 跑 smoke preflight（预检）。

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
   ```

   注意：`--preflight-only` 不运行场景，因此 run status（运行状态）可能是 `skipped（跳过）`；应查看 JSON（JavaScript 对象表示法）里的 `preflight.status`。当前真实环境下应为 `passed`。

4. 跑 smoke 真实入口。

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
   ```

5. smoke 通过后，再扩展到 core（核心验收）。

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core
   ```

## S2 当前真实结果

2026-05-13 已完成一次真实 smoke（烟测）闭环：

- `preflight.status=passed`
- live smoke status（在线烟测状态）：`passed`
- 生成 `report_data`：是
- evidence closure（证据闭环）：通过
- runtime budget（运行预算）：通过
- `first_token_seconds=57.712`

本轮 smoke 场景级预算：

```json
{
  "max_first_token_seconds": 90,
  "warning_first_token_ratio": 0.95
}
```

取舍说明：

- 默认 60 秒硬预算对真实 LLM（大语言模型）+ MCP（模型上下文协议）首轮冷启动偏严。
- 硬预算只在 `pricing_agency_quote_explanation` 场景级放宽到 90 秒，不影响全局默认预算。
- warning（警告）阈值设为 95%，避免正常冷启动在 80% 默认阈值处被误标为 degraded（降级），但接近 90 秒时仍会提示。

## 本轮验证记录

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

结果：退出码 `0`，`preflight.status=passed`，`backend_live=passed`，`backend_ready=passed`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果：退出码 `0`，`status=passed`，`passed=true`，场景数 `1`。

本地证据：

- `.runtime\acceptance-smoke\20260512-170201-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260512-170201-acceptance-summary.md`
- `.runtime\evaluations\20260513-010201-pricing_agency_quote_explanation.json`

这些 `.runtime/` 文件不提交。

## 脱敏与提交规则

- 不提交 `.runtime/`。
- 不提交 `.env`、真实密钥、手机号、邮箱、证件号、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- JSON（JavaScript 对象表示法）和 Markdown（标记文本）摘要写入前必须经过脱敏。
- 可提交文档只记录状态、场景、阻塞项、命令结果和 `.runtime/` 相对路径。

本轮对最终 smoke summary（烟测摘要）和 snapshot（快照）执行敏感形态扫描，结果为 `NO_SENSITIVE_FINDINGS`。

## 下一步

如果后续改动影响模型、RAG（检索增强生成）、MCP（模型上下文协议）或报告结构，先复跑 `acceptance-smoke`。smoke 通过后再运行 `acceptance-core`，并继续只提交脱敏摘要，不提交 `.runtime/` 原始产物。
