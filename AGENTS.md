# 项目协作说明

## 固定工作约定

- 涉及中文内容时，始终按 Unicode 安全方式处理；在 PowerShell 中读写中文文件时显式使用 UTF-8，例如：

  ```powershell
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  chcp 65001 | Out-Null
  Get-Content -Raw -Encoding UTF8 路径\文件名
  ```

- 英文专有名词或缩写第一次出现时，要标注中文释义。例如：SSE（服务器发送事件）、MCP（模型上下文协议）。
- 每次回复用户时，都要给出下一步想法或计划，让用户知道后续会怎么推进。
- 不要把 `.env` 中的真实密钥写进文档、测试快照或提交说明；对外只引用 `.env.example`。
- 当前仓库可能有用户或其他协作者的未提交改动。改文件前先看上下文，不要回滚自己没有产生的改动。

## 项目一句话

这是一个面向旅行规划场景的多智能体系统：后端用 FastAPI（快速应用接口框架）提供接口，主对话流程由 LangGraph（图式智能体编排框架）和 LangChain（大模型应用编排框架）驱动，通过 RAG（检索增强生成）补充本地知识，通过 MCP（模型上下文协议）接入天气、搜索、地图、火车、航班、酒店等外部能力，并把用户、会话、消息、检查点和长期记忆落到 PostgreSQL（关系型数据库）。

产品形态可以理解为：一个可持续对话、分阶段确认需求、查询真实候选、生成结构化旅行报告的“知行”旅行顾问。

## 当前主线快照

新 Agent（智能体）接手时，先以 `origin/main` 当前状态为准，不要沿用旧对话里的过期 review findings（评审发现）。截至最近一次更新：

- 主线提交：`589b1e0 Fix agency fast path and progress display`。
- 线上入口：`https://travel.403edr.cn/`，已按生产 runbook（运行手册）更新到服务器。
- 服务器目录：`/opt/langgraph-travel-planner`；生产部署唯一入口是 `docs/部署与运行/deployment-readiness.md`。
- 最近部署后验证：根页面、`/docs`、`/health/live`、`/health/ready` 均返回 200，`/health/ready` 为 `ready`，环境为 `production`。
- 最近本地回归：`uv run python -m pytest -q` 为 `569 passed, 24 deselected, 1 warning`；警告来自 `jieba/pkg_resources` 三方依赖弃用提示。
- 最近前端验证：`node --check frontend\app.js`、`node scripts\verify_frontend_report_renderer.js`、`node scripts\verify_frontend_browser_regression.js` 均通过。
- 真实敏感文件边界：`.env`、`.env.production`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/` 只应保持 ignored（忽略）状态，不要提交或写入文档。

最近几轮重点改动：

- 产品化 RAG：用户没有明确拒绝产品/跟团/省心方案时，允许按目的地、风格或人群弱匹配成熟路线样板；回复必须标注示例价、待核验、不锁价，并保留自由行选择。
- 双工作流重编排：首轮先做“省心方案 / 个性化旅游规划”分流；`free_planning` 继续使用 `current_step` 八阶段自由规划状态机，`agency_plan` 使用独立 `agency_step`，按“基础需求 -> 产品匹配 -> 方案草案 -> 用户评价/微调 -> 报告”推进。
- 快路径分流与补事实：`app/api/v1/chat.py` 会在创建完整 Travel Agent 前，用本地规则解析首句中的出发地、目的地、日期、人数和预算；需要确认模式或只补省心方案基础事实时，直接通过 SSE 返回，不加载全量 MCP 工具。
- 省心方案工具治理：省心方案默认只开放需求记录、产品模板、景点票价/风险/证据和报告相关能力；不主动调用自由规划的交通/酒店实时查询工具，除非用户明确要求查实时交通或酒店。
- 进度台与服务记录：前端右侧栏按工作流展示当前阶段、方案类型、已确认信息、长期偏好和确认边界；“已使用服务”单独折叠展示，同时给出用户可理解服务名和原始工具名。
- 慢响应兜底：聊天 SSE 增加 Agent 事件空闲超时，避免模型或上游流长时间无事件导致前端一直等待；首轮分流和省心方案基础事实补齐目标是秒级返回。
- 最终报告门禁：生成正式报告前必须至少确认出发城市、出发日期、交通、住宿、完整每日行程和预算；缺项时只给路线方向和待补信息，不能伪装成最终报告。
- 思考内容过滤：后端 SSE（服务器发送事件）和保存消息前会清理 `<think>...</think>`；前端历史渲染和流式渲染也有兜底清理。
- 前端演示修复：地图侧栏可折叠/放大，浅色文字对比度已增强，Markdown（标记文本）表格会渲染成可读表格，结构化报告不会再渲染“待补齐当天安排”占位日。
- 评估增强：acceptance-core（核心验收）仍是主证据；agent_metrics（智能体工业指标）只增强质量解释，不能替代结构化 `report_data` 证据闭环。

## 新 Agent 快速接手流程

1. 先执行：

   ```powershell
   [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
   $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
   chcp 65001 | Out-Null
   git fetch origin --prune
   git status --short --branch
   git worktree list
   ```

2. 如果要改代码，从最新 `origin/main` 建 `codex/...` 分支或工作树；不要在旧分支上继续猜。
3. 先读 `docs/README.md`，再按任务进入对应专题。面试演示看 `docs/前端与演示/demo-script.md` 和 `docs/前端与演示/project-demo-pack.md`；RAG 演示看 `docs/RAG与知识库/rag-demo-evaluation-guide.md`。
4. 改主链路时优先定位 `app/core/middleware.py`、`app/agents/handoffs/step_config.py`、`app/tools/state_transition.py`、`app/api/v1/chat.py` 和 `frontend/app.js`。
5. 提交前至少按改动范围运行对应回归；涉及前端报告或地图时，必须运行两个前端验证脚本。

## 技术栈与关键依赖

- Python 版本：`>=3.12`。
- 后端框架：`FastAPI`、`uvicorn`。
- Agent（智能体）与工作流：`langchain`、`langgraph`、`langgraph-checkpoint-postgres`。
- 大模型接入：通过 `langchain-openai` 的 OpenAI-compatible mode（OpenAI 兼容接口模式）调用 DashScope（阿里云灵积模型服务）上的 Qwen（通义千问）模型。
- 数据层：`PostgreSQL`、`pgvector`、`SQLAlchemy`、`asyncpg`、`psycopg`。
- 缓存与扩展：`Redis`。
- RAG：`Chroma` 向量库、`sentence-transformers`、`rank-bm25`、`jieba`。
- MCP：`langchain-mcp-adapters`、`fastmcp`、`aigohotel-mcp`。
- 测试：`pytest`、`pytest-asyncio`。

模型创建要统一走 `app/utils/llm_factory.py`，不要在新代码里绕过工厂直接创建零散模型实例。当前配置区分 `planner`、`router`、`rag`、`vision`、`report`、`transport` 等 profile（模型用途档位）。

## 目录地图

- `main.py`：本地开发快捷入口，内部转到 `app.run`。
- `app/run.py`：真正启动 Uvicorn（ASGI Web 服务器）的脚本，包含 Windows 事件循环兼容处理。
- `app/main.py`：FastAPI 应用对象、生命周期、路由挂载和健康检查。
- `app/api/`：HTTP API 层，包含用户、会话、聊天、地图预览。
- `app/agents/handoffs/`：主控旅行 Agent 与阶段配置。
- `app/agents/routers/`：目的地 Router（路由器），用于攻略、天气等目的地信息编排。
- `app/agents/subagents/`：交通子代理，包含航班、高铁、自驾和协调器。
- `app/core/`：状态定义、工作流元数据、中间件、检查点、长期记忆、意图识别。
- `app/tools/`：Agent 可调用工具，包含状态迁移、交通、酒店、RAG、MCP、记忆工具。
- `app/reports/`：最终报告契约、校验、结构化数据到 Markdown（标记文本）的渲染。
- `app/rag/`：文档加载、切分、检索、重排、缓存和完整 RAG 管道。
- `app/mcp_core/`：MCP 客户端管理器和本地 MCP Server。
- `app/models/`：SQLAlchemy 数据库模型。
- `app/schemas/`：Pydantic（数据校验模型）请求/响应结构。
- `app/evaluation/`：报告质量评估、场景集、真实链路跑批。
- `frontend/`：单页前端原型，包含 `zhixing.html`、`app.js`、`styles.css`。
- `scripts/`：数据库初始化、RAG 初始化、模型联调、评估脚本。
- `data/documents/`：公开目的地知识和内部旅行社业务知识。
- `data/evaluation/`：固定评估场景。
- `docs/`：项目文档，已按中文功能目录整理；入口索引是 `docs/README.md`。
  - `docs/项目总览/`：能力地图、新会话知识库和文档说明。
  - `docs/架构与流程/`：架构速览、状态机、模型切换、规划边界和会话一致性。
  - `docs/RAG与知识库/`：RAG 运行契约、向量库 readiness、召回评测和产品化演示指南。
  - `docs/评估与验收/`：acceptance-core、acceptance-smoke、真实链路 runbook 和评估体系。
  - `docs/部署与运行/`：数据库、运行环境、MCP 健康检查和线上部署。
  - `docs/前端与演示/`：面试演示脚本、演示包和前端报告体验。
  - `docs/治理与可观测/`：审批、工具治理、运行预算和观测。
  - `docs/问题记录/`：问题日志。
  - `docs/历史轮次/`：历史验收和历史方案，仅作参考。
- `deploy/`、`Dockerfile`、`docker-compose.yml`：容器化和部署配置。

## 后端启动与健康检查

本地启动后端优先使用：

```powershell
.\.venv\Scripts\python main.py
```

也可以直接运行：

```powershell
.\.venv\Scripts\python app\run.py
```

`app/main.py` 是应用对象定义文件，不适合作为“直接运行文件”的服务入口。

启动后重点检查：

- `GET /`：基础服务状态。
- `GET /docs`：FastAPI Swagger（接口文档）页面。
- `GET /health/live`：进程存活检查。
- `GET /health/ready`：依赖就绪检查。

`/health/ready` 的状态含义：

- `ready`：核心依赖和 MCP 启动检查都健康。
- `degraded`：核心依赖就绪，但部分 MCP 服务降级。
- `not_ready`：核心依赖未就绪，优先查 PostgreSQL、Store、Checkpointer。

## 核心业务流程

主流程不是简单问答，而是先做规划方式分流，再按不同工作流推进。`active_workflow` 只表示当前分支：

- `free_planning`：个性化旅游规划。继续使用 `current_step`，走既有八阶段状态机。
- `agency_plan`：省心方案。使用 `agency_step`，走独立的旅行社方案工作流，不进入自由规划的交通/住宿逐项确认阶段。

自由规划状态机定义在 `app/core/workflow.py`，阶段顺序是：

1. `requirement_collection`：需求收集。
2. `destination_recommendation`：目的地推荐。
3. `transport_planning`：交通规划。
4. `accommodation_planning`：住宿规划。
5. `food_planning`：餐饮规划。
6. `itinerary_generation`：行程生成。
7. `budget_summarization`：预算汇总。
8. `order_generation`：订单和最终报告生成。

状态结构在 `app/core/state.py` 的 `TravelState` 中，包含用户需求、目的地、交通、住宿、餐饮、行程、预算、报告、订单号、用户 ID、会话 ID 等字段。

省心方案阶段包括：

1. `agency_requirement`：确认基础事实，例如目的地、天数、人数、预算、出发地和日期。
2. `agency_product_match`：匹配成熟路线样板、景点票价、风险和服务边界。
3. `agency_plan_draft`：输出产品化方案，包含交通口径、住宿区域/档次、门票参考、餐饮、费用边界和待核验项。
4. `agency_feedback`：用户满意则进入报告，不满意则记录修改意见并再出一版。
5. `agency_report`：生成用户交付视图报告。

每个阶段对应的 prompt（提示词）、tools（工具）和 requires（前置依赖）在 `app/agents/handoffs/step_config.py` 中维护。修改阶段字段、状态迁移或新增阶段时，要同步检查：

- `app/core/workflow.py`
- `app/core/state.py`
- `app/agents/handoffs/step_config.py`
- `app/tools/state_transition.py`
- `tests/test_workflow_maintainability.py`
- `tests/test_step_prompt_rendering.py`

## Agent 主链路

`app/agents/handoffs/travel_agent.py` 创建主控 Travel Agent：

- 使用 `build_chat_model(profile="planner", streaming=True)` 创建流式规划模型。
- 通过 `create_step_config_middleware()` 挂载阶段配置中间件。
- 注册状态迁移工具、查询工具、记忆工具、内部 RAG 工具、酒店 follow-up 工具和 MCP 工具；实际可用工具会由中间件按规划模式和阶段收口。
- 使用 `get_checkpointer()` 接入 LangGraph checkpoint（执行检查点）。
- 绑定 `settings.langgraph_recursion_limit`，避免图执行递归过浅。

`app/core/middleware.py` 的 `StepConfigMiddleware` 是动态能力切换的关键：

- 根据 `current_step` 注入当前阶段 prompt 和工具列表。
- 加载用户长期记忆并拼进 prompt。
- 补齐交通、住宿、预算、行程摘要等 prompt 变量。
- 识别用户意图，如酒店查询、交通查询、最终报告、导出报告、报价、风险、旅行社省心方案、自由规划等。
- 在跨阶段核验场景临时开放交通或酒店真实查询工具。
- 对 Qwen3 系列模型做兼容：如果模型不支持强制 `tool_choice`，就改为用提示词强引导工具调用。
- 防止同一轮重复调用酒店或交通查询工具。
- 把最终报告请求挡在必要信息之后：未确认出发城市、出发日期、交通、住宿、完整每日行程或预算时，不允许进入 `generate_order_tool`。
- 控制产品化 RAG 的“软推荐”边界：用户未拒绝时可以给成熟路线样板，用户明确自由行/自己订/不要产品时应切回自由规划。
- 对省心方案应用独立工作流护栏：`active_workflow=agency_plan` 时，阶段由 `agency_step` 控制，并移除自由规划式交通/住宿偏好工具；只有用户明确要求实时查询时才临时开放相关工具。

## 聊天 API 与前端流式协议

`app/api/v1/chat.py` 提供核心聊天接口：

- `POST /api/v1/chat/stream/{conversation_id}`：SSE（服务器发送事件）流式聊天。
- `GET /api/v1/chat/history/{conversation_id}`：读取会话历史。

流式聊天会：

1. 校验会话归属。
2. 保存用户消息。
3. 先走轻量快路径：如果本轮只需要确认“省心方案 / 个性化旅游规划”，或省心方案只缺日期等基础事实，直接返回并把解析事实写入消息 `extra_info.fast_mode_split`，不创建完整 Travel Agent。
4. 快路径不能处理时，创建或复用 Travel Agent。
5. 以 `thread_id=conversation_id` 调用 Agent。
6. 把模型 token、工具调用、结构化报告数据和完成事件以 SSE 返回前端。
7. 保存助手消息；如果工具返回 `report_data`，会把它写入消息 `extra_info`，供前端报告页渲染。

完整 Agent 流有事件空闲超时保护；如果模型或上游长时间没有任何事件，后端会写入可恢复兜底回复，保留当前已确认状态，避免前端无限等待。

SSE 事件类型主要包括：

- `token`：模型流式文本。
- `tool_call`：工具开始调用。
- `report_data`：结构化旅行报告数据。
- `done`：本轮完成。
- `error`：异常。

注意：任何 `<think>...</think>` 都属于模型内部推理，不应展示给用户，也不应保存到助手消息。后端已经在流式 token 和最终助手文本两层清理，前端还有历史消息和异常流式片段的兜底清理；修改聊天链路时必须保留这条边界。

## 状态迁移工具

`app/tools/state_transition.py` 是流程推进的核心工具层。它们通常返回 `Command(update=...)`，既写入结构化状态，又切换 `current_step`。

关键工具：

- `record_requirement_tool`：记录需求并进入目的地推荐。
- `select_destination_tool`：记录目的地和目的地上下文。
- `select_transport_tool`：记录交通方式和具体交通候选。
- `select_accommodation_tool`：记录住宿类型或具体酒店。
- `select_food_tool`：记录餐饮偏好。
- `generate_itinerary_tool`：生成结构化每日行程。
- `summarize_budget_tool`：生成预算明细和预算置信度。
- `generate_order_tool`：生成最终报告、结构化 `report_data` 和订单号。
- `go_back_to_*`：回退到指定阶段并清理后续字段。
- `check_current_progress`：输出当前规划进度。

维护原则：

- 不要编造真实票价、酒店库存、支付链接或客服信息。
- 缺少真实数据时，明确写“待二次核实”或“兜底估算”。
- 最终报告要保留预算置信度、待核验项、地图路线和风险章节，方便前端导出。
- 最终报告 Markdown 必须由结构化 `report_data` 渲染，报告契约和校验逻辑维护在 `app/reports/`。

## 外部能力与工具

### 目的地

`app/agents/routers/destination_router.py` 是小型 LangGraph：先分类用户想查攻略、天气或两者，再调用 RAG / 天气工具并合成答案。目的地工具入口是 `app/tools/router_query.py` 的 `query_destination_info`。

### 交通

`app/tools/transport_query.py` 调用 `app/agents/subagents/transport_coordinator.py`。交通 Coordinator（协调器）会按需求分发给：

- 航班子代理：`flight_agent.py`
- 高铁子代理：`train_agent.py`
- 自驾子代理：`driving_agent.py`

交通查询应尽量使用已确认的出发地、目的地和日期。用户明确说“查真实方案”或指定飞机、高铁、自驾时，应优先调用 `query_transport_options`，不要继续泛泛追问。

### 酒店

`app/tools/hotel_query.py` 包装 `aigohotel-mcp`，用更稳定的高层参数搜索真实酒店候选。它会处理：

- 城市中英文别名。
- 景区、商圈、详细地址、偏好词拆分。
- 预算星级与价格上限。
- 亲子、江景、泳池、早餐、停车等偏好标签。
- 上游超时或不可用时的诚实兜底。

如果酒店 MCP 不可用，工具会提示稍后重试，不能凭经验编酒店名、价格或评分。

### MCP 客户端

`app/mcp_core/client.py` 的 `MCPClientManager` 会按服务独立创建、缓存、重试和降级，避免一个外部服务失败拖垮全部工具。

当前配置的 MCP 服务包括：

- `weather`：本地天气 MCP Server。
- `search`：本地搜索 MCP Server。
- `amap`：高德地图 MCP。
- `12306-mcp`：铁路查询 MCP。
- `VariFlight-Aviation`：航班 MCP。
- `aigohotel-mcp`：酒店 MCP，属于可选启动服务，只有配置酒店密钥时才加入。

`aigohotel-mcp` 启动较慢且可选，启动时不会阻塞核心服务。

## RAG 与知识库

公开目的地知识和内部业务知识都在 `data/documents/` 下：

- `data/documents/destinations/xian.md`：示例公开目的地知识。
- `data/documents/internal/products/`：旅行社产品与路线模板。
- `data/documents/internal/sop/`：服务 SOP（标准作业流程）。
- `data/documents/internal/pricing/`：报价与合同规则。
- `data/documents/internal/risk/`：风险和合规规则。
- `data/documents/internal/report/`：报告交付标准。

RAG 管道在 `app/rag/pipeline.py`，流程是：

1. 查询优化。
2. 混合检索。
3. 可选 LLM reranker（大模型重排器），当前默认关闭以避免小语料走慢路径。
4. 父文档上下文映射。
5. 长上下文重排。
6. 缓存。

内部 RAG 工具由 `app/tools/rag_tools.py` 暴露。用户未明确拒绝产品/跟团/省心方案时，Agent 可以按目的地、风格或人群弱匹配成熟路线样板；自由行或明确拒绝场景下，中间件会移除部分旅行社内部工具，避免硬推省心方案。路线样板只作为 `demo_catalog` 演示资料，不承诺真实库存、成团或锁价。

产品化 RAG 维护原则：

- 产品文档在 `data/documents/internal/products/`，字段应保留 `product_id`、`source_kind: demo_catalog`、`inventory_status: demo_only`、`external_product_ref: null`、适合人群、价格口径、包含/不含、每日行程骨架、交通住宿安排、待核验项和 `persona_tags`。
- 产品弱匹配不要求用户一次说全目的地、天数、预算和交通方式；目的地或风格明显相关时即可作为候选路线方向。
- 面向用户不要说 RAG、内部知识库、工具名或真实库存；只说“成熟路线样板”“合作产品候选”“省心路线方向”。
- 如果缺出发城市或出发日期，先轻量追问并说明报价和大交通待核验，不要输出正式报价、合同口径或最终报告。

## 数据层

业务表由 SQLAlchemy 模型提供：

- `User`：用户。
- `Conversation`：会话。
- `Message`：消息。

基础数据库配置在 `app/models/base.py`，使用 `postgresql+asyncpg` 异步连接。

LangGraph 还使用两类持久化：

- `app/core/checkpointer.py`：图执行 checkpoint。
- `app/core/store.py` 和 `app/core/memory_models.py`：用户长期记忆，例如旅行风格、饮食禁忌、食物偏好、去过的目的地、住宿偏好。

初始化数据库使用：

```powershell
.\.venv\Scripts\python -m scripts.init_db
```

这个脚本会创建业务表、Checkpointer 表、Store 表，并尝试启用 `pgvector`。

初始化 RAG 使用：

```powershell
.\.venv\Scripts\python -m scripts.init_rag
```

## 前端原型

前端当前是单页原型，不是工程化前端项目：

- `frontend/zhixing.html`：页面结构。
- `frontend/app.js`：登录注册、会话、SSE 聊天、报告渲染、地图预览、导出逻辑。
- `frontend/styles.css`：样式。

主要功能：

- 注册 / 登录，JWT（JSON Web Token，令牌认证）保存在 `localStorage`。
- 会话创建、切换、重命名、删除。
- 流式聊天展示。
- 结构化旅行报告卡片渲染。
- Leaflet（交互地图前端库）和 OSM（OpenStreetMap，开放街图）地图预览。
- 调用 `/api/v1/maps/preview` 生成路线点坐标。
- 报告导出为独立 HTML 文件。

地图预览 API 在 `app/api/v1/maps.py`，通过高德 MCP 的 `maps_geo` 做地理编码，并带有短期预览缓存和地理编码缓存。

前端演示体验的当前边界：

- 地图卡片应优先展示可交互地图；侧栏过大时必须可折叠，且保留放大查看入口。
- 报告中的每日行程不能凭空补“待补齐当天安排”占位卡；数据不足时显示空状态或追问。
- Markdown 表格要渲染成视觉表格，不能以管道文本大段堆在聊天气泡里。
- 关键确认问题应作为醒目的下一步卡片，而不是埋在普通正文中。
- 前端只做展示兜底，业务门禁仍以后端状态和 `report_data` 契约为准。
- 普通用户视图不展示内部过程词，例如“工作流”“Day 结构”“这轮先”等；右侧进度台只展示用户能理解的阶段、方案类型、已确认事实、长期偏好、确认边界和服务记录。
- 需求收集早期不展示低价值单项预算卡，避免用户误以为已形成完整预算；省心方案报告优先渲染结构化卡片，避免 Markdown 管道表格在流式结束后退化成原始字符。

## 评估体系

项目已经有第一版确定性报告质量评估，重点看最终 `report_data` 是否像可交付旅行报告，而不只是文本很长。

核心文件：

- `app/evaluation/report_quality.py`：100 分规则评分。
- `app/evaluation/scenarios.py`：固定评估场景加载与校验。
- `app/evaluation/live_runner.py`：真实后端链路跑批。
- `app/evaluation/agent_metrics.py`：轻量 Agent 工业指标，覆盖 intent accuracy（意图准确率）、tool call precision/recall（工具调用精确率/召回率）、stage transition accuracy（阶段迁移准确率）和 unsupported claim rate（无依据断言率）。
- `app/evaluation/acceptance_gate.py`：验收门禁汇总，报告结构和关键证据仍优先于解释性指标。
- `app/evaluation/runtime_metrics.py`：运行时预算、超时和降级分类。
- `app/evaluation/rag_retrieval.py`：RAG 小型召回评测，覆盖目的地、产品、SOP、报价、风险和报告依据。
- `data/evaluation/report_quality_scenarios.json`：场景目录。
- `data/evaluation/rag_retrieval_scenarios.json`：RAG 召回标注集，包含产品化弱匹配样例。
- `scripts/evaluate_report_snapshot.py`：评估已有快照。
- `scripts/run_evaluation_scenarios.py`：把场景发给本地后端，保存快照并评分。
- `docs/评估与验收/evaluation-system.md`：评估体系说明。
- `docs/RAG与知识库/rag-demo-evaluation-guide.md`：面试解释 RAG 评测和产品化召回的说明。

评分维度：

- 结构契约。
- 行程与地图。
- 预算解释。
- 风险与调整。
- 旅行社业务贴合。
- 前端导出准备。

常用命令：

```powershell
.\.venv\Scripts\python scripts\evaluate_report_snapshot.py --list-scenarios
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --dry-run
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --scenario agency_couple_relaxed --base-url http://127.0.0.1:8000
.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --json
```

默认评估账号是 `test / 000000`，也可以用 `ZHIXING_EVAL_USERNAME` 和 `ZHIXING_EVAL_PASSWORD` 覆盖。

## 测试分层

项目通过 `tests/conftest.py` 做测试分层：

- 默认 `pytest` 不运行带 `integration` 标记的测试。
- `--integration-only` 只收集或运行联调测试。
- `--run-integration` 运行默认层和联调层。

当前 marker（标记）包括：

- `unit`：本地快速回归。
- `integration`：真实集成或重链路。
- `llm`：需要真实 LLM。
- `mcp`：需要 MCP 服务。
- `slow`：较慢测试。

常用命令：

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest --collect-only -q
.\.venv\Scripts\python -m pytest --integration-only --collect-only -q
.\.venv\Scripts\python -m pytest --run-integration -q
```

最近一次主线默认回归结果是：

```text
569 passed, 24 deselected, 1 warning
```

测试数量会随功能增加变化；新增测试后优先以实际 `pytest -q` 和 `pytest --collect-only -q` 输出为准。README 中可能保留历史测试数量，不要用旧数量判断当前是否回归。

## 环境变量

主要环境变量见 `.env.example`。重要分组：

- LLM：`DASHSCOPE_API_KEY`、`QWEN_MODEL_NAME`、`QWEN_BASE_URL`，以及各 profile 模型名。
- LangSmith（LangChain 可观测平台）：`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`、`LANGSMITH_TRACING`、`LANGSMITH_ENDPOINT`。
- PostgreSQL：`POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`。
- Redis：`REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`、`REDIS_PASSWORD`。
- MCP / 外部服务：`AMAP_API_KEY`、`TAVILY_API_KEY`、`VARIFLIGHT_API_KEY`、`AIGOHOTEL_API_KEY`、兼容旧变量 `AIGOHOTEL_MCP_API` 和 `AIGOHOTEL_SECRET_KEY`。
- Auth（认证）：`JWT_SECRET_KEY`、`JWT_ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`。
- App（应用）：`APP_ENV`、`APP_HOST`、`APP_PORT`、`DEBUG`、`SQL_ECHO`、`LANGGRAPH_RECURSION_LIMIT`。

## Docker 与部署

`docker-compose.yml` 定义了：

- `backend`：后端服务镜像，挂载 `data` 和 `logs`。
- `postgres`：`pgvector/pgvector:pg17`。
- `redis`：`redis:7-alpine`。
- `caddy`：反向代理并托管 `frontend/` 静态文件。

部署相关文件：

- `Dockerfile`
- `deploy/Dockerfile.runtime`
- `deploy/Caddyfile`
- `deploy/update-runtime-image.sh`

线上更新只按 `docs/部署与运行/deployment-readiness.md` 执行。当前生产服务使用 `git archive` 生成发布包上传到 `8.145.46.253`，服务器端会先备份旧代码，再运行 `deploy/update-runtime-image.sh` 刷新运行时镜像和 `caddy`。不要通过手工复制 `.env`、向量库或本地 `.runtime` 来发布。

## 修改代码时的高风险点

- 改工作流阶段时，必须同步状态、阶段配置、状态迁移工具和维护性测试；涉及省心方案时还要同步 `agency_step`、工具白名单、进度台渲染和防漂移测试。
- 改聊天流式输出时，必须确认前端 `processSseBuffer`、`sendMessage` 和 `report_data` 渲染仍能消费对应事件，并且 `<think>` 内部推理不会泄漏到用户消息或历史消息。
- 改首轮分流或省心方案基础事实快路径时，必须确认不会创建完整 Agent、不会加载 MCP 工具，并且 `fast_mode_split` 中的出发地、目的地、日期、人数和预算能在下一轮继续合并到状态。
- 改最终报告结构时，必须同步 `report_quality.py` 评分契约和前端报告渲染逻辑。
- 改最终报告门禁时，必须同步 `app/core/middleware.py`、`app/agents/handoffs/step_config.py`、`tests/test_intent_detection.py` 和 `tests/test_step_prompt_rendering.py`。
- 改产品化 RAG 时，必须同步 `data/documents/internal/products/`、`data/evaluation/rag_retrieval_scenarios.json`、`docs/RAG与知识库/rag-demo-evaluation-guide.md` 和 RAG 召回评测。
- 改前端地图或报告卡片时，必须跑 `node scripts\verify_frontend_report_renderer.js` 和 `node scripts\verify_frontend_browser_regression.js`。
- 改酒店或交通查询时，必须保留“真实查询失败不编造”的原则。
- 改 MCP 启动逻辑时，必须保留服务级降级能力，避免可选服务阻塞核心启动。
- 改 Qwen 模型或 profile 时，优先更新 `.env` 和 `app/config.py`，并通过 `app/utils/llm_factory.py` 统一入口。
- 新增依赖真实网络、真实模型或真实外部 API 的测试时，要显式标记 `integration`。
- 新增本地纯逻辑测试时，不要标记 `integration`，保证默认回归仍然快。

## 推荐新人阅读顺序

1. `app/main.py`
2. `app/api/v1/chat.py`
3. `app/core/workflow.py`
4. `app/core/state.py`
5. `app/agents/handoffs/travel_agent.py`
6. `app/agents/handoffs/step_config.py`
7. `app/core/middleware.py`
8. `app/tools/state_transition.py`
9. `app/tools/hotel_query.py`
10. `app/tools/transport_query.py`
11. `app/mcp_core/client.py`
12. `app/rag/pipeline.py`
13. `frontend/app.js`
14. `frontend/styles.css`
15. `app/evaluation/report_quality.py`
16. `app/evaluation/agent_metrics.py`
17. `docs/README.md`

按这个顺序能先看懂主链路，再看懂外部能力、前端展示和质量门禁。
