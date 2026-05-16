# Predeploy Runtime Acceptance（部署前运行时验收）

## 2026-05-16 当前结论

- 分支：`codex/live-demo-acceptance-refresh`。
- 状态：failed（失败）。`acceptance-smoke`（冒烟验收）1/1 passed（通过），但 `acceptance-core`（核心验收）9 场景为 6/9 passed（通过），不能作为发布通过证据。
- 真实环境：使用本机真实 `.env`；`.env` 存在且未被 Git 跟踪，未打印或写入真实密钥。
- 后端：使用 `main.py` 启动，并显式设置 `DEBUG=false` 避免 reload（热重载）监听 `.runtime/` 造成验收干扰。
- 原始证据：`.runtime/` 仅本地保留，不提交。

## 环境与初始化

| 项目 | 结果 | 脱敏证据 |
|---|---:|---|
| `.env` | present / ignored | 仅确认存在和未跟踪，不记录变量值 |
| `uv sync --frozen` | passed（通过） | 依赖按锁文件同步 |
| PostgreSQL（关系型数据库） | ready | 复用本地 healthy 容器，`init_db --mode bootstrap` passed |
| Redis（内存数据结构存储） | ready | 会话锁后端为 Redis |
| RAG（检索增强生成） | ready | `init_rag` passed；public/internal 向量库计数为 36/212 |
| MCP（模型上下文协议） | ready | `/health/ready` 显示 6 个服务 healthy，37 个工具 |
| LLM（大语言模型） | ready | `DASHSCOPE_API_KEY` 存在性校验通过，未输出密钥 |
| 后端健康 | ready | `/health/live=alive`，`/health/ready=ready` |

## Smoke 结果

| 项目 | 值 |
|---|---:|
| summary（摘要） | `.runtime/acceptance-smoke/20260516-063639-acceptance-summary.json` |
| 场景 | `pricing_agency_quote_explanation` |
| 状态 | passed（通过） |
| 场景数 | 1 / 1 |
| elapsed（耗时） | 402.330s |
| first token（首个文本令牌） | 14.801s |
| tool calls（工具调用） | 18 |
| `report_data` | true |
| evidence closure（证据闭环） | passed（通过） |

smoke 结果只证明最小报价说明链路可用，不能覆盖 9 场景 core 证据包。

## Core 结果

| 项目 | 值 |
|---|---:|
| summary（摘要） | `.runtime/acceptance-core/20260516-074331-acceptance-summary.json` |
| 状态 | failed（失败） |
| 场景数 | 9 |
| passed（通过） | 6 |
| failed（失败） | 3 |
| 失败分类 | `acceptance_gate=2`, `timeout=1` |
| 证据闭环通过 | 8 / 9 |
| 总耗时 | 3974.049s |
| 工具调用 | 119 |

失败明细见 `docs/acceptance-core-report.md`。不得把本轮 core 结果写成 passed（通过）。

## 已执行关键命令

```powershell
uv sync --frozen
uv run python -m scripts.init_db --mode bootstrap
uv run python -m scripts.init_rag
uv run python scripts\check_runtime_readiness.py --target staging --check-docker --json
uv run python main.py
uv run python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
uv run python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --scenario-timeout 900 --global-timeout 7200 --json --summary-dir .runtime\acceptance-core
uv run python scripts\export_acceptance_evidence.py --runtime-dir .runtime\acceptance-core --output docs\acceptance-core-report.md --required-scenarios 9
uv run python -m compileall app tests scripts
uv run python -m pytest -q
```

结果：

- `check_runtime_readiness.py --target staging --check-docker --json`：退出码 `0`，`status=passed`，`readiness_status=ready`，脱敏原始输出在 `.runtime/readiness-20260516-final.json`。
- `compileall`：退出码 `0`。
- 默认测试：`470 passed, 24 deselected`，`jieba` 依赖弃用 warning（警告）1 条。

## 脱敏与提交边界

- 不提交 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`。
- 文档只记录状态、指标、相对路径和结论；不记录真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或供应商私密响应。
- 失败按实际分类保留：工具覆盖失败、运行预算超时和证据闭环缺口不得改写为通过。
