# 知行评估体系设计

## 目标

评估体系先解决一个核心问题：真实对话链路跑完后，最终交付物是不是足够像一份可交付的旅游规划报告，而不只是“模型写得很长”。

第一版采用确定性规则评分，不依赖额外模型，适合作为本地调试、回归测试和 CI（持续集成）的质量基线。模块 G 已把评估对象从最终报告扩展到 Agent（智能体）运行质量：同时看 RAG（检索增强生成）证据、工具调用、运行耗时和 token（令牌）近似成本。现在还提供可选 LLM-as-Judge（大模型评审）补充层，用来补足人工质感判断，但不覆盖确定性门禁结论。

## 第一阶段：结构化报告质量评分

评分对象是 `report_data`，满分 100 分：

- 结构契约 20 分：检查 `version`、顶层字段、`overview` 和导出章节是否完整。
- 行程与地图 20 分：检查每日行程数量、每日内容、路线节点和 `map_routes` 是否可用于前端展示。
- 预算解释 20 分：检查总预算、人均预算、分类预算、费用依据、预算置信度和待核验项。
- 风险与调整 15 分：检查天气、交通、酒店、预约、Plan B 和后续调整建议。
- 旅行社业务贴合 15 分：检查内部知识库来源、自由规划 / 省心方案模式、业务亮点和知识分类。
- 前端导出准备 10 分：检查地图标签、每日路线与导出章节是否能支撑 HTML/PDF/图片导出。

默认通过线是 80 分，并且不能有任何关键维度的失败发现。

## 可选 LLM-as-Judge（大模型评审）补充层

`app/evaluation/llm_judge.py` 提供可选评审层，默认关闭。它只作为质量摘要里的补充维度，不参与 `acceptance_gate.passed`、退出码或确定性阈值计算；即使 LLM-as-Judge（大模型评审）给低分，只会出现在 `supplemental_dimensions.llm_judge` 中，不能把确定性通过改成失败，也不能把确定性失败改成通过。

评审 rubric（评分规程）满分 100 分，五个维度各 20 分：

- 业务贴合：是否符合用户约束、已确认偏好、规划模式和旅行社服务边界。
- 事实忠实：是否避免编造真实票价、库存、天气、联系人、支付链接或外部事实。
- 可交付性：是否能作为顾问交付物，包含路线、预算、待核验项和导出友好结构。
- 风险表达：是否清楚表达 Plan B、待核验项和不确定性，不夸大置信度。
- 旅行社专业度：是否像专业旅行顾问，而不是泛泛的聊天回复。

真实模型评审必须显式开启：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\evaluations\sample.json --scenario agency_couple_relaxed --llm-judge
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --llm-judge
```

LLM（大语言模型）创建统一走 `app/utils/llm_factory.py` 的 `build_chat_model(profile="report")`。缺少真实 `DASHSCOPE_API_KEY` 时，显式开启的评审会返回 blocked（环境阻塞），不会假装通过；默认未开启时返回 skipped（跳过）或不生成评审结果。单元测试使用 mock（模拟）模型结果，不依赖真实模型或真实密钥。

评审输入会先经过 redaction（脱敏）再发送给模型，输出保存前也会脱敏，避免记录真实密钥、手机号、邮箱、证件号、JWT（JSON Web Token，令牌认证）或其他 PII（个人可识别信息）。场景和评审结果都预留 `manual_review` 字段，包含 `reviewer_id`、`reviewed_at`、`overall_score`、`decision`、`labels`、`dataset_candidate` 和 `corrections`，用于后续沉淀人工评审数据集。

## 使用方式

对真实链路保存的 JSON（JavaScript 对象表示法）快照运行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\real-agency-rag-final-report-retake3-20260509.json --expected-mode agency_plan
```

输出 JSON：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\real-agency-rag-final-report-retake3-20260509.json --expected-mode agency_plan --format json
```

作为质量门禁使用：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\real-agency-rag-final-report-retake3-20260509.json --expected-mode agency_plan --fail-under 80
```

## 第二阶段：场景集

当前报告质量目录已经沉淀 13 个固定评估场景，位于 `data/evaluation/report_quality_scenarios.json`：

- 自由行：近郊轻预算、城市三日、长线跨城。
- 旅行社省心方案：情侣、亲子、银发、团建。
- 报价与风险：费用包含/不包含、价格待核验、天气与 Plan B。
- 边界场景：预算不足、酒店工具失败、交通工具失败、长对话改需求。

每个场景保存输入、期望模式、最低分、关键断言和真实链路输出。这样我们改提示词、模型分工或前端报告结构时，都可以快速判断有没有回退。

规划模式边界另见 [planning-mode-boundary.md](./planning-mode-boundary.md)：自由行、亲子、银发、少走路、轻松、交通或住宿省心等弱偏好不会自动进入旅行社方案；只有明确省心方案、旅行社产品、报价、合同规则或服务标准诉求时，`agency_context.mode` 才应为 `agency_plan`。

模块 G 还新增了两个专项目录：

- `data/evaluation/rag_quality_scenarios.json`：检查省心方案是否覆盖产品、SOP（标准作业流程）、报价、风险、报告标准等证据类别；自由行场景则重点看模式适配和避免硬推旅行社表达。
- `data/evaluation/tool_call_scenarios.json`：检查交通、酒店、目的地天气等工具是否按用户意图调用，是否避免同轮重复调用高成本查询工具，以及失败后是否进入待核验兜底。
- `data/evaluation/rag_retrieval_scenarios.json`：小型 RAG（检索增强生成）召回率评估集，标注查询应命中的知识源、知识分类和来源类型，用 Top-K source recall（来源召回）、category recall（分类召回）和 MRR（平均倒数排名）对比朴素 BM25（词频检索算法）与元数据增强检索。

列出场景：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py --list-scenarios
```

运行小型 RAG（检索增强生成）召回率评估，不需要 `.env`、真实 LLM（大语言模型）或外部 API（应用程序接口）：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py
.\.venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py --json
```

用某个场景验收真实链路快照：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\real-agency-rag-final-report-retake3-20260509.json --scenario agency_couple_relaxed
```

如果指定 `--scenario`，脚本会自动使用该场景的期望模式和最低分；仍然可以用 `--expected-mode` 或 `--fail-under` 手动覆盖。

## 真实链路跑批

`run_evaluation_scenarios.py` 可以把场景真正发给本地后端，读取 SSE（服务器发送事件）返回的 `report_data`，保存快照并自动评分。跑批结果现在按综合 Agent（智能体）质量门禁判断通过，不再只看最终报告分。

### 第一阶段总体验收质量门禁

第一阶段验收把“已完成计划目标”固化成可重复运行、可审计的结果。核心入口是：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000
```

`--acceptance-core` 会选择 `data/evaluation/report_quality_scenarios.json` 中带 `acceptance-core` 标记的核心场景，目前覆盖自由行、旅行社省心方案、报价解释、天气风险、酒店兜底和交通兜底 9 个场景。该模式会自动继续执行全部核心场景，即使中途有失败，也会在最后给出完整失败清单。

为避免 9 场景跑批被单场景长循环拖住，真实验收入口现在有两层运行预算：

- `--scenario-timeout`：单个场景 wall-clock（挂钟时间）超时；省略时沿用 `--timeout`，也可用 `ZHIXING_EVAL_SCENARIO_TIMEOUT` 覆盖。
- `--global-timeout`：整批已选场景的全局超时；也可用 `ZHIXING_EVAL_GLOBAL_TIMEOUT` 覆盖。
- `--timeout`：单次 HTTP（超文本传输协议）请求或 SSE（服务器发送事件）读取的底层网络超时。

推荐 core（核心验收）跑批显式写出预算：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-core --scenario-timeout 900 --global-timeout 7200
```

运行器会在每个场景结束后立即刷新 run-level summary（整批摘要），所以单个场景失败、timeout（超时）或后续中断不会吞掉前面已完成场景的机器摘要。摘要里的 `run_context` 会标明是否是 partial summary（部分摘要）、已完成场景、待运行场景和失败分类计数。

### 可提交证据包导出

`.runtime/` 下的 summary（摘要）和 snapshot（快照）属于本地原始产物，不提交。需要把最新 acceptance-core（核心验收）结果转成可提交、可面试展示的脱敏 Markdown（标记文本）时，使用：

```powershell
.\.venv\Scripts\python.exe scripts\export_acceptance_evidence.py --runtime-dir .runtime --output docs\acceptance-core-report.md
```

导出脚本会自动扫描 `.runtime` 下最新的 `acceptance_run_summary.v1` JSON（JavaScript 对象表示法）摘要，生成稳定的 9 场景状态地图，包含每个场景的状态、首 token（文本令牌）、工具调用数、证据闭环和运行预算结论。脚本只输出脱敏后的聚合字段，不读取或写入 `.env`，也不会把真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或原始工具响应写进文档。

缺文件或只存在 partial summary（部分摘要）时，证据包不会假装通过：

- 找不到 `.runtime` summary 时输出 `missing_summary（缺少摘要）`，并以非零退出。
- 已完成场景少于选中场景时输出 `partial summary（部分摘要）`，表格中未完成场景显示 `pending（待运行）`。
- 整批 `failed（失败）`、`degraded（降级）`、`blocked（环境阻塞）` 会原样保留在结论和状态表中，不会改写为 passed（通过）。

失败分类当前用于快速排查：

- `timeout`：单场景超时或网络读取超时，通常看场景快照、后端日志和最后一个 SSE 事件。
- `global_timeout`：整批运行预算耗尽，摘要保留已完成场景和未运行场景。
- `conversation_busy`：后端返回 `session_busy`，表示同一会话仍被上一轮执行占用。
- `runtime_budget`：场景产出 `report_data`，但运行预算门禁失败，例如总耗时、首 token（文本令牌）时间、工具调用数或估算 token 超阈值。
- `evidence_closure`：证据闭环失败，例如缺少快照、预算、风险、待核验项或旅行社内部证据类别。

脚本会先执行 preflight（预检）。预检会读取当前进程环境变量和 `.env`，但只输出环境变量名和状态，不输出真实密钥值。核心场景的 `requirements` 字段会声明它需要的真实能力：

- `real_llm`：真实 LLM（大语言模型），当前对应 `DASHSCOPE_API_KEY`。
- `real_mcp`：真实 MCP（模型上下文协议）服务。
- `mcp_servers`：场景需要的 MCP（模型上下文协议）服务，例如 `weather`、`search`、`amap`、`12306-mcp`、`VariFlight-Aviation`、`aigohotel-mcp`。
- `external_apis`：场景需要的外部 API（应用程序接口），例如 `amap`、`tavily`、`variflight`、`aigohotel`。

预检同时复用 Runtime Config Readiness（运行配置就绪）矩阵，按 `staging` 验收档位要求真实值：PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、LLM（大语言模型）、RAG（检索增强生成）向量库和地图等 required（必需）依赖缺失时会直接 blocked（环境阻塞）。`test` 档位允许 mock（模拟）或 skip（跳过）真实能力，但 `--acceptance-core` 不允许用占位密钥冒充真实验收。

没有真实密钥、后端健康检查不可达，或缺少所选场景声明的真实能力时，脚本不会运行真实场景，也不会给出“有效验收通过”的结论；它会生成 blocked（环境阻塞）报告，并把受影响核心场景标为 blocked（环境阻塞）。只做 preflight（预检）且预检不是 blocked（环境阻塞）时，场景才会标为 skipped（跳过）。此时报告质量、RAG（检索增强生成）质量、工具治理质量、运行时质量、预算置信度、内部证据和工具审计都标记为不可判定。

运行时预检读取后端 `/health/ready` 时，统一按 `runtime_readiness.v1` ready check（就绪检查）契约判断：顶层会包含 `environment`、`dependencies`、`missing_required`、`degraded_optional` 和 `services`。`services` 至少包含 `checkpointer`、`store`、`mcp`、`session_lock` 和 `approval_governance`。MCP（模型上下文协议）降级可以使验收摘要进入 `degraded`；但启动未完成、Checkpointer（执行检查点）或 Store（长期存储）未初始化、生产 Redis（内存数据结构存储）会话锁不可用、审批治理不能持久化到 PostgreSQL（关系型数据库）时，预检必须视为 blocked（环境阻塞）或不可继续运行。

也可以只运行预检，不发起真实对话：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json
.\.venv\Scripts\python.exe scripts\check_runtime_readiness.py --target acceptance --json
```

在 CI/CD（持续集成/持续交付）中，默认 GitHub Actions（GitHub 自动化流水线）不会运行本节的真实链路跑批。`.github/workflows/ci.yml` 的 push（推送）和 pull request（合并请求）门禁执行单元测试、测试收集、Python 编译、内部 RAG 知识库治理校验、前端报告渲染验证、workflow（工作流）契约测试和 development（开发）运行配置预检。

默认 CI 现在还会运行内部 RAG（检索增强生成）知识库治理校验：

```powershell
.\.venv\Scripts\python.exe scripts\validate_rag_knowledge.py
```

该脚本只读取 `data/documents/internal/` 的 Markdown（标记文本）文档头部 metadata（元数据），不会读取 `.env` 密钥，也不会输出真实合同、价格表或客户资料。它会在以下情况失败：缺少 `source_type`、`category`、`visibility`、`applicable_modes`、`evidence_level`、`last_reviewed`，目录分类和 metadata 分类不一致，内部知识被标成 `public`，或文档超过复审期限。低置信证据允许存在，但检索证据必须携带 `requires_verification` 和 `prohibited_commitments`，最终报告质量评分会阻止它支撑锁价、库存、支付或预订承诺。

GraphRAG（图检索增强生成）不作为当前门禁的必选实现。后续只有在内部知识需要稳定维护“产品、供应商、城市、季节、人群、风险”这类实体关系时，再评估把图谱作为可选增强层；当前阶段仍以可校验 metadata、可追溯证据和确定性质量门禁为主。

手动 staging smoke（预生产冒烟）门禁通过 `.github/workflows/staging-smoke.yml` 的 `workflow_dispatch`（手动触发）运行。它不使用外部 staging URL（预生产地址）作为前置条件，而是在 GitHub runner（流水线执行机）内启动 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）和后端，然后对 `http://127.0.0.1:8000` 运行最小真实链路：

```powershell
python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --summary-dir .runtime\acceptance-smoke --summary-prefix staging-smoke --json
```

该门禁的必需 GitHub Secrets（密钥管理项）是：`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`DASHSCOPE_API_KEY`、`AMAP_API_KEY`、`TAVILY_API_KEY`、`JWT_SECRET_KEY`、`ZHIXING_EVAL_USERNAME`、`ZHIXING_EVAL_PASSWORD`。可选 Secrets（密钥管理项）包括 `VARIFLIGHT_API_KEY`、`AIGOHOTEL_API_KEY`、`AIGOHOTEL_MCP_API`、`AIGOHOTEL_SECRET_KEY`、`LANGSMITH_API_KEY` 和 `LANGSMITH_PROJECT`。

这意味着没有真实密钥时，验收入口应失败或返回 blocked（环境阻塞），而不是用 mock（模拟）数据假通过；默认 CI（持续集成）也不会意外消耗真实 API（应用程序接口）额度。`Validate Required Secrets` 步骤会在服务启动前拦截空值；如果密钥存在但仍是占位值、后端健康检查失败、RAG（检索增强生成）向量库不可用，或 smoke（冒烟）场景声明的真实 LLM（大语言模型）/MCP（模型上下文协议）能力不可用，`run_evaluation_scenarios.py` 必须以 blocked（环境阻塞）或失败退出。

workflow（工作流）总是上传 `.runtime/acceptance-smoke` 作为 artifact（构建产物），包含 smoke（冒烟）摘要、runtime readiness（运行时就绪）JSON（JavaScript 对象表示法）、后端日志和服务日志。该目录由 `.gitignore` 忽略，只作为 GitHub Actions（GitHub 自动化流水线）运行产物保留，不进入提交。手动 staging smoke（预生产冒烟）不做服务器部署，也不触碰真实 production（生产）环境；完整 `acceptance-core`（核心验收）仍按本节本地命令或后续专门门禁执行。

默认会在 `.runtime/evaluations/` 下生成两类整批摘要：

- JSON（JavaScript 对象表示法）：机器可读，包含每个场景的报告质量、RAG（检索增强生成）质量、工具治理质量、运行时指标、阈值和失败维度。
- Markdown（标记文本）：人工审阅，包含场景总览、阈值、每个场景分数、快照路径和排查建议。

可以调整摘要目录：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000 --summary-dir .runtime\acceptance
```

核心门禁由 `app/evaluation/acceptance_gate.py` 聚合现有评分结果，不直接修改核心 Agent（智能体）业务逻辑。当前阈值包括：

- 综合 Agent（智能体）分：不低于场景 `min_score`，且全局最低 82 分。
- 报告质量：不低于 80 分。
- RAG（检索增强生成）质量：不低于 80 分。
- 工具治理质量：不低于 80 分。
- 运行时质量：不低于 80 分，并要求运行预算门禁通过。
- 预算置信度：必须包含置信度等级、已确认或估算项、待核验项。
- 旅行社省心方案：至少覆盖 3 类内部证据。
- 工具审计：必须暴露使用来源、待核验项和不支持承诺。

失败时摘要会明确给出：

- 失败场景。
- 失败维度，例如报告、RAG（检索增强生成）、工具、运行时、预算置信度、内部证据或工具审计。
- 环境依赖失败维度，例如真实密钥、后端健康检查、RAG（检索增强生成）向量库和场景声明的外部 API（应用程序接口）。
- 关键发现。
- 建议排查方向，例如检查 `report_data` 契约、内部证据类别、SSE（服务器发送事件）工具调用、运行预算或报告中的待核验项。

摘要状态语义：

- `passed`（通过）：预检通过，所有场景门禁通过。
- `failed`（失败）：预检具备运行条件，但至少一个场景或质量维度失败。
- `degraded`（降级）：核心门禁未失败，但存在非阻塞预检、运行预算 warning（警告）或运行治理风险；不等同于 passed（通过）。
- `blocked`（环境阻塞）：缺少真实密钥、后端不可达或核心依赖不足，不能生成有效通过结论。
- `skipped`（跳过）：场景没有执行，常见原因是 blocked（环境阻塞）或只运行 preflight（预检）。

先查看将要运行的场景，不调用后端：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --dry-run
```

运行单个场景，或重复 `--scenario` 运行一个子集：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --scenario risk_weather_disruption --base-url http://127.0.0.1:8000 --summary-dir .runtime\acceptance-subset
```

覆盖运行预算阈值：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000 --max-total-seconds 900 --max-first-token-seconds 60 --max-tool-calls 32 --max-estimated-tokens 120000 --max-error-events 0
```

默认账号是 `test / 000000`，也可以通过环境变量覆盖：

```powershell
$env:ZHIXING_EVAL_USERNAME="test"
$env:ZHIXING_EVAL_PASSWORD="000000"
```

脚本会把快照写入 `.runtime/evaluations/`，用于复盘首 token 时间、工具调用、最终报告结构和评分结果。

默认每个场景会先发送原始需求。如果第一轮没有生成结构化报告，脚本会在同一个会话里按阶段追加确认消息：记录需求、确认目的地、记录交通/住宿/餐饮、生成行程、汇总预算、最终报告。这样测试目标更接近真实验收：不是只看模型第一轮回复，而是看它能否稳定走到最终交付物。

## 第三阶段：Agent 运行质量评分

成功的 live snapshot（真实链路快照）现在会包含：

- 顶层 `report_data`：最终结构化旅行报告。
- `tool_events`：从 SSE（服务器发送事件）中归一化出来的工具调用事件。
- 顶层 `turn_observability`：每轮安全运行观测摘要。
- 顶层 `quality_summary`：综合 Agent（智能体）质量摘要，便于审计直接定位。
- `summary.quality_summary.report_quality`：原有结构化报告评分。
- `summary.quality_summary.rag_quality`：证据契约、类别覆盖、模式适配、费用可追溯和安全交付评分。
- `summary.quality_summary.tool_quality`：工具意图覆盖、禁用工具规避、同轮高成本查询重复调用、失败兜底和审计可见性评分。
- `summary.quality_summary.runtime_quality`：是否产出 `report_data`、总耗时、首 token（词元）时间、事件计数、工具调用次数、错误事件数和 token 近似成本评分。
- `summary.quality_summary.runtime_quality.budget_gate`：确定性运行预算门禁，包含 `passed`、`violations`、`warnings` 和实际采用的预算阈值。
- `summary.quality_summary.runtime_governance`：运行治理摘要，用于回答“慢在哪里、成本风险在哪里、工具是否过度调用”。
- `summary.quality_summary.aggregate`：综合分，当前权重是报告 50%、RAG 20%、工具 20%、运行指标 10%。
- 可选 `llm_judge`：显式 `--llm-judge` 时写入的 LLM-as-Judge（大模型评审）补充结果；缺密钥会记录 blocked（环境阻塞），不会影响确定性门禁。

默认运行预算是：

- 最大总耗时：900 秒。
- 最大首 token 时间：60 秒，缺失时给出警告，不直接判失败。
- 最大工具调用次数：32 次。
- 最大估算 token 数：120000。
- 最大错误事件数：0。

长对话和工具降级类场景可以在 `data/evaluation/report_quality_scenarios.json` 的 `runtime_budget` 中覆盖阈值。例如长上下文场景允许 1200 秒总耗时、45 次工具调用和 180000 估算 token。

`evaluate_report_snapshot.py` 读取旧快照时仍会输出原有报告评分；如果快照里有 `events`、`turns` 和 `assistant_text`，还会补充 Agent 运行质量摘要。需要把运行预算也作为退出码门禁时，使用：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\evaluations\sample.json --scenario agency_couple_relaxed --enforce-runtime-budget
```

需要按综合 Agent 质量门禁退出时，使用：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\evaluations\sample.json --scenario agency_couple_relaxed --enforce-agent-gate
```

## 第四阶段：Shadow / A-B 离线比较

Shadow（影子流量）/ A-B（分流实验）评估框架只比较离线验收产物，不修改线上聊天路由，也不做真实用户分流。它面向三类变更回归：

- prompt（提示词）变更。
- model profile（模型用途档位）变更，例如 `planner`、`report`、`transport`。
- tool strategy（工具策略）变更，例如是否放宽候选查询、是否启用更严格的兜底策略。

核心结构在 `app/evaluation/experiment.py`：

- `experiment_id`：一次实验的稳定标识。
- `scenario_set`：固定场景集合，包含场景集 ID、场景 ID 列表、来源文件和标签。
- `variant`（实验变体）：一次 prompt、模型或工具策略组合。
- `baseline`（基线）：作为对照的当前稳定方案。
- `candidate`（候选方案）：待验证的新方案。

当前支持两种模式：

- `shadow-only`：只观测候选方案的离线结果，不影响用户，也不改变用户可见回复。
- `offline-ab`：对固定场景集做离线分组或双跑比较，只比较验收摘要，不接入真实流量分配。

比较两次验收摘要使用：

```powershell
.\.venv\Scripts\python.exe scripts\compare_acceptance_runs.py .runtime\acceptance\baseline.json .runtime\acceptance\candidate.json --mode offline-ab --experiment-id planner-prompt-20260511 --output-json .runtime\acceptance\comparison.json --output-md .runtime\acceptance\comparison.md --fail-on-regression
```

比较器会输出：

- 通过率和平均 Agent（智能体）综合分差异。
- 失败维度与降级维度变化。
- 总耗时、工具调用次数、失败工具数、fallback（兜底）次数。
- 估算 token（文本令牌）输入、输出和总量变化。
- 按工具名聚合的调用计数变化。
- 场景级退化，例如从 passed（通过）变成 failed（失败），或综合分下降 5 分以上。

隐私和安全边界：

- 比较结果不保存完整工具输入、工具输出或 SSE（服务器发送事件）原文。
- 只保存聚合工具名、计数、耗时、分数和失败维度。
- 输出会脱敏常见密钥、手机号、邮箱、身份证和访问令牌形态文本。
- `online_traffic_split` 固定为 `false`，用于审计确认没有线上真实分流。

## 第五阶段：模型表现评估

确定性评分只能判断结构和基本业务规则。LLM-as-Judge（大模型评审）和后续人工评分重点看：

- 方案是否符合用户偏好。
- 行程是否真的顺路、不超载。
- 旅行社表达是否自然，不像硬推销。
- 风险提示是否专业、温和、可执行。
- 最终报告是否可读、可分享、可导出。

## 当前边界

- 第一版不评估真实价格准确性，只检查是否标明价格依据和待核验项。
- 第一版不判断景点路线是否地理最优，只检查路线节点和每日地图数据是否存在。
- 第一版不替代真实人工验收，而是作为每次修改后的快速质量闸门。
