# R2 Live Acceptance（在线验收）记录

## 结论

日期：2026-05-12。

工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-acceptance-pass`。

分支：`codex/live-acceptance-pass`。

实际验收状态：`blocked（环境阻塞）`。

本轮完成了可复跑、可判定、可留证的 R2 验收入口，但当前本地缺真实依赖，后端健康检查不可达，所以没有运行真实对话场景，也没有生成有效 `report_data`。缺真实依赖时，脚本不会返回 `passed`。

## 已收口能力

- `--json` 输出保持机器可读：stdout（标准输出）只保留 JSON（JavaScript 对象表示法），日志进入 stderr（标准错误）。
- preflight（预检）顶层输出 `missing_required`、`health_checks`、`blocking_reasons`。
- `blocked`、`degraded`、`passed`、`failed` 的整批状态由 preflight（预检）和场景门禁共同决定。
- 新增 `acceptance-smoke`（验收冒烟）入口，后端 ready（就绪）后可先跑 `pricing_agency_quote_explanation`。
- 成功场景仍通过确定性门禁验证 `report_data`、预算、风险、待核验项、旅行社业务字段、工具审计和运行时指标。
- 验收摘要和快照写入 `.runtime/`；脚本拒绝把 `--output-dir` 或 `--summary-dir` 指到 `.runtime/` 外。
- 验收摘要和 Markdown（标记文本）写入前执行脱敏，避免保存 API（应用程序接口）密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）等敏感文本。

## 实际运行命令

```powershell
.\.venv\Scripts\python -m pytest tests\test_evaluation_live_runner.py -q
```

结果：`28 passed`。

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
```

结果：退出码 0。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

结果：退出码 2，`status=blocked`、`passed=false`、`missing_required=9`、`health_checks=2`、`blocking_reasons=9`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
```

结果：退出码 2，`status=blocked`、`passed=false`、`scenario_count=1`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json
```

结果：退出码 2，`status=blocked`、`passed=false`、`scenario_count=9`。本地摘要：

- `.runtime\evaluations\20260512-064458-acceptance-summary.json`
- `.runtime\evaluations\20260512-064458-acceptance-summary.md`

## 阻塞项与环境说明

- `.venv` 初始不可用；本轮先用 `uv run --frozen`（Python 依赖运行器）恢复依赖环境，最终验证命令已改用 `.venv\Scripts\python`。
- 缺 PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）配置。
- 缺真实 `DASHSCOPE_API_KEY`，不能调用 LLM（大语言模型）或初始化 RAG（检索增强生成）向量库。
- 缺 `AMAP_API_KEY`、`TAVILY_API_KEY`、`VARIFLIGHT_API_KEY` 和 aigohotel 酒店凭据。
- 缺 staging（预生产）验收所需 Auth（认证）/ JWT（JSON Web Token，令牌认证）配置。
- `/health/live` 和 `/health/ready` 均不可达。

## 后端 ready（就绪）后的最小复跑

先跑 smoke（冒烟测试）：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json
```

通过后再跑 core（核心验收）：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json
```

如果 smoke（冒烟测试）没有生成 `report_data`，或预算、风险、待核验项、旅行社业务字段任一门禁失败，结果必须是 `failed` 或 `degraded`，不能是 `passed`。
