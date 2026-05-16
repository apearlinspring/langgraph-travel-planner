# Predeploy Runtime Acceptance（部署前运行时验收）

## 2026-05-16 当前结论

- 分支：`codex/acceptance-core-rerun-closeout`。
- 基准：已执行 `git fetch origin --prune` 并快进到 `origin/main@620947b`。
- 状态：failed（失败）。`acceptance-smoke`（冒烟验收）1/1 passed（通过），但完整 `acceptance-core`（核心验收）9 场景为 6/9 passed（通过），不能作为发布通过证据。
- 真实环境：使用本机真实 `.env`；`.env` 存在且未被 Git（版本控制系统）跟踪，未打印或写入真实密钥。
- 后端：使用当前分支 `main.py` 启动，并显式设置 `DEBUG=false`，同时把 MCP（模型上下文协议）启动超时设置为 45 秒。
- 原始证据：`.runtime/` 仅本地保留，不提交。

## 环境与初始化

| 项目 | 结果 | 脱敏证据 |
|---|---:|---|
| `.env` | present / ignored | 仅确认存在和未跟踪，不记录变量值 |
| `uv sync --frozen` | passed（通过） | 依赖按锁文件同步到本地 `.venv/` |
| PostgreSQL（关系型数据库） | ready | 复用本地 healthy 容器，`init_db --mode bootstrap` passed |
| Redis（内存数据结构存储） | ready | 复用本地 healthy 容器 |
| RAG（检索增强生成） | ready | `init_rag` passed；public/internal 向量库计数为 18/106 |
| staging readiness（预生产就绪检查） | passed（通过） | `status=passed`，`readiness_status=ready` |
| 后端健康 | ready | `/health/live=alive`，`/health/ready=ready` |
| MCP（模型上下文协议） | ready | `/health/ready` 显示 6 个服务 healthy，37 个工具 |
| LLM（大语言模型） | ready | `DASHSCOPE_API_KEY` 存在性校验通过，未输出密钥 |

## Smoke 结果

| 项目 | 值 |
|---|---:|
| summary（摘要） | `.runtime/acceptance-smoke/20260516-092127-acceptance-summary.json` |
| 场景 | `pricing_agency_quote_explanation` |
| 状态 | passed（通过） |
| 场景数 | 1 / 1 |
| elapsed（耗时） | 484.360s |
| first token（首个文本令牌） | 50.554s |
| tool calls（工具调用） | 18 |
| `report_data` | true |
| evidence closure（证据闭环） | passed（通过） |

smoke 结果只证明最小报价说明链路可用，不能覆盖 9 场景 core 证据包。

## Core 结果

| 项目 | 值 |
|---|---:|
| summary（摘要） | `.runtime/acceptance-core/20260516-102402-acceptance-summary.json` |
| 状态 | failed（失败） |
| 场景数 | 9 |
| passed（通过） | 6 |
| failed（失败） | 3 |
| degraded（降级） | 0 |
| blocked（环境阻塞） | 0 |
| 失败分类 | `acceptance_gate=2`, `evidence_closure=1` |
| 证据闭环通过 | 8 / 9 |
| 总耗时 | 3509.789s |
| 工具调用 | 121 |

失败明细见 `docs/acceptance-core-report.md`。不得把本轮 core 结果写成 passed（通过）。

## 已执行关键命令

```powershell
git fetch origin --prune
git merge --ff-only origin/main
uv sync --frozen
.\.venv\Scripts\python.exe -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python.exe -m scripts.init_rag
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --base-url http://127.0.0.1:8000 --json --no-summary
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke --scenario-timeout 900 --global-timeout 1200
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url http://127.0.0.1:8000 --json --no-summary
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200 --continue-on-error
```

结果：

- `check_runtime_readiness.py --target staging --check-docker --json`：退出码 `0`，`status=passed`，`readiness_status=ready`。
- `check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json`：退出码 `0`，`status=passed`，`readiness_status=ready`，MCP 6 healthy / 37 tools。
- `acceptance-smoke`：1/1 passed（通过）。
- `acceptance-core`：9 场景完整执行，6/9 passed（通过），总状态 failed（失败）。
- 本轮未运行 `compileall` 或默认 `pytest`（Python 测试框架）回归；任务范围为真实环境验收复跑与脱敏证据更新。

## 失败摘要

| 场景 | 分类 | 摘要 |
|---|---|---|
| `free_weekend_nearby` | evidence_closure（证据闭环） | 未产出结构化 `report_data`，缺少预算、预算置信度、风险和待核验项。 |
| `edge_hotel_tool_fallback` | acceptance_gate（验收门禁） | 工具治理分 70.0 低于 80.0，缺少预期 `query_hotel_options` 调用。 |
| `edge_transport_tool_fallback` | acceptance_gate（验收门禁） | 工具治理分 70.0 低于 80.0，缺少预期 `query_transport_options` 调用。 |

## 脱敏与提交边界

- 不提交 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`。
- 文档只记录状态、指标、相对路径和结论；不记录真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- 失败按实际分类保留：工具覆盖失败和证据闭环缺口不得改写为通过。

## 下一步

修复 `free_weekend_nearby` 最终报告产出缺口，并修复 edge（边界）酒店/交通场景预期工具调用覆盖；之后先复跑 smoke，再复跑完整 9 场景 core，继续只提交脱敏摘要。
