# Live Acceptance（在线验收）Runbook（运行手册）

本手册用于复跑 S2 `acceptance-smoke`（验收烟测）和后续 `acceptance-core`（核心验收）。所有命令在 Windows PowerShell 中先启用 UTF-8，避免中文输出损坏。

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
```

## 当前分支

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-smoke-evidence`
- 分支：`codex/live-smoke-evidence`
- 日期：2026-05-12

## 状态判定

- `blocked（环境阻塞）`：真实依赖、凭据、后端健康检查或配置缺失，不能运行真实链路。
- `degraded（降级）`：核心链路可运行，但可选依赖、MCP（模型上下文协议）服务或运行预算降级，不能作为完全通过。
- `failed（失败）`：真实链路已运行，但确定性门禁失败。
- `passed（通过）`：真实链路已运行，产出 `report_data`，并通过报告、预算、风险、待核验项、旅行社证据、工具审计和运行时门禁。

缺真实依赖时，任何命令都不能返回 `passed`。

## 推荐复跑顺序

1. 先确认最小 smoke（烟测）场景选择：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
   ```

   预期至少包含 `pricing_agency_quote_explanation`，该场景覆盖旅行社省心方案和报价说明。

2. 跑 smoke preflight（预检）：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
   ```

   如果状态是 `blocked`，停止真实验收，只记录阻塞证据。

3. 后端 ready（就绪）后跑 smoke 真实入口：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
   ```

   产物必须写入 `.runtime/`，不能写到仓库文档或测试快照目录。

4. smoke 通过后，再跑 core（核心验收）：

   ```powershell
   .\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core
   ```

## 后端 ready 条件

真实验收前必须确认：

- `GET /health/live` 可达。
- `GET /health/ready` 返回 `ready`，或经人工确认可接受的 `degraded`。
- PostgreSQL（关系型数据库）可连通，业务表、Checkpointer（执行检查点）、Store（长期存储）已初始化。
- Redis（内存数据结构存储）在目标环境要求下可用。
- LLM（大语言模型）真实凭据存在，但不得写入文档或提交。
- RAG（检索增强生成）向量库已初始化。
- MCP（模型上下文协议）所需上游 API（应用程序接口）凭据存在。

## S2 本轮实际结果

本轮 S1 未 ready（就绪），所以 S2 记录为 `blocked（环境阻塞）`。

已运行：

```powershell
.\.venv\Scripts\python -m pytest tests\test_evaluation_live_runner.py -q
```

结果：`32 passed`。

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
```

结果：退出码 `0`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
```

结果：退出码 `2`，`status=blocked`，`passed=false`，`missing_required=7`，`health_checks=2`，`blocking_reasons=7`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果：退出码 `2`，`status=blocked`，`passed=false`，场景数 `1`。

本地证据：

- `.runtime\acceptance-smoke\20260512-134940-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260512-134940-acceptance-summary.md`

这些 `.runtime/` 文件不提交。

## 脱敏与提交规则

- 不提交 `.runtime/`。
- 不提交 `.env`、真实密钥、手机号、邮箱、证件号、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- JSON（JavaScript 对象表示法）和 Markdown（标记文本）摘要写入前必须经过脱敏。
- 可提交文档只记录状态、场景、阻塞项、命令结果和 `.runtime/` 相对路径。

本轮对 smoke summary（烟测摘要）执行敏感形态扫描，结果为 `NO_SENSITIVE_FINDINGS`。

## 下一步

下一轮先由 S1 补齐真实环境并让后端进入 ready（就绪）。S1 ready 后，按本手册先跑 `acceptance-smoke`，再扩展到 `acceptance-core`。
