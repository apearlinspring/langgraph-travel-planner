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
- `app/rag/`：文档加载、切分、检索、重排、缓存和完整 RAG 管道。
- `app/mcp_core/`：MCP 客户端管理器和本地 MCP Server。
- `app/models/`：SQLAlchemy 数据库模型。
- `app/schemas/`：Pydantic（数据校验模型）请求/响应结构。
- `app/evaluation/`：报告质量评估、场景集、真实链路跑批。
- `frontend/`：单页前端原型，包含 `zhixing.html`、`app.js`、`styles.css`。
- `scripts/`：数据库初始化、RAG 初始化、模型联调、评估脚本。
- `data/documents/`：公开目的地知识和内部旅行社业务知识。
- `data/evaluation/`：固定评估场景。
- `docs/`：架构、问题日志、模型切换、评估体系等项目文档。
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

主流程是分阶段旅行规划状态机，不是简单问答。工作流定义在 `app/core/workflow.py`，阶段顺序是：

1. `requirement_collection`：需求收集。
2. `destination_recommendation`：目的地推荐。
3. `transport_planning`：交通规划。
4. `accommodation_planning`：住宿规划。
5. `food_planning`：餐饮规划。
6. `itinerary_generation`：行程生成。
7. `budget_summarization`：预算汇总。
8. `order_generation`：订单和最终报告生成。

状态结构在 `app/core/state.py` 的 `TravelState` 中，包含用户需求、目的地、交通、住宿、餐饮、行程、预算、报告、订单号、用户 ID、会话 ID 等字段。

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
- 注册状态迁移工具、查询工具、记忆工具、内部 RAG 工具、酒店 follow-up 工具和所有 MCP 工具。
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

## 聊天 API 与前端流式协议

`app/api/v1/chat.py` 提供核心聊天接口：

- `POST /api/v1/chat/stream/{conversation_id}`：SSE（服务器发送事件）流式聊天。
- `GET /api/v1/chat/history/{conversation_id}`：读取会话历史。

流式聊天会：

1. 校验会话归属。
2. 保存用户消息。
3. 创建或复用 Travel Agent。
4. 以 `thread_id=conversation_id` 调用 Agent。
5. 把模型 token、工具调用、结构化报告数据和完成事件以 SSE 返回前端。
6. 保存助手消息；如果工具返回 `report_data`，会把它写入消息 `extra_info`，供前端报告页渲染。

SSE 事件类型主要包括：

- `token`：模型流式文本。
- `tool_call`：工具开始调用。
- `report_data`：结构化旅行报告数据。
- `done`：本轮完成。
- `error`：异常。

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

内部 RAG 工具由 `app/tools/rag_tools.py` 暴露。自由行场景下，中间件会移除部分旅行社内部工具，避免硬推省心方案。

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

## 评估体系

项目已经有第一版确定性报告质量评估，重点看最终 `report_data` 是否像可交付旅行报告，而不只是文本很长。

核心文件：

- `app/evaluation/report_quality.py`：100 分规则评分。
- `app/evaluation/scenarios.py`：固定评估场景加载与校验。
- `app/evaluation/live_runner.py`：真实后端链路跑批。
- `data/evaluation/report_quality_scenarios.json`：场景目录。
- `scripts/evaluate_report_snapshot.py`：评估已有快照。
- `scripts/run_evaluation_scenarios.py`：把场景发给本地后端，保存快照并评分。
- `docs/evaluation-system.md`：评估体系说明。

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
.\.venv\Scripts\python -m compileall app tests
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest --collect-only -q
.\.venv\Scripts\python -m pytest --integration-only --collect-only -q
.\.venv\Scripts\python -m pytest --run-integration -q
```

本文件生成时，`pytest --collect-only -q` 的实际结果是：

```text
134/158 tests collected (24 deselected)
```

README 中可能保留历史测试数量；新增测试后优先以实际 `pytest --collect-only -q` 输出为准。

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

## 修改代码时的高风险点

- 改工作流阶段时，必须同步状态、阶段配置、状态迁移工具和维护性测试。
- 改聊天流式输出时，必须确认前端 `processSseBuffer`、`sendMessage` 和 `report_data` 渲染仍能消费对应事件。
- 改最终报告结构时，必须同步 `report_quality.py` 评分契约和前端报告渲染逻辑。
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
14. `app/evaluation/report_quality.py`

按这个顺序能先看懂主链路，再看懂外部能力、前端展示和质量门禁。
