# LangGraph Travel Planner 新会话接管知识库

本文用于在新会话中快速恢复对本项目的完整认知。内容综合自：

- 当前仓库代码
- 用户提供的飞书教学文档截图
- 当前对话中的分析结论

目标不是复述所有细节，而是建立一份“高密度、可继续工作的项目认知底座”。

---

## 1. 项目一句话定义

这是一个基于 `FastAPI + LangGraph + LangChain + RAG + MCP` 的多智能体旅行规划系统，核心采用：

- `Handoffs` 作为主流程控制
- `Router` 处理分类与并行查询
- `Subagents` 处理交通等专用场景
- `Checkpointer + Store` 实现短期/长期记忆
- `SSE` 提供流式对话输出

它不是简单的“聊天机器人”，而是一个以旅行规划工作流为中心的多阶段 Agent 系统。

---

## 2. 当前对项目的总体判断

### 2.1 教程蓝图

飞书教学文档给出的课程版蓝图强调：

- 企业级 AI Agent 项目结构
- 多 Agent 协作设计
- `Handoffs + Router + Subagents + Middleware` 四大主线
- `Advanced RAG`
- `MCP` 标准化工具接入
- `Checkpointer + Store` 的状态/记忆双轨持久化

### 2.2 当前仓库实现

当前仓库已经实现了主骨架，而且和教程设计高度一致，但完整度不完全相同：

- 主体结构已经落地
- 某些模块仍是占位、简化或部分注释状态
- 有些教程里的模块在当前仓库中未完整出现

### 2.3 结论

可以把当前仓库理解为：

“基于课程蓝图实现的、已经具有完整主骨架的多 Agent 旅行规划系统，但其中若干业务节点仍处于演示版或半成品状态。”

---

## 3. 目录与模块认知

当前仓库最重要的目录如下：

- `app/`
  主应用目录
- `app/core/`
  状态、checkpointer、store、中间件
- `app/agents/`
  Handoffs、Router、Subagents
- `app/tools/`
  流程推进工具、记忆工具、RAG 工具、MCP 工具
- `app/rag/`
  Advanced RAG 相关实现
- `app/mcp_core/`
  MCP 客户端与自建 MCP Server
- `app/api/`
  用户、会话、聊天 API
- `app/models/`
  SQLAlchemy ORM 模型
- `app/schemas/`
  Pydantic 请求/响应模型
- `app/utils/`
  日志、安全等通用工具
- `scripts/`
  初始化数据库、初始化 RAG 等脚本
- `frontend/zhixing.html`
  单文件前端原型
- `data/`
  RAG 文档与向量库数据

---

## 4. 核心架构分层

结合代码与教学截图，本项目可以按下面的层次理解：

### 4.1 接入层

- FastAPI 路由
- SSE 流式输出

对应代码：

- `app/main.py`
- `app/api/v1/chat.py`
- `app/api/v1/users.py`
- `app/api/v1/conversations.py`

### 4.2 应用层

- Handoffs 主流程
- Router 路由
- Subagents 子代理
- Middleware 中间件

对应代码：

- `app/agents/handoffs/`
- `app/agents/routers/`
- `app/agents/subagents/`
- `app/core/middleware.py`

### 4.3 应用服务层

- RAG 知识服务
- MCP 工具服务

对应代码：

- `app/rag/`
- `app/mcp_core/`
- `app/tools/rag_tools.py`
- `app/tools/mcp_tools.py`

### 4.4 基础设施层

- LLM：当前主用 `Qwen`
- 数据层：PostgreSQL、Redis、Chroma
- 监控与日志：LangSmith、Loguru

---

## 5. 启动链路与入口

### 5.1 应用入口

`app/main.py`

作用：

- 创建 FastAPI 应用
- 注册路由
- 在 `lifespan` 中初始化：
  - Checkpointer
  - Store
  - MCP Client Manager

### 5.2 Windows 启动脚本

`app/run.py`

作用：

- 在 Windows 下强制使用 `SelectorEventLoop`
- 手动启动 Uvicorn

### 5.3 根目录 `main.py`

当前根目录 `main.py` 只是一个简单输出 `"Hello from langgraph-travel-planner!"` 的占位脚本，不是实际服务入口。

---

## 6. API 层认知

### 6.1 用户管理

`app/api/v1/users.py`

提供：

- 注册
- 登录
- 获取当前用户信息

安全依赖：

- JWT
- bcrypt

实现位于：

- `app/utils/security.py`
- `app/api/dependencies.py`

### 6.2 会话管理

`app/api/v1/conversations.py`

提供：

- 创建会话
- 列出会话
- 获取单个会话
- 修改会话
- 软删除会话

### 6.3 流式聊天

`app/api/v1/chat.py`

核心职责：

- 保存用户消息到数据库
- 创建 `Travel Agent`
- 调用 Agent 执行
- 用 SSE 向前端流式推送 token / tool_call / done
- 保存 AI 最终回复

这是整个系统最关键的 HTTP 入口。

---

## 7. 数据模型认知

当前业务 ORM 模型：

- `User`
- `Conversation`
- `Message`

文件位置：

- `app/models/user.py`
- `app/models/conversation.py`
- `app/models/message.py`
- `app/models/base.py`

用途：

- 用户身份与偏好
- 会话管理
- 聊天历史持久化

注意：

- `Conversation.status` 支持 `active / archived / deleted`
- 当前软删除是把状态改成 `deleted`

---

## 8. TravelState 是整个主控核心

文件：

- `app/core/state.py`

设计思想来源于教程截图：

- 最小化原则
- 类型安全
- 可扩展
- 命名清晰

### 8.1 主要字段分类

#### 对话与流程

- `messages`
- `current_step`

#### 用户输入与用户选择

- `user_requirement`
- `selected_destination`
- `selected_transport`
- `selected_accommodation_types`
- `selected_food_types`

#### 查询结果

- `destination_options`
- `transport_options`
- `accommodation_options`
- `food_options`

#### 最终结果

- `itinerary`
- `budget`
- `report`

#### 审批相关字段

- `approval_pending`
- `approval_reason`

说明：

- 这些字段出现在当前 `TravelState` 中
- 但项目目前没有真正实现“人工审批节点”流程
- 它们更像是为未来增强预留的字段

#### 元数据

- `user_id`
- `session_id`
- `created_at`
- `updated_at`

### 8.2 结论

本项目的真正主控不是“某个 Prompt”，而是：

`TravelState + current_step + Tool 返回的 Command(update=...)`

---

## 9. Handoffs 主流程

### 9.1 教程定义的 8 步

教程中的旅行规划主流程是：

1. 需求收集
2. 目的地推荐
3. 交通规划
4. 住宿规划
5. 餐饮规划
6. 行程生成
7. 预算汇总
8. 报告生成 / 订单生成

### 9.2 当前仓库的步骤

当前 `PlanningStep` 定义基本对应为：

- `requirement_collection`
- `destination_recommendation`
- `transport_planning`
- `accommodation_planning`
- `food_planning`
- `itinerary_generation`
- `budget_summarization`
- `report_generation`

注：

- 当前真实工具链里更偏向 `order_generation`
- `report_generation` 仍未正式贯通

### 9.3 主控 Agent

文件：

- `app/agents/handoffs/travel_agent.py`

职责：

- 聚合所有工具
- 配置 LLM
- 挂载 `TravelState`
- 挂载中间件
- 创建整个主控 Agent

### 9.4 关键观察

当前 `create_travel_agent()` 中：

- 使用的是 `MemorySaver()` 作为 checkpointer
- 并没有真正接上 `app/core/checkpointer.py` 创建的 PostgreSQL checkpointer

这意味着：

- 虽然项目实现了 PostgreSQL Checkpointer 管理器
- 但主 Agent 当前仍未完全使用它
- 这是后续改造的重要点之一

---

## 10. Step Middleware 是主流程装配器

文件：

- `app/core/middleware.py`
- `app/agents/handoffs/step_config.py`

### 10.1 核心思想

不是为每一步单独创建一个完全独立的 Agent，而是：

- 使用一个主 Agent
- 通过 Middleware 检查 `current_step`
- 动态注入该步骤的：
  - `prompt`
  - `tools`
  - 前置依赖检查
  - 用户长期记忆

### 10.2 Middleware 在做什么

`StepConfigMiddleware` 的核心工作：

1. 读取当前状态中的 `current_step`
2. 校验该步骤需要的字段是否已存在
3. 读取长期记忆并格式化为 Prompt 文本
4. 使用模板渲染 system prompt
5. 动态注入该步骤允许使用的工具

### 10.3 为什么这很重要

它意味着本项目的主控方式是：

“单主 Agent + 状态驱动 + 中间件动态装配”

这是当前项目最核心、最值得继承的设计之一。

---

## 11. 状态转换工具是流程引擎

文件：

- `app/tools/state_transition.py`

### 11.1 设计原则

根据教程和代码，状态转换工具的原则是：

1. 更新状态字段
2. 返回 `Command`
3. 不承载复杂业务推理
4. 使用 `ToolRuntime` 访问当前状态与 `tool_call_id`

### 11.2 当前已实现的关键工具

- `record_requirement_tool`
- `select_destination_tool`
- `select_transport_tool`
- `select_accommodation_tool`
- `select_food_tool`
- `generate_itinerary_tool`
- `summarize_budget_tool`
- `generate_order_tool`
- 各类 `go_back_to_*` 回退工具

### 11.3 当前实现现状

这些工具已经具备完整的“状态迁移”功能，但业务计算仍偏简化：

- `generate_itinerary_tool`
  生成的是简化行程结构，不是真正高质量行程编排
- `summarize_budget_tool`
  用固定估算公式计算预算
- `generate_order_tool`
  生成的是模拟订单号和支付链接

### 11.4 报告生成工具

`generate_report_tool` 在 `state_transition.py` 中存在大量注释掉的实现草稿：

- 说明教程中有“报告生成”设计
- 当前仓库未正式启用
- 后续可作为一条明确增强路线恢复

---

## 12. Router 模式：当前最清晰的案例是目的地推荐

文件：

- `app/agents/routers/destination_router.py`

### 12.1 教程中的 Router 核心理念

Router 模式 =：

- 智能分类
- 并行查询
- 结果综合

### 12.2 目的地 Router 的结构

当前仓库中包含以下节点：

- `classifier_node`
- `route_to_agents`
- `explore_agent_node`
- `weather_agent_node`
- `synthesizer_node`

### 12.3 当前实现含义

#### 分类器

基于用户查询判断需要哪些子能力：

- 只查攻略
- 只查天气
- 同时查攻略和天气

#### Explore Agent

主要通过 RAG 工具获取目的地知识。

当前实现要点：

- 使用 `create_agent(...)`
- 工具来自 `app/tools/rag_tools.py`
- 依赖 RAG 文档库

#### Weather Agent

当前是占位实现，返回示例天气文本，并没有真正接入高德天气 MCP。

#### Synthesizer

把多个 Agent 的结果拼接成最终报告。

### 12.4 与教程蓝图的差异

教程说明中，目的地 Router 理想上会结合：

- RAG 文档库
- 高德天气
- Tavily 搜索补充

当前代码中：

- RAG 已接入
- 天气是占位
- Tavily 搜索没有深度整合进 `destination_router.py` 的探索链路

因此：

- Router 模式的骨架已经很完整
- 数据源整合仍可继续增强

---

## 13. Transport Subagents：当前与教程最贴近的部分

文件：

- `app/agents/subagents/transport_coordinator.py`
- `app/agents/subagents/flight_agent.py`
- `app/agents/subagents/train_agent.py`
- `app/agents/subagents/driving_agent.py`

### 13.1 教程中的交通架构

- 主 Agent：`Transport Coordinator`
- 子 Agent：
  - 航班
  - 高铁
  - 自驾
- 每个子 Agent 封装自己专属的 MCP 工具
- 主 Agent 还能调用辅助工具，如天气、酒店等

### 13.2 当前仓库的实现

#### Coordinator

作用：

- 聚合子代理能力
- 根据用户需求决定调用哪类交通工具
- 统一输出格式

#### Flight Agent

预期接入 Aviation MCP。

当前现状：

- 代码实现了代理
- 但在 `Transport Coordinator` 中，`query_flights_tool` 没有真正加入可用工具列表
- Prompt 也明确要求当前不要调用航班工具

说明航班链路仍不稳定或未完成。

#### Train Agent

对接 `12306 MCP`，是当前交通方案中最像真实可用链路的一块。

#### Driving Agent

对接高德地图 MCP，实现地理编码与驾车路线规划。

### 13.3 当前判断

交通 `Subagents` 是整个项目里“教程蓝图与代码实现最贴合”的部分之一。

---

## 14. RAG：当前实现已具备 Advanced RAG 主骨架

相关文件：

- `app/rag/document_loader.py`
- `app/rag/text_splitter.py`
- `app/rag/vectorstore.py`
- `app/rag/query_optimizer.py`
- `app/rag/retriever.py`
- `app/rag/reranker.py`
- `app/rag/cache.py`
- `app/rag/pipeline.py`

### 14.1 教程中的 Advanced RAG 目标

解决五类问题：

1. 查询模糊
2. 关键词不匹配
3. 检索噪声多
4. 上下文碎片化
5. 响应慢

### 14.2 教程定义的 4 阶段链路

1. 查询优化
2. 混合检索
3. 重排序
4. 上下文优化

### 14.3 当前实现与教程的映射

#### 查询优化

`app/rag/query_optimizer.py`

包含：

- `MultiQueryOptimizer`
- `HyDEOptimizer`
- `QueryRewriter`
- `AdvancedQueryOptimizer`

#### 混合检索

`app/rag/retriever.py`

实现：

- `BM25`
- Dense 向量检索
- `RRF` 融合

#### 重排序

`app/rag/reranker.py`

实现：

- `LLMReranker`
- `LongContextReorder`

#### 上下文优化

`app/rag/text_splitter.py`

实现：

- 父文档 / 子文档切分
- `parent_child_map`
- `get_parent_context()`

#### 全链路串联

`app/rag/pipeline.py`

整合：

- Query optimizer
- Hybrid retriever
- Reranker
- Parent context mapping
- Long context reorder
- Cache

### 14.4 当前现状判断

Advanced RAG 是当前仓库中除主流程外最完整的一个子系统。

---

## 15. MCP：本项目的外部能力总线

### 15.1 MCP Client Manager

文件：

- `app/mcp_core/client.py`

设计：

- 单例
- 统一管理所有 MCP 服务连接
- 同时支持：
  - `stdio`
  - `http`
  - `streamable_http`

### 15.2 当前配置的服务

#### 自建 MCP 服务

- `weather`
- `search`

对应文件：

- `app/mcp_core/servers/weather_server.py`
- `app/mcp_core/servers/search_server.py`

#### 外部 MCP 服务

- `amap`
- `12306-mcp`
- `VariFlight-Aviation`

#### 预留但未完整启用

- `aigohotel-mcp`

当前在代码中有注释掉的配置。

### 15.3 工具筛选器

文件：

- `app/tools/mcp_tools.py`

作用：

- 获取全部 MCP 工具
- 按场景筛选：
  - 酒店
  - 天气
  - 搜索
  - 日期

### 15.4 重要补充：Search MCP Server

根据教程截图和当前代码：

文件：

- `app/mcp_core/servers/search_server.py`

功能：

- 使用 Tavily API 搜索旅游信息
- 返回 JSON，包含：
  - `answer`
  - `results`

关键行为：

- POST 请求
- `search_depth="basic"`
- `include_answer=True`
- 结果摘要截断到 300 字符
- `max_results` 最大限制为 10

这点有助于理解为什么课程中把它作为“搜索补充能力”。

### 15.5 重要补充：Weather MCP Server

文件：

- `app/mcp_core/servers/weather_server.py`

功能：

- 基于高德天气 API 查询天气
- 输入是 `city_adcode`

当前问题：

- 目的地 Router 里的天气节点并未真正调用它
- MCP Server 已有，但业务层还没完全用起来

---

## 16. 短期记忆：Checkpointer

文件：

- `app/core/checkpointer.py`

### 16.1 教程中的定位

- 会话级短期记忆
- 存对话消息与执行状态
- 自动按 `thread_id` 隔离
- 用于恢复对话现场

### 16.2 当前代码实现

- `CheckpointerManager` 单例
- 底层用：
  - `AsyncConnectionPool`
  - `AsyncPostgresSaver`

提供：

- `get_checkpointer()`
- `checkpointer_lifespan()`

### 16.3 教程中的使用方式

教程截图里的使用示例强调：

- 在创建 Agent 时传入 `checkpointer=...`
- 调用 Agent 时通过：
  - `config={"configurable": {"thread_id": ...}}`

这样就能在多轮对话中恢复历史状态。

### 16.4 当前仓库的重要差异

当前 `chat.py` 的调用方式确实传了：

- `configurable.thread_id = conversation_id`

但由于主 Agent 实际编译时用的是 `MemorySaver()`，所以：

- thread_id 配置在接口层是对的
- 但底层并未使用 PostgreSQL Checkpointer

这是一个明确的“架构已设计、代码未完全接通”的点。

---

## 17. 长期记忆：Store

文件：

- `app/core/store.py`
- `app/core/memory_models.py`
- `app/tools/memory_tools.py`

### 17.1 教程中的定位

- 用户级长期记忆
- 存：
  - 用户画像
  - 出行历史
  - 偏好设置
- 用于个性化推荐、避免重复推荐

### 17.2 当前实现的数据组织

#### `user_profiles`

保存：

- 旅行风格
- 饮食禁忌
- 饮食偏好

#### `travel_history`

保存：

- 已完成旅行
- 去过景点
- 住宿偏好

### 17.3 UserMemoryService 的主要能力

- `get_user_profile`
- `save_user_profile`
- `update_travel_styles`
- `update_dietary_restrictions`
- `update_food_preferences`
- `get_travel_history`
- `save_travel_history`
- `add_completed_trip`
- `update_accommodation_preference`
- `get_user_memory`
- `format_memory_for_prompt`

### 17.4 教程中的使用示例含义

根据截图，长期记忆的典型使用路径有两种：

#### 直接写入与验证

- 写用户画像
- 写出行历史
- 调用 `format_memory_for_prompt()`

#### 在 Agent 中注入

- 读取 `memory_prompt`
- 把长期记忆拼接到 system prompt

### 17.5 当前仓库中的真实接入点

当前长期记忆并不是在创建 Agent 时手工注入，而是由：

- `StepConfigMiddleware`

自动完成加载与注入。

这比教程示例更进一步，更接近实际工程化做法。

---

## 18. 前端现状

文件：

- `frontend/zhixing.html`

特点：

- 单文件原型
- 支持登录、会话列表、聊天页面
- 使用 SSE 接收流式回复

判断：

- 可作为演示界面
- 还不是工程化前端
- 后续如要长期维护，建议拆为正式前端项目

---

## 19. 当前已知的教程蓝图与仓库差异

### 19.1 教程里提到但当前仓库未完整落地

- `food_router.py`
- `hotel_tool_agent.py`
- 更完整的 Tavily + Weather 联动 Router
- `generate_report_tool` 正式启用
- 酒店 MCP 接入全链路
- 课程中部分 API 文件形态：
  - `travel.py`
  - `health.py`
  - `websocket.py`

### 19.2 当前仓库已预留但未完整实现

- `approval_pending`
- `approval_reason`
- 报告生成链路
- PostgreSQL checkpointer 真正接入主 Agent

### 19.3 用户明确补充的信息

根据当前对话，用户说明：

- 教程中应该没有真正的“人工审批节点”章节
- 如果未来要改进项目，可以考虑新增这类能力

因此当前结论是：

- 状态中有审批字段
- 但它们不是已有教学主线的一部分
- 它们更适合作为后续增强方向

---

## 20. 改进方向建议

如果在后续会话中对项目做改造，优先级较高的方向如下。

### 20.1 先做“接通型”改造

这些改造技术收益高、风险较低：

1. 让主 Agent 真正使用 PostgreSQL Checkpointer
2. 让目的地 Router 的天气节点真正调用 Weather MCP
3. 把 Tavily 搜索更自然地融入 Explore Agent 或 Synthesizer
4. 恢复并启用酒店 MCP 接入链路

### 20.2 再做“质量型”改造

1. 提升 `generate_itinerary_tool`
2. 提升 `summarize_budget_tool`
3. 恢复 `generate_report_tool`
4. 统一主流程输出结构

### 20.3 最后做“产品型”改造

1. 引入人工审批节点
2. 引入订单确认环节
3. 对前端做工程化重构
4. 增加更细的 observability 与失败恢复能力

---

## 21. 新会话中建议的阅读顺序

若要快速重新进入项目，建议按以下顺序读：

1. `docs/项目总览/new-session-knowledge-base.md`
2. `docs/架构与流程/architecture-overview.md`
3. `docs/项目总览/project-doc-notes.md`
4. `app/main.py`
5. `app/api/v1/chat.py`
6. `app/core/state.py`
7. `app/core/middleware.py`
8. `app/agents/handoffs/travel_agent.py`
9. `app/agents/handoffs/step_config.py`
10. `app/tools/state_transition.py`
11. `app/agents/routers/destination_router.py`
12. `app/agents/subagents/transport_coordinator.py`
13. `app/rag/pipeline.py`
14. `app/core/checkpointer.py`
15. `app/core/store.py`
16. `app/mcp_core/client.py`

---

## 22. 新会话中的默认工作假设

除非用户明确纠正，否则在新会话中可默认使用以下认知：

1. 当前仓库大量代码源于教程实现或直接复制教程结构。
2. Router 相关理解可以直接以 `app/agents/routers` 目录为准。
3. Handoffs 主流程是当前项目的绝对主线。
4. 当前不存在真正落地的人工审批流程。
5. Advanced RAG 和交通 Subagents 是当前仓库完成度较高的部分。
6. Checkpointer/Store 的工程架构已经具备，但主 Agent 对 PostgreSQL Checkpointer 的实际接入仍未完成。

---

## 23. 一句话总结给未来接手的自己

这个项目最重要的不是某个单独文件，而是一套架构组合：

`TravelState` 负责承载状态，`Step Middleware` 负责按步骤装配能力，`state_transition tools` 负责迁移流程，`Router` 负责分类并行查询，`Subagents` 负责专用能力，`Advanced RAG` 与 `MCP` 负责外部知识与工具接入，`Checkpointer + Store` 负责短期/长期记忆。

理解了这条主线，就能迅速接管整个项目。
