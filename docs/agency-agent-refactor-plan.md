# 旅行社智能顾问 Agent 改造计划

## 1. 背景与目标

当前项目已经从“简单旅游规划 Demo（演示项目）”走到了较完整的 Agent（智能体）工程骨架：有阶段化工作流、MCP（模型上下文协议）工具接入、RAG（检索增强生成）知识库、结构化报告和评估体系。

下一阶段目标不是继续堆更多 API（应用程序接口）或供应链系统，而是把项目从“泛目的地攻略 RAG”升级为“旅行社智能顾问 Agent”：

- 用户想自由行时，系统能保持中立实用，输出路线、住宿区域、预算依据、风险提醒。
- 用户想省心方案时，系统能参考旅行社内部产品文档、服务标准、报价规则和风险手册，输出更像真实旅行社顾问交付物的方案。
- 供应链侧暂不做复杂库存、真实下单、支付、履约系统，只保留轻量规则、产品能力表达和待核验机制。
- 改造要能支撑面试文件中强调的工程深度：Agent 范式选择、工具治理、上下文工程、RAG 质量、评估闭环、生产治理、后端工程。

最终期望：这个项目不仅能演示“会规划旅行”，还要能解释“为什么这么规划、依据来自哪里、哪些价格真实可追溯、哪些是估算、什么情况下需要人工确认”。

## 2. 当前基础判断

### 2.1 已经具备的优势

- 主流程是 Workflow（工作流）+ Agent，不是单轮问答；`current_step` 控制需求、目的地、交通、住宿、餐饮、行程、预算、报告阶段。
- `StepConfigMiddleware` 已经支持按阶段动态注入 prompt（提示词）和工具。
- 已有内部知识库工具：产品模板、服务 SOP（标准作业流程）、报价规则、风险手册、报告标准。
- MCP 客户端具备服务级缓存、重试和降级能力，外部服务失败不会直接拖垮核心服务。
- 酒店查询工具有“不编造真实候选”的兜底意识。
- 最终报告已经有 `report_data` 和 `agency_context`。
- 评估体系已经能对结构化报告做 100 分确定性评分，并支持场景跑批。

### 2.2 主要短板

- 内部 RAG 当前偏“检索几段文档文本”，缺少稳定的证据结构、适用条件和引用契约。
- 旅行社方案模式与自由行模式主要靠关键词判断，还没有显式的 planning mode（规划模式）状态和用户确认机制。
- 报告生成仍集中在 `state_transition.py`，文件过大，报告逻辑、预算逻辑、业务规则耦合重。
- 工具调用有阶段约束，但缺少统一的参数校验、调用前后异常检测、失败重试与审计记录。
- 上下文管理还没有完整策略：长对话摘要、剪枝、历史关键轮次检索、token budget（令牌预算）分配都需要补。
- 评估指标偏最终报告结构，缺少 RAG 命中质量、工具调用准确率、冗余工具调用率、延迟和成本指标。
- HITL（人类在环）和敏感动作治理只有状态字段雏形，没有完整触发条件、审批超时和审计链路。

## 3. 改造原则

- 不做真实库存系统，不承诺锁价、支付、成团、余位、客服微信或供应链履约。
- 所有旅行社能力表达必须是“能力、标准、流程、报价依据、风险控制”，不能伪装成真实库存。
- 内部知识可增强方案依据，但不要把内部工具名、RAG、文档来源裸露给用户。
- 真实查询失败时，必须明确“待二次核实”或“兜底估算”，不能编造酒店、航班、价格和预约状态。
- 新增能力必须有对应评估或测试；不能只靠手工试聊。
- 多 worktree 改造时，尽量保持写文件范围互不重叠；共享契约先定再实现。

## 4. 目标业务场景

### 4.1 自由行规划

用户表达“自由行、自己订、不跟团、只要攻略”等意图时：

- 推荐路线和每日安排要中立实用。
- 不硬推旅行社服务。
- 仍保留预算依据、风险提醒、地图路线和出发前待核验项。
- 内部知识可用于报告结构和风控，但用户可见表达要像自由规划助手。

### 4.2 省心旅行社方案

用户表达“省心、旅行社方案、亲子、银发、团建、定制游、成熟路线”等意图时：

- 系统应进入 `agency_plan` 模式。
- 方案要体现成熟路线、服务节点、可替代方案、预算透明、风险避坑。
- 输出要像真实顾问交付物，不像攻略拼接。
- 报告中要有“方案依据”，但表达为服务标准、成熟路线逻辑和预算规则，不暴露内部资料。

### 4.3 报价与费用解释

用户问报价、费用包含、不包含、为什么这么估时：

- 必须区分已确认价格、工具查询价格、规则估算价格、待核验价格。
- 给出费用依据和影响价格的变量，如日期、酒店等级、交通时段、景区预约、人数和房间数。
- 支持给出降本选项，但不能承诺真实锁价。

### 4.4 工具失败兜底

交通、酒店、地图、搜索等工具失败时：

- 用户侧要得到诚实解释和可执行兜底。
- 状态里要保留失败类型，报告里要体现待核验。
- 评估场景要覆盖失败后仍能生成合格报告。

### 4.5 最终交付物

最终报告应稳定包含：

- 行程概览。
- 交通与住宿。
- 每日行程。
- 景点地图或路线节点。
- 方案依据。
- 预算明细。
- 费用依据。
- 预算置信度与待核验项。
- 天气与风险提醒。
- 后续可调整项。

## 5. 总体架构目标

```text
用户消息
  |
  v
意图识别与模式判断
  - free_planning
  - agency_plan
  - pricing/risk/report/export 等横向意图
  |
  v
阶段化 Travel Agent
  - 需求收集
  - 目的地推荐
  - 交通规划
  - 住宿规划
  - 餐饮规划
  - 行程生成
  - 预算汇总
  - 报告生成
  |
  +-- 公开目的地 RAG
  +-- 旅行社内部 RAG
  +-- MCP 真实查询工具
  +-- 轻量产品规则与报价规则
  +-- 用户长期记忆
  |
  v
Evidence Bundle（证据包）
  - 使用了哪些知识类别
  - 哪些是工具真实返回
  - 哪些是规则估算
  - 哪些需要二次核验
  |
  v
结构化报告 report_data
  |
  v
前端渲染 / 导出 / 评估 / 审计
```

## 6. 模块改造计划

### 模块 A：知识库与 RAG 契约

负责人建议：RAG worktree。

目标：

- 把公开攻略库和旅行社内部知识库从“文本检索工具”升级为“带元数据、适用条件和证据类型的知识服务”。
- 让 Agent 能知道检索内容属于产品、SOP、报价、风险还是报告标准。
- 为后续评估提供可检查的 evidence（证据）结构。

建议改造文件：

- `app/rag/document_loader.py`
- `app/rag/pipeline.py`
- `app/rag/retriever.py`
- `app/tools/rag_tools.py`
- 新增 `app/rag/contracts.py`
- 新增 `app/rag/agency_retrieval.py`
- `data/documents/internal/**/*.md`
- 新增或扩展 `tests/test_internal_rag_businessization.py`

建议新增数据结构：

```python
class RetrievedEvidence(TypedDict):
    source: str
    source_type: str
    category: str
    visibility: str
    title: str
    snippet: str
    relevance_score: float
    evidence_level: str
    applicable_modes: list[str]
    constraints: list[str]
```

内部文档元数据建议增加：

- `category`：`products`、`sop`、`pricing`、`risk`、`report`。
- `applicable_modes`：`agency_plan`、`free_planning`。
- `user_segments`：情侣、亲子、银发、团建、自由行。
- `budget_levels`：经济、舒适、豪华。
- `travel_days_range`：适合天数。
- `regions`：适用目的地或区域。
- `evidence_level`：标准、规则、示例、注意事项。
- `last_reviewed`：文档维护时间。

验收标准：

- 内部 RAG 工具返回内容可带结构化证据，不只是拼接文本。
- 自由行模式不会误用强旅行社销售表达。
- 省心方案模式至少能检索产品、SOP、报价、风险、报告标准中的 3 类证据。
- 公开攻略 RAG 继续保留目的地匹配保护，避免拿其他城市内容回答当前城市。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_internal_rag_businessization.py -q
.\.venv\Scripts\python -m pytest tests/test_rag_agent_autonomous.py -q
```

### 模块 B：规划模式与意图路由

负责人建议：Intent / Workflow worktree。

目标：

- 把“自由行”和“旅行社省心方案”从隐式关键词判断升级为显式模式。
- 在用户表达模糊时，允许系统用一句话确认模式，而不是过早默认。
- 让 pricing（报价）、risk（风险）、final_report（最终报告）等横向意图能跨阶段触发正确工具。

建议改造文件：

- `app/core/intent.py`
- `app/core/state.py`
- `app/core/workflow.py`
- `app/core/middleware.py`
- `app/agents/handoffs/step_config.py`
- `app/tools/state_transition.py`
- `tests/test_intent_detection.py`
- `tests/test_step_prompt_rendering.py`

建议新增状态字段：

```python
planning_mode: NotRequired[Literal["free_planning", "agency_plan"]]
planning_mode_reason: NotRequired[str]
planning_mode_confirmed: NotRequired[bool]
evidence_bundle: NotRequired[dict]
tool_audit_events: NotRequired[list[dict]]
```

建议新增工具：

- `set_planning_mode_tool`
- `confirm_planning_mode_tool`
- `record_evidence_bundle_tool`

验收标准：

- 用户明确“自由行/自己订/不跟团”时，进入 `free_planning`。
- 用户明确“省心/旅行社方案/亲子/银发/团建/成熟路线”时，进入 `agency_plan`。
- 模式写入状态后，最终 `report_data.agency_context.mode` 不再只依赖最后 8 条消息推断。
- 价格、风险、报告、导出意图可以在任意阶段被识别并注入正确指令。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_intent_detection.py tests/test_step_prompt_rendering.py -q
```

### 模块 C：旅行社轻量产品与报价规则

负责人建议：Agency Rules worktree。

目标：

- 不做真实供应链，但建立轻量产品能力表达和报价规则。
- 让报告中的“方案依据”和“费用依据”更像真实旅行社顾问输出。
- 把“成熟路线”“服务节点”“报价置信度”“待核验项”变成可复用规则，而不是散落在 prompt 中。

建议新增目录：

- `app/agency/`

建议新增文件：

- `app/agency/__init__.py`
- `app/agency/models.py`
- `app/agency/planning_mode.py`
- `app/agency/product_rules.py`
- `app/agency/pricing_rules.py`
- `app/agency/risk_rules.py`
- `app/agency/evidence.py`

建议迁移或引用逻辑：

- 从 `state_transition.py` 中抽出 `_build_agency_context`。
- 从预算相关函数中抽出置信度规则和待核验项规则。
- 从报告生成中抽出“旅行社模式”和“自由规划模式”的表达差异。

轻量产品能力可以包含：

- 适合人群：情侣、亲子、银发、团建、自由行。
- 产品形态：自由规划、顾问定制、省心方案。
- 服务节点：需求确认、路线初稿、交通酒店核验、预算说明、出发前提醒。
- 交付标准：报告结构、地图路线、预算置信度、风险清单。
- 不承诺项：真实库存、锁价、支付、强制跟团。

报价规则可以包含：

- 交通：真实工具价优先；缺失时按交通类型基准估算。
- 住宿：真实酒店价优先；缺失时按预算等级、晚数、房间数估算。
- 餐饮：按餐饮类型、人均、天数估算。
- 景区体验：按已知 POI 或目的地兜底估算。
- 机动费：按人天估算。
- 置信度：已确认、可追溯、估算、兜底估算、待核验。

验收标准：

- 最终报告的费用依据能明确区分真实价、估算价、待核验价。
- `agency_plan` 报告比 `free_planning` 报告更强调服务节点、成熟路线和风险预案。
- 不出现真实支付、库存、余位、客服等无法支持的承诺。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_workflow_maintainability.py tests/test_report_quality_evaluation.py -q
```

### 模块 D：报告生成与结构化交付

负责人建议：Report worktree。

目标：

- 将最终报告生成从 `state_transition.py` 中拆出，形成可测试、可审计、可前端消费的报告模块。
- 让 `report_data` 成为稳定契约，而不是工具函数内部临时拼装结果。
- 支持自由行和旅行社省心方案两套语气和章节重点，但保持同一结构契约。

当前落地状态：

- 已新增 `app/reports/` 契约、校验、Markdown（标记文本）渲染和 bundle（交付包）构建入口。
- `generate_order_tool` 生成最终报告时先构造 `report_data`，再由报告模块校验并渲染 Markdown。
- `report_data` 已包含 `evidence_bundle` 和 `tool_audit_summary`，用于承载证据、待核验项和不支持承诺。
- 前端已优先消费结构化 `report_data.tool_audit_summary` 展示顾问交付清单。
- `_format_report_*`、`_format_budget_*` 等低层格式化函数仍在 `state_transition.py`，后续可继续细拆。

建议新增文件：

- `app/reports/__init__.py`
- `app/reports/contracts.py`
- `app/reports/builder.py`
- `app/reports/render_markdown.py`
- `app/reports/validators.py`

建议迁移函数：

- `_build_report_data`
- `_build_final_report`
- `_format_report_*`
- `_format_budget_*`
- `_format_adjustment_options`
- `_format_agency_context_lines`

报告契约建议：

- `version`
- `overview`
- `transport`
- `accommodation`
- `food_preferences`
- `itinerary`
- `map_routes`
- `agency_context`
- `budget`
- `budget_confidence`
- `risks`
- `adjustment_options`
- `evidence_bundle`
- `tool_audit_summary`
- `sections`

验收标准：

- 报告 Markdown（标记文本）和 `report_data` 来源一致。
- 前端不需要从自然语言里猜结构，优先使用 `report_data`。
- 每日路线数等于行程天数。
- 地图路线和每日行程 route summary 保持一致。
- 报告生成工具失败时能返回缺失字段清单，不生成伪最终报告。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_chat_report_metadata.py tests/test_report_quality_evaluation.py -q
.\.venv\Scripts\python -m pytest tests/test_workflow_maintainability.py -q
```

### 模块 E：工具调用治理与审计

负责人建议：Tool Governance worktree。

目标：

- 回应“工具调用不是能调通就行”的工程要求。
- 建立工具调用前参数校验、工具调用后结果校验、异常分类、重试/降级和审计事件。
- 为评估冗余工具调用、失败率和成本打基础。

建议新增文件：

- `app/tools/contracts.py`
- `app/tools/guardrails.py`
- `app/tools/audit.py`
- `app/tools/result_validation.py`

建议改造文件：

- `app/api/v1/chat.py`
- `app/core/middleware.py`
- `app/tools/hotel_query.py`
- `app/tools/transport_query.py`
- `app/tools/mcp_tools.py`
- `app/tools/state_transition.py`

工具审计事件建议字段：

```python
class ToolAuditEvent(TypedDict):
    name: str
    started_at: float
    elapsed_seconds: float
    status: Literal["success", "failed", "timeout", "degraded", "skipped"]
    input_summary: dict
    output_summary: dict
    error_type: str | None
    retry_count: int
    evidence_type: str
```

治理策略：

- 调用前：检查工具是否在当前阶段白名单或跨阶段临时开放清单中。
- 参数前：验证必填字段、日期格式、枚举、占位符。
- 调用中：设置超时和重试次数。
- 调用后：检查输出是否为空、是否包含错误、是否可结构化提取。
- 失败时：写入待核验项，不编造结果。

验收标准：

- 每次真实查询工具调用都有审计事件。
- 酒店/交通工具失败能进入报告待核验项。
- 不存在工具名不在列表却被执行的情况。
- 重复调用同一工具能被识别并降低概率。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_hotel_query_tool.py tests/test_transport_query_tool.py tests/test_system_resilience.py -q
```

### 模块 F：上下文工程与长期记忆

负责人建议：Context worktree。

目标：

- 解决长对话下 prompt 过长、历史噪声、用户偏好复用和成本控制问题。
- 区分短期会话状态、长期用户画像、RAG 检索上下文和工具证据。

建议新增文件：

- `app/core/context_budget.py`
- `app/core/conversation_summary.py`
- `app/core/context_pack.py`

建议改造文件：

- `app/core/middleware.py`
- `app/core/store.py`
- `app/core/memory_models.py`
- `app/tools/memory_tools.py`

上下文分层：

- 短期状态：`TravelState` 当前规划字段。
- 最近消息：保留最近 4-8 轮。
- 长期记忆：用户偏好、禁忌、历史目的地。
- 证据包：本轮使用的 RAG 和工具结果。
- 摘要：超过阈值后生成阶段摘要。

触发策略：

- 消息数超过阈值或 token 估算超过阈值时触发摘要。
- 进入新阶段时压缩上一阶段对话为摘要。
- 最终报告阶段只注入结构化状态、关键偏好和证据包，不注入全部聊天历史。

验收标准：

- prompt 注入内容可解释：当前阶段、必要状态、记忆、证据。
- 长对话不会无限增长。
- 用户明确偏好能进入长期记忆，但临时上下文不会污染长期记忆。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_step_prompt_rendering.py tests/test_workflow_maintainability.py -q
```

### 模块 G：评估体系升级

负责人建议：Evaluation worktree。

目标：

- 从“报告结构评分”扩展到“Agent 运行质量评分”。
- 覆盖 RAG 证据质量、工具调用质量、成本和延迟。
- 建立可用于 CI（持续集成）和回归的场景集。

建议新增文件：

- `app/evaluation/rag_quality.py`
- `app/evaluation/tool_quality.py`
- `app/evaluation/runtime_metrics.py`
- `data/evaluation/rag_quality_scenarios.json`
- `data/evaluation/tool_call_scenarios.json`

建议扩展文件：

- `app/evaluation/report_quality.py`
- `app/evaluation/live_runner.py`
- `scripts/evaluate_report_snapshot.py`
- `scripts/run_evaluation_scenarios.py`
- `docs/evaluation-system.md`

新增指标：

- 任务成功率：是否产出合格 `report_data`。
- RAG 类别覆盖：省心方案是否命中产品、SOP、报价、风险。
- 证据精度：证据是否与用户模式和场景匹配。
- 工具调用准确率：该调用的工具是否符合用户意图。
- 冗余工具调用率：同一轮是否重复查酒店/交通。
- 失败兜底质量：工具失败后是否产生待核验项。
- 延迟：首 token 时间、总耗时、工具耗时。
- 成本：估算 token 使用量，先可用近似统计。

验收标准：

- 至少新增 10 个场景，覆盖自由行、省心方案、报价、风险、工具失败、长对话。
- 每个 live snapshot（真实链路快照）包含工具事件、报告数据和评分摘要。
- `agency_plan` 场景必须检查内部证据类别覆盖。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_evaluation_scenarios.py tests/test_evaluation_live_runner.py tests/test_report_quality_evaluation.py -q
```

### 模块 H：前端报告体验与导出

负责人建议：Frontend worktree。

目标：

- 前端优先渲染结构化 `report_data`，减少从自然语言解析报告的脆弱逻辑。
- 让用户能看懂哪些是已确认、哪些待核验、哪些是旅行社服务依据。
- 自由行和旅行社方案在视觉和文案上有轻微区分，但不做营销落地页。

建议改造文件：

- `frontend/app.js`
- `frontend/styles.css`
- `frontend/zhixing.html`

前端新增或强化展示：

- 规划模式标签：自由规划 / 旅行社顾问方案。
- 预算置信度卡片。
- 待核验清单。
- 方案依据卡片。
- 工具失败提醒。
- 地图路线与每日行程联动。
- 导出报告时保留结构化章节。

验收标准：

- `report_data` 存在时，不依赖正文正则解析来构建核心报告结构。
- 导出的 HTML 报告包含预算置信度和待核验项。
- 移动端和桌面端报告不出现文字溢出或控件重叠。

验证建议：

- 启动后端后用真实评估场景跑出报告。
- 用浏览器检查聊天、报告、地图、导出。
- 前端改动后建议做截图回归。

### 模块 I：HITL 与治理轻量版

负责人建议：Governance worktree。

目标：

- 不接真实供应链，但先建立敏感动作和人工确认机制。
- 为未来接真实下单、短信、支付、客户资料导出打基础。

建议新增文件：

- `app/core/approval.py`
- `app/core/permissions.py`
- `app/schemas/approval.py`
- `app/api/v1/approvals.py`

建议改造文件：

- `app/core/state.py`
- `app/main.py`
- `app/tools/state_transition.py`

轻量 HITL 范围：

- 当前不做后台审批 UI，只实现状态和 API 契约。
- 高风险动作先包括：生成订单号、导出最终报告、未来支付/短信占位。
- 对当前项目，“生成订单号”不阻塞，但报告必须明确无真实支付。
- 若未来接入真实支付或下单，必须强制审批。

状态建议：

```python
approval_pending: bool
approval_reason: str
approval_action: str
approval_expires_at: float | None
approval_status: Literal["none", "pending", "approved", "rejected", "expired"]
```

验收标准：

- 敏感动作可以被标记、记录、查询。
- 审批超时后动作自动失效。
- 报告不会因为审批未完成而伪造已支付或已预订状态。

测试建议：

```powershell
.\.venv\Scripts\python -m pytest tests/test_system_resilience.py tests/test_workflow_maintainability.py -q
```

## 7. Git worktree 分工建议

为了减少合并冲突，建议按写文件范围拆分。每个 worktree 都要从同一基线分支创建，合并前先跑对应测试。

| Worktree | 建议分支 | 主要写入范围 | 交付物 | 依赖 |
|---|---|---|---|---|
| RAG | `codex/agency-rag-contract` | `app/rag/`、`app/tools/rag_tools.py`、`data/documents/internal/`、RAG 测试 | 结构化证据、内部知识元数据、RAG 质量测试 | 无，优先做 |
| Intent | `codex/agency-intent-workflow` | `app/core/intent.py`、`app/core/middleware.py`、`app/core/state.py`、`step_config.py` | 显式规划模式、跨阶段意图路由 | RAG 契约草案 |
| Rules | `codex/agency-rules` | 新增 `app/agency/`、预算/风险规则测试 | 产品能力、报价规则、风险规则 | RAG 元数据 |
| Report | `codex/agency-report-contract` | 新增 `app/reports/`、改 `state_transition.py` 抽离报告逻辑 | 稳定 `report_data` 契约、Markdown 渲染 | Rules 契约 |
| Tool Governance | `codex/agency-tool-audit` | `app/tools/contracts.py`、`guardrails.py`、各查询工具 | 工具审计事件、参数校验、失败分类 | Intent 契约 |
| Context | `codex/agency-context` | `app/core/context_*`、记忆和中间件 | 摘要、剪枝、上下文预算 | Intent 契约 |
| Evaluation | `codex/agency-evaluation` | `app/evaluation/`、`data/evaluation/`、`scripts/` | 新指标、新场景、快照结构 | Report / Tool 契约 |
| Frontend | `codex/agency-report-frontend` | `frontend/` | 结构化报告渲染、待核验展示、导出 | Report 契约 |
| Governance | `codex/agency-hitl-lite` | `app/core/approval.py`、`permissions.py`、审批 API | 轻量审批状态与 API | Report / Tool 契约 |
| Integration | `codex/agency-integration-audit` | 只做冲突解决、文档、少量契约修复 | 全量集成、代码审计、回归结果 | 所有模块 |

合并顺序建议：

1. RAG。
2. Intent。
3. Rules。
4. Report。
5. Tool Governance。
6. Context。
7. Evaluation。
8. Frontend。
9. Governance。
10. Integration。

## 8. 代码审计方案

### 8.1 每个模块合并前自审

每个 worktree 合并前必须附带：

- 改动范围说明。
- 设计取舍说明。
- 新增或更新的测试列表。
- 未解决风险。
- 与其他模块的契约变更。

自审清单：

- 是否引入真实密钥、真实个人信息或不可公开数据。
- 是否出现无法支持的承诺，如锁价、支付、余位、客服。
- 是否在工具失败时编造事实。
- 是否破坏默认 `pytest -q` 的本地回归分层。
- 是否新增外部服务依赖但未标记 `integration`。
- 是否让 prompt 过长且没有上下文预算控制。
- 是否新增用户可见英文缩写但未解释中文含义。

### 8.2 集成前架构审计

重点检查：

- `TravelState` 字段是否和报告、工具、评估一致。
- `planning_mode` 是否只有一个可信来源，避免多个模块重复推断。
- `evidence_bundle` 是否能被报告、评估、前端复用。
- 工具审计事件是否能贯穿 API、工具和快照。
- RAG 工具是否按模式和类别正确开放。
- 报告契约是否和前端渲染、评估规则一致。

### 8.3 RAG 质量审计

抽样检查：

- 省心方案是否命中内部产品和服务标准，而不是只查公开攻略。
- 报价问题是否命中 pricing 文档。
- 风险问题是否命中 risk 文档。
- 自由行场景是否避免旅行社硬推销。
- 未覆盖目的地时是否明确使用搜索或通用建议，不混用其他城市资料。

建议指标：

- 类别召回率。
- 证据适配率。
- 错误城市污染率。
- 内部资料暴露率。

### 8.4 工具调用审计

抽样检查：

- 酒店查询失败是否进入待核验项。
- 交通查询是否使用已确认出发地、目的地、日期。
- 同一轮是否重复调用同一高成本工具。
- 跨阶段临时开放工具是否有明确用户意图。
- 工具返回的真实价格是否被正确标记为可追溯。

### 8.5 报告交付审计

抽样检查：

- 报告天数是否等于用户需求天数。
- 每天是否有路线节点、Plan B 和风险提醒。
- 预算是否有总额、人均、分类、依据、置信度、待核验项。
- 旅行社模式是否体现服务标准，但不承诺真实履约。
- 自由行模式是否保持中立实用。

### 8.6 安全与治理审计

重点检查：

- 真实支付和下单仍未接入时，报告必须明确说明。
- 敏感动作是否有权限标签。
- 审批状态是否可查询、可过期。
- 日志和快照是否避免泄露密钥。

## 9. 测试与验证矩阵

### 9.1 本地默认回归

```powershell
.\.venv\Scripts\python -m compileall app tests
.\.venv\Scripts\python -m pytest -q
```

### 9.2 分层收集

```powershell
.\.venv\Scripts\python -m pytest --collect-only -q
.\.venv\Scripts\python -m pytest --integration-only --collect-only -q
.\.venv\Scripts\python -m pytest --run-integration --collect-only -q
```

### 9.3 重点模块测试

```powershell
.\.venv\Scripts\python -m pytest tests/test_intent_detection.py -q
.\.venv\Scripts\python -m pytest tests/test_internal_rag_businessization.py -q
.\.venv\Scripts\python -m pytest tests/test_report_quality_evaluation.py -q
.\.venv\Scripts\python -m pytest tests/test_evaluation_scenarios.py tests/test_evaluation_live_runner.py -q
.\.venv\Scripts\python -m pytest tests/test_hotel_query_tool.py tests/test_transport_query_tool.py -q
```

### 9.4 真实链路评估

先启动后端：

```powershell
.\.venv\Scripts\python main.py
```

再跑场景：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario free_city_three_days --base-url http://127.0.0.1:8000
```

### 9.5 前端验证

- 登录注册。
- 创建会话。
- 跑自由行场景。
- 跑旅行社省心方案场景。
- 查看报告卡片。
- 查看地图路线。
- 导出报告。
- 移动端宽度检查。

## 10. 阶段里程碑

### 里程碑 0：基线冻结

目标：

- 记录当前 `pytest --collect-only -q` 输出。
- 记录当前默认回归结果。
- 跑 1 个自由行和 1 个旅行社场景，保存快照。

产物：

- `.runtime/evaluations/` 快照。
- 当前质量分数。
- 当前工具调用表现。

### 里程碑 1：模式和知识契约打通

目标：

- 显式 `planning_mode`。
- 内部 RAG 返回结构化证据。
- 省心方案能稳定触发内部知识。

验收：

- `agency_plan` 场景报告 `agency_context.mode == "agency_plan"`。
- `free_planning` 场景报告 `agency_context.mode == "free_planning"`。
- 省心方案证据类别至少覆盖 3 类。

### 里程碑 2：报告和规则模块化

目标：

- 报告生成迁出 `state_transition.py`。
- 报价、风险、产品规则独立。
- `report_data` 契约稳定。

验收：

- 报告评分保持或超过当前分数。
- 前端报告渲染不回退。
- 报告中无无法支持承诺。

### 里程碑 3：工具治理和上下文工程

目标：

- 工具审计事件可用。
- 工具失败进入待核验。
- 长对话摘要和上下文预算初版可用。

验收：

- live snapshot 中能看到工具事件。
- 工具失败场景报告仍通过最低分。
- 长对话场景不会无限注入历史消息。

### 里程碑 4：评估闭环和集成审计

目标：

- 新增 Agent 运行质量指标。
- 场景集覆盖主要业务路径。
- 完成代码审计和回归。

验收：

- 默认本地回归通过。
- 至少 8 个核心场景通过质量门禁。
- 审计文档记录剩余风险。

## 11. Definition of Done（完成定义）

一次完整改造完成应满足：

- 用户可明确选择或被识别为自由行 / 旅行社省心方案。
- 内部知识库能按产品、SOP、报价、风险、报告标准提供结构化证据。
- 最终报告能区分方案依据、费用依据、预算置信度和待核验项。
- 真实工具失败时不编造结果，并能在报告和审计中体现。
- 前端能基于 `report_data` 渲染和导出报告。
- 评估体系能判断报告质量、RAG 证据覆盖和工具调用质量。
- 默认测试、模块测试、核心 live 场景通过。
- 已完成模块自审和集成代码审计。

## 12. 暂不做事项

- 不做真实供应链库存。
- 不做真实支付。
- 不做真实订单履约。
- 不做复杂 CRM（客户关系管理）系统。
- 不做完整人工客服后台。
- 不引入 GraphRAG（图检索增强生成）作为第一阶段必选项；除非后续内部知识明显需要实体关系维护。
- 不做多节点分布式锁第一版实现；先通过会话级串行和审计识别并发风险。

## 13. 优先级建议

最高优先级：

1. 显式规划模式。
2. 内部 RAG 证据契约。
3. 报告契约模块化。
4. 评估场景扩展。

第二优先级：

1. 工具审计事件。
2. 工具失败待核验闭环。
3. 前端结构化报告渲染。
4. 上下文摘要与预算。

第三优先级：

1. HITL 轻量审批。
2. 延迟和成本指标。
3. 更细的并发一致性机制。
4. 更复杂的知识图谱或供应链能力。

这个顺序的原因是：先把“旅行社智能顾问”的业务身份、知识依据和交付物契约立住，再补运行治理和生产化能力；否则容易变成又一轮功能堆叠。
