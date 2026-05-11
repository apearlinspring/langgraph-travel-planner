# Runtime Config Readiness（运行配置就绪）

本文定义运行环境档位、依赖矩阵、ready check（就绪检查）和降级边界。目标是让缺 `.env`、缺真实密钥、外部服务不可用时有统一工程契约，而不是在启动、测试和验收脚本里各自判断。

## 环境档位

| 档位 | 用途 | 密钥策略 | 典型结论 |
|---|---|---|---|
| `development` | 本地开发和调试 | 允许 mock（模拟）或占位值，但必需项要有配置 | 缺核心配置为 blocked（环境阻塞），缺可选能力不阻塞 |
| `test` | 单元测试和本地快速回归 | 允许 mock 或 skip（跳过）真实外部能力 | 默认不要求真实密钥 |
| `staging` | 验收和预生产验证 | 必需项必须是真实值 | 缺真实密钥必须 blocked，不能误报通过 |
| `production` | 生产部署 | 必需项必须是真实值，Redis 不允许静默本地降级 | 缺核心依赖必须 not_ready |

`APP_ENV` 支持别名归一化：`dev/local -> development`、`testing/tests -> test`、`stage -> staging`、`prod -> production`。

## 依赖矩阵

| 依赖 | development | test | staging | production | 说明 |
|---|---:|---:|---:|---:|---|
| PostgreSQL（关系型数据库） | required | optional | required | required | 业务表、checkpoint（执行检查点）、Store（长期存储）、审批审计 |
| Redis（内存数据结构存储） | optional | optional | required | required | 会话锁；开发可降级本地锁 |
| LLM（大语言模型） | required | optional | required | required | 主 Agent（智能体）、Router（路由器）、RAG 查询优化和报告 |
| RAG（检索增强生成）向量库 | optional | optional | required | required | `data/vectorstore` 或 `RAG_VECTORSTORE_PATH` |
| MCP（模型上下文协议）服务池 | optional | optional | optional | optional | 服务级降级，不拖垮核心会话 |
| 地图 / 高德 | optional | optional | required | required | 路线预览、地理编码、部分天气能力 |
| 搜索 / Tavily | optional | optional | optional | optional | 缺少时搜索能力降级 |
| 酒店 / aigohotel | optional | optional | optional | optional | 缺少时酒店真实候选标记待二次核实 |
| 航班 / VariFlight | optional | optional | optional | optional | 缺少时航班真实候选标记待二次核实 |
| 铁路 / 12306 MCP | optional | optional | optional | optional | 缺少时高铁候选标记待二次核实 |
| LangSmith（LangChain 可观测平台） | optional | optional | optional | optional | 缺少时降低排障可观测性 |

## Ready Check 契约

`GET /health/ready` 返回 `runtime_readiness.v1`：

- `status`：`ready`、`degraded` 或 `not_ready`。
- `environment`：归一化后的运行档位。
- `dependencies`：按依赖矩阵列出每项 `requirement`、`status`、`env_vars`、`findings` 和无密钥值的 `details`。
- `missing_required`：阻塞当前档位的必需依赖。
- `degraded_optional`：可选但不可用或未配置的能力。
- `services`：底层服务快照，保留 `checkpointer`、`store`、`mcp`、`session_lock`、`approval_governance`。

整体判断：

- 必需依赖缺失、Checkpointer 或 Store 未初始化、生产 Redis 会话锁不可用、审批治理无法持久化时，返回 `not_ready`。
- MCP 服务池或开发 Redis 降级时，核心依赖已就绪则返回 `degraded`。
- 可选外部 API 缺少密钥不会阻塞核心 ready，但会在依赖明细里显示 `not_configured`。

## 命令入口

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
```

`check_runtime_readiness.py` 不输出密钥值，只输出变量名、状态和修复方向。
