# 知行评估体系设计

## 目标

评估体系先解决一个核心问题：真实对话链路跑完后，最终交付物是不是足够像一份可交付的旅游规划报告，而不只是“模型写得很长”。

第一版采用确定性规则评分，不依赖额外模型，适合作为本地调试、回归测试和 CI（持续集成）的质量基线。模块 G 已把评估对象从最终报告扩展到 Agent（智能体）运行质量：同时看 RAG（检索增强生成）证据、工具调用、运行耗时和 token（令牌）近似成本。后续可以逐步加入 LLM-as-judge（大模型评审）和人工验收数据集。

## 第一阶段：结构化报告质量评分

评分对象是 `report_data`，满分 100 分：

- 结构契约 20 分：检查 `version`、顶层字段、`overview` 和导出章节是否完整。
- 行程与地图 20 分：检查每日行程数量、每日内容、路线节点和 `map_routes` 是否可用于前端展示。
- 预算解释 20 分：检查总预算、人均预算、分类预算、费用依据、预算置信度和待核验项。
- 风险与调整 15 分：检查天气、交通、酒店、预约、Plan B 和后续调整建议。
- 旅行社业务贴合 15 分：检查内部知识库来源、自由规划 / 省心方案模式、业务亮点和知识分类。
- 前端导出准备 10 分：检查地图标签、每日路线与导出章节是否能支撑 HTML/PDF/图片导出。

默认通过线是 80 分，并且不能有任何关键维度的失败发现。

## 使用方式

对真实链路保存的 JSON 快照运行：

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

模块 G 还新增了两个专项目录：

- `data/evaluation/rag_quality_scenarios.json`：检查省心方案是否覆盖产品、SOP（标准作业流程）、报价、风险、报告标准等证据类别；自由行场景则重点看模式适配和避免硬推旅行社表达。
- `data/evaluation/tool_call_scenarios.json`：检查交通、酒店、目的地天气等工具是否按用户意图调用，是否避免同轮重复调用高成本查询工具，以及失败后是否进入待核验兜底。

列出场景：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py --list-scenarios
```

用某个场景验收真实链路快照：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_report_snapshot.py .runtime\real-agency-rag-final-report-retake3-20260509.json --scenario agency_couple_relaxed
```

如果指定 `--scenario`，脚本会自动使用该场景的期望模式和最低分；仍然可以用 `--expected-mode` 或 `--fail-under` 手动覆盖。

## 真实链路跑批

`run_evaluation_scenarios.py` 可以把场景真正发给本地后端，读取 SSE（服务器发送事件）返回的 `report_data`，保存快照并自动评分。跑批结果现在按综合 Agent（智能体）质量门禁判断通过，不再只看最终报告分。

先查看将要运行的场景，不调用后端：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --dry-run
```

运行单个场景：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000
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

- `tool_events`：从 SSE（服务器发送事件）中归一化出来的工具调用事件。
- `summary.quality_summary.report_quality`：原有结构化报告评分。
- `summary.quality_summary.rag_quality`：证据契约、类别覆盖、模式适配、费用可追溯和安全交付评分。
- `summary.quality_summary.tool_quality`：工具意图覆盖、禁用工具规避、同轮高成本查询重复调用、失败兜底和审计可见性评分。
- `summary.quality_summary.runtime_quality`：是否产出 `report_data`、总耗时、首 token（词元）时间、事件计数、工具调用次数、错误事件数和 token 近似成本评分。
- `summary.quality_summary.runtime_quality.budget_gate`：确定性运行预算门禁，包含 `passed`、`violations`、`warnings` 和实际采用的预算阈值。
- `summary.quality_summary.runtime_governance`：运行治理摘要，用于回答“慢在哪里、成本风险在哪里、工具是否过度调用”。
- `summary.quality_summary.aggregate`：综合分，当前权重是报告 50%、RAG 20%、工具 20%、运行指标 10%。

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

## 第四阶段：模型表现评估

确定性评分只能判断结构和基本业务规则。后续可以增加 LLM-as-judge（大模型评审）或人工评分，重点看：

- 方案是否符合用户偏好。
- 行程是否真的顺路、不超载。
- 旅行社表达是否自然，不像硬推销。
- 风险提示是否专业、温和、可执行。
- 最终报告是否可读、可分享、可导出。

## 当前边界

- 第一版不评估真实价格准确性，只检查是否标明价格依据和待核验项。
- 第一版不判断景点路线是否地理最优，只检查路线节点和每日地图数据是否存在。
- 第一版不替代真实人工验收，而是作为每次修改后的快速质量闸门。
