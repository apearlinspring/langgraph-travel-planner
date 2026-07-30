# DB Migration Readiness（数据库迁移就绪）

本文定义业务数据库从“全量初始化”转向“版本化迁移”的发布策略。结论：本项目引入 Alembic（数据库迁移工具）管理业务表迁移，`scripts/init_db.py` 只作为首次环境引导入口，不再作为生产发布的唯一手段。

## 迁移边界

Alembic 只管理本项目 `app.models` 下的业务表：

| 范围 | 表 | 说明 |
|---|---|---|
| 用户与会话 | `user`、`conversation`、`message` | 登录用户、旅行规划会话、聊天消息。 |
| 审批治理 | `approval_request`、`approval_event` | 审批请求与应用层只追加的审批事件；数据库尚未提供不可变触发器，这些表也不代表 LangGraph `interrupt/resume`（中断/恢复）闭环。 |
| 工具审计 | `tool_audit_event` | 真实查询工具的脱敏输入摘要、输出摘要、状态和证据类型。 |
| 旅行社租户、门店与客户 | `agency`、`agency_membership`、`agency_branch`、`agency_branch_role_grant`、`agency_customer`、`agency_customer_invitation`、`agency_customer_consent_record`、`agency_customer_event`、`agency_customer_advisor_assignment` | 旅行社、门店、成员授权、目标账户安全认领、只追加同意记录、客户生命周期和主顾问分配；门店范围由应用层执行，不是 PostgreSQL RLS（行级安全策略）。 |
| 供应商产品 | `supplier_product` | 供应商产品目录；不代表实时库存、锁价或供应商同步。 |
| 报价、订单与审核 | `agency_quote`、`agency_order`、`agency_order_review`、`agency_order_event`、`idempotency_record` | 报价/订单快照、绑定式内部审核、只追加事件和幂等记录；内部审核通过不代表支付、预订或履约已完成。 |
| 交易执行账本 | `payment_attempt`、`fulfillment_record` | 为未来支付与供应商履约保存尝试记录；当前真实外部动作默认关闭。 |

LangGraph（图式智能体编排框架）相关表不进入 Alembic 迁移：

| 范围 | 表或对象 | 管理方式 |
|---|---|---|
| Checkpointer（执行检查点） | `checkpoint_migrations`、`checkpoints`、`checkpoint_blobs`、`checkpoint_writes` | `AsyncPostgresSaver.setup()` 由 LangGraph 包自身迁移。 |
| Store（长期存储） | `store_migrations`、`store`、`vector_migrations`、`store_vectors` | `AsyncPostgresStore.setup()` 由 LangGraph 包自身迁移。 |
| pgvector（向量扩展） | `vector extension` | 由 `scripts.init_db --mode pgvector` 或 Store 向量迁移启用。 |

这样做的原因是 LangGraph 包已经内置自己的迁移版本表和 DDL（数据定义语言）序列；把这些表复制到 Alembic 会产生双写迁移来源，升级 LangGraph 依赖时更容易漂移。业务表则必须由本仓库版本化管理，避免生产只能依赖 `create_all` 式全量初始化。

## 当前业务迁移链

当前 Alembic 业务迁移是单一线性链：

```text
20260511_0001
  -> 20260726_0002
  -> 20260726_0003
  -> 20260726_0004
  -> 20260730_0005
  -> 20260730_0006
```

- `20260511_0001`：用户、会话、消息、审批和工具审计等初始业务表。
- `20260726_0002`：旅行社租户、成员、客户关系、供应商产品、报价、订单、订单事件、幂等、支付尝试和履约记录。
- `20260726_0003`：新增 `agency_order_review`，保存与旅行社、订单、修订号、负载哈希、金额和币种绑定的内部审核记录；触发器禁止删除、篡改绑定字段和再次修改已终结审核。
- `20260726_0004`：新增门店、门店岗位授权、客户生命周期事件和主顾问分配；把报价、订单、审核和事件绑定到门店与客户关系。升级会为每个旧旅行社创建 `MAIN` 门店、回填旧客户/交易归属，并将旧客户同意统一置为 `unknown`，不会伪造历史同意。报价/订单触发器会固化租户、门店、客户和账户绑定，复验客户同意、门店状态、报价有效期和订单/报价金额、币种、快照一致性，要求更新时 `revision` 恰好加一、状态只按白名单迁移，并要求新订单保持 `external_action_enabled=false` 的惰性状态；客户触发器还阻止在停用前的 `pending_review` 被明确拒绝前重新激活关系；DEFERRABLE（延迟到事务提交校验）约束触发器会确认待审核订单至少有一名有效门店审批员，并校验订单与审核批准/拒绝终态成对一致。
- `20260730_0005`：新增 `agency_customer_invitation` 和 `agency_customer_consent_record`。认领邀请只保存 256-bit 高熵原始 token 的 SHA-256 摘要，状态为 `pending -> claimed|revoked`，终态不可修改且记录不可删除；同一客户以及同一旅行社同一目标账户各自同一时刻最多一条 `pending` 邀请。服务端按固定技术告知版本和文档摘要生成 `server_canonical` 同意记录，记录只允许追加。迁移把存量账户绑定标记为 `legacy_direct`、旧客户端同意摘要标记为 `legacy_client_hash`，不会伪装成 `secure_claim` 或服务端证据；原账户仍可 `deny/revoke`，升级认领时应用会重置旧同意投影并先停用原 active 关系，再要求新的规范化 `grant` 与激活。为保留历史 `active + legacy_direct` 行，active 安全约束以 `NOT VALID` 加入但会约束之后的新写入/更新；一旦存在任何认领邀请、安全认领或服务端规范化证据，`downgrade()` 会失败关闭而不是静默丢弃。
- `20260730_0006`：不改写 frozen `0005`，只替换客户、认领邀请和同意记录共用的 DEFERRABLE（提交时延迟校验）触发器函数。表专属的 `NEW.status`、`NEW.target_user_id` 和 `NEW.customer_revision` 只在对应 `TG_TABLE_NAME` 分支内访问，避免 PostgreSQL 在其他表行类型上抛出 `UndefinedColumn`。

这只说明仓库中的迁移依赖关系和 DDL 已版本化，不代表这些迁移已经在目标 PostgreSQL（关系型数据库）执行。实现候选 [`20ff715`](https://github.com/apearlinspring/langgraph-travel-planner/commit/20ff71592096dfb4fc718cef050832a745bfe174) 曾由 [GitHub Actions 运行 30534862434](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434) 在一次性 PostgreSQL 17 中执行到 `0004`，数据库 job 为 `10 passed`，默认 job 为 `1713 passed, 34 deselected`；该结果是 `0005` 之前的历史基线。首次包含 `0005` 的 [运行 30542366036](https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30542366036) 默认 job 通过，但 PostgreSQL job 因共享触发器访问了错误表行类型的 `NEW.target_user_id` / `NEW.status` 而失败，因此也不是绿灯证据；`0006` 已以新增 revision 修复，仍必须重新执行 `0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006` 并取得成功 CI。目标环境还要在发布窗口内完成备份、`alembic current`、迁移执行、集成测试和迁移后验证。

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

可以先生成离线 SQL（结构化查询语言）做 DDL 结构审阅：

```powershell
alembic upgrade head --sql
```

该命令只渲染迁移 SQL，不连接或修改真实数据库，也不能证明 PostgreSQL 扩展、权限、锁等待、历史数据兼容性或实际执行结果。审阅时重点核对迁移顺序、表归属、外键、唯一约束、检查约束、索引和 `downgrade()` 影响。

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

`check_runtime_readiness.py` 会输出 `database_migrations` 区块，列出 Alembic 配置、迁移文件、业务表范围和 LangGraph 边界。CI 的 `Static Checks And Tests` job 不连接数据库，只验证静态契约；独立的 `PostgreSQL Transaction Integration` job 只连接 runner（流水线执行机）内一次性 PostgreSQL 17 service，并精确执行：

```powershell
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_customer_claim_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py
```

`0004` 历史候选只运行原 3 个文件、共 10 项 PostgreSQL 集成测试：3 项交易、5 项客户生命周期和 2 项门店权限，并已在运行 `30534862434` 得到 `10 passed`。当前 `0005 -> 0006` workflow 新增 `tests/test_agency_customer_claim_postgres_integration.py`，在同一隔离数据库边界下覆盖全链迁移、非空 legacy provenance 回填、目标账户认领、过期/撤销/重复 token、同 target 待邀请唯一、legacy 认领重置、同意记录不可变和新交易安全客户门禁；在修复后的正式 CI 完成前，不预填新的 `passed`。CI 不得读取 staging 或 production 数据库 secret（密钥配置）。旅行社 API 在响应发送前完成事务提交，避免 DEFERRABLE 约束失败却先返回 `2xx`；业务写入采用 `customer -> branch -> quote/order` 锁序，授权敏感写入持有门店/成员共享锁，以阻止并发撤权或门店状态变化造成 TOCTOU（检查与使用时序差）竞态。这仍不能替代目标环境的锁等待和事务回滚验证。

## 环境命令

| 环境 | 迁移命令 | 验收命令 | 数据库策略 |
|---|---|---|---|
| 本地 development（开发） | `python -m scripts.init_db --mode bootstrap` 或 `alembic upgrade head` | `python scripts/check_runtime_readiness.py --target development --json` | 可用本地 PostgreSQL；不写真实客户数据。 |
| CI（持续集成） | 一次性 PostgreSQL service 中执行 `upgrade head -> downgrade base -> legacy upgrade head` | 静态 job 运行 development readiness；数据库 job 精确运行交易、客户生命周期、客户认领与门店权限四个 PostgreSQL 测试文件。实现候选 `20ff715` / 运行 `30534862434` 的默认 `1713 passed, 34 deselected` 与 PostgreSQL `10 passed` 只覆盖 `0004`；修复后的 `0005 -> 0006` 必须产生新的成功运行结果 | 仅使用固定 CI-only 凭据和隔离数据库，不读取部署环境 secret；未运行不得写成通过，CI 也不能替代目标环境迁移验收。 |
| staging（预生产） | `alembic upgrade head`，首次环境补跑 `python -m scripts.init_db --mode langgraph` 和 `--mode pgvector` | `alembic current`、`python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url <staging-url> --json` | 使用预生产密钥和隔离数据，不复用生产客户数据。 |
| production（生产） | `alembic upgrade head`，必要时只由运维窗口执行 LangGraph/pgvector 引导 | `alembic current`、`python scripts/check_runtime_readiness.py --target production --json` | 只使用部署密钥系统注入，不在文档、日志或提交中写真实连接串。 |

## 发布规则

- 业务表变更必须带 Alembic migration（迁移脚本），不能只改 SQLAlchemy（Python ORM，关系映射）模型。
- 生产发布前必须确认 `alembic current` 等于 `alembic heads`。
- 回滚策略优先使用应用回滚和向前修复迁移；涉及数据删除的 `downgrade()` 只能在明确备份和运维窗口内执行。
- `.env`、真实数据库密码、真实连接串、真实客户行程或审批记录不得写入迁移、文档、测试快照和提交说明。
- LangGraph 包升级后，先在 staging 执行 `python -m scripts.init_db --mode langgraph`，观察其自带 migration 表，再发布生产。
