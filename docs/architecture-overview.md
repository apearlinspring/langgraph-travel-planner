# LangGraph Travel Planner 架构速览

## 1. 项目一句话说明

这是一个面向“旅行规划”场景的多智能体后端系统：

- 后端接口用 `FastAPI`
- 对话主控用 `LangChain / LangGraph`
- 知识检索用 `RAG + Chroma`
- 外部能力通过 `MCP` 接入
- 业务数据和用户体系落在 `PostgreSQL`
- 前端目前是一个单文件原型页 `frontend/zhixing.html`

如果把它看成一个产品，可以理解为：

“一个会和用户持续对话、分阶段做决策、能查攻略/天气/交通/酒店，并逐步生成出行方案的 AI 旅行顾问系统。”

## 2. 整体架构图

```text
前端页面 / 第三方客户端
        |
        v
FastAPI API 层
  - 用户注册登录
  - 会话管理
  - SSE 流式聊天
        |
        v
Travel Agent（主控 Agent）
  - 基于 TravelState 管理状态
  - 按 current_step 分阶段推进
  - 通过中间件动态切换 prompt / tools
        |
        +---- 状态流转工具（记录需求、选择目的地、回退步骤）
        +---- 目的地 Router（攻略 + 天气）
        +---- 交通 Coordinator（高铁 / 航班 / 自驾子代理）
        +---- RAG 工具（本地旅游知识库检索）
        +---- Memory 工具（用户长期偏好）
        +---- MCP 工具（天气、搜索、地图、12306 等）
        |
        v
数据与基础设施
  - PostgreSQL：用户/会话/消息、LangGraph store/checkpoint
  - Chroma：RAG 向量库
  - .env：模型、数据库、API Key 配置
```

## 3. 先看哪些目录最容易理解项目

- `app/main.py`
  FastAPI 入口，负责应用生命周期、路由挂载、启动时初始化 checkpointer/store/MCP。

- `app/api/`
  HTTP API 层。最重要的是 `v1/chat.py`，它负责 SSE 流式输出，并把用户消息送进主 Agent。

- `app/agents/`
  智能体核心。
  `handoffs/` 是主流程控制。
  `routers/` 是目的地路由。
  `subagents/` 是交通子代理。

- `app/core/`
  全局状态、LangGraph 持久化、长期记忆服务、中间件等“骨架层”。

- `app/tools/`
  Agent 可调用的工具集合，是真正驱动流程推进的关键层。

- `app/rag/`
  本地知识库加载、切分、检索、重排、缓存的实现。

- `app/mcp_core/`
  MCP 客户端和自建 MCP Server，负责把天气、搜索、地图、铁路等外部能力接进来。

- `app/models/` + `app/schemas/`
  数据库模型和 API 请求/响应模型。

- `scripts/`
  初始化数据库、初始化 RAG 的脚本。

- `frontend/zhixing.html`
  一个单页原型前端，可直接连后端接口。

## 4. 主业务流程怎么跑

主流程不是“问一句答一句”，而是一个分阶段旅行规划状态机。

核心状态定义在 `app/core/state.py`，`current_step` 会在以下阶段之间推进：

1. `requirement_collection`
2. `destination_recommendation`
3. `transport_planning`
4. `accommodation_planning`
5. `food_planning`
6. `itinerary_generation`
7. `budget_summarization`
8. `order_generation`

每个阶段都对应：

- 一套专门 prompt
- 一组允许调用的工具
- 一组前置依赖字段

这套映射定义在 `app/agents/handoffs/step_config.py`。

真正让 Agent“按阶段切换能力”的，是 `app/core/middleware.py` 里的 `StepConfigMiddleware`：

- 读取当前 `current_step`
- 检查本阶段需要哪些状态字段
- 注入用户长期记忆
- 动态覆盖 system prompt 和 tools

所以这个项目最关键的设计思想是：

“不是做一个万能大模型，而是把旅行规划拆成多个可控阶段，每个阶段只开放该阶段应有的能力。”

## 5. 一次聊天请求的完整调用链

以用户发送一条消息为例：

1. 前端调用 `/api/v1/chat/stream/{conversation_id}`
2. `app/api/v1/chat.py` 保存用户消息
3. 创建 `Travel Agent`
4. 把 `messages` 和 `user_id` 作为输入送入 Agent
5. Agent 在当前阶段使用对应 prompt 和 tools 推理
6. 如果触发工具，工具会返回 `Command(update=...)` 更新状态
7. LangGraph 继续基于新状态进入下一轮
8. API 通过 SSE 持续把 token / tool_call / done 推给前端
9. 最终回复再写回消息表

这意味着：

- API 层只负责“接入和流式输出”
- 真正的业务推进发生在 Agent + Tool + State 三层

## 6. 多智能体部分怎么分工

### 6.1 主控 Agent

`app/agents/handoffs/travel_agent.py`

职责：

- 作为整个旅行规划的总入口
- 汇总全部工具
- 基于 `TravelState` 管控流程
- 借助 middleware 在不同步骤切换能力

### 6.2 目的地 Router

`app/agents/routers/destination_router.py`

这部分是一个小型 LangGraph：

- 先由 `classifier_node` 判断需要查什么
- 再并发分发到 `explore` 和/或 `weather`
- 最后由 `synthesizer` 合并结果

其中：

- `explore` 主要依赖本地 RAG
- `weather` 当前是占位实现，返回的是写死示例数据

### 6.3 交通 Coordinator

`app/agents/subagents/transport_coordinator.py`

这是另一个“主 Agent + 子 Agent”结构：

- 航班子代理
- 高铁子代理
- 自驾子代理

Coordinator 负责：

- 判断用户更适合哪种交通方式
- 把问题转给对应子代理
- 再把结果整理回用户可读的答案

## 7. 工具层是这个项目的发动机

最关键的是 `app/tools/state_transition.py`。

这些工具不是简单“查数据”，而是会直接修改流程状态，比如：

- `record_requirement_tool`
- `select_destination_tool`
- `select_transport_tool`
- `select_accommodation_tool`
- `select_food_tool`
- `generate_itinerary_tool`
- `summarize_budget_tool`
- `generate_order_tool`
- 一组 `go_back_to_*` 回退工具

它们的共同特点是：

- 接收 Agent 当前上下文
- 返回 `Command(update=...)`
- 既改字段，又切换 `current_step`

所以从架构上看，这些工具其实就是“流程状态迁移器”。

## 8. RAG 在项目里承担什么角色

RAG 主要用于补充本地旅游知识，不让 Agent 纯靠模型记忆回答。

相关模块：

- `app/rag/document_loader.py` 载入文档
- `app/rag/text_splitter.py` 文档切分
- `app/rag/vectorstore.py` Chroma 向量库
- `app/rag/retriever.py` 混合检索
- `app/rag/reranker.py` 重排
- `app/rag/pipeline.py` 把检索流程串起来
- `app/tools/rag_tools.py` 暴露给 Agent 使用

当前知识库来源是本地 Markdown，比如：

- `data/documents/destinations/xian.md`

可以理解为：

“项目目前更像是一个可扩展的旅游知识问答底座，现在已经接入了西安这类示例目的地文档。”

## 9. 数据层分成三类

### 9.1 业务数据

SQLAlchemy 模型在 `app/models/`：

- `User`
- `Conversation`
- `Message`

对应用户体系、会话列表、聊天历史。

### 9.2 LangGraph 持久化

`app/core/checkpointer.py`

负责图执行过程的 checkpoint。

### 9.3 用户长期记忆

`app/core/store.py` + `app/core/memory_models.py`

这里保存的是：

- 用户旅行风格
- 饮食禁忌
- 食物偏好
- 历史去过的目的地/景点
- 住宿偏好

这层不是普通聊天记录，而是“可复用的用户画像”。

## 10. MCP 在项目里的位置

这个项目把外部能力统一收口在 MCP：

- 自建 MCP Server
  - `app/mcp_core/servers/weather_server.py`
  - `app/mcp_core/servers/search_server.py`

- 外部 MCP 服务
  - 高德地图
  - 12306
  - 航班服务

`app/mcp_core/client.py` 负责统一连接这些服务，`app/tools/mcp_tools.py` 再把工具按类别筛出来给 Agent 用。

这层的意义是：

“把外部世界的查询能力，标准化成 Agent 可调用工具。”

## 11. 前端目前是什么状态

`frontend/zhixing.html` 是一个较完整的单页原型：

- 注册/登录
- 会话列表
- 聊天窗口
- SSE 流式消息渲染

它已经能体现产品交互链路，但仍属于“原型页”形态：

- 没有工程化前端框架
- 样式和逻辑在一个 HTML 文件里
- 更适合作为演示界面，而不是长期维护的正式前端架构

## 12. 当前项目成熟度判断

从代码结构上看，这个项目已经具备“可扩展产品骨架”，但还不是完全打磨完的生产版。

比较成熟的部分：

- 分层清晰
- 主流程和阶段设计明确
- Agent / Tool / State 的边界比较清楚
- RAG、MCP、长期记忆都已经有接入口

仍然偏演示/占位的部分：

- `destination_router.py` 里的天气结果还是写死示例
- `state_transition.py` 里的行程、预算、订单生成仍是简化实现
- 主 Agent 当前实际使用的是 `MemorySaver()`，不是前面初始化好的 PostgreSQL checkpointer
- 前端还是单文件原型页

所以更准确地说，这不是“一个简单 demo”，而是：

“一个已经搭好主骨架、但部分节点还在用占位实现的旅行规划 Agent 系统。”

## 13. 新人最快理解方式

建议按这个顺序读代码：

1. `app/main.py`
2. `app/api/v1/chat.py`
3. `app/core/state.py`
4. `app/agents/handoffs/travel_agent.py`
5. `app/agents/handoffs/step_config.py`
6. `app/core/middleware.py`
7. `app/tools/state_transition.py`
8. `app/agents/routers/destination_router.py`
9. `app/agents/subagents/transport_coordinator.py`
10. `app/rag/` 和 `app/mcp_core/`

按这条线，你会先看懂“主链路”，再看懂“外接能力”。

## 14. 外部教学文档说明

提供的飞书链接：

- `https://q0kyes8lnt5.feishu.cn/wiki/J7lNwXtviigi3WkgtN5cgQ5MnWf`

我这边无法读取正文，因为访问时被重定向到了飞书登录页，需要登录授权后才能继续查看。
