# 第一阶段总体验收报告

## 结论

本阶段已建立可重复运行、可审计的总体验收质量门禁。门禁不改核心 Agent（智能体）业务逻辑，只聚合真实链路快照中的结构化报告、RAG（检索增强生成）证据、工具调用事件和运行时指标，把“是否达成阶段目标”转成确定性评分和失败维度。

核心验收命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation_scenarios.py --acceptance-core --base-url http://127.0.0.1:8000
```

该命令会运行 `acceptance-core` 标记的 9 个核心场景，并生成 JSON（JavaScript 对象表示法）和 Markdown（标记文本）两种摘要。摘要默认写入 `.runtime/evaluations/`。

## 验收范围

核心场景覆盖：

- 自由行近郊两日。
- 自由行城市三日。
- 旅行社省心情侣方案。
- 旅行社亲子方案。
- 旅行社银发低压力方案。
- 酒店工具失败兜底。
- 旅行社报价解释。
- 天气和 Plan B 风险。
- 交通工具失败兜底。

每个场景都会输出：

- 报告质量评分。
- RAG（检索增强生成）质量评分。
- 工具治理质量评分。
- 运行时指标评分。
- 预算置信度契约检查。
- 旅行社内部证据引用检查。
- 工具审计表面检查。

## 门禁阈值

当前默认阈值：

- 综合 Agent（智能体）分：不低于场景最低分，且全局最低 82 分。
- 报告质量：不低于 80 分。
- RAG（检索增强生成）质量：不低于 80 分。
- 工具治理质量：不低于 80 分。
- 运行时质量：不低于 80 分。
- 运行预算：必须通过。
- 预算置信度：必须有等级、已确认或估算项、待核验项。
- 旅行社省心方案：至少 3 类内部证据。
- 工具审计：必须有使用来源、待核验项和不支持承诺。

## 失败输出

失败摘要会明确指出：

- 失败场景。
- 失败维度。
- 实际分数和阈值。
- 关键失败发现。
- 建议排查方向。

常见排查方向：

- 报告失败：检查 `report_data` 顶层字段、每日行程、地图路线、预算明细和风险章节。
- RAG（检索增强生成）失败：检查 `agency_context.evidence` 和 `evidence_bundle` 的类别覆盖。
- 工具失败：检查 SSE（服务器发送事件）里的 `tool_call`、重复高成本工具调用和待核验兜底。
- 运行时失败：检查首 token（令牌）时间、总耗时、工具调用次数、错误事件和估算 token（令牌）数量。
- 预算置信度失败：检查 `budget_confidence` 是否区分已确认、估算和待核验。

## 当前验证记录

已完成轻量验证：

```powershell
uv run --frozen pytest tests\test_evaluation_scenarios.py tests\test_evaluation_live_runner.py tests\test_report_quality_evaluation.py tests\test_rag_quality_evaluation.py tests\test_tool_quality_evaluation.py tests\test_runtime_metrics.py -q
```

结果：`50 passed`。

已完成验收核心场景空跑：

```powershell
uv run --frozen python scripts\run_evaluation_scenarios.py --acceptance-core --dry-run
```

结果：列出 9 个核心验收场景和每个场景的阶段推进消息。

真实后端、真实模型和真实外部 API（应用程序接口）验收未在本文件生成时运行；需要先启动本地后端并准备评估账号后再执行核心验收命令。

## 后续使用建议

每次合并影响报告、RAG（检索增强生成）、工具治理或运行时行为的改动前，至少运行一次 `--acceptance-core`。如果失败，优先查看 Markdown（标记文本）摘要中的失败维度，再打开对应 JSON（JavaScript 对象表示法）快照复盘原始事件。
