# AgentOps 轻量回放与版本记录

## 定位

本文把当前项目已有的轻量观测、工具审计和验收摘要整理成 AgentOps（智能体运行运营与治理）公开工程证据。它强调“能复盘一次 turn（单轮对话）的运行轮廓”，不把能力夸大成完整 APM（应用性能监控）、OpenTelemetry（开放遥测标准）或分布式 trace（链路追踪）。

当前可证明的是：

- 每轮对话有 `turn_id` 作为排查追踪码，并有阶段、模式、耗时、工具调用、兜底、降级和 token（文本令牌）估算摘要。
- 工具调用会留下脱敏后的审计摘要，可判断调用是否成功、失败、跳过、超时、需人工审批或需二次核验。
- readiness（就绪检查）、preflight（验收前置检查）和 acceptance summary（验收摘要）会把 blocked（阻塞）、skipped（跳过）、degraded（降级）、failed（失败）和 passed（通过）区分开。
- 运行复盘可以追到“这一轮为什么慢、为什么降级、哪个工具需要复查、是否触发验收门禁”，但不能还原完整内部调用链。

## 证据来源

| 来源 | 公开复盘用途 | 当前保存形态 | 边界 |
|---|---|---|---|
| `turn_observability` | 复盘单轮状态、阶段、模式、耗时、工具调用数、兜底次数和文本量估算。 | SSE（服务器发送事件）安全摘要、助手消息 `extra_info.observability`、进程内最近快照。 | 单进程和快照级观测，重启后进程内快照会丢失。 |
| `tool_audit` | 复盘工具是否执行、是否降级、耗时、重试次数和证据类型。 | SSE 安全摘要、`extra_info.tool_audit_events`、报告侧工具审计摘要。 | 不展示完整工具输入、完整工具输出、认证头或上游原始错误。 |
| `runtime_governance` | 复盘慢路径、成本风险、工具过度调用、兜底和错误预算。 | 评估和验收摘要中的聚合指标。 | token 数是字符近似估算，不等同于供应商真实计费。 |
| `check_runtime_readiness.py` | 复盘环境、数据库迁移、Docker、RAG 安全门禁和 acceptance 前置条件。 | 命令行 JSON 或人类可读报告。 | blocked 代表不能声明通过，不应包装成 passed。 |
| `run_evaluation_scenarios.py` | 复盘场景选择、preflight、dry-run（试运行计划）和 live acceptance（真实链路验收）。 | `.runtime` 下的本地摘要或命令行 JSON。 | `.runtime` 原始证据不作为公开提交内容。 |

## turn 级可观测字段

`turn_observability` 面向公开展示的是安全摘要，不包含用户原文、完整消息、工具明细原文或密钥。当前主要字段如下：

| 字段 | 含义 | 复盘价值 |
|---|---|---|
| `version` | 摘要契约版本，如 `turn_observability.public.v1`。 | 判断不同跑批摘要是否同一结构。 |
| `turn_id` | 单轮追踪码。 | 把前端治理台、后端日志和验收快照串起来。 |
| `status` | 单轮状态。 | 区分 completed、failed、busy、cancelled 等结果。 |
| `step` | 当前自由规划阶段。 | 复盘是否停在正确工作流阶段。 |
| `planning_mode` | 当前规划模式。 | 区分 `free_planning`、`agency_plan` 或待确认模式。 |
| `first_token_seconds` | 首个响应片段等待时间。 | 判断模型或上游链路是否首响过慢。 |
| `total_elapsed_seconds` | 本轮总耗时。 | 判断是否触发运行预算风险。 |
| `tool_call_count` | 工具启动次数。 | 判断工具压力和是否存在重复调用。 |
| `tool_failure_count` | 工具失败次数。 | 判断工具链质量和兜底原因。 |
| `fallback_count` | 兜底次数。 | 判断是否用降级回复继续服务。 |
| `degradation_status` | `ok`、`degraded` 或 `failed`。 | 快速判断本轮是否可作为稳定证据。 |
| `estimated_input_tokens` | 输入 token 近似估算。 | 只用于预算趋势，不用于真实账单。 |
| `estimated_output_tokens` | 输出 token 近似估算。 | 只用于预算趋势，不用于真实账单。 |
| `estimated_total_tokens` | 输入和输出估算总量。 | 判断长上下文和输出膨胀风险。 |
| `progress_snapshot` | 当前阶段、方案类型、已确认信息和偏好摘要。 | 复盘前端进度台与后端状态是否一致。 |

内部快照还会保存脱敏后的 `conversation_id`、`user_id`、`started_at`、`finished_at`、`planning_mode_source`、`user_message_chars`、公开工具事件、降级原因和错误类型。这些字段只适合本地排查，不应作为公开明细展示。

## 工具审计摘要

工具审计侧的公开摘要只暴露“执行轮廓”，用于解释工具调用是否可靠：

- `tool`：工具名，例如交通、住宿、天气、地图或搜索相关工具。
- `status`：原始状态，例如 `success`、`failed`、`timeout`、`degraded`、`skipped`、`approval_required`。
- `semantic_status`：前端可理解语义，例如成功、未查到、需核验、参数不足、已跳过或服务异常。
- `elapsed_seconds`：粗粒度耗时。
- `retry_count`：重试次数。
- `evidence_type`：证据类型，例如真实查询、兜底估算或未知来源。
- `error_type`：只在失败类状态中保留脱敏后的错误类型。
- `degraded`：是否属于失败、超时、降级、跳过或审批阻断类事件。

复盘时可以回答：

1. 本轮是否真的调用了外部或内部工具。
2. 工具失败是服务异常、参数不足、未查到候选，还是人工审批未通过。
3. 报告里的 `pending_checks` 是否来自工具审计，而不是凭空生成。
4. 如果工具状态是 `blocked`、`failed`、`timeout` 或 `skipped`，最终对外口径是否保留“需核验/不可承诺”的边界。

## 版本记录建议

当前工程已有若干 `version` 字段，但还不是完整的 Prompt Registry（提示词注册中心）或 Model Registry（模型注册中心）。为了让轻量回放更稳，后续每次 acceptance 或重要演示建议记录以下公开安全字段：

| 类型 | 建议字段 | 用途 | 不应记录 |
|---|---|---|---|
| Prompt（提示词）版本 | `prompt_contract_version`、阶段名、Prompt 文件或函数名、Git commit。 | 解释同一场景为何生成策略变化。 | 完整用户原文、未发布 Prompt 草稿。 |
| 模型版本 | provider（供应商）、model name（模型名）、profile（模型配置档）、temperature（采样温度）等非密钥配置。 | 复盘模型切换、成本和质量变化。 | API Key、账号、私有 endpoint 密钥。 |
| 工具配置版本 | 工具清单、MCP 服务必需/可选状态、外部能力是否声明 required。 | 复盘工具缺失为何是 degraded 还是 blocked。 | 真实凭据、Cookie、Refresh Token。 |
| 评估版本 | scenario set id（场景集标识）、场景文件版本、runtime budget（运行预算）、acceptance summary 版本。 | 复盘 passed/failed 是否同一门禁口径。 | `.runtime` 原始聊天、未脱敏日志、人工私密备注。 |
| 代码版本 | Git commit、分支、运行时间、命令参数。 | 让跑批结果可定位到具体工程状态。 | 本地绝对私密路径、未整理草稿材料。 |

这些字段可以进入公开摘要或演示报告；完整原始证据、私有数据和运行产物仍应留在本地。

## 轻量回放清单

复盘一次 turn 或一次 acceptance run 时，按下面顺序检查：

1. 定位版本：确认 Git commit、分支、场景集、命令参数和摘要 `version`。
2. 定位场景：确认 `scenario_id`、规划模式、当前阶段和 `turn_id`。
3. 看 readiness：如果 readiness 或 preflight 是 `blocked`，停止宣称通过，先记录阻塞原因。
4. 看首响和总耗时：用 `first_token_seconds` 与 `total_elapsed_seconds` 判断慢点。
5. 看工具压力：用 `tool_call_count`、工具名计数和 `runtime_governance.tool_usage` 判断是否过度调用。
6. 看工具可信度：逐条看 `tool_audit` 的 `status`、`semantic_status`、`evidence_type` 和 `retry_count`。
7. 看兜底和降级：如果 `fallback_count > 0` 或 `degradation_status != ok`，报告口径必须带“需核验/降级”。
8. 看验收门禁：只有 `acceptance_summary.status == "passed"` 且失败维度为空，才可作为通过证据。
9. 看公开边界：移除 `.runtime` 原始证据、完整聊天记录、PII（个人身份信息）、密钥和未脱敏错误原文。

## 可复跑命令

以下命令用于复查当前轻量 AgentOps 证据链。命令输出如果出现 `blocked`、`skipped`、`failed` 或关键 `degraded`，不能写成 `passed`。

```powershell
# Runtime readiness（运行配置就绪）汇总；默认会包含 deterministic RAG mixed-corpus safety gate。
uv run python scripts\check_runtime_readiness.py --target local --target acceptance --json

# 如果已经启动当前 worktree 的后端，可增加 backend readiness 探针。
uv run python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json

# Acceptance preflight（验收前置检查），只检查能否跑，不调用 live 场景。
uv run python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary

# Acceptance dry-run（试运行计划），只列出将运行的场景，不请求后端。
uv run python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run

# 相关单元测试：覆盖 turn 观测、工具审计、运行 readiness、live runner 和 Agent 指标。
uv run python -m pytest tests\test_chat_report_metadata.py tests\test_tool_audit_governance.py tests\test_runtime_readiness.py tests\test_evaluation_live_runner.py tests\test_agent_metrics_evaluation.py -q
```

如需真实 live acceptance（真实链路验收），必须先确认后端从当前 worktree 启动，并使用真实但不提交的本地配置。公开文档只能引用脱敏 summary，不应提交 `.runtime` 原始快照。

## 明确边界

当前能力不是：

- 不是完整 OpenTelemetry 分布式 trace，不能跨服务串联每个 span（链路片段）。
- 不是生产 APM，不能替代指标数据库、日志聚合、告警、采样策略和容量规划。
- 不是完整 replay engine（回放引擎），不能重放完整工具入参、完整工具出参或模型 token 流。
- 不是真实账单系统，token 和成本只做近似趋势判断。
- 不是隐私归档系统，不保存完整用户聊天、PII、密钥、Cookie、原始 `.env` 或 `.runtime` 原始证据。

公开口径建议写成：

> 项目具备 turn 级轻量观测、工具审计摘要、readiness/preflight/acceptance 版本化摘要，可支持单轮问题定位和离线验收复盘；它尚未接入完整分布式 tracing 或生产 APM，因此只承诺安全摘要级复盘，不承诺还原完整内部调用链。
