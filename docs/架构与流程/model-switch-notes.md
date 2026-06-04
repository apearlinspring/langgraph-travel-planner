# 模型切换注意事项

这份说明专门记录项目从一个千问模型切到另一个千问模型时，哪些地方需要改、哪些地方不要再沿用旧写法。

当前项目默认模型已经切到 `qwen3.6-plus`，并且统一通过 DashScope 的 OpenAI compatible-mode 调用。

## 最常见的切换入口

日常切换模型，优先改 `.env`：

```env
QWEN_MODEL_NAME=qwen3.6-plus
```

如果你只是想把运行时模型从 `qwen-max` 改成 `qwen3.6-plus`，通常改这一处就够了。

## 还需要检查哪些文件

### 1. 配置默认值

`app/config.py`

- 这里定义了 `qwen_model_name` 的默认值。
- 如果某些环境没有正确加载 `.env`，项目会回退到这里的默认模型。
- 所以当你希望“默认行为”也切过去时，需要同步核对这个文件。

### 2. 统一的 LLM（大语言模型）工厂

`app/utils/llm_factory.py`

- 项目现在要求主要运行链路统一通过 `build_chat_model(...)` 创建模型。
- 这里集中管理：
  - `QWEN_MODEL_NAME`
  - `QWEN_BASE_URL`
  - `DASHSCOPE_API_KEY`
  - 默认 temperature
  - 默认 max_tokens

如果后续要切到别的 compatible-mode 模型，优先看这里，而不是去各个 Agent 里逐个改。

### 3. 调试脚本与联调测试

以下入口也容易被忽略：

- `scripts/test_llm.py`
- `test1.py`
- `test2.py`
- `tests/test_rag_agent_autonomous.py`

这些文件现在也已经统一走 `build_chat_model(...)`。以后如果新增新的调试脚本或联调脚本，也建议沿用同一工厂。

## 不建议再做的写法

不建议在项目里继续混用：

- `ChatOpenAI + DashScope compatible-mode`
- `ChatTongyi`

之前项目里两套接法并存时，`qwen-max` 没有立刻暴露问题；切到 `qwen3.6-plus` 后，真实交通链路出现了 `InvalidParameter / url error`。根因不是“模型不可用”，而是“项目里存在两套不一致的模型入口”。

所以当前建议是：

- 主运行链路统一走 `build_chat_model(...)`
- 真实联调脚本也走 `build_chat_model(...)`
- 除非有非常明确的实验目的，否则不要再直接新写 `ChatTongyi(...)`

## 切换模型后的推荐验证顺序

### 1. 语法与导入检查

```powershell
.\\.venv\\Scripts\\python -m compileall app tests
```

### 2. 默认本地回归

```powershell
.\\.venv\\Scripts\\python -m pytest -q
```

### 3. 关键联调验证

建议至少补两类真实验证：

- 主 Agent 多轮会话验证
  - 住宿查询 -> 选择酒店 -> 状态写回
  - 航班查询 -> 选择方案 -> 状态写回
  - 高铁查询 -> 选择方案 -> 状态写回
- 交通协调器推荐质量验证
  - 长途省时场景：比较航班和高铁
  - 长途但不赶时间场景：看是否合理提高高铁权重
  - 短途 + 老人/行李多场景：看是否合理引入自驾对照

## Windows 环境特别注意

如果你在 Windows 上跑真实主 Agent 会话验证，且链路里会初始化 PostgreSQL checkpointer，建议先设置：

```python
import asyncio

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

否则可能遇到 psycopg 与默认 `ProactorEventLoop` 的兼容问题。

## 一句话原则

以后切模型，先改 `.env`，再确认关键入口都通过 `app/utils/llm_factory.py` 创建模型，不要让项目重新回到“两套模型接法并存”的状态。
