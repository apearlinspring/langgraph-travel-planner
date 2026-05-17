# 飞书教学文档截图笔记

本文根据用户提供的飞书教学文档截图整理，目标是补充项目的“设计意图”和“课程版架构认知”。

注意：

- 本文来源是截图，不是完整原文。
- 本文反映的是教学文档中的设计说明。
- 某些内容与当前仓库代码并不完全一致，需区分“课程蓝图”和“当前实现”。

## 1. 项目定位

教学文档将本项目定义为：

- 基于 `LangGraph` 构建的企业级智能旅行规划系统
- 采用 `多 Agent 协作架构`
- 围绕 `Handoffs + Router + Subagents` 三种主流模式展开
- 结合 `Advanced RAG`、`MCP 标准化工具接入`、`短期/长期记忆持久化`
- 通过多轮对话完成从需求收集到完整旅行规划生成的全流程

文档中强调，这不是一个单点功能 demo，而是一个带完整服务端业务逻辑和 API 设计的 Agent 项目。

## 2. 教学文档中的核心卖点

从截图可提炼出几条课程想重点传达的能力：

- 贴近企业主流 AI 技术栈：`LangGraph + LangChain + FastAPI + PostgreSQL`
- 多模式融合架构：主流程、并行查询、工具化子代理共同存在
- 状态驱动工作流：用状态流转控制复杂多轮对话
- Advanced RAG 深度优化：不仅做向量检索，还包含多查询、混合检索、重排、父文档映射
- MCP 标准化接入：把天气、搜索、地图、铁路、航班、酒店等能力统一成工具接口
- 长短期记忆双轨持久化：`Checkpointer` 管会话级短期记忆，`Store` 管用户级长期记忆
- SSE 流式输出：让前端体验接近真实聊天助手

## 3. 教学文档里的架构分层

截图中的“项目架构图”把系统分成六层：

### 3.1 接入层

- `FastAPI 路由层`
- `SSE 流式输出`

### 3.2 应用层

- `Handoffs 主流程`
- `Router 路由`
- `Subagents 子代理`
- `Middleware 中间件`

### 3.3 应用服务层

- `RAG 知识库`
- `MCP 工具集`

### 3.4 基础设施层

- `Qwen max`
- `DeepSeek`

### 3.5 数据存储层

- `ChromaDB / Milvus`
- `PostgreSQL`
- `Redis`

### 3.6 基础服务层

- `LangSmith 监控`
- `Loguru 日志`

这说明课程版设计强调的是“分层清晰、能力解耦、便于扩展”的企业项目风格。

## 4. 教学文档中的模块划分

截图中给出的主要模块如下：

- `app`
  项目入口与基本配置，负责 FastAPI 实例和生命周期管理
- `core`
  核心模块，包含 `TravelState`、`Checkpointer`、`Store`、中间件
- `agents`
  Agent 实现模块，包含 `Handoffs`、`Router`、`Subagents`
- `tools`
  工具定义模块，包含状态转换、回退、记忆、RAG 等工具
- `rag`
  文档加载、切分、检索、重排、向量存储
- `mcp_core`
  自建 MCP Server 与 MCP Client 管理
- `api`
  用户、会话、流式对话等 API
- `schemas`
  Pydantic 请求/响应模型
- `models`
  ORM 数据库模型
- `utils`
  日志、安全、异常处理等通用工具

这和当前仓库的大方向是一致的，说明我们之前从代码里总结出来的主结构判断是对的。

## 5. 教学文档中的技术选型

截图中明确列出的技术栈包括：

- Python `3.11+`
- LangChain `1.0.0+`
- LangGraph `1.0.0+`
- LangSmith `Latest`
- FastAPI `0.115.0+`
- FastMCP `2.13.0+`
- PostgreSQL `15+`
- Redis `7.0+`
- ChromaDB `0.5.23+`
- loguru `0.7.2`
- bcrypt `5.0+`
- PyJWT `2.10+`
- httpx `0.28+`
- UV `Latest`

LLM 侧：

- 主模型是 `阿里千问 Qwen`
- 推荐配置中使用 `qwen-max`
- 文档强调其优势包括：
  - 中文理解较好
  - Function Calling 稳定
  - 上下文窗口大
  - 成本较优

MCP 侧：

- 自建服务：
  - 高德天气
  - Tavily 搜索
- 接入服务：
  - `12306 MCP`
  - `高德地图 MCP`
  - `AIGoHotel MCP`
  - `Aviation MCP`

## 6. 课程版为何这样设计

截图“技术选型理由”部分给出了几条非常关键的架构动机：

### 6.1 为什么 Handoffs 做主流程

- 旅行规划天然是顺序步骤
- 每一步有明确状态转移条件
- 不同步骤都需要与用户直接交互
- 需要支持从后续步骤回退到前面步骤

### 6.2 为什么引入 Router

- 某些任务天然需要并行查多个信息源
- 例如目的地推荐需要同时看攻略与实时天气
- 餐饮推荐也可能需要做分流
- 目标是降低延迟、提升吞吐

### 6.3 为什么引入 Subagents

- 用户一旦明确交通方式，不需要调用所有工具
- 不同交通方式的逻辑复杂度不同
- 通过 Supervisor 或 Coordinator 统一输出

### 6.4 为什么使用 Advanced RAG

- 攻略文档是非结构化文本，不能全塞进 Prompt
- 需要关键词检索和语义检索结合
- 需要重排保证最相关内容优先
- 需要父文档上下文映射避免碎片化

这部分对理解整个项目非常重要，因为它解释了“为什么要这样拆架构”，而不是只告诉我们“代码怎么写”。

## 7. 课程版目录设计要点

截图中的课程目录树透露出一些原始设计意图：

- `agents/handoffs/step_config.py`
- `agents/handoffs/travel_agent.py`
- `agents/routers/destination_router.py`
- `agents/routers/food_router.py`
- `agents/subagents/flight_agent.py`
- `agents/subagents/train_agent.py`
- `agents/subagents/driving_agent.py`
- `agents/subagents/hotel_tool_agent.py`
- `tools/state_transition.py`
- `tools/search_tools.py`
- `tools/approval_tools.py`
- `api/v1/travel.py`
- `api/v1/health.py`
- `api/websocket.py`
- `schemas/request.py`
- `schemas/response.py`
- `schemas/state.py`

这说明课程设计里，曾经预留或规划过：

- 单独的餐饮 Router
- 单独的酒店子代理
- travel/health/websocket 风格的 API 分层
- 更明显的 request/response/state 拆分

## 8. 与当前仓库代码的对照结论

下面这些点很关键，能帮助区分“教学架构”和“当前仓库现状”。

### 8.1 基本一致的部分

- 项目主路线仍然是 `FastAPI + LangGraph + 多 Agent + RAG + MCP`
- 当前仓库确实存在：
  - `core`
  - `agents`
  - `tools`
  - `rag`
  - `mcp_core`
  - `api`
  - `models`
  - `schemas`
  - `utils`
- 当前仓库确实使用了：
  - `TravelState`
  - `Checkpointer`
  - `Store`
  - `StepConfigMiddleware`
  - `Destination Router`
  - `交通 Subagents`
  - `SSE 流式对话`

### 8.2 存在差异的部分

教学文档中的部分结构，在当前仓库里没有完全落地，或已经演化成别的实现：

- 教学文档提到 `food_router.py`
  当前仓库中未看到对应文件
- 教学文档提到 `hotel_tool_agent.py`
  当前仓库中未看到该文件
- 教学文档展示 `api/v1/travel.py`、`health.py`、`websocket.py`
  当前仓库实际是 `users.py`、`conversations.py`、`chat.py`
- 教学文档提到 `approval_tools.py`
  当前仓库主要看到的是 `state_transition.py`、`memory_tools.py`、`rag_tools.py`、`transport_query.py` 等
- 教学文档架构图里出现 `DeepSeek`
  当前实际代码里主模型仍以 `Qwen` 为主，未见完整的 DeepSeek 主流程接入
- 教学文档数据层写 `ChromaDB/Milvus`
  当前仓库实际落地的是 `Chroma`

因此更合理的理解是：

- 飞书文档描述的是课程版目标架构 / 演进蓝图
- 当前仓库实现的是其中一条已经落地的代码版本

## 9. 对当前项目认知的修正

基于截图，我对这个项目的理解可以进一步修正为：

1. 这个仓库不是随意堆砌功能，而是有比较明确的“课程级企业项目蓝图”支撑。
2. `Handoffs + Router + Subagents + Middleware` 是这个项目最核心的教学主线。
3. `Checkpointer + Store` 不是附属功能，而是课程明确强调的状态与记忆体系。
4. `Advanced RAG` 和 `MCP` 不是点缀，而是架构中的正式服务层组成部分。
5. 当前代码实现和教学文档之间存在“蓝图先于代码”的现象，后续阅读时需要把“设计意图”和“仓库现状”同时看。

## 10. 后续阅读建议

如果继续补知识库，建议优先补下面几块截图或正文：

- `TravelState` 状态设计
- `Checkpointer` 与 `Store` 的数据库表结构
- `Handoffs` 主流程实现
- `Router` 模式的具体案例
- `Advanced RAG` 的四阶段检索链路
- `MCP` 客户端与 Server 的接入说明

这些部分一旦拿到，基本就能把“课程架构”和“当前代码”完全对齐起来。

## 11. 第二批截图补充结论

用户后续提供的截图，补足了以下几块关键知识：

- `TravelState` 的设计原则
- `Checkpointer` 与 `Store` 的职责边界和数据库表结构
- `Handoffs` 八步主流程与中间件驱动方式
- `Router` 模式的标准案例
- `Advanced RAG` 的四阶段优化链路
- `MCP` 客户端配置与交通 `Subagents` 的封装方式

这些信息让课程版设计意图比前一版更完整，尤其是“状态驱动”和“工具驱动流程迁移”两条主线。

## 12. TravelState 设计意图

截图中明确强调：

- 状态是 Agent 之间共享数据的核心机制
- 设计原则是：
  - 最小化原则：只保留必要信息
  - 类型安全：使用 `TypedDict` 或 `Pydantic`
  - 可扩展性：预留扩展字段
  - 清晰命名：字段语义明确

文档中列出的 `TravelState` 管理信息包括：

1. 对话消息
2. 流程控制字段 `current_step`
3. 用户选择
4. 查询结果
5. 元数据

这和当前仓库 [state.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/core/state.py) 的结构高度一致，说明这部分代码基本是按教程主线落地的。

### 12.1 当前仓库中的对应关系

当前代码里的 `TravelState` 主要包含：

- `messages`
- `current_step`
- `user_requirement`
- `selected_destination`
- `selected_transport`
- `selected_accommodation_types`
- `selected_food_types`
- `destination_options / transport_options / accommodation_options / food_options`
- `itinerary / budget / report`
- `approval_pending / approval_reason`
- `user_id / session_id / created_at / updated_at`

因此可以确认：

- 教程里的状态设计思想已经真实落到当前代码里
- 当前项目的流程控制核心，确实是 `current_step + state update`

## 13. Checkpointer 与 Store 的边界

截图中给出的结论非常清楚：

- `Checkpointer`
  - 短期记忆
  - 存对话消息和执行状态
  - 生命周期通常跟会话走
  - 按 `thread_id` 分组
  - 用于恢复对话现场

- `Store`
  - 长期记忆
  - 存用户画像、出行历史、偏好设置
  - 长期保存
  - 按 `namespace + key` 组织
  - 用于个性化推荐和历史记忆

这和当前仓库实现完全吻合：

- [checkpointer.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/core/checkpointer.py)
- [store.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/core/store.py)
- [memory_models.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/core/memory_models.py)

### 13.1 Store 中的长期记忆模型

截图显示课程版长期记忆分两块：

- `travel_history`
  - 已完成旅行
  - 去过景点
  - 住宿偏好
- `user_profiles`
  - 基础偏好
  - 饮食禁忌
  - 饮食偏好

当前仓库也正是这样组织的：

- `namespace=("travel_history", user_id)`
- `namespace=("user_profiles", user_id)`

这说明长期记忆的数据组织方式基本与教程一一对应。

## 14. 数据库表结构认知

截图中给出了 `checkpointer.setup()` 和 `store.setup()` 之后的表结构设计意图。

### 14.1 Checkpointer 表

关键字段包括：

- `thread_id`
- `checkpoint_ns`
- `checkpoint_id`
- `parent_checkpoint_id`
- `type`
- `checkpoint`
- `metadata`
- `created_at`

设计意图是：

- 用 `thread_id` 区分会话
- 用 `checkpoint_id` 标识某次检查点
- 用 `parent_checkpoint_id` 形成历史链，支持状态回溯
- `checkpoint` 字段保存完整状态

### 14.2 Store 表

关键字段包括：

- `namespace`
- `key`
- `value`
- `created_at`
- `updated_at`

设计意图是：

- 用 `namespace[] + key` 作为主键
- 用 JSON 保存长期记忆值
- 用 GIN 索引支持命名空间查询

虽然当前仓库没有手写这些 SQL 表定义，但从 [init_db.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/scripts/init_db.py) 的 `setup()` 调用方式看，项目确实依赖 LangGraph 官方 Postgres 组件自动建表，这与教程说明一致。

## 15. Handoffs 主流程认知补强

截图中把 `Handoffs` 主流程明确成 8 个步骤：

1. 需求收集
2. 目的地推荐
3. 交通规划
4. 住宿规划
5. 餐饮规划
6. 行程生成
7. 预算汇总
8. 报告生成 / 订单生成

这与当前仓库 [state.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/core/state.py) 中 `PlanningStep` 的定义基本一致，只是当前代码更偏向：

- `order_generation`
- `report_generation` 仍处于注释/未完全落地状态

### 15.1 每一步由工具触发状态迁移

截图里列出的关键工具链路：

- `record_requirement_tool`
- `select_destination_tool`
- `select_transport_tool`
- `select_accommodation_tool`
- `select_food_tool`
- `generate_itinerary_tool`
- `summarize_budget_tool`
- `generate_report_tool / generate_order_tool`

当前仓库 [state_transition.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/tools/state_transition.py) 与这套命名高度一致，说明这部分确实是教程代码的直接延伸。

## 16. 中间件驱动配置的设计含义

截图中明确强调核心思想：

- 一个 Agent
- 一个 Middleware
- 通过 `current_step` 动态改变 Prompt 与 Tools

这与当前仓库 [middleware.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/core/middleware.py) 完整对应：

- 检查当前 `current_step`
- 校验该步骤 `requires`
- 加载长期记忆
- 渲染步骤 Prompt 模板
- 注入该步骤允许使用的工具

因此可以把当前项目的主控方式概括为：

“单主 Agent + 状态驱动 + 中间件动态装配”

这比“每一步一个独立 Agent”更轻，更适合作为主流程控制器。

## 17. 状态转换工具的设计原则

截图中给出了状态转换工具的原则：

1. 更新状态字段
2. 返回 `Command`
3. 不承担复杂业务，只负责记录和迁移
4. 通过 `ToolRuntime` 访问当前状态与 `tool_call_id`

这和当前 `state_transition.py` 的写法完全一致。

这意味着教程有一个非常明确的工程分层：

- Prompt 负责“说什么”
- Middleware 负责“装配什么能力”
- Tool 负责“改什么状态”

这种拆法是当前项目里最值得学习的部分之一。

## 18. Router 模式的具体案例

截图把目的地推荐 Router 的标准结构写得非常清楚：

- 分类器 `classifier`
  - 判断查询意图
  - 决定调用哪些 Agent
- 探索 Agent
  - 查景点攻略
  - 可结合 RAG 与 Tavily 搜索补充
- 天气 Agent
  - 查实时天气
- 综合器 `synthesizer`
  - 合并多个 Agent 结果

其核心思想是：

- 智能分类
- 并行查询
- 结果综合

### 18.1 当前仓库的对应实现

当前仓库 [destination_router.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/agents/routers/destination_router.py) 基本就是这条教程思路的代码化版本：

- `classifier_node`
- `route_to_agents`
- `explore_agent_node`
- `weather_agent_node`
- `synthesizer_node`

因此关于 Router 模式，不需要再额外猜测设计意图，当前代码已经能很好反映教程结构。

### 18.2 当前实现与教程的差异

差异主要在落地完整度上：

- 教程里提到探索 Agent 还会调用 Tavily 做补充搜索
- 当前代码中探索 Agent 主体已接入 RAG 工具
- 当前天气 Agent 仍是占位返回，不是完整实时天气整合

所以可以判断：

- 架构模式已经落地
- 数据源整合还没全部达到教程设想的完整度

## 19. Advanced RAG 的课程主线

截图中把 Advanced RAG 优化目标概括为 5 个痛点：

1. 查询模糊
2. 关键词不匹配
3. 检索噪声多
4. 上下文碎片化
5. 响应速度慢

对应优化点是：

1. 查询改写 / 意图识别
2. `BM25 + Dense` 混合检索
3. `Reranker`
4. 父文档检索
5. 缓存策略

### 19.1 教程中的四阶段链路

截图给出的标准链路是：

1. 查询优化
   - `Multi-Query`
   - `HyDE`
   - 查询改写
2. 混合检索
   - `BM25`
   - `Dense`
   - `RRF` 融合
3. 重排序
   - `Cross-Encoder`
   - `LLM Reranker`
4. 上下文优化
   - 父文档检索
   - `Long Context Reorder`

### 19.2 当前仓库的对应实现

当前仓库中可以直接映射到：

- [query_optimizer.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/rag/query_optimizer.py)
  - `MultiQueryOptimizer`
  - `HyDEOptimizer`
  - `QueryRewriter`
  - `AdvancedQueryOptimizer`
- [retriever.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/rag/retriever.py)
  - `BM25 + Dense + RRF`
- [reranker.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/rag/reranker.py)
  - `LLMReranker`
  - `LongContextReorder`
- [text_splitter.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/rag/text_splitter.py)
  - 父子文档映射
- [pipeline.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/rag/pipeline.py)
  - 串起整个检索链

所以可以确认：当前仓库的 Advanced RAG 代码结构与教程主线高度一致。

## 20. MCP 客户端管理器的教程意图

截图里 `.env` 示例强调需要配置多个 MCP 服务：

- 高德 API
- Tavily
- VariFlight
- AIGoHotel
- 12306 外部服务

教程的目标是：

- 把多来源 MCP 服务统一交给一个客户端管理器管理
- 通过工具筛选器把能力按场景分发给主 Agent 或子 Agent

### 20.1 当前仓库对应情况

当前 [client.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/mcp_core/client.py) 中确实采用统一配置表：

- `weather`
- `search`
- `amap`
- `12306-mcp`
- `VariFlight-Aviation`

并预留了 `aigohotel-mcp`，但目前是注释掉的。

这说明：

- 教程设计中酒店 MCP 是正式组成部分
- 当前仓库里酒店接入尚未完整启用

## 21. 交通 Subagents 的架构认知

截图里的交通 MCP 架构图说明：

- 主 Agent 是 `Transport Coordinator`
- 子 Agent 分为：
  - `Flight Agent`
  - `Train Agent`
  - `Driving Agent`
- 每个子 Agent 封装专属 MCP 工具
- 主 Agent 还能直接调用辅助工具，如天气、酒店等

### 21.1 当前仓库的对应实现

当前代码几乎就是这个架构：

- [transport_coordinator.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/agents/subagents/transport_coordinator.py)
- [flight_agent.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/agents/subagents/flight_agent.py)
- [train_agent.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/agents/subagents/train_agent.py)
- [driving_agent.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/agents/subagents/driving_agent.py)

这一块可以认为是“课程设计与当前代码最接近的一部分”。

### 21.2 当前实现的限制

结合代码可以补充几个现状判断：

- `query_flights_tool` 在 coordinator 里当前被注释掉，没有实际加入工具列表
- 协调器提示词里也明确写了当前不要调用航班工具
- 酒店辅助工具在项目里有设计意图，但未完全贯通

所以交通子代理架构已经成形，但真实外部依赖可用性还不完全稳定。

## 22. 对项目整体认知的再次修正

基于这一批截图和当前代码，可以更准确地把项目定义为：

1. 这是一个“以教程蓝图为先、以真实代码逐步落地”的 Agent 项目。
2. 当前仓库最成熟的设计主线是：
   - `TravelState`
   - `Step Middleware`
   - `State Transition Tools`
   - `Destination Router`
   - `Transport Subagents`
   - `Advanced RAG`
   - `Checkpointer + Store`
3. 当前仓库仍存在若干“课程中有，代码里未完全落地”的模块：
   - 酒店 MCP 接入
   - 更完整的天气与搜索整合
   - 报告生成链路
   - 课程中提到的部分 Router/API 文件形态

## 23. 目前还值得继续补的内容

如果后续还要继续补知识库，最有价值的内容会是：

- `Router` 里探索 Agent 如何结合 Tavily 补搜索
- `Checkpointer` / `Store` 的实际使用案例与测试流程
- `AIGoHotel MCP` 的接入细节
- `订单生成 / 报告生成` 的最终链路
- 当前课程版完整目录和当前仓库目录的演进关系

这些内容拿到后，基本就可以形成一份“课程蓝图 vs 仓库实现”的完整对照知识库。
