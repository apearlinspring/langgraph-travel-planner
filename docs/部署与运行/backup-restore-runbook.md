# Backup and Restore Runbook（备份与恢复演练手册）

本文定义 ZhiXing Travel Planner 在 M1 受控试运行中的备份、恢复演练和回滚边界。生产化判断不能只看服务能启动，还必须证明关键数据可以备份、可以恢复、恢复后能重新通过 readiness（就绪检查）和 acceptance smoke（验收冒烟）。

## 1. 备份范围

| 对象 | 是否必须备份 | 原因 | M1 策略 |
|---|---|---|---|
| 代码发布包 | 必须 | 回滚到上一版本 | 每次发布前保留上一版本归档或目录备份 |
| `.env` | 必须受控保存 | 真实配置和密钥入口 | 只在服务器或密钥系统保存，不进入 Git，不放入公开备份包 |
| PostgreSQL（关系型数据库） | 必须 | 用户、会话、消息、审批、工具审计、LangGraph checkpoint/store | 每次发布前备份，至少每日备份 |
| Redis（缓存数据库） | 建议 | 会话锁、短期运行状态 | 开启持久化；M1 记录是否可接受丢失活跃会话 |
| RAG（检索增强生成）向量库 | 必须有恢复路径 | 公开攻略和内部知识库检索 | 可备份生成目录，也可记录语料版本并重建 |
| `data/documents/` | 必须 | RAG 重建源数据 | Git 中只保留安全样例；私有脱敏语料留在受控存储 |
| 日志 | 按需 | 排障和审计 | 保留脱敏日志摘要；不备份真实密钥或完整 token |
| Caddy 数据 | 建议 | TLS（传输层安全协议）证书和反向代理状态 | 可由 Caddy 重签，但备份可减少恢复时间 |

## 2. 备份位置和保留周期

M1 最低要求：

| 项目 | 要求 |
|---|---|
| 本机备份目录 | 服务器上的受控目录，例如 `$ZHIXING_BACKUP_DIR` |
| 异地备份 | 至少一个对象存储、云盘快照或受控下载位置 |
| 加密 | 含 `.env`、数据库 dump（导出文件）或私有语料的备份必须加密或放入受控存储 |
| 保留周期 | M1 至少保留最近 7 天每日备份和最近 3 次发布前备份 |
| 恢复演练 | 首次试运行前至少完成一次非生产环境恢复演练 |

不要把真实备份文件、数据库 dump、`.env`、向量库或日志原文提交到 Git。

如果备份或恢复演练在 Docker（容器运行工具）容器内执行，先确认容器内备份目录确实挂载到了宿主机或受控存储。否则演练产物可能只留在容器可写层里，容器重建后丢失：

```sh
docker inspect zhixing-backend --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

期望能看到受控宿主目录或共享目录挂载到 `/app/backups`。如果当前发布版还没有该挂载，恢复演练可以先用 `docker cp` 把脱敏证据和生成向量库复制到服务器受控备份目录，但这只能作为过渡措施；后续发布应把备份目录挂载纳入 Compose（容器编排配置）并复验。

可以先生成备份/恢复演练证据计划。默认不读取 `.env`、不连接数据库、不扫描备份目录：

```sh
python scripts/collect_backup_restore_drill_evidence.py --json
```

目标环境完成发布前备份后，再显式收集脱敏证据。该命令只记录目录、备份文件数量、最新 dump 元数据和 `pg_restore --list` 结果，不输出真实备份路径、文件名或 dump 内容：

```sh
python scripts/collect_backup_restore_drill_evidence.py \
  --include-readiness \
  --check-backup-dir \
  --check-latest-dump \
  --check-pg-restore-list \
  --require-restore-drill-declaration \
  --json
```

注意：`pg_restore --list` 只能证明 dump catalog（备份目录清单）可读，不能替代把 dump 恢复到非生产库并跑 readiness 和 smoke。

做真实恢复演练前，先用已有备份探针和容量快照做安全预检。该命令不连接服务器、不读取 dump 内容、不启动容器，只判断备份格式、备份新鲜度和恢复工作区磁盘空间是否足够：

```sh
python scripts/check_restore_drill_feasibility.py \
  --backup-schedule-json <private-workdir>/backup-schedule-live-probe.json \
  --capacity-json <private-workdir>/server-capacity-snapshot.json \
  --markdown \
  --output <private-workdir>/restore-drill-feasibility.md
```

如果该预检因为磁盘空间、水位或备份格式返回 `blocked`，不要在同一台服务器上直接启动 restore drill。应先清理受控 Docker image、扩容磁盘、挂载外部恢复工作区，或把恢复演练迁移到独立非生产机器。

预检通过后，可以执行一次 PostgreSQL 非生产恢复演练。该脚本通过 SSH 在目标服务器上选择 PostgreSQL dump，启动临时 PostgreSQL 容器，执行 `pg_restore --list` 和实际恢复，然后记录 catalog 行数、恢复状态、表数量和临时容器清理状态。它不覆盖生产库，不输出 SSH 目标、部署目录、备份路径、dump 内容、凭据或真实行数据：

```powershell
uv run python scripts\collect_postgres_restore_drill_live_probe.py `
  --ssh-target <ssh-user>@<server-host> `
  --deploy-dir <deploy-dir> `
  --timeout-seconds 300 `
  --output <private-workdir>\postgres-restore-drill-live-probe.json

uv run python scripts\collect_postgres_restore_drill_live_probe.py `
  --ssh-target <ssh-user>@<server-host> `
  --deploy-dir <deploy-dir> `
  --timeout-seconds 300 `
  --markdown `
  --output <private-workdir>\postgres-restore-drill-live-probe.md
```

如果已有明确受控备份目录，增加 `--backup-dir <private-backup-dir-outside-git>`；否则脚本只做发现式扫描，并优先选择部署目录外的 PostgreSQL dump。该证据证明一次 dump 可恢复性，不证明 PITR（时间点恢复）、异地灾备、多可用区高可用或自动故障转移。

如果要把备份/恢复证据映射回 PostgreSQL / Redis 运维声明，先生成候选声明报告：

```powershell
uv run python scripts\render_postgres_redis_backup_declaration_candidates.py `
  --backup-schedule-json <private-workdir>\backup-schedule-live-probe.json `
  --backup-restore-json <private-workdir>\postgres-restore-drill-live-probe.json `
  --restore-feasibility-json <private-workdir>\restore-drill-feasibility.json `
  --markdown `
  --output <private-workdir>\postgres-redis-backup-declaration-candidates.md
```

该报告只处理 `ZHIXING_POSTGRES_BACKUP_STATUS` 和 `ZHIXING_POSTGRES_RESTORE_DRILL_STATUS`。新鲜备份证据可以让 backup status 进入候选状态；restore drill status 必须等 `pg_restore --list` / catalog 检查加非生产恢复演练证据通过后才能进入候选状态。旧的 `collect_backup_restore_drill_evidence.py` 仍可用于 catalog 和声明型证据，但 M1 更推荐引用 `collect_postgres_restore_drill_live_probe.py` 生成的真实恢复演练证据。

如果候选报告显示 `ZHIXING_POSTGRES_BACKUP_STATUS=candidate_ready`，但 `ZHIXING_POSTGRES_RESTORE_DRILL_STATUS=blocked`，先看 `restore-drill-feasibility` 的阻塞原因。若阻塞来自恢复工作区空间不足，应刷新只读存储探针并生成扩容/挂盘申请：

```powershell
uv run python scripts\collect_storage_expansion_readiness.py `
  --ssh-target <ssh-user>@<server-host> `
  --deploy-dir <deploy-dir> `
  --required-free-mb 4096 `
  --output <private-workdir>\storage-expansion-readiness-current-refresh.json

uv run python scripts\render_storage_expansion_request.py `
  --storage-readiness-json <private-workdir>\storage-expansion-readiness-current-refresh.json `
  --post-cleanup-json <private-workdir>\disk-remediation-post-cleanup.json `
  --go-no-go-json <private-workdir>\m1-current-go-no-go.json `
  --output <private-workdir>\storage-expansion-request-current-refresh.md
```

扩容或挂载外部恢复工作区完成后，再重新运行 restore feasibility、备份/恢复声明候选、接受记录和 env patch。不要为了让状态变绿而把 `ZHIXING_POSTGRES_RESTORE_DRILL_STATUS` 手工写成 `passed`。

线上服务器可额外执行只读备份调度探针。该命令通过 SSH（安全外壳协议）读取目录元数据和 cron/systemd（定时任务/系统服务定时器）摘要，不读取 `.env`、数据库行、Redis key、日志、dump 内容或向量库内容，也不输出真实服务器、部署目录、备份目录、备份文件名或调度行：

```sh
python scripts/collect_backup_schedule_live_probe.py \
  --ssh-target <ssh-user>@<server-host> \
  --deploy-dir <deploy-dir> \
  --backup-dir <private-backup-dir-outside-git> \
  --timeout-seconds 90 \
  --json \
  --output <private-workdir>/backup-schedule-live-probe.json

python scripts/collect_backup_schedule_live_probe.py \
  --report-json <private-workdir>/backup-schedule-live-probe.json \
  --markdown \
  --output <private-workdir>/backup-schedule-live-probe.md
```

如果备份文件新鲜、RAG 恢复产物和代码回滚目录存在，但没有 cron/systemd 调度证据，结论应写为 `degraded`，不能写成“自动化备份已生产化”。如果最新 PostgreSQL dump 过期、过小或找不到，结论应写为 `blocked`。

如果暂时没有显式 `--backup-dir`，该探针可以只用 `--ssh-target` 和 `--deploy-dir` 做发现式扫描，范围包括部署目录、`/opt` 和 `/var/backups`。这种结果可以作为“线上存在备份产物和调度痕迹”的私有证据，但最终 M1 上线记录仍必须声明受控备份目录、保留周期、恢复负责人和恢复演练结果。

M1 可以使用仓库内的安全脚本安装每日 cron（定时任务）。两个脚本都默认 dry-run（只演练不落盘），只有显式加 `--execute` 才会创建备份或写入 `/etc/cron.d`：

```sh
sh deploy/run-backup.sh \
  --deploy-dir <deploy-dir> \
  --backup-root <private-backup-dir-outside-git>

sh deploy/install-backup-cron.sh \
  --deploy-dir <deploy-dir> \
  --backup-root <private-backup-dir-outside-git> \
  --schedule "17 3 * * *"
```

确认 dry-run 输出无异常后，才执行：

```sh
sh deploy/run-backup.sh \
  --execute \
  --deploy-dir <deploy-dir> \
  --backup-root <private-backup-dir-outside-git>

sh deploy/install-backup-cron.sh \
  --execute \
  --deploy-dir <deploy-dir> \
  --backup-root <private-backup-dir-outside-git> \
  --schedule "17 3 * * *"
```

`run-backup.sh` 会生成 PostgreSQL custom dump、`pg_restore --list` catalog 检查、Redis 数据目录快照、RAG 语料/向量库归档和脱敏 `backup-summary.json`。脚本不打印 `.env`、数据库连接串、密码、备份路径或文件名。`install-backup-cron.sh` 只写 cron 配置，不直接读取密钥；cron 行只包含路径和执行命令，不包含 API key 或数据库密码。安装后复跑 `collect_backup_schedule_live_probe.py`，只有发现调度证据且 cron/crond 进程处于 active，才可把 `backup_schedule_live` 写成 `passed`。

## 3. 发布前备份

以下命令示例在服务器上执行。执行前只确认变量存在，不打印 `.env` 内容。

```sh
cd "$ZHIXING_DEPLOY_DIR"
set -a
. ./.env
set +a

backup_stamp="$(date +%Y%m%d%H%M%S)"
backup_root="${ZHIXING_BACKUP_DIR:-./backups}"
backup_dir="$backup_root/$backup_stamp"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
```

### 3.1 代码和配置摘要

代码备份只备公开项目文件，不复制 `.env` 到公开归档：

```sh
git rev-parse --short HEAD > "$backup_dir/release_commit.txt" 2>/dev/null || true
docker compose ps > "$backup_dir/docker-compose-ps.txt"
```

`.env` 若需要备份，只能进入受控密钥备份位置。公开验收记录只写“已备份/未备份”，不写内容。

### 3.2 PostgreSQL 备份

使用 PostgreSQL 容器内的环境变量导出 custom format（自定义归档格式），方便后续 `pg_restore` 验证：

```sh
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
  > "$backup_dir/postgres.dump"

test -s "$backup_dir/postgres.dump"
docker compose exec -T postgres sh -c \
  'pg_restore --list' \
  < "$backup_dir/postgres.dump" \
  > "$backup_dir/postgres-dump-list.txt"
```

如果使用托管 PostgreSQL，优先使用云厂商快照或托管备份；仍需保留一次可恢复的逻辑备份或明确恢复流程。

### 3.3 Redis 备份

Redis 对 M1 不是长期事实来源，但丢失可能影响活跃会话。先触发持久化，再备份数据目录：

```sh
docker compose exec -T redis sh -c \
  'if [ -n "$REDIS_PASSWORD" ]; then redis-cli -a "$REDIS_PASSWORD" BGSAVE; else redis-cli BGSAVE; fi'

docker cp zhixing-redis:/data "$backup_dir/redis-data"
```

如果业务确认可以接受试运行时丢失活跃会话，验收记录里写清楚 Redis 恢复策略和影响范围。

### 3.4 RAG 向量库和语料

RAG 向量库可以备份，也可以通过语料和初始化脚本重建。M1 必须二选一并记录：

```sh
tar -czf "$backup_dir/rag-vectorstores.tgz" data/vectorstore data/vectorstore_internal 2>/dev/null || true
tar -czf "$backup_dir/rag-documents.tgz" data/documents
```

备份后复跑：

```sh
docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --json
docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

注意：私有脱敏语料和生成向量库属于运行时数据，不进入 Git。

## 4. 恢复演练

恢复演练必须先在非生产环境执行，不直接覆盖生产数据库。

### 4.1 PostgreSQL dump 可恢复性检查

优先使用仓库脚本生成脱敏证据：

```powershell
uv run python scripts\collect_postgres_restore_drill_live_probe.py `
  --ssh-target <ssh-user>@<server-host> `
  --deploy-dir <deploy-dir> `
  --backup-dir <private-backup-dir-outside-git> `
  --timeout-seconds 300 `
  --markdown `
  --output <private-workdir>\postgres-restore-drill-live-probe.md
```

必要时也可以在服务器上手工用临时容器验证 dump 能否恢复：

```sh
docker run -d --rm \
  --name zhixing-postgres-restore-check \
  -e POSTGRES_PASSWORD=<temporary-restore-check-password> \
  -e POSTGRES_DB=restore_check \
  pgvector/pgvector:pg17

sleep 10
cat "$backup_dir/postgres.dump" | docker exec -i zhixing-postgres-restore-check \
  pg_restore -U postgres -d restore_check --no-owner --no-acl

docker exec zhixing-postgres-restore-check psql -U postgres -d restore_check -c '\dt'
docker stop zhixing-postgres-restore-check
```

恢复演练只记录表数量、恢复结果和错误摘要，不记录真实行数据。

### 4.2 RAG 重建检查

如果选择“从语料重建”而不是备份向量库，恢复演练必须证明：

```sh
docker compose exec -T backend python -m scripts.init_rag
docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --json
docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

如果该步骤缺少真实 LLM、embedding 或语料，结论写 `blocked`，不能写恢复成功。

### 4.3 应用恢复检查

恢复后至少执行：

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
docker compose exec -T backend python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url "$ZHIXING_PUBLIC_BASE_URL" --json
```

只有这些检查通过，才可以把恢复演练写为 `passed`。

恢复演练完成后，把以下状态写入目标环境变量或受控记录，再用证据脚本收束：

```text
ZHIXING_POSTGRES_BACKUP_STATUS=passed
ZHIXING_POSTGRES_RESTORE_DRILL_STATUS=passed
ZHIXING_RAG_RESTORE_DRILL_STATUS=passed
ZHIXING_RESTORE_DRILL_OWNER=<owner>
ZHIXING_ACCEPTABLE_DATA_LOSS=<window>
```

公开记录只写变量名和 `passed / blocked / not run`，不写负责人真实联系方式、备份路径、dump 文件名或日志原文。

## 5. 回滚策略

回滚分三层：

| 层级 | 适用场景 | 优先动作 |
|---|---|---|
| 应用回滚 | 新代码导致错误率升高、报告异常、前端不可用 | 回滚代码和镜像，不动数据库 |
| 配置回滚 | 新密钥、外部 API、CORS（跨域资源共享）或超时配置异常 | 恢复上一版 `.env` 或密钥配置 |
| 数据恢复 | 迁移或数据写入造成不可接受损坏 | 先停止写入，再从备份恢复到新环境验证，最后决定切换 |

生产数据恢复必须先确认：

- 当前故障不能通过应用回滚或配置回滚解决。
- 已停止会继续写坏数据的服务入口。
- 备份文件可读且恢复演练成功。
- 恢复会丢失哪些时间窗口内的数据已经被接受。
- 负责人和回滚窗口明确。

## 6. 验收记录字段

每次 M1 试运行至少记录：

| 字段 | 内容 |
|---|---|
| `backup_id` | 时间戳或备份编号 |
| `release_commit` | 发布 commit |
| `postgres_backup` | passed / blocked / not run |
| `postgres_restore_drill` | passed / blocked / not run |
| `redis_backup` | passed / blocked / not run |
| `rag_restore_path` | backup / rebuild / blocked |
| `rollback_ready` | yes / no |
| `data_loss_window` | 可接受丢失窗口 |
| `backup_freshness_live` | passed / blocked / not run |
| `backup_schedule_live` | passed / degraded / blocked / not run |
| `evidence_location` | 只写受控位置类型，不写真实敏感路径 |

## 7. 需要用户准备的信息

请只确认状态，不发送真实密钥或备份文件：

| 字段 | 示例 |
|---|---|
| `backup_target` | 服务器本机目录 / 云盘快照 / 对象存储 |
| `backup_retention` | 最近 7 天每日备份 + 最近 3 次发布前备份 |
| `backup_encryption` | 云厂商默认加密 / 自管加密 / 待定 |
| `restore_owner` | 谁能执行恢复演练 |
| `backup_window` | 每日低峰时段 |
| `backup_schedule_status` | cron/systemd 已配置 / 手工备份过渡 / 未配置 |
| `acceptable_data_loss` | M1 可接受最多丢失 X 小时测试数据 |
| `postgres_backup_status` | passed / blocked / not run |
| `postgres_restore_drill_status` | passed / blocked / not run |
| `rag_restore_drill_status` | passed / blocked / not run |
| `rag_restore_strategy` | 备份向量库 / 从语料重建 |
| `redis_restore_strategy` | 恢复 AOF/RDB / 可接受活跃会话丢失 |

## 8. 禁止事项

- 不在公开文档、聊天记录或提交说明中写真实备份路径、数据库连接串、密钥或账号口令。
- 不把 `.env`、数据库 dump、Redis 数据、向量库或日志原文提交到 Git。
- 不在生产数据库上直接做第一次恢复演练。
- 不用 `git reset --hard`、批量删除或清空目录来“清理部署”。
- 不把只做了备份但未恢复演练的状态写成“已具备恢复能力”。
- 不把“手工备份新鲜”写成“定时备份、异地备份、PITR 或完整灾备已完成”。
