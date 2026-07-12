# DB Migration Readiness（数据库迁移就绪）

本文定义业务数据库从“全量初始化”转向“版本化迁移”的发布策略。结论：本项目引入 Alembic（数据库迁移工具）管理业务表迁移，`scripts/init_db.py` 只作为首次环境引导入口，不再作为生产发布的唯一手段。

## 迁移边界

Alembic 只管理本项目 `app.models` 下的业务表：

| 范围 | 表 | 说明 |
|---|---|---|
| 用户与会话 | `user`、`conversation`、`message` | 登录用户、旅行规划会话、聊天消息。 |
| 审批治理 | `approval_request`、`approval_event` | 审批请求与只追加审批事件；这些表只证明审批记录可持久化，不代表 LangGraph `interrupt/resume`（中断/恢复）闭环。 |
| 工具审计 | `tool_audit_event` | 真实查询工具的脱敏输入摘要、输出摘要、状态和证据类型。 |

LangGraph（图式智能体编排框架）相关表不进入 Alembic 迁移：

| 范围 | 表或对象 | 管理方式 |
|---|---|---|
| Checkpointer（执行检查点） | `checkpoint_migrations`、`checkpoints`、`checkpoint_blobs`、`checkpoint_writes` | `AsyncPostgresSaver.setup()` 由 LangGraph 包自身迁移。 |
| Store（长期存储） | `store_migrations`、`store`、`vector_migrations`、`store_vectors` | `AsyncPostgresStore.setup()` 由 LangGraph 包自身迁移。 |
| pgvector（向量扩展） | `vector extension` | 由 `scripts.init_db --mode pgvector` 或 Store 向量迁移启用。 |

这样做的原因是 LangGraph 包已经内置自己的迁移版本表和 DDL（数据定义语言）序列；把这些表复制到 Alembic 会产生双写迁移来源，升级 LangGraph 依赖时更容易漂移。业务表则必须由本仓库版本化管理，避免生产只能依赖 `create_all` 式全量初始化。

## 入口分层

### 首次初始化

新环境第一次创建数据库对象时运行：

```powershell
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
```

`bootstrap` 会依次执行：

1. `alembic upgrade head`，创建或升级业务表。
2. `AsyncPostgresSaver.setup()`，创建或升级 LangGraph Checkpointer 表。
3. `AsyncPostgresStore.setup()`，创建或升级 LangGraph Store 表。
4. `CREATE EXTENSION IF NOT EXISTS vector`，启用 pgvector。

本地一次性调试仍保留：

```powershell
.\.venv\Scripts\python -m scripts.init_db --legacy-create-all
```

该选项只允许 development（开发）或 test（测试）环境使用；staging（预生产）和 production（生产）会直接拒绝。

### 增量迁移

发布业务表变更时运行：

```powershell
.\.venv\Scripts\alembic upgrade head
```

也可以通过脚本只执行业务迁移：

```powershell
.\.venv\Scripts\python -m scripts.init_db --mode migrate
```

新增业务表或字段时，先生成迁移草稿并人工审查：

```powershell
.\.venv\Scripts\alembic revision --autogenerate -m "describe business schema change"
```

提交迁移前必须确认迁移只触碰业务表，不包含 `checkpoints`、`checkpoint_*`、`store`、`store_*`、`vector_migrations` 等 LangGraph 自管对象。

### 验收检查

不连接真实数据库的静态检查：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target development --json
```

连接目标环境的真实检查：

```powershell
.\.venv\Scripts\alembic current
.\.venv\Scripts\alembic heads
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
```

`check_runtime_readiness.py` 会输出 `database_migrations` 区块，列出 Alembic 配置、迁移文件、业务表范围和 LangGraph 边界。默认 CI 不连接 PostgreSQL（关系型数据库），只验证这些静态契约；也可以理解为 CI 默认不连接真实 PostgreSQL，只做迁移文件和边界检查。

## 环境命令

| 环境 | 迁移命令 | 验收命令 | 数据库策略 |
|---|---|---|---|
| 本地 development（开发） | `python -m scripts.init_db --mode bootstrap` 或 `alembic upgrade head` | `python scripts/check_runtime_readiness.py --target development --json` | 可用本地 PostgreSQL；不写真实客户数据。 |
| CI（持续集成） | 不执行真实 `alembic upgrade` | `python scripts/check_runtime_readiness.py --target development --json` | 默认不依赖真实数据库，只检查迁移文件与配置。 |
| staging（预生产） | `alembic upgrade head`，首次环境补跑 `python -m scripts.init_db --mode langgraph` 和 `--mode pgvector` | `alembic current`、`python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url <staging-url> --json` | 使用预生产密钥和隔离数据，不复用生产客户数据。 |
| production（生产） | `alembic upgrade head`，必要时只由运维窗口执行 LangGraph/pgvector 引导 | `alembic current`、`python scripts/check_runtime_readiness.py --target production --json` | 只使用部署密钥系统注入，不在文档、日志或提交中写真实连接串。 |

## 发布规则

- 业务表变更必须带 Alembic migration（迁移脚本），不能只改 SQLAlchemy（Python ORM，关系映射）模型。
- 生产发布前必须确认 `alembic current` 等于 `alembic heads`。
- 回滚策略优先使用应用回滚和向前修复迁移；涉及数据删除的 `downgrade()` 只能在明确备份和运维窗口内执行。
- `.env`、真实数据库密码、真实连接串、真实客户行程或审批记录不得写入迁移、文档、测试快照和提交说明。
- LangGraph 包升级后，先在 staging 执行 `python -m scripts.init_db --mode langgraph`，观察其自带 migration 表，再发布生产。
