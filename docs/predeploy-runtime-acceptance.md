# Predeploy Runtime Acceptance（部署前运行时验收）

## 2026-05-17 当前结论

- 分支：`codex/acceptance-core-final-gates-fix`。
- 基准：用户指定保持 `origin/main@3b02f41`；本轮在当前分支未合入状态下执行。
- 状态：passed（通过）。`acceptance-smoke`（验收冒烟测试）1/1 passed（通过），完整 `acceptance-core`（核心验收）9 场景 9/9 passed（通过）。
- 真实环境：使用本机真实 `.env`；`.env` 存在且未被 Git（版本控制系统）跟踪，未打印或写入真实密钥。
- 后端：使用当前分支 `main.py` 启动，`/health/live=alive` 且 `/health/ready=ready`。
- 原始证据：`.runtime/` 仅本地保留，不提交。

## 环境与初始化

| 项目 | 结果 | 脱敏证据 |
|---|---:|---|
| `.env` | present / ignored | 仅确认存在和未跟踪，不记录变量值 |
| PostgreSQL（关系型数据库） | ready | 本地服务可用，`scripts.init_db --mode bootstrap` passed |
| Redis（内存数据结构存储） | ready | 本地服务可用 |
| RAG（检索增强生成） | ready | public/internal 向量库就绪；向量库目录不提交 |
| 后端健康 | ready | `/health/live=alive`，`/health/ready=ready` |
| MCP（模型上下文协议） | ready | `/health/ready` 显示所需服务 healthy |
| LLM（大语言模型） | ready | `DASHSCOPE_API_KEY` 存在性校验通过，未输出密钥 |

## 单测与重点场景

| 项目 | 值 |
|---|---:|
| 相关单测 | 185 passed（通过），1 个第三方弃用 warning（警告） |
| 重点 4 场景 summary（摘要） | `.runtime/acceptance-fix-singles/20260517-four-after-transport-guard/20260516-212155-four-after-transport-guard.json` |
| 重点 4 场景 | 4 / 4 passed（通过） |
| 覆盖场景 | `free_weekend_nearby`, `edge_hotel_tool_fallback`, `pricing_agency_quote_explanation`, `edge_transport_tool_fallback` |

重点结果：

- `free_weekend_nearby`: 产出结构化 `report_data`，预算、预算置信度、风险和待核验项齐全。
- `edge_hotel_tool_fallback`: 保留 `query_hotel_options` 审计式调用，通过工具覆盖门禁。
- `edge_transport_tool_fallback`: 保留 `query_transport_options` 审计式调用，通过工具覆盖门禁。
- `pricing_agency_quote_explanation`: runtime budget（运行预算）通过，首 token 40.277s。

## Smoke 结果

| 项目 | 值 |
|---|---:|
| summary（摘要） | `.runtime/acceptance-smoke/20260517-transport-guard/20260516-212958-acceptance-smoke.json` |
| 场景 | `pricing_agency_quote_explanation` |
| 状态 | passed（通过） |
| 场景数 | 1 / 1 |
| elapsed（耗时） | 308.394s |
| first token（首个文本令牌） | 37.061s |
| tool calls（工具调用） | 19 |
| `report_data` | true |
| evidence closure（证据闭环） | passed（通过） |

smoke 结果只证明最小报价说明链路可用；本轮已继续复跑完整 9 场景 core，没有用 smoke 结论覆盖 core 证据。

## Core 结果

| 项目 | 值 |
|---|---:|
| summary（摘要） | `.runtime/acceptance-core/20260517-transport-guard/20260516-223916-acceptance-core.json` |
| 状态 | passed（通过） |
| 场景数 | 9 |
| passed（通过） | 9 |
| failed（失败） | 0 |
| degraded（降级） | 0 |
| blocked（环境阻塞） | 0 |
| 失败分类 | - |
| 证据闭环通过 | 9 / 9 |
| 总耗时 | 4015.637s |
| 工具调用 | 169 |

场景结果见 `docs/acceptance-core-report.md`。

## 已执行关键命令

```powershell
git fetch origin --prune
git status --short --branch
git diff --name-status
git diff --check
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python.exe -m pytest tests\test_evaluation_live_runner.py tests\test_intent_detection.py tests\test_planning_mode_boundary.py tests\test_tool_quality_evaluation.py tests\test_hotel_query_tool.py tests\test_transport_query_tool.py tests\test_tool_loop_guard.py tests\test_step_prompt_rendering.py -q
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario edge_transport_tool_fallback --scenario edge_hotel_tool_fallback --scenario free_weekend_nearby --scenario pricing_agency_quote_explanation --continue-on-error --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-fix-singles\20260517-four-after-transport-guard --summary-dir .runtime\acceptance-fix-singles\20260517-four-after-transport-guard --summary-prefix four-after-transport-guard --scenario-timeout 1200 --global-timeout 7200 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-smoke\20260517-transport-guard --summary-dir .runtime\acceptance-smoke\20260517-transport-guard --summary-prefix acceptance-smoke --scenario-timeout 1200 --global-timeout 1800 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --continue-on-error --base-url http://127.0.0.1:8000 --output-dir .runtime\acceptance-core\20260517-transport-guard --summary-dir .runtime\acceptance-core\20260517-transport-guard --summary-prefix acceptance-core --scenario-timeout 1200 --global-timeout 14400 --json
```

结果：

- 相关单测：185 passed（通过）。
- 重点 4 场景：4/4 passed（通过）。
- `acceptance-smoke`：1/1 passed（通过）。
- `acceptance-core`：9 场景完整执行，9/9 passed（通过），总状态 passed（通过）。

## 脱敏与提交边界

- 不提交 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`。
- 文档只记录状态、指标、相对路径和结论；不记录真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- 通过结论来自完整 9 场景 core，不来自 1 场景 smoke。

## 下一步

可以提交本轮代码、测试和脱敏文档；合入或部署前如运行环境、模型、MCP、RAG 或报告契约变化，应重新执行 smoke 和完整 9 场景 core。
