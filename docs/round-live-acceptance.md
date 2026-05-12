# S2 Live Acceptance（在线验收）记录

日期：2026-05-12。

工作树：`D:\Users\Administrator\PycharmProjects\ZhiXing\langgraph-travel-planner-live-smoke-evidence`。

分支：`codex/live-smoke-evidence`。

## 结论

实际验收状态：`blocked（环境阻塞）`。

本轮已完成 acceptance-smoke（验收烟测）真实链路证据闭环的代码收口和本地阻塞留证。当前 S1（环境准备阶段）未 ready（就绪）：缺真实运行依赖，且后端 `/health/live` 与 `/health/ready` 均不可达。因此没有执行真实聊天对话链路，也没有生成有效 `report_data`，不能声明 `passed（通过）`。

## 场景覆盖

`acceptance-smoke` 当前选择 1 个最小场景：

- `pricing_agency_quote_explanation`

该场景满足 S2 覆盖要求：

- `expected_mode=agency_plan`，属于旅行社省心方案。
- prompt（提示词）明确包含“省心方案”。
- focus（关注点）和 tags（标签）覆盖 `pricing`、`budget`、报价说明、费用包含/不包含、二次核验。
- requirements（依赖声明）要求真实 LLM（大语言模型）、真实 MCP（模型上下文协议）以及 `amap`、`tavily` 外部 API（应用程序接口）。

代码层新增程序化约束：如果 `acceptance-smoke` 只包含自由行或缺少省心方案/报价说明场景，`acceptance_smoke_scenarios()` 会直接报错。

## 状态语义

S2 保持以下语义：

- `blocked`：真实依赖、配置、后端健康检查或凭据缺失，不能运行真实验收。
- `degraded`：核心依赖可运行，但可选依赖或运行预算出现降级，不能冒充 `passed`。
- `failed`：真实链路已运行，但报告、预算、风险、待核验项、旅行社证据、工具审计或运行时门禁失败。
- `passed`：真实链路已运行并产出合格 `report_data`，且所有确定性门禁通过。

新增防护：即使调用方传入陈旧的 `acceptance_summary.status=passed`，只要 preflight（预检）是 `blocked` 或 `degraded`，CLI（命令行接口）JSON 顶层也会被纠正为非 passed。

## 证据闭环

成功 live run（在线运行）会在结果中输出 `evidence_closure`，检查项包括：

- snapshot（快照）路径。
- `report_data` 是否存在。
- `budget` 与 `budget_confidence` 是否存在。
- `risks` 是否存在。
- `verification_items` 或等价待核验项是否存在。
- 旅行社业务证据类别是否不少于 3 类。

本轮因 S1 环境未 ready，`evidence_closure` 汇总为 0 条有效闭环记录，这是预期结果：缺真实依赖时不能伪造 `report_data` 或业务证据。

## 本地证据产物

完整 smoke 入口命令：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

结果：

- 退出码：`2`
- 顶层状态：`blocked`
- `passed=false`
- 场景数：`1`
- `missing_required=7`
- `health_checks=2`
- `blocking_reasons=7`

本地 `.runtime/` 证据：

- `.runtime\acceptance-smoke\20260512-134940-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260512-134940-acceptance-summary.md`
- `.runtime\acceptance-smoke-run-current.txt`
- `.runtime\acceptance-smoke-preflight-current.txt`

这些文件只作为本机证据，不提交。

## 脱敏检查

已对本轮 `.runtime\acceptance-smoke\20260512-134940-acceptance-summary.json` 和 `.runtime\acceptance-smoke\20260512-134940-acceptance-summary.md` 扫描以下敏感形态：

- 邮箱。
- 手机号。
- JWT（JSON Web Token，令牌认证）。
- 常见 API key（应用程序接口密钥）形态。

结果：`NO_SENSITIVE_FINDINGS`。

## 阻塞项

本轮 preflight（预检）阻塞项：

- `runtime_config`
- `real_llm`
- `external_api:amap`
- `external_api:tavily`
- `real_mcp`
- `backend_live`
- `backend_ready`

具体含义：

- 缺 PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）配置。
- 缺真实 `DASHSCOPE_API_KEY`。
- 缺高德与 Tavily 外部 API（应用程序接口）凭据。
- 真实 MCP（模型上下文协议）服务缺上游凭据。
- 后端 `GET /health/live` 和 `GET /health/ready` 当前连接被拒绝。
- RAG（检索增强生成）向量库目录不存在。
- Auth（认证）/ JWT（JSON Web Token，令牌认证）配置缺失。

## 验证记录

```powershell
.\.venv\Scripts\python -m pytest tests\test_evaluation_live_runner.py -q
```

结果：`32 passed`。

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
```

结果：退出码 `0`。

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
```

结果：退出码 `2`，`status=blocked`，`passed=false`，`missing_required=7`，`health_checks=2`，`blocking_reasons=7`。

## 与 S1 的依赖关系

S2 的真实链路通过依赖 S1 先达到 ready（就绪）。S1 至少需要完成：

- PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）可用。
- `.env` 具备真实但不提交的 LLM（大语言模型）、地图、搜索、Auth（认证）/ JWT（JSON Web Token，令牌认证）配置。
- RAG（检索增强生成）向量库初始化完成。
- 后端健康检查进入 ready（就绪）或经人工接受的 degraded（降级）。

S1 未 ready 时，S2 的唯一正确结果是 `blocked`，不能返回 `passed`。
