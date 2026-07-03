# M1 Execution Input Gap Checklist（执行前输入缺口清单）

本文用于在真正执行 M1 受控试运行前确认“还缺什么”。它只记录公开工程口径、变量名、私有文件位置规则和验收命令，不记录真实服务器 IP、域名、SSH 用户、密码、API key、数据库连接串、日志、备份文件名或客户资料。

如果私有运行手册已经写有具体服务器、域名、部署目录或负责人，把它们映射到本文的占位符和变量中使用；不要复制到公开仓库、公开文档、工单正文或聊天记录。

机器检查入口：

```powershell
uv run python scripts\prepare_m1_private_execution_workspace.py --private-workdir <private-workdir> --execute --markdown
# Optional: dot-source a private env starter outside Git if deployment coordinates are already known.
# . <private-workdir>\m1-known-deployment-env.local.ps1
uv run python scripts\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\m1-launch-inputs.local.json --markdown
```

`prepare_m1_private_execution_workspace.py` 只在显式 `--execute` 时把私有模板写入 `<private-workdir>`，默认不覆盖已有文件；`check_m1_execution_input_gap.py` 只读取当前进程环境变量和显式传入的私有 JSON。两者都不读取 `.env`，不连 SSH，不探测公网 URL，不启动服务，不写部署文件，不回显真实 URL/IP/路径/凭据。输出 `ready_to_execute_private_m1` 只代表执行输入齐备，仍不代表真实部署或线上验收已经通过。

执行准备脚本还会生成 `m1-private-inputs.todo.md` 和 `m1-live-inputs.local.ps1`。前者把当前缺口整理成可填写清单，后者只包含注释掉的 PowerShell 环境变量示例；填真实值并取消注释前，不会影响当前 shell。

## 0. 结论规则

| 结论 | 使用条件 |
|---|---|
| `ready_to_execute_private_m1` | 下表必需项都已在仓库外准备，并且对应校验报告为 `passed` 或明确可接受的 `degraded`。 |
| `blocked_missing_private_input` | 缺 SSH 目标、公网 URL、部署目录、备份目录、probe 凭据、负责人、预算、验收窗口或私有证据目录。 |
| `blocked_sensitive_boundary` | 真实密钥、URL/IP、日志、数据库备份、向量库、`.env` 或运行时文件进入 Git 工作区或公开文档。 |
| `dry_run_only` | 只生成模板、资源申请包或计划态证据，没有连接目标环境。 |

没有真实目标环境执行摘要时，不得把状态写成“生产可用”。M1 只证明受控试运行；不证明真实支付、真实预订、真实库存锁价、出票、履约、多地域高可用、自动扩缩容或长时间压测。

## 1. 必需私有输入

| 缺口 | 必须准备什么 | 放在哪里 | 校验或使用命令 |
|---|---|---|---|
| 私有工作目录 | 用于保存 M1 输入 JSON、go/no-go、rollout、运维复盘、signoff、证据矩阵和证据包 | `<private-workdir>`，必须在 Git 工作区外 | `run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --markdown` |
| 服务器访问 | `<ssh-user>@<server-host>`，只给受控执行者使用 | 私有 shell、CI secrets 或私有运行手册 | `collect_live_server_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --public-base-url <public-url> --markdown` |
| 部署目录 | `<deploy-dir>`，并确认 `current/`、`releases/`、`shared/` 规划 | 私有运行手册或服务器环境变量 `ZHIXING_DEPLOY_DIR` | `check_server_preflight_readiness.py --check-deploy-dir --json` |
| 公网访问地址 | `https://<your-domain>` 或受控临时 HTTPS 地址 | 环境变量 `ZHIXING_PUBLIC_BASE_URL` / `ZHIXING_EVAL_BASE_URL` | `check_server_preflight_readiness.py --check-health-url --json` |
| 服务器 `.env` | 必需变量、密钥、数据库、Redis、供应商 key 和验收账号 | `<deploy-dir>/shared/.env` 或密钥系统 | `check_server_env_file.py --env-file <deploy-dir>\shared\.env --json` |
| Probe 账号或 token | 用于认证检查和可选 live chat 探针 | `ZHIXING_PROBE_USERNAME` / `ZHIXING_PROBE_PASSWORD` 或 `ZHIXING_PROBE_ACCESS_TOKEN` | `check_probe_auth_readiness.py --base-url <public-url> --username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD --markdown` |
| 备份目录 | PostgreSQL、Redis、RAG、发布前备份的目标目录或对象存储声明 | `ZHIXING_BACKUP_DIR` 或私有备份系统 | `collect_backup_schedule_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --backup-dir <private-backup-dir-outside-git> --markdown` |
| 预算和配额 | LLM、地图、搜索、航班、酒店每日预算、供应商控制台负责人和告警阈值 | `m1-launch-inputs.local.json` 或环境变量状态声明 | `check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json` |
| 验收窗口 | 真实执行日期、低风险并发窗口、live chat 是否批准、外部 API 调用上限 | 私有变更单或 `m1-launch-inputs.local.json` | `check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json` |
| 数据范围 | 公开资料、脱敏路线模板、风险 SOP、报告字段；不含真实客户或供应商私密数据 | `data/documents/` 的安全样例或仓库外待审数据目录 | `check_travel_data_sources.py` |
| Release owner | 谁能批准发布包、执行部署、接受 `conditional_go` 风险 | 私有记录 JSON，不写联系方式 | `check_m1_private_evidence_signoff.py --signoff-owner <release-owner> ...` |
| Rollback owner | 谁能执行回滚、查看备份、复验 health/smoke | 私有 rollout / incident 记录 | `check_rollback_execution_record.py --record-json <private-rollback-record.json> --json` |

## 2. 不能提供或不能写入公开仓库

- 不需要把 `.env`、API key、密码、token、Cookie、私钥、数据库连接串发出来。
- 不需要提交 `.runtime/`、日志、数据库 dump、Redis 快照、向量库、浏览器截图、原始聊天记录或供应商响应正文。
- 不要在公开文档中写真实服务器 IP、真实域名、SSH 用户、部署目录、备份路径、负责人联系方式或 probe 账号。
- 如果上述内容已经进入 Git、公开文档、公开截图或聊天记录，先轮换密钥并清理公开材料，再继续 M1。

## 3. 执行前最小交接包

下列文件都应保存在 `<private-workdir>`，不要提交 Git：

| 文件 | 作用 | 生成或校验命令 |
|---|---|---|
| `m1-launch-inputs.local.json` | 非密钥输入状态：服务器、域名、备份、监控、负责人、预算、验收窗口 | `check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json` |
| `m1-launch-inputs-report.json` | 非密钥输入校验报告 | `check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json --output <private-workdir>\m1-launch-inputs-report.json` |
| `m1-private-inputs.todo.md` | 当前缺口的私有填写清单 | `prepare_m1_private_execution_workspace.py --private-workdir <private-workdir> --execute --markdown` |
| `m1-live-inputs.local.ps1` | 备份目录和 probe 凭据的本地环境变量 starter；默认全是注释 | 填真实值、取消对应注释后再 `. <private-workdir>\m1-live-inputs.local.ps1` |
| `external-dependency-resilience-record.local.json` | 外部 API、成本、降级、工具失败监控记录 | `check_external_dependency_resilience_record.py --template --output <private-workdir>\external-dependency-resilience-record.local.json` |
| `m1-rollout-execution-record.local.json` | 上线执行、发布包、备份点、部署步骤、问题和回滚准备 | `check_m1_rollout_execution_record.py --template --output <private-workdir>\m1-rollout-execution-record.local.json` |
| `m1-operations-review-record.local.json` | 上线后磁盘、Docker、PostgreSQL、Redis、备份、限流、监控和后续项复盘 | `check_m1_operations_review_record.py --template --output <private-workdir>\m1-operations-review-record.local.json` |
| `m1-live-evidence-workflow\workflow-report.json` | 私有线上证据流水线执行报告 | `run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --execute` |
| `m1-live-evidence-workflow\signoff.json` | 私有证据签核结果 | `check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --signoff-owner <release-owner> --output <private-workdir>\m1-live-evidence-workflow\signoff.json` |
| `m1-deployment-evidence-matrix.md` | 脱敏证据矩阵 | `render_m1_deployment_evidence_matrix.py --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json --markdown --output <private-workdir>\m1-deployment-evidence-matrix.md` |

## 4. 推荐执行顺序

```powershell
uv run python scripts\prepare_m1_private_execution_workspace.py --private-workdir <private-workdir> --execute --markdown
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json --output <private-workdir>\m1-launch-inputs-report.json
# Fill <private-workdir>\m1-private-inputs.todo.md and uncomment needed lines in m1-live-inputs.local.ps1.
# . <private-workdir>\m1-known-deployment-env.local.ps1
# . <private-workdir>\m1-live-inputs.local.ps1
uv run python scripts\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\m1-launch-inputs.local.json --markdown
uv run python scripts\render_server_env_checklist.py --markdown
uv run python scripts\check_server_env_file.py --env-file <deploy-dir>\shared\.env --json
uv run python scripts\check_m1_first_deploy_dry_run.py --json
uv run python scripts\check_server_preflight_readiness.py --json
uv run python scripts\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json
```

上面这组命令用于执行前预检。只有确认私有输入齐备、发布候选冻结、服务器侧 `.env` 和备份目录准备完成、且 release owner 批准执行窗口后，才进入真实部署、live probe、rollout 记录、运维复盘、signoff 和证据矩阵阶段。

## 5. 执行许可边界

| 操作 | 默认许可 | 需要单独批准 |
|---|---|---|
| 生成模板、资源申请包、执行前 Markdown checklist | 允许 | 无 |
| 读取公开文档、公开脚本、`.env.example` 变量名 | 允许 | 无 |
| 检查服务器 `.env` 文件完整性 | 只在目标服务器或受控 shell 执行 | 需要确认 env 文件路径，但不打印内容 |
| SSH 只读 live probe | 仅在给出 SSH 目标、部署目录和测试窗口后执行 | 需要 release owner 或运维批准 |
| 首次部署 `--execute --start-services` | 默认禁止 | 需要发布窗口、发布包 manifest、备份点和回滚 owner |
| Docker 镜像清理 `--execute` | 默认禁止 | 需要 cleanup plan、批准 token 和执行后磁盘复验 |
| Live chat 探针 | 默认不执行 | 需要 probe 凭据和明确允许调用 LLM / 外部 API |
| 真实支付、预订、库存锁价、出票、履约 | M1 禁止 | 不在 M1 范围内 |

## 6. 当前仍缺时怎么表述

如果某项还没准备好，公开记录只写：

```text
status=blocked_missing_private_input
missing=probe credentials / private workdir / backup dir / acceptance window / release owner
next_action=prepare private input outside Git and rerun the listed validator
```

不要写“已上线”“生产可用”“完整高并发”“完整支付闭环”或“真实供应链已接入”。M1 的可信表述应该是：目标环境、基础服务、低风险并发、限流、备份、监控、外部 API 降级和签核证据分别通过哪些命令验证；未验证的部分保持 `not run` 或 `blocked`。
