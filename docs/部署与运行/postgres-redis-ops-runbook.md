# PostgreSQL / Redis Operations Runbook（数据库与缓存运维手册）

本文记录 M1 受控试运行和后续生产化时，PostgreSQL（关系型数据库）、Redis（缓存数据库）、Caddy（反向代理服务器）和后端服务的运行边界、验收命令和故障处置口径。它不记录真实服务器地址、SSH 用户、密钥、数据库口令或内部路径；这些信息只放在仓库外的部署输入文件、服务器 `.env` 或密钥系统。

## 1. M1 运行形态

M1 可以先采用单机 Docker Compose（容器编排）部署：

| 服务 | 当前角色 | M1 要求 |
|---|---|---|
| `backend` | FastAPI（快速应用接口框架）后端、Agent 流程、报告生成、健康检查 | 必须通过 `/health/live` 和 `/health/ready` |
| `caddy` | HTTPS、静态前端、反向代理 | 只暴露 80 / 443；证书和转发规则可复验 |
| `postgres` | 用户、会话、消息、checkpoint（检查点）、长期记忆、审批和审计数据 | 必须持久化到 Docker volume（卷）或托管数据库 |
| `redis` | 会话锁、缓存和运行时短状态 | 生产不允许裸露公网；建议设置口令和持久化 |

M1 可以使用 Compose 内置 PostgreSQL / Redis，也可以切到托管服务。无论选择哪一种，应用侧都必须通过环境变量记录模式：

```text
ZHIXING_POSTGRES_MODE=compose-postgresql 或 managed-postgresql
ZHIXING_REDIS_MODE=compose-redis 或 managed-redis
SESSION_LOCK_BACKEND=redis
SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false
API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_BACKEND=redis
API_RATE_LIMIT_LOCAL_FALLBACK=false
```

`SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false` 是生产边界：Redis 不可用时应暴露阻塞或降级，而不是偷偷退回本机锁。多实例部署时，本机锁无法保护跨实例并发。

`API_RATE_LIMIT_LOCAL_FALLBACK=false` 同样是生产边界：入口限流依赖 Redis 跨进程计数。Redis 不可用时应 fail closed（失败关闭，返回受控 429），不要用单进程本地计数假装仍有全局限流能力。

## 2. 发布前检查

在发布候选冻结后、正式启动服务前，先完成这些检查：

```powershell
uv run python scripts\check_m1_first_deploy_dry_run.py --json
uv run python scripts\check_server_preflight_readiness.py --json
uv run python scripts\check_postgres_redis_ops_status.py --check-compose --json
uv run python scripts\check_backup_restore_readiness.py --json
uv run python scripts\check_monitoring_alerting_readiness.py --json
uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json
```

通过标准：

- 发布包只来自 Git 已跟踪文件，不包含 `.env`、运行时目录、向量库、日志或数据库文件。
- `ZHIXING_DEPLOY_DIR`、公网访问地址、备份目标、监控渠道和回滚负责人已在私有输入里声明。
- PostgreSQL 和 Redis 模式明确；如果使用 Compose，volume 名称和备份策略明确；如果使用托管服务，连接方式、备份策略和访问白名单明确。
- `POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`JWT_SECRET_KEY` 和供应商 key 均为真实密钥系统或服务器环境值，不使用示例值。

## 3. 基础服务运维证据门禁

`check_postgres_redis_ops_status.py` 用来检查 PostgreSQL / Redis 运维状态声明和仓库 Compose 配置，不读取 `.env`、不连接数据库、不读取 Redis key、不启动服务，也不回显填写值：

```powershell
uv run python scripts\check_postgres_redis_ops_status.py --check-compose --json --output <private-workdir>\postgres-redis-ops-status.json
```

目标服务器上可以在 backend 容器内执行：

```sh
docker compose exec -T backend python scripts/check_postgres_redis_ops_status.py --json
```

注意：`--check-compose` 适合在仓库或 release 目录能读取 `docker-compose.yml` 的位置执行；如果在精简后的 backend 镜像内运行，镜像里可能没有 Compose 文件，此时应只做环境声明检查，并由 release 目录或本地仓库单独完成 Compose wiring（编排连线）扫描。

它检查的重点：

| 方向 | 关键变量或证据 |
|---|---|
| 服务形态 | `ZHIXING_POSTGRES_MODE`、`ZHIXING_REDIS_MODE` |
| 密钥状态 | `ZHIXING_DATABASE_SECRET_STATUS`、`ZHIXING_REDIS_SECRET_STATUS` |
| 备份恢复 | `ZHIXING_POSTGRES_BACKUP_STATUS`、`ZHIXING_POSTGRES_RESTORE_DRILL_STATUS` |
| RPO / RTO | `ZHIXING_RPO_TARGET`、`ZHIXING_RTO_TARGET` |
| 迁移与慢查询 | `ZHIXING_POSTGRES_MIGRATION_POLICY`、`ZHIXING_POSTGRES_SLOW_QUERY_POLICY` |
| 超时 | `POSTGRES_CONNECT_TIMEOUT_SECONDS`、`POSTGRES_POOL_TIMEOUT_SECONDS`、`POSTGRES_STATEMENT_TIMEOUT_SECONDS` |
| 会话锁 | `SESSION_LOCK_BACKEND=redis`、`SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false` |
| API 限流 | `API_RATE_LIMIT_ENABLED=true`、`API_RATE_LIMIT_BACKEND=redis`、`API_RATE_LIMIT_LOCAL_FALLBACK=false` |
| Redis 运维 | `SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS`、`ZHIXING_REDIS_PERSISTENCE_STATUS`、`ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS`、`ZHIXING_REDIS_RECOVERY_STRATEGY` |
| Compose 配置 | `postgres_data`、`redis_data`、Redis appendonly、健康依赖、session lock 环境变量 |

结果解释：

- `passed`：PostgreSQL / Redis 运维声明和 Compose wiring（连线）均满足当前门禁。
- `degraded`：没有硬阻塞，但存在 M1 可解释的生产缺口，例如单机 Compose PostgreSQL / Redis，不应包装成完整高可用。
- `blocked`：缺声明、密钥状态不清、Redis fallback 打开、Redis 可能公网暴露、RPO/RTO 无数字窗口或超时边界不合理，不能放行。

公开记录只写 status、blocked/degraded 原因和下一步，不写真实数据库地址、Redis 地址、密码、dump 文件名或日志。

如果已经有只读 SSH 权限，可以进一步收集线上实际运行证据：

```powershell
uv run python scripts\collect_postgres_redis_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --output <private-workdir>\postgres-redis-live-probe.json
uv run python scripts\collect_postgres_redis_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown --output <private-workdir>\postgres-redis-live-probe.md
```

该探针只验证：

- PostgreSQL / Redis 容器是否存在、运行、healthy。
- PostgreSQL 是否有 `/var/lib/postgresql/data` 持久化 mount。
- Redis 是否有 `/data` 持久化 mount。
- Docker 端口发布是否存在非 loopback 绑定。
- `pg_isready` 是否通过。
- Redis `PING` 是否通过。
- Redis 启动命令是否声明 appendonly。

它不读取 `.env` 内容，不读取数据库表，不读取 Redis key，不读取日志，不打印 SSH 目标和部署目录。端口存在非 loopback 绑定时会标记 `degraded`，因为这还需要防火墙或安全组证明；健康检查失败、持久化 mount 缺失、`pg_isready` / Redis `PING` 失败会标记 `blocked`。

如果线上实际容器已经健康，但 `check_postgres_redis_ops_status.py` 仍因为运维声明缺失而 blocked，可以先生成一份非密钥声明请求交给运维负责人填写。该请求只读取脱敏 JSON，不读取 `.env`、不连接 PostgreSQL / Redis / SSH、不写服务器环境文件，也不会把真实地址、口令或路径写进仓库：

```powershell
uv run python scripts\render_postgres_redis_ops_declaration_request.py `
  --ops-status-json <private-workdir>\postgres-redis-ops-status.live-env.json `
  --live-probe-json <private-workdir>\postgres-redis-live-probe.json `
  --json `
  --output <private-workdir>\postgres-redis-ops-declaration-request.json

uv run python scripts\render_postgres_redis_ops_declaration_request.py `
  --ops-status-json <private-workdir>\postgres-redis-ops-status.live-env.json `
  --live-probe-json <private-workdir>\postgres-redis-live-probe.json `
  --markdown `
  --output <private-workdir>\postgres-redis-ops-declaration-request.md
```

该文件只说明“缺哪些非密钥声明、建议怎么填、哪些需要负责人确认”。它不能证明声明已经写入服务器，也不能替代备份、恢复演练或 Redis 恢复策略验收。负责人接受后，把声明写入服务器共享 `.env` 或密钥系统，再重新运行 ops status、ops summary 和 M1 go/no-go。

为了把负责人确认变成可执行问题清单，可以再生成一份私有 owner questionnaire（负责人问卷）：

```powershell
uv run python scripts\render_postgres_redis_ops_owner_questionnaire.py `
  --request-json <private-workdir>\postgres-redis-ops-declaration-request.json `
  --markdown `
  --output <private-workdir>\postgres-redis-ops-owner-questionnaire.md
```

问卷会按 `can_prepare_from_live_probe`、`requires_backup_or_restore_artifact`、`requires_operator_confirmation`、`requires_owner_acceptance` 分组列出问题、可接受答案、证据要求和拒绝条件。它不会把任何问题自动标成 `owner_confirmed=true`，也不会替代接受记录校验。

对于 `requires_backup_or_restore_artifact` 中的两项 PostgreSQL 声明，应先从备份调度、备份恢复演练和恢复可行性报告生成候选答案：

```powershell
uv run python scripts\render_postgres_redis_backup_declaration_candidates.py `
  --backup-schedule-json <private-workdir>\backup-schedule-live-probe.json `
  --backup-restore-json <private-workdir>\postgres-restore-drill-live-probe.json `
  --restore-feasibility-json <private-workdir>\restore-drill-feasibility.json `
  --markdown `
  --output <private-workdir>\postgres-redis-backup-declaration-candidates.md
```

该候选报告只给 `ZHIXING_POSTGRES_BACKUP_STATUS` 和 `ZHIXING_POSTGRES_RESTORE_DRILL_STATUS` 的证据化建议，不会写服务器环境，也不会把负责人确认预填为 true。备份 freshness passed 只能支持备份状态候选；恢复演练必须有 `pg_restore --list` / catalog 检查加非生产恢复记录，否则仍是 `blocked`。推荐用 `collect_postgres_restore_drill_live_probe.py` 生成真实恢复演练证据；旧的 `collect_backup_restore_drill_evidence.py` 只适合 catalog 检查或声明型过渡证据。

负责人确认前，可以先从请求生成一份私有接受记录草稿：

```powershell
uv run python scripts\check_postgres_redis_ops_declaration_record.py `
  --request-json <private-workdir>\postgres-redis-ops-declaration-request.json `
  --draft-from-request `
  --output <private-workdir>\postgres-redis-ops-declaration-record.draft.json
```

草稿会把声明分成几个执行桶：

| 执行桶 | 含义 |
|---|---|
| `can_prepare_from_live_probe` | 可以用线上只读探针作为建议依据，但仍要负责人确认 |
| `requires_owner_acceptance` | 有安全默认值，但需要负责人接受风险窗口 |
| `requires_operator_confirmation` | 需要负责人根据私有运维事实填写 |
| `requires_backup_or_restore_artifact` | 需要备份、恢复演练或 `pg_restore --list` 等证据，不能只靠口头声明 |

负责人填完 `owner`、`owner_confirmed=true`、`evidence_ref` 和真实非密钥声明值后，再跑接受记录校验：

```powershell
uv run python scripts\check_postgres_redis_ops_declaration_record.py `
  --request-json <private-workdir>\postgres-redis-ops-declaration-request.json `
  --record-json <private-workdir>\postgres-redis-ops-declaration-record.local.json `
  --output <private-workdir>\postgres-redis-ops-declaration-record-report.json
```

该校验只检查接受记录本身，不读取 `.env`、不连接 PostgreSQL / Redis / SSH、不写服务器环境文件。`degraded` 表示接受记录完整但仍是 M1 单机 Compose 边界；`blocked` 表示缺负责人确认、缺证据引用、值仍是占位、RPO/RTO 无数字窗口、Redis 暴露边界不明确或记录里出现了 URL、IP、密钥形态内容。只有接受记录不是 `blocked`，才进入服务器侧写入和重新验收。

接受记录校验不是写入动作。需要生成服务器侧审阅补丁时，再渲染私有 env patch：

```powershell
uv run python scripts\render_postgres_redis_ops_env_patch.py `
  --record-json <private-workdir>\postgres-redis-ops-declaration-record.local.json `
  --record-report-json <private-workdir>\postgres-redis-ops-declaration-record-report.json `
  --markdown `
  --output <private-workdir>\postgres-redis-ops-env-patch.md
```

如果接受记录仍是 `blocked`，该渲染器不会输出可写入的 env 行。若输出 `degraded`，通常表示 M1 单机 Compose 声明可写入，但不能对外说成高可用、PITR、多可用区或长期稳定性已经具备。把补丁写入服务器共享 `.env` 或密钥系统后，必须重新运行：

```sh
docker compose exec -T backend python scripts/check_postgres_redis_ops_status.py --json
```

然后重新生成 `postgres-redis-ops-summary` 和 M1 go/no-go。只有目标运行时重新验收通过，才能把状态从“声明草案”提升为“服务器已加载并通过检查”。

## 4. 服务器启动后检查

除非 runbook 另有说明，以下命令都应在目标服务器 release 的 `current` 目录执行：

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
docker compose exec -T backend python scripts/check_server_preflight_readiness.py --check-docker --check-deploy-dir --check-disk --check-health-url --json
```

通过标准：

- `backend`、`postgres`、`redis` 和 `caddy` 均为 healthy，或托管服务有等价健康状态。
- `/health/live` 返回 alive。
- `/health/ready` 返回 ready；如果返回 degraded，必须能解释是哪个可选依赖降级，且不影响 M1 目标范围。
- readiness 不出现数据库连接失败、Redis 锁不可用、密钥占位符、RAG 向量库不可读或 MCP（模型上下文协议）必需服务阻塞。

## 5. PostgreSQL 运维边界

PostgreSQL 是有状态核心，不属于发布包。代码发布只能更新 release 目录，不能删除数据库 volume 或托管数据库实例。

M1 最低要求：

| 项 | 要求 |
|---|---|
| 持久化 | Compose 使用 `postgres_data` volume；托管服务使用云厂商持久实例 |
| 密码 | 禁止 `change-me`、空值和公开文档中的示例值 |
| 连接超时 | 使用 `POSTGRES_CONNECT_TIMEOUT_SECONDS` 控制连接失败等待 |
| 连接池等待 | 使用 `POSTGRES_POOL_TIMEOUT_SECONDS` 控制池耗尽等待 |
| 语句超时 | 使用 `POSTGRES_STATEMENT_TIMEOUT_SECONDS` 防止慢查询长时间占用连接 |
| 备份 | 至少每日备份一次；发布前有一次可识别的备份点 |
| 恢复演练 | M1 前至少完成一次 `pg_restore --list` 或等价恢复演练 |

常用检查：

```sh
docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"
docker compose exec -T backend python scripts/check_backup_restore_readiness.py --check-filesystem --json
uv run python scripts\collect_postgres_restore_drill_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --backup-dir <private-backup-dir-outside-git> --timeout-seconds 300 --markdown --output <private-workdir>\postgres-restore-drill-live-probe.md
```

生产问题处置：

| 现象 | 常见原因 | 处置 |
|---|---|---|
| `/health/ready` 数据库项 blocked | 密码错误、网络不通、数据库未启动、schema 未初始化 | 先查 `docker compose ps postgres`，再查后端 readiness；不要改表或删库 |
| 请求大量超时 | 连接池耗尽、慢查询、外部 API 卡住后占用事务 | 降低入口流量，检查后端日志和数据库慢操作，必要时重启后端释放连接 |
| 发布后缺表或字段 | schema 变更未迁移 | 回滚代码或执行已评审 migration；先备份再迁移 |
| 备份失败 | 目录不可写、空间不足、口令错误 | 先修复备份目标，不要继续放行 M1 |

PostgreSQL 或 Redis 恢复/演练后，不要只靠口头说明，应填写一份私有恢复记录并做机器校验：

```powershell
uv run python scripts\check_postgres_redis_recovery_record.py --template --output <private-workdir>\postgres-redis-recovery-record.local.json
uv run python scripts\check_postgres_redis_recovery_record.py --record-json <private-workdir>\postgres-redis-recovery-record.local.json --output <private-workdir>\postgres-redis-recovery-report.json
```

该校验只读取私有 JSON 记录，不读取 `.env`、不连接 PostgreSQL、Redis 或 SSH、不启动/重启服务、不删除文件。它要求记录包含负责人、影响服务、detect/isolate/recover/verify 四个阶段、数据安全边界、恢复后 health/M1 gate、停机和恢复耗时、无数据丢失声明、沟通闭环以及脱敏边界。记录中不得包含原始日志、截图、客户信息、真实密钥、URL 或公网 IP。

完成声明检查、线上只读探针和恢复记录校验后，再生成一份统一的基础服务运维摘要，作为 M1 go/no-go 和复盘材料的引用入口：

```powershell
uv run python scripts\render_postgres_redis_ops_summary.py `
  --ops-status-json <private-workdir>\postgres-redis-ops-status.json `
  --live-probe-json <private-workdir>\postgres-redis-live-probe.json `
  --recovery-record-json <private-workdir>\postgres-redis-recovery-report.json `
  --json `
  --output <private-workdir>\postgres-redis-ops-summary.json

uv run python scripts\render_postgres_redis_ops_summary.py `
  --ops-status-json <private-workdir>\postgres-redis-ops-status.json `
  --live-probe-json <private-workdir>\postgres-redis-live-probe.json `
  --recovery-record-json <private-workdir>\postgres-redis-recovery-report.json `
  --markdown `
  --output <private-workdir>\postgres-redis-ops-summary.md

uv run python scripts\collect_m1_go_no_go_evidence.py `
  --include-postgres-redis-ops-summary `
  --postgres-redis-ops-summary-json <private-workdir>\postgres-redis-ops-summary.json `
  --json
```

该摘要只读取前面三份脱敏 JSON，不读取 `.env`、数据库行、Redis key、日志或 SSH 目标。三份证据缺任意一份都会是 `blocked`；单机 Compose、非 loopback 端口绑定或其他 M1 可接受但未生产化的限制会是 `degraded`。摘要中的 `cannot_claim` 用来约束对外口径：不能把 M1 单机证据说成高可用、PITR（时间点恢复）、多可用区容灾、真实支付或真实履约能力。M1 总判定读取的是 JSON 版本，Markdown 版本用于人工复盘和对齐话术。

## 6. Redis 运维边界

Redis 在当前系统中主要用于会话锁和缓存。M1 生产口径下，Redis 不是“可有可无”的优化项；它承担并发下防止同一会话重复推进的职责。

M1 最低要求：

| 项 | 要求 |
|---|---|
| 持久化 | Compose 使用 appendonly；托管 Redis 使用持久化或快照策略 |
| 密码 | 生产建议设置 `REDIS_PASSWORD`，并确认 `ZHIXING_REDIS_SECRET_STATUS` |
| 公网暴露 | 禁止直接暴露公网；Compose 端口只在受控网络中使用 |
| 锁后端 | `SESSION_LOCK_BACKEND=redis` |
| fallback | `SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false` |
| 操作超时 | `SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS` 应低于用户请求可接受等待 |

常用检查：

```sh
docker compose exec -T redis sh -lc 'if [ -n "$REDIS_PASSWORD" ]; then redis-cli -a "$REDIS_PASSWORD" ping; else redis-cli ping; fi'
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
```

生产问题处置：

| 现象 | 常见原因 | 处置 |
|---|---|---|
| 同一会话并发推进异常 | Redis 不可用或 fallback 被打开 | 先停止放量，恢复 Redis；确认 fallback 没有在生产打开 |
| Redis healthcheck 失败 | 口令不一致、容器未启动、AOF 文件异常 | 查 `docker compose logs redis`；必要时从备份或快照恢复 |
| 请求偶发锁等待 | 外部 API 或 LLM 慢，锁持有时间变长 | 检查 P95（95 分位耗时）、工具超时和 Agent 步骤耗时；优先收缩超时和并发 |

## 7. 高并发和扩容口径

当前 M1 不是大规模公开流量系统。真实瓶颈通常不是 FastAPI 本身，而是 LLM、地图、搜索、航班、酒店等外部 API 的延迟、配额和失败率。

M1 放量前需要明确：

- 单日 LLM / 地图 / 搜索 / 航班 / 酒店预算和告警阈值。
- 单用户同一会话并发请求的锁策略。
- API 入口限流窗口和 429 重试头是否已部署。
- 外部 API 超时、重试和降级策略。
- SSE（服务器发送事件）长连接数量上限和代理超时。
- P95 延迟、错误率、工具失败率、成本和备份失败告警。

放量前先收集一次服务器容量快照，再跑低风险并发探针：

```powershell
uv run python scripts\collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown
uv run python scripts\collect_live_concurrency_probe.py --base-url https://<your-domain> --requests-per-endpoint 30 --concurrency 10 --timeout-seconds 5 --max-p95-ms 2000 --markdown --output <private-workdir>\live-concurrency-probe.md
uv run python scripts\collect_m1_go_no_go_evidence.py --include-server-capacity-snapshot --live-server-ssh-target <ssh-user>@<server-host> --live-server-deploy-dir <deploy-dir> --json
```

`collect_server_capacity_snapshot.py` 只读采集 CPU、load average（平均负载）、内存、磁盘、容器状态和一次 `docker stats` 样本，不读取 `.env`、日志、数据库行、Redis key、备份或向量库，也不启动/停止服务。它用于解释“这台服务器当时的资源压力是什么”，不能替代压测。`collect_live_concurrency_probe.py` 用于解释低风险健康和模拟订单 GET endpoint 在短窗口下的表现，也不能替代真实 chat 链路吞吐、LLM 长尾延迟或外部 API 配额验证。

低风险并发和限流探针执行后，应填写一份私有验收记录并做机器校验：

```powershell
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --template --output <private-workdir>\concurrency-rate-limit-record.local.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --draft-from-probes --concurrency-probe-json <private-workdir>\live-concurrency-probe.json --rate-limit-probe-json <private-workdir>\rate-limit-live-probe.json --output <private-workdir>\concurrency-rate-limit-record.draft.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --record-json <private-workdir>\concurrency-rate-limit-record.local.json --output <private-workdir>\concurrency-rate-limit-report.json
```

该校验只读取私有 JSON 记录，不读取 `.env`、不跑压测、不访问线上服务、不连接 Redis、不连 SSH。它要求记录包含低风险并发探针结果、限流探针结果、`API_RATE_LIMIT_BACKEND=redis`、`API_RATE_LIMIT_LOCAL_FALLBACK=false`、Redis 不可用时 fail closed（返回受控 429）的声明、剩余风险和脱敏边界。通过该记录只能说明 M1 低风险 endpoint 的短窗口并发和限流有效，不能包装成 chat 高并发、自动扩缩容、WAF、长期压测或真实交易能力。

水平扩容前必须满足：

- PostgreSQL 和 Redis 已迁移为共享服务，不能依赖单实例本地状态。
- 生产关闭本地锁 fallback。
- 生产关闭 API 限流本地 fallback，使用 Redis 作为共享计数后端。
- 上传文件、向量库和日志目录要么挂共享存储，要么明确每个实例的责任边界。
- Caddy / 网关健康检查能摘除异常后端实例。
- release、回滚、数据库迁移和向量库构建流程支持多实例顺序切换。

## 8. Caddy 和后端故障

| 现象 | 先看哪里 | 判断 |
|---|---|---|
| 502 / 503 | `docker compose ps backend caddy`、`docker compose logs --tail=120 backend caddy` | 多数是后端未 ready、端口错误或代理配置错误 |
| HTTPS 异常 | Caddy 日志、证书状态、公网 DNS | 先区分应用故障和 TLS / DNS / 备案路径问题 |
| 根页面可访问但 API 失败 | `/health/live`、`/health/ready`、浏览器 network | 多数是后端 readiness、CORS（跨域资源共享）或代理路径 |
| 健康检查 alive 但 not ready | readiness JSON | alive 只证明进程在，ready 才证明依赖可用 |

M1 验收不以“页面能打开”为唯一标准，必须同时保存脱敏的健康检查、readiness、smoke 和 go/no-go 摘要。

## 9. 发布和回滚原则

- 发布只覆盖代码 release，不覆盖服务器 `.env`、`shared/`、数据库 volume、Redis volume、向量库和日志目录。
- 回滚优先回滚代码 release；涉及 schema 变更时，必须先判断数据兼容性。
- 向量库更新使用构建新目录、readiness 通过后再切换的方式；失败目录保留到 generated data 区域，不进 Git。
- 任一数据库迁移、备份恢复演练、监控告警或回滚证据仍是 `not_checked` / `blocked` 时，M1 go/no-go 必须写 `no_go`。

## 10. 证据记录

每次 M1 发布或演练至少记录：

| 证据 | 记录方式 |
|---|---|
| 发布 commit / manifest / sha256 | 只写摘要，不写私有路径 |
| `docker compose ps` | 只写服务状态摘要 |
| `/health/live` 和 `/health/ready` | 只写 status、environment 和阻塞项 |
| PostgreSQL 备份/恢复演练 | 只写 `passed / blocked / not run`、时间和原因 |
| Redis 可用性 | 只写 ping / readiness 状态 |
| PostgreSQL/Redis 线上只读探针 | 使用 `collect_postgres_redis_live_probe.py` 脱敏输出 |
| PostgreSQL 非生产恢复演练 | 使用 `collect_postgres_restore_drill_live_probe.py` 脱敏输出 |
| PostgreSQL/Redis 恢复演练记录 | 使用 `check_postgres_redis_recovery_record.py` 校验私有记录 |
| 服务器容量快照 | 使用 `collect_server_capacity_snapshot.py` 脱敏输出 |
| 低风险并发/限流验收记录 | 使用 `check_concurrency_rate_limit_evidence_record.py` 校验私有记录 |
| smoke 结果 | 使用 `collect_m1_smoke_evidence.py` 脱敏输出 |
| go/no-go | 使用 `collect_m1_go_no_go_evidence.py` 脱敏输出 |

如果需要把“服务器内部可用，但当前验收机公网 HTTPS 路径异常”这类问题讲清楚，可以运行只读 live server probe。该脚本通过 SSH（安全外壳协议）在目标机上检查系统规格、Compose 服务、内部 health、服务器侧公网 health、向量库存在性和模拟订单路由是否已部署；它不读取 `.env`、日志、数据库 dump 或向量库内容，输出中也不回显 SSH 目标、部署目录和公网 URL：

```powershell
uv run python scripts\collect_live_server_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --public-base-url https://<your-domain>
uv run python scripts\collect_live_server_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --public-base-url https://<your-domain> --markdown
```

Windows 发起 SSH 脚本时要特别注意 CRLF（Windows 换行）问题。典型症状是远端 bash 报 `set: -^M: invalid option`、`command not found` 或脚本一直等到超时。`collect_live_server_probe.py` 会把远端脚本按 LF（Unix 换行）并以二进制 stdin 发送，避免本地文本模式把 `\n` 自动转换成 `\r\n`。如果手写 SSH one-liner，也要显式控制换行和引号，优先用单条只读命令验证，再扩展成脚本。

live server probe 可以接入最终 go/no-go 汇总：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py --include-live-server-probe --live-server-ssh-target <ssh-user>@<server-host> --live-server-deploy-dir <deploy-dir> --base-url https://<your-domain> --json
```

如果该 section 返回 `blocked`，最终 `decision` 必须是 `no_go`。例如模拟订单路由还没有发布到服务器时，`mock_checkout_live_route` 会阻塞，即使 `backend`、`postgres`、`redis` 和 `/health/ready` 都是 healthy。

API 限流线上证据使用脱敏探针收集：

```powershell
uv run python scripts\check_rate_limit_release_scope.py --json
uv run python scripts\collect_rate_limit_live_probe.py --base-url https://<your-domain> --request-count 130 --timeout-seconds 5 --output <private-workdir>\rate-limit-live-probe.json
uv run python scripts\collect_rate_limit_live_probe.py --report-json <private-workdir>\rate-limit-live-probe.json --markdown --output <private-workdir>\rate-limit-live-probe.md
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --draft-from-probes --concurrency-probe-json <private-workdir>\live-concurrency-probe.json --rate-limit-probe-json <private-workdir>\rate-limit-live-probe.json --output <private-workdir>\concurrency-rate-limit-record.draft.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-rate-limit-live-probe --base-url https://<your-domain> --rate-limit-request-count 130 --timeout-seconds 5 --json
```

`check_rate_limit_release_scope.py` 先确认限流相关代码、配置、探针和测试都已经进入 Git HEAD，且没有未提交改动；否则正式发布包可能仍然不包含限流能力。`collect_rate_limit_live_probe.py` 只访问 M1 mock checkout status GET endpoint（模拟订单状态读取接口），不触发 LLM、外部供应商、真实支付、真实预订、库存锁定或履约动作。公开记录只写 `passed / blocked`、HTTP 状态计数、是否看到 `Retry-After` / `X-RateLimit-*` 头，以及安全的 limit/remaining/backend 摘要；不写真实 URL、路径或响应正文。

不能记录：真实 IP、SSH 用户、密码、token、Cookie、数据库 dump 文件名、日志原文、客户资料、供应商底价或真实订单信息。
