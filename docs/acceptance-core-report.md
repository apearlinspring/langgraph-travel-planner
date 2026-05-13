# Acceptance Core Evidence（核心验收证据）报告

## 结论

本轮从最新 `origin/main` fast-forward 基准开始，执行了 acceptance-core（核心验收）preflight（预检）和完整入口。当前真实本地环境不能进入 9 个核心场景的 Agent（智能体）业务跑批，最终验收状态为 `blocked（环境阻塞）`。

这不是 acceptance gate（验收门禁）误判，也不是业务链路真实失败；门禁正确地阻止了缺真实依赖的运行被标记为 `passed（通过）`。

## 基准与命令

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-acceptance-core-evidence`
- 分支：`codex/acceptance-core-evidence`
- 基准命令：`git fetch origin; git merge --ff-only origin/main`
- 结果：`Already up to date.`
- 本地 Python 环境：当前工作树缺 `.venv`，已用 `uv sync --frozen` 按 `uv.lock` 重建虚拟环境。

执行过的验收命令：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core
```

随后短暂启动后端复核健康检查：

```powershell
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core
```

本地原始产物只保留在 `.runtime/`，不提交：

- `.runtime\acceptance-core\20260513-051811-acceptance-summary.json`
- `.runtime\acceptance-core\20260513-051811-acceptance-summary.md`
- `.runtime\acceptance-core-live-blocked.stdout.txt`
- `.runtime\acceptance-core-backend-rerun.stdout.txt`
- `.runtime\acceptance-core-backend-rerun.stderr.txt`

## Preflight 结果

最新带后端运行的摘要：

- `status=blocked`
- `passed=false`
- `.env` 存在：`false`
- `/health/live`：`passed`
- `/health/ready`：`blocked`
- ready 阻塞：`Backend readiness returned HTTP 503 with status not_ready`
- ready 缺失核心依赖：`postgresql`、`llm`

preflight 阻塞项：

- runtime config（运行配置）缺少 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、LLM（大语言模型）、RAG（检索增强生成）向量库、地图和 Auth（认证）/ JWT（JSON Web Token，令牌认证）相关配置。
- 缺少真实 `DASHSCOPE_API_KEY`。
- 缺少 aigohotel、amap、tavily、variflight 对应真实外部 API（应用程序接口）凭据。
- MCP（模型上下文协议）真实服务因外部凭据缺失被阻塞。
- 后端进程可启动并通过 live 检查，但 ready 检查因 PostgreSQL 和 LLM 未就绪返回 `not_ready`。

## 场景通过/失败地图

| 场景 | 类别 | 状态 | 原因 |
|---|---|---|---|
| `free_weekend_nearby` | free planning（自由规划） | blocked | preflight 阻塞，未进入真实对话跑批。 |
| `free_city_three_days` | free planning（自由规划） | blocked | preflight 阻塞，未进入真实对话跑批。 |
| `agency_couple_relaxed` | agency plan（旅行社方案） | blocked | preflight 阻塞，未进入真实对话跑批。 |
| `agency_family_parent_child` | agency plan（旅行社方案） | blocked | preflight 阻塞，未进入真实对话跑批。 |
| `agency_senior_low_stress` | agency plan（旅行社方案） | blocked | preflight 阻塞，未进入真实对话跑批。 |
| `edge_hotel_tool_fallback` | hotel fallback（酒店兜底） | blocked | preflight 阻塞，酒店真实工具依赖不可用。 |
| `pricing_agency_quote_explanation` | pricing（报价解释） | blocked | preflight 阻塞，未生成 `report_data`（结构化报告数据）。 |
| `risk_weather_disruption` | risk（风险预案） | blocked | preflight 阻塞，天气、搜索、酒店等真实依赖不可用。 |
| `edge_transport_tool_fallback` | transport fallback（交通兜底） | blocked | preflight 阻塞，交通相关真实工具依赖不可用。 |

状态统计：

- `passed`: 0
- `failed`: 0
- `degraded`: 0
- `blocked`: 9

## 失败归因

本轮没有发现 evaluation gate（评估门禁）语义 bug，因此没有放宽门禁，也没有修改 `app/evaluation/*` 或 `scripts/run_evaluation_scenarios.py`。

归因分类：

- 环境/密钥/外部 API 问题：是，本轮主因。
- Agent 业务链路问题：未验证，因 preflight 阻塞没有进入对话。
- RAG 证据问题：未验证，向量库缺失。
- MCP 工具问题：未验证，MCP 真实服务因外部凭据缺失被阻塞。
- `report_data` 契约问题：未验证，未生成最终报告。
- runtime budget（运行预算）问题：未验证，场景未运行。
- evaluation gate 误判：否，门禁正确返回 blocked。

## 下一轮模块拆分建议

1. 环境基线模块：准备 `.env`、PostgreSQL、Redis、JWT、真实 LLM 和外部 API 凭据；运行 `scripts.init_db` 和 `scripts.init_rag`，只提交配置清单和脱敏检查结果。
2. MCP 健康模块：逐个验证 weather、search、amap、12306、VariFlight、aigohotel 的启动、降级和 preflight 映射，产出服务级状态表。
3. acceptance-core 真实跑批模块：环境 ready 后只负责运行 9 个场景并提交脱敏摘要，不改业务逻辑。
4. 失败维度分析模块：若真实跑批进入 failed/degraded，再按 Agent、RAG、MCP、report_data、runtime budget 拆分修复。
5. 报告证据审计模块：检查 `report_data`、tool audit（工具审计）、预算置信度、待核验项和内部证据类别覆盖，避免把弱证据误写成通过。

## 自审

- 改动范围：本报告记录验收证据；未提交 `.runtime/` 原始产物。
- acceptance-core 实际状态：`blocked`，9 个核心场景均未进入真实业务跑批。
- 门禁逻辑：未修改；当前 blocked 语义符合“不把 blocked/failed 伪装成 passed”的目标。
- 新增/更新测试：本报告阶段未改代码，后续文档提交前会跑 compileall 和评估相关测试。
- 未解决风险：当前工作树缺真实运行配置与向量库，无法判断业务链路、RAG 证据、MCP 工具和最终报告契约质量。

## 下一步

下一步先恢复真实 acceptance-core 环境依赖，再复跑 preflight；只有 preflight 达到 `passed` 或可解释的 `degraded` 后，才进入 9 个场景的真实跑批和失败维度拆分。
