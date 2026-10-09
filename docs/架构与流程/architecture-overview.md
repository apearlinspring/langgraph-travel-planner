# LangGraph Travel Planner 架构速览

## 1. 项目一句话说明

知行用状态驱动的 Agent 完成旅行规划与顾问报告交付。单个 Travel Agent 控制主链路，按需调用目的地 Router 与交通 Coordinator：

- 后端接口用 `FastAPI`
- 对话主控用 `LangChain / LangGraph`
- 知识检索用 `RAG + Chroma`
- 外部能力通过 `MCP` 接入
- 业务数据和用户体系落在 `PostgreSQL`
- 前端是轻量单页工作台，由 `frontend/zhixing.html`、`frontend/app.js` 和 `frontend/styles.css` 组成

用户通过持续对话逐步确认需求，系统查询攻略、天气、交通和酒店，并汇总为结构化旅行报告。

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
  - 先按 active_workflow 路由到省心方案或个性化旅游规划
  - free_planning 按 current_step 分阶段推进
  - agency_plan 按 agency_step 推进独立省心方案阶段
  - 通过中间件动态切换 prompt / tools
        |
        +---- 状态流转工具（记录需求、选择目的地、回退步骤）
        +---- 目的地 Router（攻略 + 天气）
        +---- 交通 Coordinator（高铁 / 航班 / 自驾查询工具）
        +---- RAG 工具（公开目的地知识 + 内部旅行社知识）
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
  `handoffs/` 保存主 Travel Agent 与阶段配置，沿用历史目录名。
  `routers/` 是目的地路由。
  `subagents/` 当前只保留在用的交通 Coordinator；航班、高铁和自驾差异由查询工具封装。

- `app/core/`
  全局状态、LangGraph 持久化、长期记忆服务和中间件。

- `app/tools/`
  Agent 工具集合，负责查询、选择确认与状态推进。

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

主流程先确认规划方式，再进入对应的阶段工作流。

### 4.1 意图分流

用户第一句话如果已经包含目的地、天数、人数、预算或日期等旅行需求，但没有明确选择规划方式，`app/api/v1/chat.py` 会先走轻量快路径，不创建完整 Travel Agent，直接问：

> 您想要现成省心方案，还是个性化旅游规划？

这条快路径会同步解析并暂存首句里的出发地、目的地、日期、人数和预算，写入消息 `extra_info.fast_mode_split`，避免第二轮再让用户重复描述。

### 4.2 个性化旅游规划

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

`app/core/middleware.py` 中的 `StepConfigMiddleware` 按阶段配置模型能力：

- 读取当前 `current_step`
- 检查本阶段需要哪些状态字段
- 注入用户长期记忆
- 动态覆盖 system prompt 和 tools

阶段配置把需求、工具和前置条件集中管理，使规划按已确认状态推进。

### 4.3 省心方案工作流

用户选择“省心方案 / 现成方案 / 成熟产品”后，状态写入：

- `planning_mode=agency_plan`
- `active_workflow=agency_plan`
- `agency_step=agency_requirement`

省心方案不复用自由规划的交通、住宿、餐饮逐项确认阶段，而是使用独立阶段：

1. `agency_requirement`：确认基础事实，例如目的地、天数、人数、预算、出发地和出发日期。
2. `agency_product_match`：检索成熟路线样板、景点票价、风险和服务边界。
3. `agency_plan_draft`：输出产品化方案，包含交通口径、住宿区域/档次与示例酒店、门票参考、餐饮、费用说明、涵盖服务和待核验项。
4. `agency_feedback`：用户满意则进入报告，不满意则记录修改意见并再出一版。
5. `agency_report`：生成用户交付视图报告。

省心方案默认不开放实时交通查询、实时酒店搜索、交通选择和住宿选择工具。只有用户明确要求“查真实航班/高铁/酒店”时，中间件才临时开放对应能力，查询结果保留来源和待核验项。

## 5. 一次聊天请求的完整调用链

以用户发送一条消息为例：

1. 前端调用 `/api/v1/chat/stream/{conversation_id}`
2. `app/api/v1/chat.py` 保存用户消息
3. 先尝试轻量快路径：规划方式确认、方向语义解析和省心方案基础事实补齐可以直接返回
4. 快路径不能处理时，创建 `Travel Agent`
5. 把 `messages` 和 `user_id` 作为输入送入 Agent
6. Agent 在当前工作流和阶段使用对应 prompt 和 tools 推理
7. 如果触发工具，工具会返回 `Command(update=...)` 更新状态
8. LangGraph 继续基于新状态进入下一轮
9. API 通过 SSE 持续把 token / tool_call / report_data / done 推给前端
10. 最终回复再写回消息表

`app/api/v1/chat.py` 集中处理会话归属、持久化、配额、会话锁、分流、SSE、报告保存与异常降级，后续需继续拆分职责。首轮分流与少量省心方案补事实采用 API 快路径，省去完整 Agent 和 MCP 初始化；完整 Agent 流设有事件空闲超时保护。

## 6. Agent、Router 与 Coordinator 怎么分工

### 6.1 主控 Agent

`app/agents/handoffs/travel_agent.py`

职责：

- 作为整个旅行规划的总入口
- 汇总全部工具
- 基于 `TravelState` 管控流程
- 借助 middleware 在不同工作流和阶段切换能力
- 对省心方案执行独立工具白名单，避免漂回自由规划

### 6.2 目的地 Router

`app/agents/routers/destination_router.py`

这部分是一个小型 LangGraph：

- 先由 `classifier_node` 判断需要查什么
- 再并发分发到 `explore` 和/或 `weather`
- 最后由 `synthesizer` 合并结果

其中：

- `explore` 主要依赖本地 RAG。
- `weather` 通过自建天气 MCP Server 调用高德天气 API；缺少密钥或上游异常时返回错误原因与待核验状态。

### 6.3 交通 Coordinator

`app/agents/subagents/transport_coordinator.py`

交通 Coordinator 是由主 Travel Agent 通过 `query_transport_options` 工具按需调用的嵌套 Agent。它负责判断交通方式、组织比较和汇总结果，但当前直接调用 `query_flights`、`query_trains`、`plan_driving_route` 等查询工具。

航班、高铁和自驾差异由 `app/tools/flight_query.py`、`train_query.py`、`driving_query.py` 封装，Coordinator 直接使用这些查询工具。

## 7. 工具层是这个项目的发动机

最关键的是 `app/tools/state_transition.py`。

以下工具通过状态更新推进规划：

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

工具调用后的字段与阶段变化由同一次 `Command` 更新完成。

## 8. RAG 在项目里承担什么角色

RAG 为规划提供本地旅游知识与旅行社业务依据。

相关模块：

- `app/rag/document_loader.py` 载入文档
- `app/rag/text_splitter.py` 文档切分
- `app/rag/vectorstore.py` Chroma 向量库
- `app/rag/retriever.py` 混合检索
- `app/rag/reranker.py` 重排
- `app/rag/pipeline.py` 把检索流程串起来
- `app/tools/rag_tools.py` 暴露给 Agent 使用

当前知识库来源是本地 Markdown：

- `data/documents/destinations/`：公开目的地攻略。
- `data/documents/internal/products/`：旅行社产品和路线模板。
- `data/documents/internal/sop/`：服务 SOP。
- `data/documents/internal/pricing/`：报价和合同规则。
- `data/documents/internal/risk/`：风险和合规规则。
- `data/documents/internal/report/`：报告交付标准。

项目还补了小型离线召回评估：`scripts/evaluate_rag_retrieval.py` 按当前标注集计算 Top-K recall、安全命中和 MRR。场景数、文档数和指标以重新生成的 `docs/RAG与知识库/rag-retrieval-evaluation.md` 为准；该报告评估本地确定性 BM25/metadata 排序；Chroma、Dense、RRF、重排与在线 Agent 通过相应真实环境流程另行验收。产品化样板支持目的地级弱匹配，例如用户只说“想去新疆”，也可召回新疆 8 天小团/包车路线候选；用户明确拒绝产品时切回自由规划。

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

这些跨会话偏好组成可复用的用户画像。

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

MCP 将外部查询统一为 Agent 工具，连接与工具筛选分别由客户端和工具层管理。

## 11. 前端目前是什么状态

`frontend/zhixing.html` 是单页入口。请求、聊天、报告、旅程地图和治理台已经拆出一批独立脚本，但 `frontend/app.js` 仍是近 7000 行的遗留主文件，继续承担大量接线和业务交互；`frontend/styles.css` 也仍是大型全局样式文件。当前可见能力包括：

- 注册/登录
- 会话列表
- 聊天窗口
- SSE 流式消息渲染
- 结构化 `report_data` 报告卡片
- 地图路线预览和导出
- 服务治理台和脱敏运行摘要

它已经能体现产品交互链路，但仍属于轻量前端原型：

- 没有工程化前端框架
- `app.js` 的地图、治理、认证、会话和渲染遗留逻辑尚未完成模块化收口
- 当前用于本地、内部和白名单受控演示；公开部署需另做目标环境验收
- 长期产品化前仍需补组件边界、错误采集、权限路由、可访问性、兼容矩阵和正式前端发布流程

## 12. 当前项目成熟度判断

项目已具备可运行的规划、报告与治理链路。维护重点是 API 编排与前端主文件的职责拆分，以及当前版本的目标环境复验。

比较成熟的部分：

- 已建立分层目标和主要目录边界，但 `chat.py`、`app.js` 等核心文件仍未完全按该边界收敛
- 主流程和阶段设计明确
- Agent / Tool / State 的边界比较清楚
- RAG、MCP、长期记忆和治理边界都有接入口
- 前端优先消费结构化 `report_data`
- acceptance-core 和 acceptance-smoke 已有可复跑门禁；历史结果按日期和版本保存
- 已有双工作流编排：个性化旅游规划走八阶段状态机，省心方案走独立 `agency_step` 节奏
- 首轮分流和省心方案基础事实补齐已有快路径，可在不加载完整 Agent 的情况下秒级返回

待完成的工作：

- 真实支付、预订、短信和供应链适配尚未接入；省心方案使用路线样例与待核验报价，外部查询失败会保留降级说明
- 扩展 RAG 标注集，补充线上查询分布与重复运行评测
- 推进前端组件化与发布工程化
- 审批治理已有策略、API 和事件账本，但尚未接成 LangGraph `interrupt/resume` 执行闭环
- acceptance 已收紧普通场景的工具失败数、失败率和 fallback 预算；两个专门降级场景仍允许有界失败。后续需补工具轨迹评估、Badcase 归因、重复运行分布与当前环境复验
- 会话删除当前是 `status=deleted` 的软删除，但读取、修改、聊天、历史和旅程接口尚未由统一 API 契约定义可见性、恢复、`404/410` 与状态枚举；这是业务 API 的一致性债务
- 聊天入口尚未形成统一的单消息长度/token 上限，SSE 也没有事件 ID、断线重放或从 checkpoint 恢复的公开契约；面向公网前需要补齐请求边界与断线语义

当前定位为旅行社智能顾问工程原型，验收与部署状态由目标版本的运行结果记录。

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

上述顺序覆盖入口、状态、编排、迁移工具，再进入 RAG 和 MCP。

## 14. 外部教学文档说明

提供的飞书链接：

- `https://q0kyes8lnt5.feishu.cn/wiki/J7lNwXtviigi3WkgtN5cgQ5MnWf`

此前访问该资料被重定向到登录页，正文尚未核对。
