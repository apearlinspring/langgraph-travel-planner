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
- `app/core/conversation_summary.py`：用确定性规则提取预算、日期、目的地、禁忌、确认选择、待核验等关键上下文。
- `app/core/context_pack.py`：把短期状态、近期消息、长期记忆、证据包和摘要打成可解释上下文包。
- `app/core/middleware.py`：在 `StepConfigMiddleware` 中注入上下文包，并在超过预算时只把最近关键轮次传给模型。
- `app/core/state.py`：新增 `conversation_summary`、`context_last_step`、`context_pack_metadata`、`context_summary_updated_at`。
- `app/core/memory_models.py` 与 `app/tools/memory_tools.py`：增加长期记忆写入判定，区分 stable（稳定长期）和 temporary（本次临时）条件。
- `app/agents/handoffs/step_config.py`：明确记忆工具只保存稳定偏好，不把“这次/本次/当前行程”写入长期画像。

## 设计取舍

- 摘要先用确定性规则，不新增一次 LLM 调用，保证本地测试稳定，也避免额外成本。
- 近期消息仍保留原始消息对象，尤其保留最新工具结果；长工具输出会按预算截断。
- 最终报告阶段只保留较少近期轮次，更依赖结构化状态、证据包和预算摘要。
- 长期记忆默认保存稳定偏好；如果模型传入 `memory_scope="temporary"` 或内容明显是本次旅行条件，则工具不会写入长期 Store（持久化存储）。

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

结果：`43 passed`。

## 自审

- 未读取、写入或提交 `.env` 真实密钥。
- 未新增真实库存、锁价、支付、客服或余位承诺。
- 工具失败兜底原则未改变；本模块只管理上下文注入和记忆边界。
- 新增测试均为本地确定性测试，没有真实网络、真实 LLM 或真实外部 API 依赖。
- 已避免把临时同行人要求、单次住宿偏好、单次预算写入长期用户画像。

## 剩余风险

- 当前摘要是规则型摘要，不如人工顾问或 LLM 摘要细腻；后续可在成本允许时增加可选 summarizer（摘要器）profile。
- 中间件通过状态对象记录摘要元数据，实际持久化行为依赖 LangGraph（图式智能体编排框架）运行时对 state 的保存方式；当前测试覆盖了注入和状态字段更新。
- 长期记忆工具仍依赖模型正确传参；prompt 已约束 `memory_scope`，后续可以继续把写入事件纳入工具审计。
