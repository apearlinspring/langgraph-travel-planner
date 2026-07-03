# M1 Operations Evidence Playbook（运行证据手册）

本文把 M1 受控试运行中的运行问题按工程域归类，说明每类问题应收集什么证据、如何处置、如何复验，以及最终能写成什么结论。它是公开工程手册，不记录真实服务器地址、SSH 用户、`.env`、密钥、数据库备份文件名、日志原文、截图或私有路径。

## 1. 使用边界

本手册只服务于 M1 受控试运行，不把项目包装成完整生产高可用系统。

M1 可以证明：

- 服务在真实目标环境中完成一次受控发布。
- PostgreSQL（关系型数据库）和 Redis（缓存数据库）的运行形态、持久化、健康检查和恢复边界有记录。
- 低风险并发、限流、备份、回滚、磁盘容量、外部依赖降级和最终签核有可复跑证据。
- 模拟订单确认页可用，但不触发真实支付、预订、锁价、出票或履约。

M1 不能证明：

- 自动扩缩容、多地域高可用或长时间压测已经完成。
- 真实支付、真实库存锁定、真实订单履约已经打通。
- 所有供应商、网络、云资源和数据库故障都已覆盖。
- 所有证据都可以提交到公开仓库；私有证据必须留在仓库外。

## 2. 总体证据链

一次 M1 运行应按以下顺序沉淀证据：

| 阶段 | 主要命令 | 证据用途 |
|---|---|---|
| 输入声明 | `uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json` | 证明服务器、域名、备份、监控、负责人和预算等非密钥输入已声明 |
| 服务器预检 | `uv run python scripts\check_server_preflight_readiness.py --json` | 证明部署目录、Docker、域名、TLS、端口、反向代理等前置状态已声明 |
| 线上只读探针 | `uv run python scripts\run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --execute` | 收集 live server、PostgreSQL/Redis、备份调度、容量、并发、限流、probe auth 等私有证据 |
| 上线执行记录 | `uv run python scripts\check_m1_rollout_execution_record.py --record-json <private-workdir>\m1-rollout-execution-record.local.json --output <private-workdir>\m1-rollout-execution-report.json` | 证明发布包、部署阶段、健康检查、回滚准备和数据安全已人工记录并校验 |
| 运维复盘记录 | `uv run python scripts\check_m1_operations_review_record.py --record-json <private-workdir>\m1-operations-review-record.local.json --output <private-workdir>\m1-operations-review-report.json` | 证明问题、根因、处置、复验、恢复演练可行性、磁盘处置审批、经验和后续项已记录 |
| 当前总判定 | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-restore-drill-feasibility --restore-drill-feasibility-json <private-workdir>\restore-drill-feasibility.json --include-disk-remediation-approval --disk-remediation-approval-json <private-workdir>\disk-remediation-approval-gate.json --include-docker-build-cache-cleanup-approval --docker-build-cache-cleanup-approval-json <private-workdir>\docker-build-cache-cleanup-approval-gate.json --include-docker-build-cache-post-cleanup --docker-build-cache-post-cleanup-json <private-workdir>\docker-build-cache-post-cleanup.json --json --output <private-workdir>\m1-current-go-no-go.json` | 把恢复演练安全门禁、镜像清理审批门禁、build cache 清理审批和清理后复盘纳入 no-go / conditional / go 判定 |
| 私有签核 | `uv run python scripts\check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-owner <release-owner> --output <private-workdir>\m1-live-evidence-workflow\signoff.json` | 证明私有证据哈希、go/no-go、人工报告和 release-owner 签核一致 |
| 证据矩阵 | `uv run python scripts\render_m1_deployment_evidence_matrix.py --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json --markdown --output <private-workdir>\m1-deployment-evidence-matrix.md` | 把输入、go/no-go、上线执行、运维复盘和签核汇成一张脱敏矩阵；后续补充证据用 `--supplemental-go-no-go-json` 单独列入 supplemental evidence |

所有 `<private-workdir>` 都必须在 Git 工作区外。公开仓库只保留脚本、模板和安全样例，不保留真实运行结果。

### 2.1 Release pointer 与 Compose project 身份

首部署或运行镜像刷新命令通常在 `<deploy-dir>/current` 下执行。`current` 是 release pointer（发布指针），不是一个稳定的 Compose project（Compose 项目名）。如果没有显式固定 project 名，Compose 可能把 `current` 当成新项目，并在已有固定容器名的服务器上触发容器名冲突。

处置原则：

- `first-deploy.sh` 和 `update-runtime-image.sh` 默认固定 `ZHIXING_COMPOSE_PROJECT_NAME=langgraph-travel-planner`，需要变更时必须显式覆盖并写入复盘。
- 如果已经发生 project 名冲突，先确认现有 PostgreSQL 和 Redis 所在 project 与 volume 边界，再只重建 backend / edge 这类无状态服务。
- 不因为容器名冲突删除 PostgreSQL、Redis、volume、备份、日志、`.env` 或向量库。
- 修复后至少复验 rollout execution record、public health smoke、live server probe、server capacity snapshot 和 operations review record。

判断口径：

| 状态 | 说明 |
|---|---|
| `passed` | Compose project 名固定，backend / edge 刷新后健康，PostgreSQL / Redis 保持在原 project 和 volume 边界内 |
| `degraded` | 发生过 project 名冲突但已通过无状态服务重建恢复，且复盘记录列出根因、处置和后续修复 |
| `blocked` | 需要删除或迁移状态服务才能恢复，或无法确认 PostgreSQL / Redis volume 边界 |

## 3. 认证与聊天业务链路

### 3.1 需要回答的运行问题

- 线上公开地址是否能完成健康检查。
- 探针账号是否能注册或登录，且凭据不进入 Git、日志或验收摘要。
- 能否创建会话并完成一轮 SSE（服务器发送事件）聊天流。
- 该探针是否清楚标注可能调用 LLM（大语言模型）或外部 API。
- 是否明确不触发真实支付、真实预订、锁价、出票或履约。

### 3.2 证据命令

无论是否已有探针账号，执行真实聊天探针前都必须先生成并校验审批 report：

```powershell
uv run python scripts\check_live_chat_probe_execution_approval.py --template --output <private-workdir>\live-chat-probe-execution-approval.local.json
uv run python scripts\check_live_chat_probe_execution_approval.py --approval-json <private-workdir>\live-chat-probe-execution-approval.local.json --json --output <private-workdir>\live-chat-probe-execution-approval-report.json
```

已有探针账号时：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py `
  --base-url <public-url> `
  --include-smoke-evidence --check-health-url `
  --include-live-chat-probe --execute-live-chat-probe `
  --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json `
  --live-chat-username-env ZHIXING_PROBE_USERNAME `
  --live-chat-password-env ZHIXING_PROBE_PASSWORD `
  --json --output <private-workdir>\m1-business-link-go-no-go.json
```

需要创建探针账号时，必须额外提供 `ZHIXING_PROBE_EMAIL` 并显式打开注册开关：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py `
  --base-url <public-url> `
  --include-smoke-evidence --check-health-url `
  --include-live-chat-probe --execute-live-chat-probe --register-live-chat-probe-user `
  --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json `
  --live-chat-username-env ZHIXING_PROBE_USERNAME `
  --live-chat-password-env ZHIXING_PROBE_PASSWORD `
  --live-chat-email-env ZHIXING_PROBE_EMAIL `
  --json --output <private-workdir>\m1-business-link-go-no-go.json
```

`live-chat-probe-execution-approval-report.json` 必须为 `passed` 后才能执行聊天探针。该 approval checker（审批检查器）只读私有 JSON，不触网、不调用登录/聊天、不注册用户、不读 `.env`。

如果只是准备证据而未获准写线上测试用户或会话，保留计划态：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py --base-url <public-url> --include-smoke-evidence --check-health-url --include-live-chat-probe --json --output <private-workdir>\m1-business-link-gap-go-no-go.json
```

### 3.3 小流量 chat 并发采样

完成一轮单请求 chat SSE 探针后，可以在明确获批的前提下执行极小样本并发采样。该动作会创建少量探针会话并可能调用 LLM 或外部 API，但仍不是 load test（压测），不能写成高并发容量结论。

审批与执行命令：

```powershell
uv run python scripts\check_live_chat_concurrency_probe_approval.py --template --output <private-workdir>\live-chat-concurrency-probe-approval.local.json
uv run python scripts\check_live_chat_concurrency_probe_approval.py --approval-json <private-workdir>\live-chat-concurrency-probe-approval.local.json --json --output <private-workdir>\live-chat-concurrency-probe-approval-report.json
uv run python scripts\collect_live_chat_concurrency_probe.py `
  --base-url <public-url> `
  --approval-json <private-workdir>\live-chat-concurrency-probe-approval-report.json `
  --username-env ZHIXING_PROBE_USERNAME `
  --password-env ZHIXING_PROBE_PASSWORD `
  --email-env ZHIXING_PROBE_EMAIL `
  --register-probe-user `
  --execute `
  --request-count 3 `
  --concurrency 2 `
  --timeout-seconds 120 `
  --max-p95-total-seconds 120 `
  --max-blocked-rate 0.34 `
  --output <private-workdir>\live-chat-concurrency-probe.json
uv run python scripts\collect_live_chat_concurrency_probe.py --report-json <private-workdir>\live-chat-concurrency-probe.json --markdown --output <private-workdir>\live-chat-concurrency-probe.md
```

把该证据接入 M1 总判定时，只读取已生成的脱敏 JSON，不再次调用线上 chat：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py `
  --include-live-chat-concurrency-probe `
  --live-chat-concurrency-probe-json <private-workdir>\live-chat-concurrency-probe.json `
  --json `
  --output <private-workdir>\m1-go-no-go.live-chat-concurrency-supplement.json
```

把补充 go/no-go 接入最终矩阵时，使用 supplemental evidence，不把它写成旧 private signoff 已覆盖：

```powershell
uv run python scripts\render_m1_deployment_evidence_matrix.py `
  --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json `
  --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json `
  --rollout-report-json <private-workdir>\m1-rollout-execution-report.json `
  --operations-review-report-json <private-workdir>\m1-operations-review-report.json `
  --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json `
  --supplemental-go-no-go-json <private-workdir>\m1-go-no-go.live-chat-concurrency-supplement.json `
  --markdown `
  --output <private-workdir>\m1-deployment-evidence-matrix.with-chat-concurrency-supplement.md
```

如果要让该补充证据拥有独立 workflow/signoff 覆盖，可把已生成的脱敏 JSON 导入单独工作流。该流程只读取证据文件，不重新执行线上 chat，不调用外部 API，也不代表旧基线签核范围被自动扩大：

```powershell
uv run python scripts\run_m1_private_live_evidence_workflow.py `
  --output-dir <private-workdir>\m1-live-evidence-workflow-chat-concurrency-import `
  --include-live-chat-concurrency-probe `
  --live-chat-concurrency-probe-json <private-workdir>\live-chat-concurrency-probe.json `
  --execute `
  --json
uv run python scripts\check_m1_private_evidence_signoff.py `
  --workflow-report-json <private-workdir>\m1-live-evidence-workflow-chat-concurrency-import\workflow-report.json `
  --signoff-owner <release-owner> `
  --no-require-standard-live-sections `
  --output <private-workdir>\m1-live-evidence-workflow-chat-concurrency-import\signoff.json
uv run python scripts\check_m1_private_evidence_signoff.py `
  --workflow-report-json <private-workdir>\m1-live-evidence-workflow-chat-concurrency-import\workflow-report.json `
  --signoff-owner <release-owner> `
  --no-require-standard-live-sections `
  --markdown `
  --output <private-workdir>\m1-live-evidence-workflow-chat-concurrency-import\signoff.md
```

判断口径：

| 状态 | 说明 |
|---|---|
| `passed` | 请求数和并发数不超过审批上限，所有或足够多的 chat SSE 样本完成，错误率和 P95 总耗时满足阈值，输出不回显 URL、token、账号、密码、邮箱、prompt、会话 id 或助手正文 |
| `degraded` | 小样本完成但存在个别 blocked 样本、首事件/首 token/总耗时偏慢，或样本量太小只能作为受控试运行证据 |
| `blocked` | 审批 report 未通过、请求数超审批上限、认证失败、会话创建失败、SSE 错误、超时或 blocked rate 超阈值 |

### 3.4 公开口径

可以说：M1 已完成一轮认证 + chat SSE 单请求探针，以及一次 3 请求、并发 2 的 chat 小流量采样。

不能说：M1 已完成 chat 高并发压测、长时间 soak、自动扩缩容验证或供应商长期 SLA 验证。

### 3.5 判断口径

| 状态 | 说明 |
|---|---|
| `passed` | 健康检查、探针认证、会话创建和一轮 SSE 聊天均通过，且输出不回显 URL、token、账号、密码、邮箱、prompt、会话 id 或助手正文 |
| `degraded` | 聊天完成但首事件、首 token 或总耗时超过阈值；或只覆盖单轮采样，不能证明并发吞吐和长稳 |
| `blocked` | 探针账号缺失、审批 report 未通过、未获准执行、认证失败、会话创建失败、SSE 错误、超时或 `live_chat_probe=not_checked` |

### 3.6 处置和复验

- 缺探针账号时，不要临时使用个人账号；准备仓库外 `ZHIXING_PROBE_USERNAME`、`ZHIXING_PROBE_PASSWORD` 和 `ZHIXING_PROBE_EMAIL` 后再执行。
- 认证失败先查 `/api/v1/users/login`、JWT（JSON Web Token，身份令牌）配置、Cookie secure/samesite 和反向代理头，不直接改数据库。
- 会话创建失败先查 PostgreSQL 健康、迁移状态和用户权限；不要把 health endpoint 通过写成聊天链路通过。
- SSE 超时先区分 LLM 响应慢、外部 API 卡住、会话锁阻塞和反向代理超时。
- 复验后把 `m1-business-link-go-no-go.json` 接入 acceptance record；如果仍是 `not_checked`，最终 M1 必须保持 `no_go`。

## 4. PostgreSQL / Redis

### 4.1 需要回答的运行问题

- PostgreSQL 和 Redis 是 Compose 内置服务还是托管服务。
- 数据是否持久化到 Docker volume 或托管实例，而不是容器临时层。
- PostgreSQL 是否可连接，Redis 是否可 `PING`。
- Redis 是否承担会话锁和限流计数，且生产 fallback 是否关闭。
- 备份、恢复演练、RPO（恢复点目标）和 RTO（恢复时间目标）是否有声明。

### 4.2 证据命令

```powershell
uv run python scripts\check_postgres_redis_ops_status.py --check-compose --json
uv run python scripts\collect_postgres_redis_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown
uv run python scripts\check_postgres_redis_recovery_record.py --template --output <private-workdir>\postgres-redis-recovery-record.local.json
uv run python scripts\check_postgres_redis_recovery_record.py --record-json <private-workdir>\postgres-redis-recovery-record.local.json --output <private-workdir>\postgres-redis-recovery-report.json
```

### 4.3 判断口径

| 状态 | 说明 |
|---|---|
| `passed` | PostgreSQL/Redis 模式、持久化、健康检查、密钥状态、备份恢复和 Redis fail-closed 边界齐备 |
| `degraded` | 单机 Compose、端口暴露需依赖安全组、恢复演练未完全自动化等 M1 可接受但不能夸大的状态 |
| `blocked` | 容器不健康、无持久化 mount、Redis fallback 打开、密钥/备份状态不清、恢复记录缺失 |

### 4.4 处置和复验

- PostgreSQL 不健康时，先看 `docker compose ps postgres`、`pg_isready` 和 `/health/ready`，不要直接改表或删除 volume。
- Redis 不健康时，先确认 `SESSION_LOCK_BACKEND=redis`、`SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false` 和 Redis `PING` 结果；多实例场景不能退回本地锁。
- 处理后复跑 `collect_postgres_redis_live_probe.py`，并在 `check_m1_operations_review_record.py` 的 `postgres_redis_ops` 证据引用里写入最终状态。

## 5. 并发与限流

### 5.1 需要回答的运行问题

- 低风险接口在短窗口并发下是否能稳定返回。
- Mock checkout status endpoint 是否受限流保护。
- 429 是否带 `Retry-After` 或 `X-RateLimit-*` 头。
- Redis 作为限流后端不可用时是否 fail closed，而不是退回本地计数。

### 5.2 证据命令

```powershell
uv run python scripts\collect_live_concurrency_probe.py --base-url <public-url> --requests-per-endpoint 30 --concurrency 10 --timeout-seconds 5 --max-p95-ms 2000 --markdown --output <private-workdir>\live-concurrency-probe.md
uv run python scripts\collect_rate_limit_live_probe.py --base-url <public-url> --request-count 160 --concurrency 16 --timeout-seconds 10 --output <private-workdir>\rate-limit-live-probe.json
uv run python scripts\collect_rate_limit_live_probe.py --report-json <private-workdir>\rate-limit-live-probe.json --markdown --output <private-workdir>\rate-limit-live-probe.md
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --template --output <private-workdir>\concurrency-rate-limit-record.local.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --draft-from-probes --concurrency-probe-json <private-workdir>\live-concurrency-probe.json --rate-limit-probe-json <private-workdir>\rate-limit-live-probe.json --output <private-workdir>\concurrency-rate-limit-record.draft.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --record-json <private-workdir>\concurrency-rate-limit-record.local.json --output <private-workdir>\concurrency-rate-limit-report.json
```

### 5.3 判断口径

| 状态 | 说明 |
|---|---|
| `passed` | 采样接口错误率、P95 和限流响应满足阈值，429 头可观测，记录中说明 Redis 后端边界 |
| `degraded` | 采样通过但窗口短、接口低风险、未覆盖 SSE（服务器发送事件）聊天吞吐或长稳压测 |
| `blocked` | 低风险接口超时/错误率超阈值，限流未触发，429 头缺失，Redis fallback 边界不清 |

### 5.4 处置和复验

- 并发探针失败时，先区分应用错误、反向代理超时、数据库/Redis 阻塞和外部 API 卡顿。
- 限流探针失败时，先看是否因为串行请求跨过 rate-limit window（限流窗口）而没有打到 429；复验应使用 `--concurrency` 做 burst 采样，再检查 API rate limit 配置和 Redis backend；不要把单进程本地计数写成全局限流。
- 复验后把最终状态写入 `m1_operations_review_record` 的 `concurrency_rate_limit` 证据引用。

## 6. Docker 磁盘与容量

### 6.1 需要回答的运行问题

- 发布前磁盘水位是否允许构建/导入镜像。
- 当前运行容器占用是否可观测。
- Docker image cleanup plan 是否保护所有容器引用镜像。
- Docker build cache 是否有单独计划和审批边界。
- 清理是否经过单独批准，且不删除 volume、日志、`.env`、备份或向量库。

### 6.2 证据命令

```powershell
uv run python scripts\collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown --output <private-workdir>\server-capacity-snapshot.md
uv run python scripts\collect_docker_disk_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-candidates 20 --output <private-workdir>\docker-disk-cleanup-plan.json
uv run python scripts\execute_docker_disk_cleanup.py --plan-json <private-workdir>\docker-disk-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-delete-count 20 --markdown --output <private-workdir>\docker-disk-cleanup-dry-run.md
uv run python scripts\collect_docker_build_cache_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --output <private-workdir>\docker-build-cache-cleanup-plan.json
uv run python scripts\execute_docker_build_cache_cleanup.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --markdown --output <private-workdir>\docker-build-cache-cleanup-dry-run.md
uv run python scripts\check_docker_build_cache_cleanup_approval.py --template --output <private-workdir>\docker-build-cache-cleanup-approval.template.json
uv run python scripts\check_docker_build_cache_cleanup_approval.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --dry-run-json <private-workdir>\docker-build-cache-cleanup-dry-run.json --capacity-json <private-workdir>\server-capacity-snapshot.json --markdown --output <private-workdir>\docker-build-cache-cleanup-approval-gate.md
uv run python scripts\render_docker_build_cache_cleanup_approval_request.py --approval-gate-json <private-workdir>\docker-build-cache-cleanup-approval-gate.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\docker-build-cache-cleanup-approval-request.md
uv run python scripts\check_disk_remediation_approval.py --template --output <private-workdir>\docker-disk-remediation-approval.template.json
uv run python scripts\check_disk_remediation_approval.py --cleanup-plan-json <private-workdir>\docker-disk-cleanup-plan.json --dry-run-json <private-workdir>\docker-disk-cleanup-dry-run.json --capacity-json <private-workdir>\server-capacity-snapshot.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility.json --markdown --output <private-workdir>\disk-remediation-approval-gate.md
uv run python scripts\render_disk_remediation_approval_request.py --approval-gate-json <private-workdir>\disk-remediation-approval-gate.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\disk-remediation-approval-request.md
uv run python scripts\check_disk_remediation_post_cleanup.py --execution-json <private-workdir>\docker-disk-cleanup-execution.json --before-capacity-json <private-workdir>\server-capacity-snapshot.json --after-capacity-json <private-workdir>\server-capacity-snapshot-post-cleanup.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility-post-cleanup.json --markdown --output <private-workdir>\disk-remediation-post-cleanup.md
uv run python scripts\check_docker_build_cache_post_cleanup.py --execution-json <private-workdir>\docker-build-cache-cleanup-execution.json --before-capacity-json <private-workdir>\server-capacity-snapshot.json --after-capacity-json <private-workdir>\server-capacity-snapshot-post-build-cache-cleanup.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility-post-build-cache-cleanup.json --markdown --output <private-workdir>\docker-build-cache-post-cleanup.md
uv run python scripts\collect_storage_expansion_readiness.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --required-free-mb 4096 --markdown --output <private-workdir>\storage-expansion-readiness.md
uv run python scripts\render_storage_expansion_request.py --storage-readiness-json <private-workdir>\storage-expansion-readiness.json --post-cleanup-json <private-workdir>\disk-remediation-post-cleanup.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\storage-expansion-request.md
```

这些命令统一由脚本写入 UTF-8 文件，避免 Windows 重定向生成 UTF-16 证据文件。Docker 清理计划只显示 image id 前缀、大小估算和 tag 数量，不回显镜像 tag 原文。Docker build cache 计划只记录 `docker system df` 的聚合 build-cache 数量、大小和可回收空间，不删除缓存。`check_docker_build_cache_cleanup_approval.py` 只做 build cache 清理审批门禁，不连接 SSH、不清理缓存；缺少私有审批记录时只输出 `ready_for_explicit_approval`。`render_docker_build_cache_cleanup_approval_request.py` 只把 build cache gate / go-no-go 结果整理成脱敏审批请求，不代表已经批准执行。`execute_docker_build_cache_cleanup.py` 默认 dry-run；真实执行必须显式 `--execute --approval-token APPROVE_DOCKER_BUILD_CACHE_CLEANUP`，只运行 `docker builder prune -a -f`，不运行 `docker system prune`，不删除镜像、容器、volume、日志、`.env`、备份或向量库。`check_docker_build_cache_post_cleanup.py` 用于 build cache 清理后复盘：它只读取执行报告、容量快照和恢复演练可行性，判断清理是否真正解除容量阻塞。`check_disk_remediation_approval.py` 只做镜像清理审批门禁，不连接 SSH、不删除镜像；它要求私有审批记录明确禁止 `docker system prune`、删除容器、删除 volume、删除日志、删除 `.env`、删除备份和删除向量库。`render_disk_remediation_approval_request.py` 只把当前 gate / go-no-go 结果整理成脱敏审批请求，不代表已经批准执行。`check_disk_remediation_post_cleanup.py` 用于镜像清理后复盘：它只读取执行报告、清理前后容量快照和恢复演练可行性，判断清理是否真正解除容量阻塞；如果输出 `storage_expansion_required`，停止继续清理，改走扩容或挂载新盘。`collect_storage_expansion_readiness.py` 是只读拓扑探针，用于判断 root、部署目录和 Docker data-root 是否共用同一挂载点，以及是否存在可挂载的新块设备；它不回显设备名、挂载路径、SSH 目标或部署目录。`render_storage_expansion_request.py` 只生成扩容变更请求和扩容后验收命令，不执行云盘扩容、挂载或 Docker data-root 迁移。

### 6.3 判断口径

| 状态 | 说明 |
|---|---|
| `passed` | 容量快照正常，清理计划只读且无待处理风险，发布流程不受磁盘阻塞 |
| `degraded` | 磁盘接近阈值但有清理或扩容计划，M1 可条件放行 |
| `blocked` | 磁盘达到阻塞阈值，Docker build/import 不能继续，或清理计划会影响容器引用镜像/volume |

### 6.4 处置和复验

- 先收集 cleanup plan，再人工确认候选镜像，最后才执行 cleanup。
- 不使用 `docker system prune` 这类宽泛清理作为默认动作。
- 如果镜像已清完但 `docker system df` 显示 build cache 仍大，单独收集 build-cache cleanup plan；执行 build-cache cleanup 需要独立批准，且要记录未来构建可能变慢。
- 镜像清理执行前必须通过 `check_disk_remediation_approval.py`；build cache 清理执行前必须通过 `check_docker_build_cache_cleanup_approval.py`；如果状态是 `ready_for_explicit_approval`，说明证据足够提交审批，但还没有获准执行。
- 清理或扩容后复跑 `collect_server_capacity_snapshot.py` 和 `check_restore_drill_feasibility.py`，再用 `check_disk_remediation_post_cleanup.py` 做前后对比；如果清理释放空间很少，应记录为“镜像清理不足以恢复可用空间”，并转入扩容或挂载新盘。
- 扩容前先跑 `collect_storage_expansion_readiness.py`：如果 root、部署目录和 Docker data-root 共用同一挂载点且没有未挂载块设备，优先扩 root volume；如果存在足够大的未挂载块设备，可以规划挂载后迁移 Docker data-root 或恢复演练工作区。

## 7. 备份与恢复

### 7.1 需要回答的运行问题

- PostgreSQL dump 是否存在、是否可读、是否有保留周期。
- Redis 和 RAG 向量库是否有恢复路径。
- 是否完成过非生产恢复演练。
- 备份调度是否存在，还是只做了一次手工备份。

### 7.2 证据命令

```powershell
uv run python scripts\check_backup_restore_readiness.py --json
uv run python scripts\collect_backup_restore_drill_evidence.py --include-readiness --require-restore-drill-declaration --json --output <private-workdir>\backup-restore-drill-evidence.json
uv run python scripts\collect_backup_restore_drill_evidence.py --include-readiness --require-restore-drill-declaration --markdown --output <private-workdir>\backup-restore-drill-evidence.md
uv run python scripts\collect_backup_schedule_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --backup-dir <private-backup-dir-outside-git> --timeout-seconds 90 --output <private-workdir>\backup-schedule-live-probe.json
uv run python scripts\collect_backup_schedule_live_probe.py --report-json <private-workdir>\backup-schedule-live-probe.json --markdown --output <private-workdir>\backup-schedule-live-probe.md
uv run python scripts\check_restore_drill_feasibility.py --backup-schedule-json <private-workdir>\backup-schedule-live-probe.json --capacity-json <private-workdir>\server-capacity-snapshot.json --markdown --output <private-workdir>\restore-drill-feasibility.md
uv run python scripts\check_backup_alert_status.py --backup-dir <private-backup-dir-outside-git> --require-rag-restore-artifact --json
```

### 7.3 判断口径

| 状态 | 说明 |
|---|---|
| `passed` | 备份目标、保留策略、最新 dump、catalog 可读、RAG 恢复路径和调度证据齐备 |
| `degraded` | 有备份但缺自动调度、只完成 catalog 检查、恢复演练未完整跑通 |
| `blocked` | 备份目录不可写、dump 缺失或过期、恢复路径不明、备份告警缺失 |

### 7.4 处置和复验

- 发布前至少保留一次明确备份点。
- 真实恢复演练前先跑 `check_restore_drill_feasibility.py`；如果磁盘空间不足或备份格式不适合当前恢复命令，先清理、扩容或迁移演练环境。
- `pg_restore --list` 只能证明 catalog 可读，不能替代恢复到非生产库并跑 readiness/smoke。
- 复验后把结果写入 `backup_restore` 和 `restore_drill_feasibility` 证据引用，并在证据矩阵中汇总最终状态。

## 8. 发布回滚与事故响应

### 8.1 需要回答的运行问题

- 是否能回到上一 release，而不覆盖 `.env`、数据库 volume、Redis volume、日志或向量库。
- 回滚后是否重新跑 `/health/ready`、M1 gate 和 smoke。
- 是否有事故复盘记录和负责人。
- 数据恢复是否先经过非生产演练。

### 8.2 证据命令

```powershell
uv run python scripts\check_rollback_rehearsal_status.py --deploy-dir <deploy-dir> --backup-dir <rollback-backup-dir> --release-archive <release-archive> --expected-archive-sha256 <archive-sha256> --check-health --check-mock-checkout --json
uv run python scripts\check_rollback_execution_record.py --record-json <private-rollback-record.json> --json
uv run python scripts\check_incident_tabletop_status.py --record-json <private-tabletop-record.json> --json
uv run python scripts\collect_incident_rollback_evidence.py --json
```

### 8.3 判断口径

| 状态 | 说明 |
|---|---|
| `passed` | 回滚目标、命令、负责人、健康检查、M1 gate、事故复盘和数据安全边界齐备 |
| `degraded` | 只完成 tabletop（桌面演练）或 dry-run，未执行真实回滚 |
| `blocked` | 回滚目标不明、archive hash 缺失、会覆盖运行时数据、回滚后复验缺失 |

### 8.4 处置和复验

- 代码回滚和数据恢复分开处理；不要用代码回滚掩盖数据库 schema 问题。
- 外部 API 或密钥异常优先降级对应能力，不默认回滚全系统。
- 回滚后复验 health、mock checkout、M1 gate，再写 incident rollback evidence。

## 9. 最终复盘写法

每个运行问题都按同一结构写入私有复盘记录：

| 字段 | 写什么 |
|---|---|
| `signal` | 哪个脚本或 health 指标暴露问题 |
| `impact` | 对 M1 范围的影响，是否影响真实用户或只影响验证 |
| `root_cause` | 证据支持的根因；不确定时写待验证，不猜 |
| `action_taken` | 做了什么修复、降级、清理、扩容或回滚 |
| `verification` | 复跑了哪个脚本，状态从什么变成什么 |
| `risk_acceptance` | 如果仍为 degraded，谁接受、接受到什么边界 |
| `followups` | 后续自动化、监控、文档或容量计划 |

最终 `render_m1_deployment_evidence_matrix.py` 只汇总这些私有报告，不替代真实复盘。矩阵 `passed` 表示 M1 受控试运行证据链闭合；矩阵 `degraded` 表示可条件进入 M1 但必须有风险接受；矩阵 `blocked` 表示不能写成已上线通过。
