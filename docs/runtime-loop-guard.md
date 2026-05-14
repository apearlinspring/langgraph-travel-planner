# Runtime Loop Guard（运行期循环保护）

## 背景

`acceptance-core`（核心验收）里的 `free_weekend_nearby` 和 `agency_senior_low_stress` 曾暴露真实 Agent（智能体）链路里的重复工具调用、长回合等待和 `conversation_busy` / `session_busy`（会话繁忙）问题。修复原则是不放宽 runtime budget（运行预算）掩盖失败，而是在同一 turn（轮次）内阻断等价工具循环，并把上游慢调用转成可解释、可恢复结果。

## 本轮保护点

- `query_hotel_options`、`query_transport_options`、`query_destination_info` 以及目的地阶段的底层搜索工具同一轮只允许一次真实查询。重复调用会返回 `duplicate_tool_call_same_turn` 或被中间件从可见工具列表移除，提示模型基于已有结果总结，下一轮再刷新。
- StepConfigMiddleware（阶段配置中间件）会在强制单工具场景收窄本轮工具列表。例如需求已经足够记录时，只暴露 `record_requirement_tool`；需要直接查询目的地、酒店、交通或记录选择时，只暴露对应的单个工具，避免不支持强制 `tool_choice` 的模型在同一轮串联多种工具。用户同一轮明确要求同时核验交通和住宿时，会保留对应的复合查询工具。
- 需求收集阶段会把当前日期直接注入 prompt（提示词），并移除日期 MCP 工具；“这个周末/下周”等相对日期由模型基于注入日期换算，避免首轮为了日期工具额外等待一次外部工具和一次模型续写。
- 需求收集阶段默认把“轻松、少走路、美食、住宿、口味”等表述当作当前行程条件，不开放长期记忆工具；只有用户明确说“请记住/以后/每次/一直/过敏”或提到已经去过的历史旅行时，才保留对应记忆工具，避免先写偏好再记录需求的首轮工具膨胀。
- 需求收集首轮遇到复杂慢请求时优先轻量响应：如果用户第一句话已经同时包含酒店、天气、交通、风险、老人低压力、兜底或完整旅行社省心方案，StepConfigMiddleware 会暂缓所有工具，只确认理解并说明后续会核验真实证据。用户确认后再调用 `record_requirement_tool` 和对应真实工具，避免首 token（文本令牌）被慢 MCP 或 RAG（检索增强生成）阻塞。
- 首轮轻量响应会把用户原始诉求和规划模式线索暂存到状态中，后续 `record_requirement_tool` 会纳入这些线索推断 `agency_plan` 或 `free_planning`，避免因首轮不调用工具而丢失模式边界。
- 目的地推荐阶段已有目的地候选或工具结果时，在用户明确确认前会移除 `select_destination_tool`、`query_destination_info` 和 `search_travel_info` 等重复目的地刷新工具，并提示直接总结候选、等待确认，避免“查询后立刻再查/抢先选择”的同轮循环。
- 交通阶段没有已选方案时会优先收窄到 `query_transport_options`；交通真实查询刚返回的同一轮，若用户尚未授权记录，会暂时移除 `select_transport_tool`，只总结候选并等待确认。若用户本轮已经明确说“直接记录/按你推荐/确认”，中间件会保留并优先引导 `select_transport_tool`，同时移除重复交通查询，避免同一轮再次刷新同类信息。
- 交通阶段如果尚未记录交通方案，即使用户下一句提前确认住宿，也会先收窄到 `select_transport_tool` 写入交通，不跨阶段抢跑酒店查询或住宿记录，避免后续报告缺少交通证据。
- 交通方案刚写入后，即使工作流已经推进到住宿阶段，中间件也会在同一轮暂时移除 `query_hotel_options` 和住宿选择工具，避免一轮内连续执行“查交通 -> 选交通 -> 查酒店 -> 选酒店”的长链路导致 first-token（首个令牌）预警。验收脚本下一条住宿确认消息会重新开放酒店查询。
- 住宿阶段没有酒店候选且尚未选择住宿时，会直接收窄到 `query_hotel_options`；已有酒店候选时，会移除 `query_hotel_options` 和 `update_accommodation_preference_tool`，优先用候选调用 `select_accommodation_tool` 记录；如果模型只给酒店 ID（标识符）/酒店名，或已有候选时漏传 `accommodation_types`，选择工具会从候选推断住宿类型，必要时默认使用第一条候选；酒店 ID、价格、评分、设施等模型常见字符串参数会先安全归一化，避免停留在 `accommodation_planning` 直到真实验收超时；“这次/本次/当前行程”的住宿条件只作为当前行程参数，不写入长期住宿记忆。
- 最终报告阶段如果用户明确要求生成最终报告、完整方案或 `report_data`，中间件会把工具列表收窄到 `generate_order_tool`，并提示不要先输出短文本或手写报告，确保结构化 `report_data`、预算置信度、风险和待核验项由报告契约生成。
- RAG（检索增强生成）工具按工具名和参数 fingerprint（指纹）去重。同一轮重复读取同一证据会快速返回可恢复说明，不继续消耗检索预算。
- 酒店查询增加整轮总运行上限；候选地逐个超时时，不再把所有候选都等满导致长时间占用会话锁。
- `record_requirement_tool`、`select_destination_tool`、`select_transport_tool`、`select_accommodation_tool`、`select_food_tool` 对已经写入的等价状态执行 no-op（无操作）返回，避免重复写同一状态或把流程回退到旧阶段。
- duplicate skip（重复跳过）通过 `tool_audit`（工具审计）记录为 `skipped`，不会产生 SSE `error` 事件；运行指标仍能看到一次可恢复降级。
- `turn_observability`（轮次可观测）事件继续随真实 SSE（服务器发送事件）输出，acceptance snapshot（验收快照）和 summary（摘要）保留 `tool_call_count`、`error_event_count`、`estimated_total_tokens` 等运行指标；脱敏只遮蔽 PII（个人可识别信息）、JWT（JSON Web Token，令牌认证）、API key（应用程序接口密钥）和 secret（密钥），不遮蔽 token（文本令牌）计数。
- test（测试）运行环境默认关闭 LangSmith（LangChain 可观测平台）tracing（链路追踪）并压低其上报日志级别，避免无效测试密钥触发 `403 Forbidden` 噪声；这不改变业务异常、SSE `error` 事件或 runtime budget（运行预算）门禁的失败语义。

## 运行结果预期

- 同一轮内模型即使再次尝试酒店、交通或目的地真实查询，也会快速拿到“本轮已查询”的工具结果。
- 在需求记录、目的地查询、酒店查询、住宿记录等单步推进场景，模型的可见工具会被前置收窄，预期从源头减少 `duplicate_tool_call_same_turn`。
- 上游酒店 MCP（模型上下文协议）慢响应时，工具会在本轮预算内停止等待，明确“不编造酒店候选”，并建议下一轮放宽条件后重试。
- acceptance snapshot（验收快照）中应看到工具调用数下降，`error_event_count` 维持 0；如触发循环保护，`tool_audit` 会出现 `duplicate_tool_call_same_turn`。
- 测试默认输出不应再出现 LangSmith 403 上报刷屏；若真实 staging（预生产）或 production（生产）启用有效 LangSmith 密钥，第三方链路追踪仍可用，项目自身的 `turn_observability` 和验收运行指标也保持可读。

## 建议复核

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_tool_loop_guard.py tests\test_runtime_metrics.py tests\test_workflow_maintainability.py -q
.\.venv\Scripts\python -m pytest -q
```

具备真实环境时，优先单场景复跑：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario free_weekend_nearby --base-url http://127.0.0.1:8000 --json
```

复盘重点：`tool_call_count`、`tool_audit` 中的 `duplicate_tool_call_same_turn`、酒店/交通超时状态、`error_event_count` 和 `session_busy_event_count`。

## 2026-05-14 验证结果

完整 acceptance-core（核心验收）9 场景真实跑批已通过：

- 摘要：`.runtime\acceptance-core-full\20260514-134448-acceptance-summary.json`
- `status=passed`
- `passed_count=9`
- `degraded_count=0`
- `failed_count=0`
- 9 个场景均生成 `report_data`
- 9 个场景 `evidence_closure.missing=[]`
- 9 个场景 `runtime_budget=passed`
- 9 个场景 `error_event_count=0`
- 9 个场景 `session_busy_event_count=0`
- 按快照同轮同名工具事件复核，`duplicate_tool_call_same_turn=0`

本轮没有修改 runtime budget（运行预算）阈值或 warning ratio（警戒比例）。`.runtime/` 原始快照仅本地保留，不提交。
