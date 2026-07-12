# 模块 F：上下文工程与长期记忆

## 目标

真实旅行社智能顾问不会把所有聊天历史原样塞给 LLM（大语言模型），而是像顾问工作台一样维护几层上下文：

- 当前规划状态：目的地、日期、人数、预算、已选交通、住宿、行程和待核验项。
- 最近对话：保留用户最新修改、确认和反悔，避免回复脱节。
- 长期记忆：只保存稳定偏好、饮食禁忌和真实历史旅行。
- 证据包：保留 RAG（检索增强生成）与工具结果的摘要，让最终报告知道哪些依据可追溯。
- 会话摘要：长对话或跨阶段时压缩旧消息，降低 prompt（提示词）噪声和成本。

## 本次落地

- `app/core/context_budget.py`：提供近似 token（令牌）估算、消息数阈值和摘要触发决策。
- `app/core/conversation_summary.py`：默认用确定性规则提取预算、日期、目的地、禁忌、确认选择、待核验等关键上下文；同时提供可配置 LLM 摘要器，模型创建统一走 `app/utils/llm_factory.py`。
- `app/core/context_pack.py`：把短期状态、近期消息、长期记忆、会话摘要、关键历史轮次和证据包打成可解释上下文包。
- `app/core/middleware.py`：在 `StepConfigMiddleware` 中注入上下文包，并在超过预算时只把最近关键轮次传给模型，同时把上下文元数据写回 state（状态）。
- `app/core/state.py`：新增或维护 `conversation_summary`、`key_history_turns`、`context_last_step`、`context_pack_metadata`、`context_layer_boundaries`、`context_summary_updated_at`。
- `app/core/memory_models.py`、`app/core/store.py` 与 `app/tools/memory_tools.py`：增加长期记忆写入判定和审计字段，区分 stable（稳定长期）和 temporary（本次临时）条件，并记录来源、原因、置信度。
- `app/agents/handoffs/step_config.py`：明确记忆工具只保存稳定偏好，不把“这次/本次/当前行程”写入长期画像。

## 摘要策略

默认策略是确定性摘要，测试和本地回归不需要真实 LLM 调用。需要在线上或联调环境试用 LLM 摘要时，通过环境变量开启：

```powershell
$env:CONVERSATION_SUMMARY_BACKEND='llm'
$env:ZHIXING_CONTEXT_SUMMARY_PROFILE='rag'
$env:ZHIXING_CONTEXT_SUMMARY_MAX_TOKENS='700'
$env:CONVERSATION_SUMMARY_FALLBACK='true'
```

说明：

- `deterministic`：默认值，只使用本地规则，稳定、便宜、适合测试。
- `llm`：调用 `build_chat_model(profile=...)` 生成摘要；失败时默认回退确定性摘要。
- 当 `CONVERSATION_SUMMARY_BACKEND=llm` 但没有 `DASHSCOPE_API_KEY` 时，不允许无声回退：默认会显式降级到确定性摘要，并把原因写入 `summary_fallback_reason`；如果设置 `CONVERSATION_SUMMARY_FALLBACK=false`，则直接配置失败。
- 兼容旧变量 `ZHIXING_CONTEXT_SUMMARY_MODE` 和 `ZHIXING_CONTEXT_SUMMARY_FALLBACK`，但新文档优先使用 `CONVERSATION_SUMMARY_BACKEND`。
- `ZHIXING_CONTEXT_SUMMARY_PROFILE` 默认使用 `rag`，避免占用主规划模型档位。

## 上下文边界

上下文包按层组织，避免把所有信息混成一段不可解释 prompt：

- 短期状态：来自 `TravelState` 的结构化当前行程字段，可信度最高。
- 最近消息：少量原始对话，承接用户最新修改、确认或反悔。
- 会话摘要：旧消息压缩结果，只承载可复用事实、阶段变更和待核验项。
- 关键历史轮次：从旧消息里检索出的少量原文片段，用来补充摘要之外的可追溯依据。
- 长期记忆：跨会话稳定偏好和历史事实，不代表本次临时条件。
- 证据包：RAG 与工具证据摘要，用于报告依据、预算置信度和待核验项。

这些边界会写入 `context_pack_metadata.context_layer_boundaries`，方便调试和解释。

## 关键历史轮次

旧对话不再只依赖一段摘要承载。`extract_key_history_turns` 会按以下信号保留少量原文轮次：

- 含确认、选择、预算、日期、目的地、酒店、交通、忌口、过敏、待核验等关键词。
- 含人数、天数、价格或日期。
- 与当前最新问题有词面匹配。
- 用户原话或工具结果会有轻微加权。

最终上下文中会出现独立的 `【关键历史轮次】` 区块，数量和 token 预算由 `ContextBudget.max_key_history_turns` 与 `ContextBudget.key_history_tokens` 控制。

## 长期记忆审计

长期记忆写入现在有可解释字段：

- `source`：来源，例如 `memory_tool:update_food_preference_tool`。
- `extraction_method`：抽取方式，区分 `rule_extraction`（规则抽取）、`llm_extraction`（LLM 抽取）和 `human_confirmed`（人工确认）。
- `reason`：为什么接受或拒绝写入。
- `confidence`：0 到 1 的置信度。
- `scope`：`stable` 或 `temporary`。
- `accepted`：是否真正写入长期记忆。

画像和出行历史分别保留最近的审计记录，`format_memory_for_prompt` 只注入少量最近接受记录的依据，避免 prompt 膨胀。

## 设计取舍

- 摘要默认用确定性规则，保证本地测试稳定，也避免额外成本；可选 LLM 摘要用于长对话质量更高的线上场景。
- 近期消息仍保留原始消息对象，尤其保留最新工具结果；长工具输出会按预算截断。
- 关键历史轮次保留少量原文，弥补纯摘要可能丢失原话依据的问题。
- 最终报告阶段只保留较少近期轮次，更依赖结构化状态、证据包和预算摘要。
- 长期记忆默认保存稳定偏好；如果模型传入 `memory_scope="temporary"` 或内容明显是本次旅行条件，则工具不会写入长期 Store，并返回拒绝原因。

## 验证

已通过：

```powershell
$env:DASHSCOPE_API_KEY='test-key'
$env:LANGSMITH_API_KEY='test-key'
$env:POSTGRES_DB='test_db'
$env:POSTGRES_USER='test_user'
$env:POSTGRES_PASSWORD='test_password'
.\.venv\Scripts\python -m pytest tests\test_context_engineering.py tests\test_step_prompt_rendering.py tests\test_workflow_maintainability.py -q
```

当前本地没有预置 `.venv` 时可用：

```powershell
uv run python -m pytest tests\test_context_engineering.py tests\test_step_prompt_rendering.py tests\test_workflow_maintainability.py -q
```

测试数量会随项目演进变化，以命令当次输出为准；不要把旧的固定通过数当作当前证据。

注意：无模型密钥环境下通过的是确定性摘要路径，只说明上下文预算、规则摘要、关键历史轮次和记忆审计契约可用；不代表线上 LLM 摘要质量已经通过评估。线上启用 `CONVERSATION_SUMMARY_BACKEND=llm` 后，还需要用真实长对话样例单独验收摘要准确性、遗漏率和成本。

## 自审

- 未读取、写入或提交 `.env` 真实密钥。
- 未新增真实库存、锁价、支付、客服或余位承诺。
- 工具失败兜底原则未改变；本模块只管理上下文注入和记忆边界。
- 新增测试均为本地确定性测试，没有真实网络、真实 LLM 或真实外部 API 依赖。
- 已避免把临时同行人要求、单次住宿偏好、单次预算写入长期用户画像。
- 长期记忆写入有来源、抽取方式、原因和置信度；拒绝写入临时条件时也返回可解释原因。

## 剩余风险

- LLM 摘要虽然已经可配置，但真实模型输出质量仍需要线上样例评估；默认路径仍是确定性摘要。
- 中间件通过状态对象记录摘要元数据，实际持久化行为依赖 LangGraph（图式智能体编排框架）运行时对 state 的保存方式；当前测试覆盖了注入和状态字段更新。
- 长期记忆工具仍依赖模型正确传参；prompt 已约束 `memory_scope`，本次新增审计字段，但尚未接入统一工具审计事件表。
- 会话摘要、长期记忆和证据包最终会进入 system prompt；它们包含用户或外部来源内容，应继续按不可信输入处理。当前已有字段化、裁剪和来源信息，但仍需增加提示注入语料、指令/数据分隔和跨来源冲突评测。
