# LangGraph Travel Planner

这是一个基于 `FastAPI + LangGraph + LangChain + RAG（检索增强生成） + MCP（模型上下文协议）` 的多智能体旅行规划项目。

## 当前展示口径

- 产品定位：面向自由行规划和旅行社省心方案交付的旅行顾问 Agent（智能体）系统，不是普通攻略问答页。
- 线上入口：最近一次一体化 Docker（容器化平台）部署使用 `https://travel.403edr.cn`，线上验证仍以 `/health/ready`、`acceptance-smoke`（验收冒烟）和 `acceptance-core`（核心验收）为准。
- 核心证据：`docs/acceptance-core-report.md` 保留完整 9 场景核心验收证据，`docs/predeploy-runtime-acceptance.md` 只记录部署前最小 smoke，不覆盖 core 结论。
- RAG 证据：`docs/rag-retrieval-evaluation.md` 记录 8 条小型标注查询的离线召回评估；metadata-aware BM25（元数据感知 BM25）相对正文 BM25 在 source/category recall@3 上提升 6.25 个百分点。
- 目录卫生：`.env`、`.runtime/`、`.venv/`、`node_modules/`、`data/vectorstore*/`、本地截图和 Playwright（浏览器自动化测试框架）产物均为本地忽略项，不应进入提交或演示包。

## 项目演示包

如果需要把项目能力整理成可讲述、可复跑的 AI-Agent（人工智能智能体）项目展示材料，优先看：

- [docs/project-demo-pack.md](docs/project-demo-pack.md)：演示包主入口，覆盖本地讲解、acceptance-smoke（验收烟测）和前端报告三条路径。
- [docs/project-capability-map.md](docs/project-capability-map.md)：AI-Agent 项目问题、架构回答、代码定位和验证命令。
- [docs/demo-script.md](docs/demo-script.md)：现场演示脚本。

生成脱敏演示包目录：

```powershell
.\.venv\Scripts\python scripts\build_project_demo_pack.py --output .runtime\project-demo-pack
```

当前仓库已经把测试体系分成了两层：

- 默认本地回归测试：不依赖真实 LLM、真实 MCP、外网服务，适合日常改代码后快速验证。
- 联调/集成测试：会触发真实 LLM、MCP、外部 API 或较重的端到端流程，适合功能联调和发布前验证。

这份文档重点说明测试怎么跑、每条测试命令代表什么、预期输出长什么样，以及遇到不同结果时应该怎么理解。

## 测试分层

### 1. 默认本地回归测试

默认执行 `pytest` 时，只会跑本地纯回归测试。

这类测试的特点是：

- 不依赖真实 DashScope / Tavily / 高德 / MCP 远端服务。
- 可以在离线或外部服务不稳定时继续跑。
- 运行速度快，适合每次提交前都执行。
- 主要覆盖工作流一致性、系统韧性、以及 MCP Server 的本地逻辑单测。

当前默认层包含：

- `tests/test_date_normalization.py`
- `tests/test_driving_query_tool.py`
- `tests/test_system_resilience.py`
- `tests/test_workflow_maintainability.py`
- `tests/test_destination_router_enhancements.py`
- `tests/test_mcp_client_config_unit.py`
- `tests/test_flight_query_tool.py`
- `tests/test_train_query_tool.py`
- `tests/test_hotel_query_tool.py`
- `tests/test_step_prompt_rendering.py`
- `tests/test_travel_agent_tool_registry.py`
- `tests/test_mcp/test_search_server_unit.py`
- `tests/test_mcp/test_weather_server_unit.py`

### 2. 联调/集成测试

联调测试需要显式开启，不会被默认 `pytest` 自动执行。

这类测试的特点是：

- 可能依赖真实 LLM。
- 可能依赖真实 MCP 服务或外部 HTTP API。
- 可能需要可用的环境变量和网络。
- 运行更慢，也更容易受到外部环境波动影响。

当前联调层主要包括：

- RAG 全链路测试
- Destination Router 测试
- Autonomous RAG Agent 测试
- Transport Subagents 测试
- MCP 真实联调测试
- Flight Query Wrapper 真实联调测试
- Train Query Wrapper 真实联调测试
- Hotel MCP 真实搜索测试
- Hotel Query Wrapper 真实联调测试
- Accommodation 阶段真实链路测试
- Transport Recommendation Quality 真实场景测试

## 环境准备

在运行测试前，建议先确认以下事项：

- 已创建虚拟环境并安装依赖。
- 当前工作目录为项目根目录。
- 使用项目虚拟环境中的 Python。

Windows PowerShell 下建议统一使用：

```powershell
.\.venv\Scripts\python -m pytest
```

如果需要联调测试，还应确认：

- `.env` 中相关密钥已配置。
- 网络可用。
- 外部 MCP 服务当前可访问。

## 模型切换注意事项

当前项目默认通过 DashScope 的 OpenAI compatible-mode 调用千问模型，默认模型已切到 `qwen3.6-plus`。

- 日常只需要修改 `.env` 里的 `QWEN_MODEL_NAME`。
- 如果希望“未配置 `.env` 时的默认行为”也同步变化，需要同时检查 [app/config.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/config.py)。
- 如果你在调试脚本、联调脚本或测试里单独创建 LLM，优先统一走 [app/utils/llm_factory.py](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/utils/llm_factory.py)，不要再直接混用 `ChatTongyi`。
- 更完整的切换说明见 [docs/model-switch-notes.md](D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/docs/model-switch-notes.md)。

## 推荐测试顺序

日常开发建议按下面顺序执行：

1. 先做编译检查，确认没有语法错误。
2. 再跑默认本地回归测试。
3. 如果修改涉及 LLM、MCP、RAG、Router、Subagent，再按需跑联调测试。

## 测试命令详解

### 1. 编译检查

命令：

```powershell
.\.venv\Scripts\python -m compileall app tests
```

这条命令代表什么：

- 检查 `app/` 和 `tests/` 里的 Python 文件能否被解释器成功编译。
- 适合快速发现语法错误、缩进错误、明显的导入结构问题。

预期效果：

- 命令成功退出。
- 终端输出中会看到很多 `Listing ...` 和 `Compiling ...`。
- 不应出现 `SyntaxError`、`IndentationError`、`Traceback`。

怎么理解结果：

- 如果这一步失败，说明代码本身还不能稳定加载，后面的 pytest 结果通常没有参考价值。
- 如果这一步通过，只能说明“语法层面没问题”，不代表业务逻辑正确。

### 2. 默认本地回归测试

命令：

```powershell
.\.venv\Scripts\python -m pytest -q
```

这条命令代表什么：

- 运行默认本地回归层。
- 自动跳过所有显式标记为 `integration` 的测试。
- 这是最推荐日常使用的一条命令。

当前预期输出：

```text
53 passed, 24 deselected, 1 warning
```

怎么理解结果：

- `53 passed`：当前默认层里的 53 条本地测试全部通过。
- `24 deselected`：有 24 条联调测试被故意分流，没有执行，这不是失败，是设计目标。
- `1 warning`：当前环境下会出现一条来自 `fastmcp/authlib` 的三方依赖弃用警告，不影响本地回归通过。

什么时候应该跑这条命令：

- 改了普通业务代码后。
- 改了测试基础设施后。
- 提交代码前做快速回归时。

如果这条命令失败，通常说明：

- 本地业务逻辑回归了。
- 工作流定义、状态流转、MCP server 本地逻辑或韧性逻辑有问题。
- 这类失败优先级通常高于联调失败，因为它不依赖外部环境。

### 3. 查看默认层究竟会跑哪些测试

命令：

```powershell
.\.venv\Scripts\python -m pytest --collect-only -q
```

这条命令代表什么：

- 只做测试收集，不真正执行测试。
- 用于确认“默认层现在会选中哪些测试”。

当前预期输出特点：

- 会列出 53 条测试。
- 末尾应看到类似：

```text
53/77 tests collected (24 deselected)
```

怎么理解结果：

- `77` 是当前仓库中 pytest 可见的测试总数。
- `53` 是默认层实际会执行的测试数。
- `24` 是联调层测试数。

这条命令适合用在：

- 修改 pytest 分层规则后。
- 新增测试后，确认它被分到了正确层级。

### 4. 只查看联调层会跑哪些测试

命令：

```powershell
.\.venv\Scripts\python -m pytest --integration-only --collect-only -q
```

这条命令代表什么：

- 只收集联调测试。
- 不执行。
- 用于确认联调层的边界是否清晰。

当前预期输出特点：

- 会列出 24 条联调测试。
- 末尾应看到类似：

```text
24/77 tests collected (53 deselected)
```

怎么理解结果：

- 说明默认层和联调层已经被明确区分。
- 如果一条需要外部服务的测试没有出现在这里，通常说明它漏打了 `integration` 标记。
- 如果一条纯本地测试出现在这里，通常说明打标过重了。

### 5. 查看“全量测试”收集结果

命令：

```powershell
.\.venv\Scripts\python -m pytest --run-integration --collect-only -q
```

这条命令代表什么：

- 开启联调测试的收集与运行资格。
- 在 `--collect-only` 模式下，只看全量测试是否都能被识别。

当前预期输出特点：

- 应看到所有 77 条测试。
- 末尾应看到类似：

```text
77 tests collected
```

怎么理解结果：

- 说明测试没有丢，只是默认进行了分层。
- 这一步很适合确认测试体系没有把某些联调用例“藏没了”。

### 6. 只跑新增的 MCP 本地单测

命令：

```powershell
.\.venv\Scripts\python -m pytest tests/test_mcp/test_search_server_unit.py tests/test_mcp/test_weather_server_unit.py -q
```

这条命令代表什么：

- 只跑第四轮新增的 4 条 MCP Server 本地单测。
- 不需要真实 Tavily 或高德服务。

当前预期输出：

```text
4 passed
```

这 4 条测试分别验证什么：

- `test_search_server_trims_result_content`
  验证 Tavily 搜索结果会被裁剪到预期长度。
- `test_search_server_returns_timeout_error`
  验证搜索请求超时时，服务会返回可预期的错误结构。
- `test_weather_server_returns_forecast_payload`
  验证天气接口成功时，服务会抽取并返回核心字段。
- `test_weather_server_surfaces_upstream_error`
  验证上游 API 失败时，错误信息会被正确透传。

### 7. 真正执行联调/集成测试

命令：

```powershell
.\.venv\Scripts\python -m pytest --run-integration -q
```

这条命令代表什么：

- 运行默认层和联调层的全部测试。
- 会触发真实外部依赖或较重流程。

预期效果：

- 会比默认回归明显更慢。
- 是否全部通过，取决于本地环境、密钥、网络和外部服务健康度。

怎么理解结果：

- 如果默认层通过、联调层失败，优先怀疑外部环境、密钥、网络或第三方服务，而不是立刻判定本地代码有严重回归。
- 如果默认层和联调层都失败，优先先修默认层。

什么时候应该跑这条命令：

- 修改了 RAG、Router、Transport、MCP、LLM 相关核心链路后。
- 准备做一次完整联调时。
- 发布前想做更高置信度验证时。

## 当前测试计数说明

以当前仓库状态为准，测试总量如下：

- 总测试数：67
- 默认本地回归测试：46
- 联调/集成测试：21

这组数字未来可能会变化。

如果你新增测试，建议遵守这条规则：

- 不依赖外部服务的，默认留在本地回归层。
- 依赖真实外部服务的，显式标记为 `integration`。

## 当前使用的 pytest 分层规则

测试分层规则位于：

- [tests/conftest.py](tests/conftest.py)
- [pyproject.toml](pyproject.toml)

规则说明：

- 默认不跑 `integration` 测试。
- `--integration-only` 只跑 `integration` 测试。
- `--run-integration` 跑全部测试。
- 未显式标记为 `integration` 的测试，会被视为默认本地回归测试。

项目当前注册了这些 marker：

- `unit`
- `integration`
- `llm`
- `mcp`
- `slow`

这些 marker 的含义是：

- `unit`：本地快速回归测试。
- `integration`：真实集成或重链路测试。
- `llm`：需要真实 LLM 能力。
- `mcp`：需要 MCP 服务或 MCP 集成。
- `slow`：执行速度较慢。

注意：

- 当前分层逻辑真正用于“默认是否执行”的关键 marker 只有 `integration`。
- 其他 marker 主要用于分类和后续扩展。

## 常见使用场景

### 场景 1：我只是改了状态机、工具或中间件

建议运行：

```powershell
.\.venv\Scripts\python -m compileall app tests
.\.venv\Scripts\python -m pytest -q
```

这代表什么：

- 先保证代码能编译。
- 再保证默认回归层通过。

### 场景 2：我改了 MCP server 的本地返回格式

建议运行：

```powershell
.\.venv\Scripts\python -m pytest tests/test_mcp/test_search_server_unit.py tests/test_mcp/test_weather_server_unit.py -q
.\.venv\Scripts\python -m pytest -q
```

这代表什么：

- 先精确验证你改动影响的那组单测。
- 再确认没有破坏默认回归层。

### 场景 3：我改了 Router / RAG / Transport / MCP 接入

建议运行：

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest --run-integration -q
```

这代表什么：

- 先看本地逻辑是否稳定。
- 再看真实链路是否还能联通。

### 场景 4：我只想确认测试分层有没有配错

建议运行：

```powershell
.\.venv\Scripts\python -m pytest --collect-only -q
.\.venv\Scripts\python -m pytest --integration-only --collect-only -q
.\.venv\Scripts\python -m pytest --run-integration --collect-only -q
```

这代表什么：

- 第一条看默认层。
- 第二条看联调层。
- 第三条看全量测试是否都还在。

## 如何解读失败

### 默认回归失败

说明什么：

- 本地逻辑大概率出了问题。
- 这类失败优先级很高，应优先修复。

常见原因：

- 工作流步骤定义漂移。
- 状态流转工具回归。
- 本地解析逻辑或错误处理变更。

### 联调失败

说明什么：

- 不一定是代码错了，也可能是环境问题。

常见原因：

- `.env` 缺少密钥。
- 第三方服务限流、超时或不可用。
- MCP 远端连接失败。
- 网络波动。

推荐排查顺序：

1. 先确认默认回归层是否通过。
2. 再确认 `.env` 和网络。
3. 再看具体失败的是哪一类联调测试。

## 当前我已验证过的命令

本轮文档对应的测试体系，我已经实际执行并验证过以下命令：

```powershell
.\.venv\Scripts\python -m compileall app tests
.\.venv\Scripts\python -m pytest tests/test_mcp/test_search_server_unit.py tests/test_mcp/test_weather_server_unit.py -q
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pytest --collect-only -q
.\.venv\Scripts\python -m pytest --integration-only --collect-only -q
.\.venv\Scripts\python -m pytest --run-integration --collect-only -q
```

对应结果是：

- 编译检查通过
- MCP 本地单测 `4 passed`
- 默认回归 `46 passed, 21 deselected`
- 默认层收集 `46/67`
- 联调层收集 `21/67`
- 全量收集 `67 collected`

## 后续新增测试时的建议

如果后面继续扩展测试，建议保持下面这条约定：

- 默认层优先覆盖“本地逻辑正确性”和“结构一致性”。
- 联调层负责覆盖“真实环境下能不能跑通”。

也就是说：

- 能 mock 的尽量在默认层 mock 掉。
- 需要真实联网和真实模型的，再放到联调层。

这样做的好处是：

- 日常回归更快。
- 外部环境抖动不会拖垮每次本地开发验证。
- 真正需要联调时，也仍然保留完整测试入口。

## 开发启动方式

当前项目建议区分“启动服务”和“执行测试/脚本”两类入口。

### 1. 启动后端服务

命令行方式：

```powershell
.\.venv\Scripts\python main.py
```

或者：

```powershell
.\.venv\Scripts\python app\run.py
```

两者代表什么：

- `main.py` 是本地开发的快捷入口。
- 它内部会转到 `app.run`，所以更适合在 IDE 里直接点运行。
- `app/run.py` 才是真正负责启动 Uvicorn 的脚本，特别处理了 Windows 下的事件循环兼容性。

预期效果：

- 服务启动成功后，会监听 `.env` 中的 `APP_HOST` 和 `APP_PORT`。
- 按当前默认配置，通常是 `http://127.0.0.1:8000` 或 `http://localhost:8000`。
- 根路径 `/` 应返回服务基本状态。
- `/docs` 应打开 FastAPI Swagger 文档。
- `/health/live` 应返回存活状态。
- `/health/ready` 应返回依赖就绪状态。

建议启动后立刻检查：

```text
GET /
GET /docs
GET /health/live
GET /health/ready
```

怎么理解结果：

- `/` 通了，说明 FastAPI 进程起来了。
- `/health/live` 通了，说明应用没有崩。
- `/health/ready` 返回 `ready`，说明核心依赖已正常初始化。
- `/health/ready` 返回 `degraded`，说明核心服务已起，但部分 MCP 处于降级。
- `/health/ready` 返回 `not_ready`，说明核心依赖还没起来，通常先查数据库、Store、Checkpointer。

### 2. 不建议直接运行的服务文件

- `app/main.py`

它代表什么：

- 这是 FastAPI 应用对象定义文件。
- 它本身不是拿来直接点“Run file”启动的脚本，因为没有 `if __name__ == "__main__"` 的服务启动逻辑。

预期效果：

- 如果在 IDE 里直接运行这个文件，通常不会像 `app/run.py` 那样正常启动一个可访问的 HTTP 服务。

推荐做法：

- 要启动后端服务，请运行 `main.py` 或 `app/run.py`。

## IDE 里直接运行哪个文件，分别代表什么

这一节专门回答“在 PyCharm / IDE 里直接点运行某个文件，会发生什么”。

### 1. 运行 `main.py`

文件：

- [main.py](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/main.py:1)

代表什么：

- 本地开发快捷启动入口。
- 最适合在 IDE 里直接点绿色运行按钮。

运行后效果：

- 启动整个 FastAPI 后端。
- 会加载 Checkpointer、Store、MCP warmup。
- 成功后可以访问接口和 Swagger。

适用场景：

- 你想本地启动整个后端服务。
- 你想手工联调前端或接口。

### 2. 运行 `app/run.py`

文件：

- [app/run.py](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/app/run.py:1)

代表什么：

- 实际的 Uvicorn 启动脚本。
- 比 `main.py` 更底层，适合你明确知道自己在跑服务脚本时使用。

运行后效果：

- 和运行根目录 `main.py` 基本等价。
- 只是更直接。

适用场景：

- 排查服务启动问题。
- 想确认 Windows 事件循环兼容逻辑是否生效。

### 3. 运行 `python -m scripts.init_db`

文件：

- [scripts/init_db.py](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/scripts/init_db.py:1)

代表什么：

- 数据库初始化脚本。
- 会创建业务表、LangGraph Checkpointer 表、Store 表，并尝试启用 `pgvector`。

运行前需要什么：

- PostgreSQL 可访问。
- `.env` 中数据库连接配置正确。
- 当前数据库用户有建表和扩展权限。

预期效果：

- 控制台会输出类似“业务表创建成功”“Checkpointer 表创建成功”“Store 表创建成功”“pgvector 启用成功”。
- 成功后数据库基础结构就绪。

适用场景：

- 第一次搭项目环境。
- 换了一套全新数据库。
- 排查数据库结构是否缺失。

如果失败，通常说明：

- PostgreSQL 没启动。
- 用户名密码不对。
- 数据库不存在。
- 当前用户没有 `CREATE EXTENSION vector` 权限。

### 4. 运行 `python -m scripts.init_rag`

文件：

- [scripts/init_rag.py](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/scripts/init_rag.py:1)

代表什么：

- RAG 初始化脚本。
- 会加载目的地文档、切分文档、创建向量库。

运行前需要什么：

- `data/` 下已有 RAG 源文档。
- 依赖已安装。

预期效果：

- 控制台会输出文档数、父文档数、子文档数、向量库目录。
- 成功后 RAG 检索可用性会更高。

适用场景：

- 第一次建立向量库。
- 更新了目的地知识文档后重建索引。

如果失败，通常说明：

- 文档目录为空。
- 向量库依赖或模型加载失败。

### 5. 运行 `scripts/test_llm.py`

文件：

- [scripts/test_llm.py](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/scripts/test_llm.py:1)

代表什么：

- 一个手工 LLM 联调脚本。
- 它不是默认回归测试的一部分，而是“我只想确认模型能不能通”的快速检查。

运行前需要什么：

- `.env` 中 `DASHSCOPE_API_KEY` 可用。
- 网络可访问 DashScope。

预期效果：

- 成功时会打印模型返回的一句话。
- 失败时会打印连接失败异常。

适用场景：

- 想单独验证 Qwen 连通性。
- 怀疑不是业务代码问题，而是模型侧环境问题。

注意：

- 这个脚本更像手工诊断工具，不建议把它当作默认自动化回归的一部分。

### 6. 运行 `tests/handoffs_flow_test.py`

文件：

- [tests/handoffs_flow_test.py](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/tests/handoffs_flow_test.py:1)

代表什么：

- 一个交互式的手工会话测试脚本。
- 会创建 Travel Agent，然后让你在终端里一轮轮输入消息，观察主流程是否能跑起来。

运行前需要什么：

- LLM、数据库、MCP 等核心依赖尽量可用。
- 否则你会很快在对话中撞到初始化或工具调用问题。

预期效果：

- 终端会出现一个交互式提示符。
- 你可以输入旅行需求。
- 输入 `q` / `quit` / `exit` 退出。

适用场景：

- 手工走一遍 Handoffs 主流程。
- 观察多轮对话状态是否能延续。
- 直观看 Agent、Tool、状态流转的联动效果。

注意：

- 它更像“人工联调工具”，不是稳定的自动回归测试。

### 7. 运行 `tests/test_*.py`

代表什么：

- 这些文件大多数是 pytest 测试文件。
- 在 IDE 里直接“Run file”和用 pytest 跑，效果不完全一样。

如何理解：

- 如果文件内部写了 `if __name__ == "__main__"`，直接运行通常会按脚本模式执行。
- 如果没有，直接运行可能只是定义测试函数，不一定有你想要的效果。
- 对这类文件，优先建议用 pytest 执行，而不是直接 Run file。

推荐方式：

```powershell
.\.venv\Scripts\python -m pytest 路径\到\测试文件.py -q
```

### 8. 打开 `frontend/zhixing.html`

文件：

- [frontend/zhixing.html](/D:/Users/Administrator/PycharmProjects/ZhiXing/langgraph-travel-planner/frontend/zhixing.html:1)

代表什么：

- 这是前端原型页面。
- 不是 Python 脚本，不能“运行”成后端服务。

预期效果：

- 直接在浏览器打开时，可以看静态界面。
- 若页面要真正调用后端接口，仍需要先把后端服务跑起来。

适用场景：

- 看前端原型。
- 做非常轻量的手工联调。

## 环境变量说明

项目主要依赖 `.env`。

建议把环境变量理解成 5 组：

### 1. LLM 相关

- `DASHSCOPE_API_KEY`
- `QWEN_MODEL_NAME`
- `QWEN_BASE_URL`

代表什么：

- Qwen 模型调用所需配置。

影响什么：

- 主 Agent
- Router 中的 LLM 分类和生成
- 手工 LLM 联调脚本
- 所有依赖真实 LLM 的联调测试

### 2. LangSmith 相关

- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `LANGSMITH_TRACING`
- `LANGSMITH_ENDPOINT`

代表什么：

- LangSmith 追踪和观测配置。

影响什么：

- 调试链路可观测性。

### 3. PostgreSQL 相关

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

代表什么：

- 业务表、Checkpointer、Store 依赖的数据库配置。

影响什么：

- 用户/会话/消息表
- LangGraph Checkpointer
- 长期记忆 Store

### 4. Redis 相关

- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_DB`
- `REDIS_PASSWORD`

代表什么：

- 缓存或后续扩展能力使用的 Redis 配置。

### 5. MCP / 外部服务相关

- `AMAP_API_KEY`
- `TAVILY_API_KEY`
- `VARIFLIGHT_API_KEY`
- `AIGOHOTEL_API_KEY`
- `AIGOHOTEL_MCP_API`（兼容旧变量名，建议逐步迁移到 `AIGOHOTEL_API_KEY`）

代表什么：

- 天气、搜索、航班、酒店等外部能力配置。

影响什么：

- Weather MCP
- Search MCP
- 12306 MCP（当前公共服务接法通常不需要单独 API Key）
- Flight / hotel / map 相关联调

### 6. 应用启动相关

- `APP_ENV`
- `APP_HOST`
- `APP_PORT`
- `DEBUG`

代表什么：

- 本地服务监听地址、端口和调试模式。

建议：

- 本地开发优先确认 `APP_PORT` 与你的实际访问端口一致。

注意：

- README 中不要写入真实密钥。
- 如果你要分享仓库，建议把 `.env` 改成 `.env.example` 模板形式。

## 常见故障排查

### 1. 服务启动后 `/health/ready` 一直不是 `ready`

优先检查：

1. PostgreSQL 是否已启动。
2. `.env` 中数据库配置是否正确。
3. `python -m scripts.init_db` 是否已成功执行。
4. MCP 是否只是降级而不是核心未就绪。

怎么理解：

- `degraded`：核心好了，MCP 部分异常。
- `not_ready`：核心依赖没起来，通常先查数据库或 Store。

### 2. 默认 `pytest -q` 通过，但联调测试失败

通常代表：

- 本地逻辑没问题。
- 问题更可能在外部环境、密钥、网络或第三方服务。

建议排查：

1. 跑 `scripts/test_llm.py` 看模型通不通。
2. 检查 `.env` 中 API Key。
3. 单独跑 MCP 联调测试，缩小范围。

### 3. `python -m scripts.init_db` 失败

通常原因：

- PostgreSQL 没启动。
- 库不存在。
- 账号权限不足。
- `pgvector` 无法创建。

建议排查：

1. 先确认数据库能登录。
2. 再确认用户有建表权限。
3. 若卡在 `vector` 扩展，检查 PostgreSQL 是否安装了 pgvector。

### 4. `python -m scripts.init_rag` 失败

通常原因：

- 文档目录为空。
- 向量库依赖未安装完整。
- 嵌入模型或本地资源加载失败。

建议排查：

1. 先确认数据目录里真的有文档。
2. 再单独看 vectorstore 初始化错误。

### 5. 在 IDE 里直接运行测试文件，效果和 pytest 不一致

这是正常现象。

原因是：

- IDE Run file 更像“把这个文件当普通脚本执行”。
- pytest 是“测试框架模式”，会做收集、fixture 注入、marker 过滤、参数控制。

建议：

- 真正的自动化测试，请优先用 pytest 命令。
- 只有明确知道某个文件是手工脚本时，才直接 Run file。

## 推荐的 IDE 使用习惯

如果你使用 PyCharm，建议这样分：

- 启动后端服务：运行 `main.py`
- 初始化数据库：运行 `python -m scripts.init_db`
- 初始化 RAG：运行 `python -m scripts.init_rag`
- 只测模型连通性：运行 `scripts/test_llm.py`
- 手工走多轮 Agent：运行 `tests/handoffs_flow_test.py`
- 自动化回归：用 pytest Run Configuration 或终端执行 pytest 命令

最推荐保留 3 个 Run Configuration：

1. `Backend Dev`
   运行 `main.py`
2. `Pytest Fast`
   运行 `python -m pytest -q`
3. `Pytest Integration`
   运行 `python -m pytest --run-integration -q`
