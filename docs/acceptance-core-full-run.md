# Acceptance Core Full Run（核心验收全量跑批）复核

## 结论

2026-05-14 在 `codex/acceptance-core-full-run` 分支，以最新 `origin/main` 为基准，使用真实 `.env`、PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG（检索增强生成）向量库、MCP（模型上下文协议）服务和本地后端，启动了一次 `acceptance-core` 9 场景真实跑批。

本轮结论：`acceptance-core` 未通过，但已经确认不是环境阻塞。preflight（预检）通过，后端 `/health/ready=ready`，MCP 服务 6 healthy、0 unavailable、37 tools。失败集中在真实 Agent（智能体）链路：运行预算、工具重复/长链路、自由行模式误判为旅行社方案、公开 RAG 运行时检索降级，以及长回合导致的会话锁占用。

为避免继续消耗真实 API（应用程序接口）配额，跑批在超过 75 分钟且第 6 个场景仍未落盘时人工停止。停止前已落盘 5 个场景快照；这些原始产物保留在 `.runtime/`，不提交。

## 运行基线

- 工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-acceptance-core-full-run`
- 分支：`codex/acceptance-core-full-run`
- 基准：`origin/main` at `8997fb2`
- `.env`：存在，未打印，未提交
- `.venv`：由 `uv sync --frozen` 创建，未提交
- RAG 向量库：公开库 18 条 embedding（向量嵌入），内部库 61 条 embedding，未提交

执行过的关键命令：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core-full
```

## 前置结果

- Docker（容器运行环境）：passed
- runtime readiness（运行时就绪检查）：passed
- `scripts.init_db --mode bootstrap`：退出码 `0`
- `scripts.init_rag`：首次遇到 `ChunkedEncodingError`，清理半成品 ignored（忽略）向量库后重试通过
- `/health/live`：`alive`
- `/health/ready`：`ready`
- core preflight：退出码 `0`，`preflight.status=passed`

## 场景结果

| 场景 | 结果 | 关键证据 |
|---|---|---|
| `free_weekend_nearby` | failed | `report_data=true`，证据闭环通过；但 runtime quality（运行时质量）75，`tool_call_count=40 > 32`，`error_event_count=1 > 0`。 |
| `free_city_three_days` | failed | runtime 通过；但自由行场景生成了 `agency_context.mode=agency_plan`，导致 report quality（报告质量）和 RAG quality（RAG 质量）均未通过。 |
| `agency_couple_relaxed` | passed | 综合分 100，`report_data=true`，证据闭环通过，runtime budget（运行预算）通过。 |
| `agency_family_parent_child` | passed | 综合分 100，`report_data=true`，证据闭环通过，runtime budget 通过。 |
| `agency_senior_low_stress` | failed/incomplete | 第 8 回合超时 900 秒；未生成 `report_data`，缺 budget、risk、verification_items 和 agency_business_evidence。 |
| `edge_hotel_tool_fallback` | not_run | 第 6 场景继续循环，跑批被人工停止。 |
| `pricing_agency_quote_explanation` | not_run | 第 6 场景继续循环，跑批被人工停止；该场景此前 smoke（验收烟测）通过。 |
| `risk_weather_disruption` | not_run | 第 6 场景继续循环，跑批被人工停止。 |
| `edge_transport_tool_fallback` | not_run | 第 6 场景继续循环，跑批被人工停止。 |

已完成场景统计：

- `passed`: 2
- `failed`: 3
- `not_run`: 4
- 已完成快照数：5
- 总跑批耗时：超过 75 分钟后人工停止

## 失败归因

1. 运行预算与工具循环

   `free_weekend_nearby` 的报告和证据闭环都通过，但工具调用 40 次，超过默认预算 32 次，并产生 1 个错误事件。后端日志还显示多次重复 `select_food_tool`、`select_accommodation_tool` 和 `search_travel_info`。

2. 自由行/旅行社模式边界

   `free_city_three_days` 是 `expected_mode=free_planning`，但最终报告里 `agency_context.mode=agency_plan`。这说明当前模式路由或报告组装会把自由行场景过度推向旅行社省心方案。

3. 公开 RAG 运行时检索降级

   readiness 已确认公开和内部向量库存在，但运行时多次出现 `rag_empty_or_unavailable`，涉及 `search_destination_guide` 和 `search_food_recommendations`。这说明“向量库已初始化”和“工具可检索到合适内容”之间还有契约缺口。

4. 长回合导致会话锁占用

   `agency_senior_low_stress` 第 8 回合超时 900 秒，后续出现 `conversation_busy`。当前会话锁能保护并发一致性，但缺少验收场景中的长回合快速失败/恢复策略。

5. 外部工具链过厚

   交通场景会连续触发 `query_transport_options`、`query_trains`、`query_train_options`、`get-station-code-of-citys`、`get-tickets` 等工具，部分上游 timeout（超时）后仍继续走多步兜底，导致总耗时和 fallback（兜底）数偏高。

## 下一轮建议

下一轮不建议继续直接跑 9 场景。先拆 4 个可并行工作树修复：

1. Runtime loop guard（运行时循环保护）：收紧同一 turn（轮次）重复状态迁移工具、酒店/餐饮选择工具和交通链路重复调用，并让超时回合输出可恢复状态。
2. RAG runtime contract（RAG 运行时契约）：修复公开向量库 readiness passed 但工具返回 `rag_empty_or_unavailable` 的不一致，补充检索命中率测试。
3. Planning mode boundary（规划模式边界）：自由行场景不得生成 `agency_context.mode=agency_plan`，内部旅行社证据只在省心方案或报价场景中主导。
4. Acceptance runner resilience（验收运行器韧性）：为 9 场景跑批增加全局超时、单场景摘要即时落盘、被中断后的脱敏 partial summary（部分摘要）和 `conversation_busy` 明确失败维度。

修完后先跑 3 个代表场景：`free_weekend_nearby`、`free_city_three_days`、`agency_senior_low_stress`。这 3 个通过后，再恢复 9 场景完整验收。
