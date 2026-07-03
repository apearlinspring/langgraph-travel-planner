# M1 Launch Checklist（受控试运行上线总清单）

本文把 ZhiXing Travel Planner 的 M1 受控试运行准备项收束成一张总表。它不是完整生产上线批准书，而是进入“真实环境、真实依赖、内部或白名单用户、强人工兜底”前的最低检查清单。

PostgreSQL（关系型数据库）、Redis（缓存数据库）、Caddy（反向代理服务器）、并发和扩容处置见 `docs/部署与运行/postgres-redis-ops-runbook.md`。

## 0. 结论规则

M1 结论只能写以下状态：

| 状态 | 含义 |
|---|---|
| `passed` | 目标环境真实执行成功，且证据已脱敏记录。 |
| `degraded` | 核心链路可继续，但可选能力、监控或外部服务存在降级。 |
| `blocked` | 缺环境、缺密钥、缺备份、缺验收账号、服务不可达或必需门禁失败。 |
| `not run` | 尚未执行，不能推断为通过。 |
| `dry-run only` | 只验证了计划或场景列表，没有证明真实链路。 |

没有目标环境真实执行摘要时，不得写“生产可用”。

## 1. 用户需要准备的非密钥输入

请只确认状态，不发送真实密钥、口令、连接串或客户资料。

| 类别 | 字段 | 示例或要求 | 状态 |
|---|---|---|---|
| 范围 | `m1_audience` | 内部测试 / 白名单用户 |  |
| 范围 | `real_payment_order_disabled` | M1 只允许模拟订单确认跳转；不开放真实支付、预订、锁价、出票 |  |
| 服务器 | `server_provider` | 云厂商或自有服务器 |  |
| 服务器 | `os_version` | Ubuntu 22.04 / 24.04 |  |
| 服务器 | `cpu_ram_disk` | 2-4 vCPU / 8-16 GB RAM / 80-160 GB SSD |  |
| 网络 | `domain_ready` | 域名或临时访问地址 |  |
| 网络 | `server_egress_ip` | 是否有固定出口 IP |  |
| 部署 | `deploy_mode` | Docker Compose / 托管服务混合 |  |
| 数据库 | `postgres_mode` | Compose / 托管 PostgreSQL |  |
| 缓存 | `redis_mode` | Compose / 托管 Redis |  |
| 密钥 | `secret_store` | 服务器 `.env` / CI secrets / 云密钥系统 |  |
| 密钥 | `secret_owner` | 谁能创建、查看、轮换密钥 |  |
| 密钥 | `rotation_cadence` | 30 天 / 90 天 / 试运行后 |  |
| 外部 API | `llm_provider_ready` | DashScope 已准备 / 未准备 |  |
| 外部 API | `map_api_ready` | 高德已准备 / 未准备 |  |
| 外部 API | `optional_external_apis` | Tavily、航班、酒店、LangSmith 启用状态 |  |
| 数据 | `data_scope` | 公开资料 + 脱敏产品模板 |  |
| 验收 | `acceptance_window` | 计划测试日期和时间段 |  |
| 验收 | `eval_account_ready` | 验收账号已在密钥系统或服务器环境准备 |  |
| 备份 | `backup_target` | 本机目录 / 云盘快照 / 对象存储 |  |
| 备份 | `backup_retention` | 最近 7 天每日备份 + 最近 3 次发布前备份 |  |
| 备份 | `rag_restore_strategy` | 备份向量库 / 从语料重建 |  |
| 监控 | `monitoring_provider` | 云监控 / 自建脚本 / Prometheus / 待定 |  |
| 告警 | `alert_channel` | 邮件 / 短信 / 企业 IM / 电话 |  |
| 成本 | `daily_cost_budget` | LLM、地图、搜索、航班、酒店每日预算 |  |
| 负责人 | `rollback_owner` | 谁能执行回滚 |  |
| 负责人 | `incident_owner` | 谁处理 P0/P1 事故 |  |

这些输入可以先用脚本做机器检查。脚本只读取当前进程环境变量，不读取 `.env` 文件，也不回显变量值：

```powershell
uv run python scripts\check_m1_launch_inputs.py --json
```

在正式收集服务器、env、数据和运维资源前，可以先生成资源申请包：

```powershell
uv run python scripts\render_m1_resource_request.py --markdown
uv run python scripts\check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\render_server_env_checklist.py --markdown
uv run python scripts\render_server_env_checklist.py --template
uv run python scripts\check_server_env_file.py --env-file <deploy-dir>/shared/.env --json
```

资源申请包、非密钥 JSON 模板和服务器 env 清单适合发给部署负责人或运维负责人确认状态；非密钥 JSON 只记录服务器、域名、备份、监控、负责人和预算等状态，不记录真实密钥；服务器 env 文件校验应在目标服务器或受控 shell 执行，只输出变量名级别的阻塞摘要，不打印真实值或 `.env` 路径。真实密钥仍只能放到服务器环境、CI secrets 或云密钥系统。

M1 发布候选可以再跑聚合门禁。它会串起公开边界、M1 输入、服务器 preflight、Compose 配置、备份恢复前置、外部 API 前置、监控告警前置、安全发布前置和生产 readiness；默认不读取 `.env`，不启动服务：

```powershell
uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json
```

发布包生成前必须先冻结候选。冻结检查只读取 Git 工作区状态，把未提交文件按 workstream 归类；只要仍是 `blocked`，就不能进入正式打包：

```powershell
uv run python scripts\check_release_candidate_freeze.py --json
uv run python scripts\render_release_candidate_freeze_record.py --draft-baseline-decisions --markdown
uv run python scripts\check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json
```

`--draft-baseline-decisions` 只用于生成发布控制基线拟填写稿，不等于 release owner 签核。进入候选的方向仍必须补真实验证结果、验证证据摘要、风险结论和签核。

门禁结果可以生成脱敏 M1 验收记录。默认输出到终端；指定 `--output` 时才写文件：

```powershell
uv run python scripts\render_m1_acceptance_record.py
```

部署后 smoke（冒烟）证据可以先生成执行计划。默认不触网、不跑真实 Agent、不调用外部 API：

```powershell
uv run python scripts\collect_m1_smoke_evidence.py --json
```

最终 M1 go/no-go（上线前总判定）可以把 gate、smoke、备份恢复、监控告警、事故回滚证据收束到同一份脱敏摘要。默认计划模式不会读取 `.env`、不会启动服务、不会执行回滚，也不会触网：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py --json
```

生产放行口径更严格：只要被纳入的证据 section 仍是 `not_checked`、`blocked`、`failed`、`unknown` 或 `skipped`，最终 `decision` 必须是 `no_go`；只有全部请求证据 `passed` 才能写 `go_for_m1_controlled_trial`。

## 2. 发布候选门禁

在本地或 CI（持续集成）环境执行：

| 检查 | 命令 | 通过标准 |
|---|---|---|
| 工作区边界 | `git status --short --branch` | 只包含本次计划发布范围；不混入本地私有资料 |
| 发布候选冻结 | `uv run python scripts\check_release_candidate_freeze.py --json` | `status=passed`；否则按 workstream 决定 include/defer，直到工作区干净 |
| 发布候选冻结记录 | `uv run python scripts\render_release_candidate_freeze_record.py --draft-baseline-decisions --markdown` | 输出可填写的 include/defer/remove、验证结果和剩余风险记录；预填不等于签核 |
| 发布候选签核校验 | `uv run python scripts\check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json` | 进入候选的 workstream 均已验证通过、有验证证据摘要、风险结论明确且有人签核；记录仍匹配当前 Git 工作区路径快照 |
| 公开边界 | `uv run python scripts\check_public_release_boundary.py --json` | `status=passed` |
| M1 资源申请包 | `uv run python scripts\render_m1_resource_request.py --markdown` | 列出服务器、env、数据、验收、备份、监控和回滚资源；不要求填写真实密钥 |
| M1 执行输入缺口清单 | `docs/部署与运行/m1-execution-input-gap-checklist.md` | 执行前确认 SSH 目标、公网 URL、部署目录、私有证据目录、probe 凭据、备份目录、预算、验收窗口和负责人都在仓库外准备；缺任一项写 `blocked_missing_private_input` |
| M1 私有执行工作区准备 | `uv run python scripts\prepare_m1_private_execution_workspace.py --private-workdir <private-workdir> --execute --markdown` | 在仓库外创建 `m1-launch-inputs.local.json`、外部依赖记录、上线执行记录、运维复盘记录和私有 README；默认不覆盖已有文件，不读 `.env`、不连 SSH、不触网 |
| M1 执行输入缺口机器检查 | `uv run python scripts\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\m1-launch-inputs.local.json --markdown` | 聚合非密钥输入、私有工作目录、live workflow 输入和私有记录 JSON；不读 `.env`、不连 SSH、不触网、不回显真实值 |
| M1 非密钥输入模板 | `uv run python scripts\check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json` | 生成可填写 JSON；填好后不提交 Git |
| M1 非密钥输入文件校验 | `uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json` | 校验服务器、域名、备份、监控、负责人和预算等非密钥状态；不回显填写值 |
| 服务器 env 清单 | `uv run python scripts\render_server_env_checklist.py --markdown` | 列出 `<deploy-dir>/shared/.env` 变量名、占位符和交付方式；不读取真实 `.env` |
| 服务器 env 文件校验 | `uv run python scripts\check_server_env_file.py --env-file <deploy-dir>/shared/.env --json` | 必需变量齐备、无明显占位符、无重复声明、权限收敛；不打印真实值或 `.env` 路径 |
| M1 首部署 dry-run | `uv run python scripts\check_m1_first_deploy_dry_run.py --json` | 不 SSH、不上传、不打包；目标输入、本机工具、工作区、Compose 和公开边界通过 |
| 发布包 manifest | `uv run python scripts\build_release_artifact.py --execute --output-dir <release-output-dir> --json` | 工作区干净、公开边界通过；输出 archive 和 manifest，包含 commit、tree、tracked file count 和 sha256 |
| 上线执行记录模板 | `uv run python scripts\check_m1_rollout_execution_record.py --template --output <private-workdir>\m1-rollout-execution-record.local.json` | 生成私有 rollout 记录模板；用于记录发布包、备份点、部署步骤、健康检查、问题处理、回滚准备和数据安全 |
| 上线执行记录草稿回填 | `uv run python scripts\check_m1_rollout_execution_record.py --draft-from-evidence --server-preflight-json <private-workdir>\server-preflight-report.json --postgres-redis-json <private-workdir>\postgres-redis-live-probe.json --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --output <private-workdir>\m1-rollout-execution-record.draft.json` | 从 server preflight、PostgreSQL/Redis live probe 和私有流水线 workflow report 回填草稿；草稿仍需人工补齐 owner、release artifact、部署步骤、问题复盘、回滚和数据安全确认；拒绝仓库内、`.env`、`.runtime`、`.venv`、logs、vector store 或含 raw URL/IP/密钥形态的证据 |
| 上线执行记录校验 | `uv run python scripts\check_m1_rollout_execution_record.py --record-json <private-workdir>\m1-rollout-execution-record.local.json --output <private-workdir>\m1-rollout-execution-report.json` | 校验 release artifact、必需 deployment phases、server preflight、runtime services、post-deploy checks、issue log、rollback readiness 和 redaction boundary；不执行部署、不读 `.env`、不连 SSH |
| 上线执行记录纳入 go/no-go | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --json` | 把正向上线执行记录作为 M1 总判定 section；缺记录、坏 JSON 或记录 blocked 都会 `decision=no_go`；私有路径不回显 |
| 运维复盘记录模板 | `uv run python scripts\check_m1_operations_review_record.py --template --output <private-workdir>\m1-operations-review-record.local.json` | 生成私有 post-rollout review 模板；用于记录上线后的磁盘、Docker、PostgreSQL、Redis、备份、限流、外部 API、回滚、监控问题和后续动作 |
| 运维复盘记录草稿回填 | `uv run python scripts\check_m1_operations_review_record.py --draft-from-evidence --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --external-dependency-json <private-workdir>\external-dependency-resilience-report.json --output <private-workdir>\m1-operations-review-record.draft.json` | 从 rollout report、私有 go/no-go 和外部依赖复原力报告回填复盘草稿；草稿仍需人工补齐 root cause、risk acceptance、lessons、followups 和 owner；拒绝仓库内、`.env`、`.runtime`、`.venv`、logs、vector store 或含 raw URL/IP/密钥形态的证据 |
| 运维复盘记录校验 | `uv run python scripts\check_m1_operations_review_record.py --record-json <private-workdir>\m1-operations-review-record.local.json --output <private-workdir>\m1-operations-review-report.json` | 校验证据引用、issue review、root cause、action taken、verification、lessons、followups 和 M1 边界；不读 `.env`、不连 SSH、不查数据库/Redis、不读日志 |
| 运维复盘纳入 go/no-go | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --json` | 把上线后运维复盘作为 M1 总判定 section；缺记录、坏 JSON、缺后续项或夸大 M1 能力都会 `decision=no_go` |
| 服务器首部署脚本 | `deploy/first-deploy.sh` | 默认 dry-run；显式 `--execute --start-services` 才切换 release 和启动 Compose；默认固定 `ZHIXING_COMPOSE_PROJECT_NAME=langgraph-travel-planner`，避免 `current` 符号链接推断出错误 project；拒绝 `.env`、运行时目录和向量库进入发布包 |
| 生产镜像构建策略模板 | `uv run python scripts\check_production_image_build_policy.py --template --output <private-workdir>\production-image-build-policy.local.json` | 生成私有策略记录模板，覆盖包镜像源、远程后台构建、超时、日志/PID、镜像 ID/大小、健康探针和禁止清理边界 |
| 生产镜像构建策略校验 | `uv run python scripts\check_production_image_build_policy.py --policy-json <private-workdir>\production-image-build-policy.local.json --output <private-workdir>\production-image-build-policy-report.json` | 不运行 Docker、不连 SSH、不读 `.env`；确认下一次完整镜像重建必须可留证，且必须固定 Compose project，禁止 `docker system prune`、删除 volume、`.env`、备份或向量库 |
| 生产镜像构建执行记录模板 | `uv run python scripts\check_production_image_build_execution_record.py --template --output <private-workdir>\production-image-build-execution-record.local.json` | 生成真实远程后台 build 后要填写的私有记录模板，覆盖后台进程、镜像源、runtime 依赖输入、镜像 ID/大小、健康探针和运行时数据安全 |
| 生产镜像构建 dry-run | `uv run python scripts\prepare_production_image_build_execution.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --build-id <build-id> --release-label <release-label> --markdown --output <private-workdir>\production-image-build-execution-prep.md` | 默认不连接 SSH、不运行 Docker、不启动服务；只生成脱敏执行计划和后续执行记录要求 |
| 生产镜像构建启动 | `uv run python scripts\prepare_production_image_build_execution.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --build-id <build-id> --release-label <release-label> --execute --approval-token APPROVE_PRODUCTION_IMAGE_BUILD_EXECUTION --output <private-workdir>\production-image-build-execution-start.json` | 只在独立批准后执行；在远程后台启动 `deploy/update-runtime-image.sh`，不把启动成功当成构建通过；后台任务完成后必须填写执行记录 |
| 生产镜像构建执行记录校验 | `uv run python scripts\check_production_image_build_execution_record.py --record-json <private-workdir>\production-image-build-execution-record.local.json --output <private-workdir>\production-image-build-execution-report.json` | 不运行 Docker、不连 SSH、不读 `.env` 或原始日志；通过后才可把本次镜像重建写成已验收证据 |
| M1 输入边界 | `uv run python scripts\check_m1_launch_inputs.py --json` | 非密钥输入齐备；默认样例值会 `blocked` |
| RAG 数据源治理 | `uv run python scripts\check_travel_data_sources.py` | 公开目的地样例和候选外部数据源已登记来源、许可、归因和“不代表真实库存/实时价格”边界；不联网、不下载数据 |
| 公开数据候选采集 | `uv run python scripts\collect_public_travel_data_candidates.py --city xian --output-dir <private-workdir>\public-travel-candidates --execute` | 仅在扩充公开数据时执行；输出留在私有目录，候选仍需人工复核，不能直接作为入库或上线通过证据 |
| 公开数据候选审查 | `uv run python scripts\review_public_travel_data_candidates.py --candidate-json <private-workdir>\public-travel-candidates\public-travel-data-candidates.json --review-json <private-workdir>\public-travel-candidate-review.json --output-dir <private-workdir>\approved-public-travel-candidates --execute` | 仅在扩充公开数据时执行；四项人工审查通过后才生成 staging 草稿，草稿仍不是线上 RAG 通过证据 |
| 服务器 preflight | `uv run python scripts\check_server_preflight_readiness.py --json` | 服务器、域名、部署目录、端口、TLS、反向代理和 Docker 状态声明齐备 |
| PostgreSQL/Redis 恢复记录模板 | `uv run python scripts\check_postgres_redis_recovery_record.py --template --output <private-workdir>\postgres-redis-recovery-record.local.json` | 生成私有恢复/演练记录模板；不提交 Git |
| PostgreSQL/Redis 恢复记录校验 | `uv run python scripts\check_postgres_redis_recovery_record.py --record-json <private-workdir>\postgres-redis-recovery-record.local.json --output <private-workdir>\postgres-redis-recovery-report.json` | 校验负责人、影响服务、detect/isolate/recover/verify 阶段、数据安全、恢复后 health/M1 gate、耗时、无数据丢失和脱敏边界；不读取 `.env`、不连接数据库/Redis/SSH、不重启服务 |
| 备份恢复前置 | `uv run python scripts\check_backup_restore_readiness.py --json` | 备份目标、目录、保留策略和 RAG 恢复策略齐备 |
| 备份恢复演练证据计划 | `uv run python scripts\collect_backup_restore_drill_evidence.py --json` | 默认 `status=not_checked`，只证明执行计划和脱敏边界 |
| 外部 API 前置 | `uv run python scripts\check_external_api_readiness.py --json` | 必需/可选供应商、配额预算、超时重试和降级策略声明齐备 |
| 监控告警前置 | `uv run python scripts\check_monitoring_alerting_readiness.py --json` | 监控供应商、告警渠道和每日成本预算齐备 |
| 监控告警证据计划 | `uv run python scripts\collect_monitoring_alerting_evidence.py --json` | 默认 `status=not_checked`，只证明执行计划和脱敏边界 |
| 外部依赖韧性记录模板 | `uv run python scripts\check_external_dependency_resilience_record.py --template --output <private-workdir>\external-dependency-resilience-record.local.json` | 生成私有记录模板，用于收口外部 API readiness、成本预算、工具失败监控、超时重试和降级演练；不提交 Git |
| 外部依赖韧性记录校验 | `uv run python scripts\check_external_dependency_resilience_record.py --record-json <private-workdir>\external-dependency-resilience-record.local.json --output <private-workdir>\external-dependency-resilience-report.json` | 校验负责人、预算阈值、工具失败率、三类降级场景、超时/重试上限、M1 红线和脱敏边界；不读 `.env`、不调用供应商、不连 SSH、不打印真实 URL/IP/密钥 |
| 外部依赖纳入 go/no-go | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --json` | 把外部依赖韧性记录作为 M1 总判定 section；缺文件、坏 JSON 或校验 blocked 都会 `decision=no_go`；私有路径不回显 |
| 安全发布前置 | `uv run python scripts\check_security_release_readiness.py --json` | 密钥托管、轮换、泄露响应、来源限制和高风险动作关闭声明齐备 |
| 事故/回滚证据计划 | `uv run python scripts\collect_incident_rollback_evidence.py --json` | 默认 `status=not_checked`，只证明执行计划和脱敏边界 |
| M1 部署总门禁 | `uv run python scripts\check_m1_deployment_gate.py --json` | 聚合门禁 `status=passed`；否则按 section 修复 |
| M1 部署总门禁（非密钥文件） | `uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json` | 资源状态未写入目标环境前，用填好的非密钥 JSON 校验 M1 输入 section；最终服务器验收仍以目标环境为准 |
| M1 记录生成 | `uv run python scripts\render_m1_acceptance_record.py` | 输出脱敏 Markdown；不含 `.env`、密钥或日志原文 |
| M1 smoke 证据计划 | `uv run python scripts\collect_m1_smoke_evidence.py --json` | 默认 `status=not_checked`，只证明执行计划和脱敏边界 |
| M1 go/no-go 总判定 | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-disk --json` | 请求证据中任一 `not_checked` 或 `blocked` 都输出 `decision=no_go`；磁盘 `warning` 输出 `conditional_go` 并要求清理或扩容计划证据 |
| 真实服务器只读探测 | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-live-server-probe --live-server-ssh-target <ssh-user>@<server-host> --live-server-deploy-dir <deploy-dir> --base-url https://<your-domain> --json` | 目标服务器基础服务、内部 health、服务器侧公网 health 和 M1 模拟订单路由均通过；磁盘高水位进入 `degraded`；输出不回显真实目标 |
| Docker 磁盘清理计划 | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-docker-disk-cleanup-plan --live-server-ssh-target <ssh-user>@<server-host> --live-server-deploy-dir <deploy-dir> --docker-disk-cleanup-max-candidates 20 --json` | 只读列出未被任何容器引用的候选镜像，保护所有容器引用镜像；不删除镜像、容器、卷、日志或运行时数据；磁盘高水位仍只能 `conditional_go`，直到清理或扩容被单独批准并复验 |
| Docker 清理执行 dry-run | `uv run python scripts\execute_docker_disk_cleanup.py --plan-json <private-cleanup-plan-or-go-no-go-json> --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-delete-count 20 --markdown --output <private-workdir>\docker-disk-cleanup-dry-run.md` | 可读取单独 cleanup plan 或嵌入该 section 的私有 go/no-go JSON；重新保护所有容器引用镜像；不删除任何镜像；用于执行前复核；Windows 下用 `--output` 保证 UTF-8 |
| Docker build cache 清理计划 | `uv run python scripts\collect_docker_build_cache_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --output <private-workdir>\docker-build-cache-cleanup-plan.json` | 只读记录 build cache 聚合大小和可回收空间；不删除 build cache、镜像、容器、卷、日志或运行时数据；用于镜像清完但磁盘仍高水位时单独审批 |
| Docker build cache 清理 dry-run | `uv run python scripts\execute_docker_build_cache_cleanup.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --markdown --output <private-workdir>\docker-build-cache-cleanup-dry-run.md` | 默认不删除；真实执行必须加 `--execute --approval-token APPROVE_DOCKER_BUILD_CACHE_CLEANUP`；只运行 `docker builder prune -a -f`，不运行 `docker system prune` |
| Docker build cache 审批门禁 | `uv run python scripts\check_docker_build_cache_cleanup_approval.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --dry-run-json <private-workdir>\docker-build-cache-cleanup-dry-run.json --capacity-json <private-workdir>\server-capacity-snapshot.json --markdown --output <private-workdir>\docker-build-cache-cleanup-approval-gate.md` | 缺私有审批记录时只能到 `ready_for_explicit_approval`；有效审批必须确认只清 build cache、禁止 `docker system prune`、禁止删除镜像/容器/卷/日志/`.env`/备份/向量库，并接受未来构建变慢 |
| Docker build cache 审批请求 | `uv run python scripts\render_docker_build_cache_cleanup_approval_request.py --approval-gate-json <private-workdir>\docker-build-cache-cleanup-approval-gate.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\docker-build-cache-cleanup-approval-request.md` | 把当前 build cache 证据、审批边界、禁止动作和执行后复验命令整理成脱敏人工审批请求；不代表已经批准执行 |
| 服务器容量快照 | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-server-capacity-snapshot --live-server-ssh-target <ssh-user>@<server-host> --live-server-deploy-dir <deploy-dir> --json` | 只读记录 CPU、负载、内存、磁盘、容器状态和 `docker stats` 单次样本；不读 `.env`、日志、数据库、Redis key 或向量库；只能证明当时资源画像 |
| 低风险并发/限流记录模板 | `uv run python scripts\check_concurrency_rate_limit_evidence_record.py --template --output <private-workdir>\concurrency-rate-limit-record.local.json` | 生成私有验收记录模板；用于粘贴并发探针、限流探针和 Redis fail-closed 配置结论；不提交 Git |
| 低风险并发/限流记录校验 | `uv run python scripts\check_concurrency_rate_limit_evidence_record.py --record-json <private-workdir>\concurrency-rate-limit-record.local.json --output <private-workdir>\concurrency-rate-limit-report.json` | 校验并发探针 `passed`、限流探针出现成功响应和 429、`Retry-After`/`X-RateLimit-*` 头存在、限流后端为 Redis、本地 fallback 关闭、Redis 不可用 fail closed、且不夸大为 chat 高并发/自动扩缩容/长期压测 |
| Probe 认证检查 | `uv run python scripts\collect_m1_go_no_go_evidence.py --include-probe-auth-readiness --execute-probe-auth-login --base-url <public-url> --probe-auth-username-env ZHIXING_PROBE_USERNAME --probe-auth-password-env ZHIXING_PROBE_PASSWORD --timeout-seconds 20 --json` | 在 live chat 前验证 probe token 或 probe 账号能登录并访问 `/api/v1/users/me`；不创建会话、不调用 LLM、不写聊天消息、不回显 URL、token、账号、密码或 user id |
| 真实聊天 SSE 探针 | 先运行 `uv run python scripts\check_live_chat_probe_execution_approval.py --template --output <private-workdir>\live-chat-probe-execution-approval.local.json` 和 `uv run python scripts\check_live_chat_probe_execution_approval.py --approval-json <private-workdir>\live-chat-probe-execution-approval.local.json --json --output <private-workdir>\live-chat-probe-execution-approval-report.json`，再运行 `uv run python scripts\collect_m1_go_no_go_evidence.py --include-live-chat-probe --execute-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --base-url <public-url> --live-chat-access-token-env ZHIXING_PROBE_ACCESS_TOKEN --timeout-seconds 90 --json` 或 `uv run python scripts\collect_m1_go_no_go_evidence.py --include-live-chat-probe --execute-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --base-url <public-url> --live-chat-username-env ZHIXING_PROBE_USERNAME --live-chat-password-env ZHIXING_PROBE_PASSWORD --timeout-seconds 90 --json` | 需要私有 probe token 或已有 probe 账号密码，以及 passed 审批 report；会创建探针会话并可能调用 LLM/外部 API；输出不回显 URL、token、账号、密码、prompt、会话 id 或回复正文；只能证明一轮认证聊天链路 |
| M1 私有线上证据流水线预检 | `uv run python scripts\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json` | 计划模式输出脱敏 checklist，串起 M1 输入声明、server preflight、PostgreSQL/Redis live probe、私有流水线预检、正式执行、rollout 草稿/人工校验、运维复盘草稿/人工校验和签核；列出 live 输入、私有记录 JSON、阻断项和建议执行命令；不写文件、不触网、不连 SSH、不读取 `.env` |
| M1 私有线上证据流水线 | `uv run python scripts\run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --execute` | 串起 live server、PostgreSQL/Redis、备份计划、容量、低风险并发、限流、probe auth、Docker 磁盘计划、外部依赖韧性记录、上线执行记录和运维复盘记录；执行前先检查 live 私有输入，缺 URL、SSH、部署目录、备份目录或 probe 凭据时直接 `blocked` 且不启动 live probe；被选择的私有记录 JSON 缺路径、在 Git 工作区、落在 `.env` / `.runtime` / `.venv` / logs / vector store 等敏感或运行时路径、或文件不存在时也直接 `blocked`；外部依赖、上线执行和运维复盘记录只读私有 JSON，不触发 SSH/网络/部署/数据库查询/供应商调用；通过后写入私有目录下的 go/no-go JSON、摘要、证据包和哈希；随后按推荐顺序回填草稿、人工补齐并校验 rollout/复盘记录；默认禁止写入 Git 工作区；不读取 `.env`、不部署、不启动服务、不删除文件、不打印真实 URL/SSH/路径/凭据；live chat 仍需额外加 `--include-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --execute-live-chat-probe` |
| M1 私有证据签核校验 | `uv run python scripts\check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-owner <release-owner> --output <private-workdir>\m1-live-evidence-workflow\signoff.json` | 只读取私有 workflow 报告、引用的证据文件、人工校验后的 rollout report 和运维复盘 report；校验标准 live section、go/no-go 决策、证据 SHA-256、证据目录不在 Git、review reports 已 `passed`、无 URL/IP/密钥形态泄漏，并要求 release-owner signoff；不读取 `.env`、不跑 live probe、不连 SSH、不启动服务；`conditional_go` 必须额外传 `--allow-conditional-go --risk-acceptance` |
| M1 部署证据矩阵 | `uv run python scripts\render_m1_deployment_evidence_matrix.py --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json --markdown --output <private-workdir>\m1-deployment-evidence-matrix.md` | 只读取私有 JSON 报告并渲染脱敏矩阵；汇总 M1 输入、go/no-go、上线执行、运维复盘和最终签核；任一必需报告缺失、blocked、版本不匹配、在 Git 工作区或含 raw URL/IP/密钥形态文本都会 `blocked`；只证明 M1 受控试运行证据链，不证明完整生产 HA、扩缩容、长稳压测或真实履约 |
| M1 线上证据摘要 | `uv run python scripts\render_m1_live_evidence_summary.py --go-no-go-json <private-go-no-go.json> --output <private-workdir>\m1-live-evidence-summary.md` | 只读取已有 go/no-go JSON 并渲染脱敏 Markdown；不执行 SSH、健康检查、聊天、备份、恢复或 Docker 删除；用于汇总 live server、PostgreSQL/Redis、备份、容量、并发、限流、probe auth、live chat、磁盘、外部依赖韧性、上线执行和运维复盘证据 |
| M1 证据包归档 | `uv run python scripts\build_m1_evidence_bundle.py --go-no-go-json <private-go-no-go.json> --output-dir <private-workdir>\m1-evidence-bundle --execute` | 生成脱敏 go/no-go JSON、线上证据摘要、README 和 manifest 哈希清单；默认禁止写入 Git 工作区；不执行任何 live probe，只证明证据文件已被归档 |
| 格式检查 | `git diff --check` | 无错误 |
| Python 编译 | `uv run python -m compileall app tests scripts` | 通过 |
| 后端测试 | `uv run python -m pytest -q` | 通过，或记录失败和阻断原因 |
| 前端语法 | `node --check frontend\app.js` | 通过 |
| 报告渲染 | `node scripts\verify_frontend_report_renderer.js` | 通过 |
| 浏览器回归 | `node scripts\verify_frontend_browser_regression.js` | 通过 |

如果发布候选门禁失败，M1 状态写 `blocked`。

## 3. 服务器门禁

目标服务器准备：

| 检查 | 命令或证据 | 通过标准 |
|---|---|---|
| Docker | `docker --version`、`docker compose version` | 可用 |
| 部署目录 | `ZHIXING_DEPLOY_DIR` | 已创建，权限明确 |
| `.env` 权限 | `chmod 600 "$ZHIXING_DEPLOY_DIR/shared/.env"` | 只限部署负责人读取；不进入发布包 |
| `.env` 文件校验 | `python scripts/check_server_env_file.py --env-file "$ZHIXING_DEPLOY_DIR/shared/.env" --json` | 必需变量存在、非空、非明显占位符、无重复声明；只输出变量名级摘要 |
| 首部署脚本 dry-run | `sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir "$ZHIXING_DEPLOY_DIR"` | 校验上传包 sha256，只输出计划，不创建 release、不切换 current、不启动服务 |
| 首部署脚本执行 | `sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir "$ZHIXING_DEPLOY_DIR"` | `current` 指向新 release；runtime 数据保留在 `shared/` |
| 服务器 preflight | `python scripts/check_server_preflight_readiness.py --check-docker --check-deploy-dir --check-disk --check-health-url --json` | `status=passed` 或明确阻塞项；磁盘 `warning` 需要清理或扩容计划证据 |
| Docker 磁盘清理计划 | `python scripts/collect_docker_disk_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-candidates 20 --output <private-workdir>\docker-disk-cleanup-plan.json` | 只读输出候选镜像和虚拟大小估算；保护所有容器引用镜像；镜像 tag 不回显；共享层可能重复计算；没有明确批准前不得执行 `docker image rm` 或 `docker system prune` |
| Docker 镜像清理执行 | `python scripts/execute_docker_disk_cleanup.py --plan-json <private-cleanup-plan-or-go-no-go-json> --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-delete-count 20 --execute --approval-token APPROVE_DOCKER_IMAGE_CLEANUP --markdown --output <private-workdir>\docker-disk-cleanup-execution.md` | 只在单独批准后执行；再次跳过所有容器引用镜像；不 prune 容器、卷、日志、备份、`.env` 或向量库；执行后必须复跑磁盘探测 |
| Docker build cache 清理执行 | `python scripts/execute_docker_build_cache_cleanup.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --execute --approval-token APPROVE_DOCKER_BUILD_CACHE_CLEANUP --markdown --output <private-workdir>\docker-build-cache-cleanup-execution.md` | 只在独立批准后执行；只清 Docker 构建缓存；不删除镜像、容器、卷、日志、备份、`.env` 或向量库；执行后必须复跑容量快照和 go/no-go |
| Docker build cache 清理后复盘 | `python scripts/check_docker_build_cache_post_cleanup.py --execution-json <private-workdir>\docker-build-cache-cleanup-execution.json --before-capacity-json <private-workdir>\server-capacity-snapshot.json --after-capacity-json <private-workdir>\server-capacity-snapshot-post-build-cache-cleanup.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility-post-build-cache-cleanup.json --markdown --output <private-workdir>\docker-build-cache-post-cleanup.md` | 只读复盘执行报告、容量变化和恢复演练可行性；若磁盘或恢复空间仍阻塞，继续走扩容或 Docker data-root 迁移 |
| 容量快照 | `python scripts/collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown --output <private-workdir>\server-capacity-snapshot.md` | CPU、内存、负载、磁盘和容器资源有脱敏摘要；高磁盘/高负载/容器重启只能 `degraded`，不能包装成完整压测 |
| PostgreSQL | `cd "$ZHIXING_DEPLOY_DIR/current" && docker compose ps postgres` 或托管健康状态 | healthy |
| Redis | `cd "$ZHIXING_DEPLOY_DIR/current" && docker compose ps redis` 或托管健康状态 | healthy |
| 后端和代理 | `cd "$ZHIXING_DEPLOY_DIR/current" && docker compose ps backend caddy` | healthy |
| 本机健康 | `curl -fsS http://127.0.0.1:8000/health/live` | 返回 alive |
| 本机就绪 | `curl -fsS http://127.0.0.1:8000/health/ready` | ready 或明确 degraded |

## 4. 初始化门禁

除非命令里另写路径，本节 `docker compose` 命令都应在 `$ZHIXING_DEPLOY_DIR/current` 下执行，并保持 `ZHIXING_COMPOSE_PROJECT_NAME=langgraph-travel-planner`。如果缺少这个 project 名，Compose 可能把符号链接目录名 `current` 当成新项目，导致 `zhixing-redis` / `zhixing-postgres` 固定容器名冲突。

| 检查 | 命令 | 通过标准 |
|---|---|---|
| 数据库初始化 | `docker compose exec -T backend python -m scripts.init_db --mode bootstrap` | 无错误 |
| RAG 初始化 | `docker compose exec -T backend python -m scripts.init_rag` | 向量库可读、collection 正确 |
| M1 输入 readiness | `docker compose exec -T backend python scripts/check_m1_launch_inputs.py --json` | `status=passed` |
| 服务器 env 文件校验 | `python scripts/check_server_env_file.py --env-file "$ZHIXING_DEPLOY_DIR/shared/.env" --json` | 在服务器宿主机的当前 release 目录执行；`status=passed`；缺失、空值、占位符、重复声明或权限过宽时阻塞 |
| 服务器 preflight readiness | `docker compose exec -T backend python scripts/check_server_preflight_readiness.py --check-docker --check-deploy-dir --check-disk --check-health-url --json` | 目标服务器基础条件、Docker、目录、磁盘水位和公开 health URL 可用 |
| 备份恢复 readiness | `docker compose exec -T backend python scripts/check_backup_restore_readiness.py --check-filesystem --json` | 备份声明齐备且目录可写 |
| 备份恢复演练证据 | `docker compose exec -T backend python scripts/collect_backup_restore_drill_evidence.py --include-readiness --check-backup-dir --check-latest-dump --check-pg-restore-list --require-restore-drill-declaration --json` | 最新 PostgreSQL dump 元数据、catalog 可读性和恢复演练声明进入脱敏摘要 |
| 外部 API readiness | `docker compose exec -T backend python scripts/check_external_api_readiness.py --json` | 供应商启用状态、预算、超时重试和降级策略齐备 |
| 监控告警 readiness | `docker compose exec -T backend python scripts/check_monitoring_alerting_readiness.py --check-health-url --json` | 声明齐备，且公开 health URL 可探测 |
| 监控告警投递证据 | `docker compose exec -T backend python scripts/collect_monitoring_alerting_evidence.py --include-readiness --check-health-url --require-alert-delivery-declaration --require-metric-declaration --json` | health/readiness 告警投递、核心指标监控、成本/备份/日志脱敏状态进入脱敏摘要 |
| 安全发布 readiness | `docker compose exec -T backend python scripts/check_security_release_readiness.py --check-public-boundary --json` | 密钥托管、轮换、泄露响应和公开边界前置通过 |
| 事故/回滚演练证据 | `docker compose exec -T backend python scripts/collect_incident_rollback_evidence.py --require-ownership-declaration --require-rollback-drill-declaration --require-incident-review-declaration --include-post-rollback-smoke-evidence --check-health-url --run-gate --json` | 负责人、回滚目标、回滚后 health/gate 和事故复盘状态进入脱敏摘要 |
| M1 部署总门禁 | `docker compose exec -T backend python scripts/check_m1_deployment_gate.py --include-acceptance --check-backend --check-server-docker --check-server-deploy-dir --check-server-disk --check-server-health-url --check-monitoring-health-url --base-url "$ZHIXING_PUBLIC_BASE_URL" --json` | `status=passed` 或明确阻塞项；磁盘 `warning` 进入 degraded |
| M1 记录生成 | `docker compose exec -T backend python scripts/render_m1_acceptance_record.py` | 生成或打印脱敏记录 |
| M1 smoke 证据收束 | `docker compose exec -T backend python scripts/collect_m1_smoke_evidence.py --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url "$ZHIXING_PUBLIC_BASE_URL" --json` | 公开 health、M1 gate 和 acceptance smoke 结果进入同一份脱敏摘要；不回显真实 URL |
| M1 go/no-go 总判定 | `docker compose exec -T backend python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url "$ZHIXING_PUBLIC_BASE_URL" --json` | 全部请求证据 `passed` 才能 `go_for_m1_controlled_trial`；否则 `no_go` 或 `conditional_go` |
| 生产 readiness | `docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json` | `status=passed` 或只存在可接受降级 |
| acceptance preflight | `docker compose exec -T backend python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url "$ZHIXING_PUBLIC_BASE_URL" --json` | 必需项不 blocked |

`blocked_reasons` 不为空时，不能开放白名单。

## 5. 验收门禁

| 检查 | 命令 | 通过标准 |
|---|---|---|
| acceptance smoke | `docker compose exec -T backend python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url "$ZHIXING_PUBLIC_BASE_URL" --json` | 通过或仅可接受降级 |
| smoke evidence | `docker compose exec -T backend python scripts/collect_m1_smoke_evidence.py --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url "$ZHIXING_PUBLIC_BASE_URL" --json` | `status=passed` 或记录真实阻塞；默认计划模式不能当作通过 |
| RAG retrieval | `docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --json` | 通过并记录样本规模 |
| mixed-corpus safety | `docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json` | 通过 |
| 外部访问 live | `curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/live"` | 返回 alive |
| 外部访问 ready | `curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/ready"` | ready 或明确 degraded |

离线 RAG `passed` 不能替代目标环境真实向量库 `configured`，也不能替代在线 Agent 验收。

## 6. 运维门禁

| 方向 | 检查 | 通过标准 |
|---|---|---|
| 备份 | PostgreSQL 发布前备份 | 已生成并完成可恢复性检查 |
| 恢复 | 非生产恢复演练 | `pg_restore` 或托管恢复演练通过 |
| 证据 | 备份恢复演练摘要 | `collect_backup_restore_drill_evidence.py` 显式执行并保留脱敏摘要 |
| Redis | 持久化或丢失边界 | 说明活跃会话是否可接受丢失 |
| RAG | 向量库恢复路径 | 备份向量库或从语料重建已验证 |
| 回滚 | 代码和配置回滚 | 负责人、命令、触发条件明确 |
| 监控 | health/readiness 告警 | 已配置、脚本前置通过或明确 `not measured` |
| 告警证据 | health/readiness 投递演练 | 已显式收集脱敏摘要；不保存真实通知内容 |
| 指标 | P95、错误率、工具失败率 | 已配置或明确 `not measured` |
| 事故/回滚 | P0/P1 响应和发布回滚 | 负责人、回滚目标、回滚后复验和事故复盘已脱敏记录 |
| 成本 | LLM/地图/搜索/航班/酒店预算 | 有日预算和负责人 |
| 外部 API | 故障降级策略 | 搜索可降级，航班/酒店待核验，支付/预订仅允许站内模拟确认跳转 |
| 外部依赖韧性 | 私有记录校验 | 外部 API readiness、成本 guard、工具失败监控、超时/重试和降级演练已脱敏收口；不夸大为供应商 SLA、强配额、完整 HA 或长期压测 |
| 安全 | 密钥轮换和泄露响应 | 负责人、频率、响应流程明确 |

缺备份或恢复演练时，不得进入 M2 有限生产。

## 7. 可开放白名单的最低条件

同时满足以下条件，才能把 M1 试运行开放给内部或白名单用户：

- M1 边界已确认：只开放站内模拟订单确认跳转，不开放真实支付、预订、锁价、出票。
- 必需密钥已通过密钥系统或服务器 `.env` 注入。
- 服务器 `.env` 文件校验已通过，且没有把真实值写入公开记录。
- 服务器 preflight 已通过，部署目录、Docker、域名、TLS、端口和反向代理状态明确。
- 如果磁盘为 `warning/degraded`，已完成只读 Docker 磁盘清理计划，并在单独批准的清理或扩容后重新探测通过；未复验前只能写 `conditional_go`，不能写 `passed`。
- 已收集服务器容量快照和低风险并发探针；容量快照只证明当时 CPU/内存/磁盘/容器资源状态，并发探针只证明 sampled GET endpoints，不等于真实 chat 压测。
- 已完成外部依赖韧性记录校验；外部 API 故障只能降级或待核验，不能写真实库存、锁价、支付、预订、出票或履约承诺。
- 服务器、数据库、Redis、后端、反向代理健康。
- production readiness 和 acceptance preflight 无必需项阻塞。
- acceptance smoke 已通过或只存在明确可接受降级。
- `GET /api/v1/mock-checkout/<ORDER-ID>` 模拟确认页可访问，并且 `status` 证据明确 `real_payment=false`、`real_booking=false`、`inventory_locked=false`。
- `collect_m1_smoke_evidence.py` 已在目标环境显式执行 health、M1 gate 和 acceptance smoke，并保留脱敏摘要。
- `collect_m1_go_no_go_evidence.py` 已在目标环境纳入全部声明证据和 live smoke，且最终 `decision` 不是 `no_go`。
- PostgreSQL 已备份，恢复演练有记录。
- 备份恢复演练证据收集器已显式执行，且没有把真实路径、dump 文件名、日志原文或 `.env` 写入公开记录。
- 外部 API 降级策略和成本预算已明确。
- 外部 API readiness 已通过或可接受降级已写明。
- 监控告警负责人已明确。
- 监控告警投递证据已显式执行；缺指标时只能写 `degraded` 或 `not measured`，不能写 `passed`。
- 安全发布 readiness 已通过，密钥托管、轮换和泄露响应负责人明确。
- `m1-acceptance-record-template.md` 已填写脱敏摘要。

任一条件不满足，结论写 `blocked` 或 `degraded`，不能写 `passed`。

## 8. 进入 M2 前的最低条件

M2 有限生产需要额外满足：

- 连续多次 M1 发布和回滚演练稳定。
- health/readiness、错误率、P95、工具失败率、备份失败、成本配额有自动告警。
- PostgreSQL 备份恢复演练稳定通过。
- 日志脱敏抽样通过。
- Prompt（提示词）、模型、RAG 语料、工具策略有版本记录。
- 如需真实支付、预订、短信或客户资料导出，先完成 HITL（人类在环）、幂等、权限和审计闭环。

## 9. 文档索引

| 文档 | 用途 |
|---|---|
| `production-readiness-gap.md` | 真实生产系统差距和 M0/M1/M2/M3 定义 |
| `production-deployment-inputs.md` | 用户需要准备的服务器、密钥、数据、验收和运维输入 |
| `m1-release-candidate-freeze.md` | 发布候选冻结、workstream 归类和打包前阻塞口径 |
| `m1-controlled-trial-runbook.md` | M1 受控试运行步骤 |
| `m1-operations-evidence-playbook.md` | PostgreSQL/Redis、并发限流、Docker 磁盘、备份恢复和回滚的运行证据故事线 |
| `m1-acceptance-record-template.md` | M1 脱敏验收记录 |
| `external-api-failure-runbook.md` | 外部 API 故障处理 |
| `backup-restore-runbook.md` | 备份、恢复演练和数据回滚 |
| `monitoring-alerting-runbook.md` | 监控、告警、运行指标和成本配额 |
| `incident-response-rollback-runbook.md` | 事故响应、发布回滚和回滚后复验 |
| `security-release-key-rotation-runbook.md` | 安全发布、密钥轮换和泄露响应 |

所有公开记录只写变量名、状态、摘要和风险，不写真实密钥、`.env`、日志原文、数据库备份、向量库文件、客户资料或本地私有路径。
