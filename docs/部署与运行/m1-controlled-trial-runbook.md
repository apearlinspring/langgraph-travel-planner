# M1 Controlled Trial Runbook（受控试运行手册）

本文把生产化差距清单和部署输入清单落成一套可执行步骤，用于把 ZhiXing Travel Planner 推进到 M1 受控试运行。M1 的目标是“真实环境、真实依赖、少量内部或白名单用户、强人工兜底”，不是全量生产开放。

## 0. 试运行边界

M1 必须保持以下边界：

- 不开放真实支付、真实预订、真实锁价、真实出票或自动客服履约。
- 不把真实密钥、账号口令、Cookie、数据库备份、日志原文、`.env` 或向量库提交到 Git。
- 不在聊天记录、工单、公开文档或验收摘要里粘贴真实密钥值。
- 外部 API（应用程序接口）失败时，报告只能写待核验或降级说明，不能编造真实班次、库存、酒店确认或价格锁定。
- 所有验收结论按真实结果写 `passed`、`blocked`、`degraded`、`not run` 或 `dry-run only`。

外部 API 故障处理见 `docs/部署与运行/external-api-failure-runbook.md`；每次试运行的脱敏记录模板见 `docs/部署与运行/m1-acceptance-record-template.md`。
上线前总检查表见 `docs/部署与运行/m1-launch-checklist.md`。
执行前私有输入缺口清单见 `docs/部署与运行/m1-execution-input-gap-checklist.md`，用于确认 SSH 目标、公网 URL、部署目录、私有证据目录、probe 凭据、备份目录、预算、验收窗口和负责人是否已在仓库外准备。
备份、恢复演练和数据回滚边界见 `docs/部署与运行/backup-restore-runbook.md`。
监控、告警、运行指标和成本配额边界见 `docs/部署与运行/monitoring-alerting-runbook.md`。
事故响应、发布回滚和回滚后复验见 `docs/部署与运行/incident-response-rollback-runbook.md`。
安全发布、密钥轮换和泄露响应见 `docs/部署与运行/security-release-key-rotation-runbook.md`。
运行问题的证据故事线见 `docs/部署与运行/m1-operations-evidence-playbook.md`，用于把 PostgreSQL/Redis、并发限流、Docker 磁盘、备份恢复和回滚证据串成统一复盘结构。

## 1. 输入确认

执行前先完成 `docs/部署与运行/production-deployment-inputs.md` 的非密钥表格。最低需要确认：

| 类别 | 必需状态 |
|---|---|
| 服务器 | 已有目标机器、操作系统、部署方式、域名或临时访问地址 |
| 基础服务 | PostgreSQL（关系型数据库）和 Redis（缓存数据库）已选择 Compose 或托管服务 |
| 必需密钥 | `DASHSCOPE_API_KEY`、`JWT_SECRET_KEY`、`AMAP_API_KEY` 已准备并能注入目标环境 |
| 数据 | 只使用公开资料和脱敏产品模板，不含真实客户资料 |
| 验收 | 已有测试账号、验收场景、API 预算和测试时间窗口 |
| 运维 | 明确备份、回滚、日志查看和异常响应负责人 |

如果以上任一项未准备，当前阶段结论写 `blocked`，不要继续包装成试运行通过。

正式收集服务器、env、数据和运维资源前，可以先生成资源申请包：

```sh
python scripts/render_m1_resource_request.py --markdown
python scripts/check_m1_launch_inputs.py --template --output <private-workdir>/m1-launch-inputs.local.json
python scripts/check_m1_launch_inputs.py --input-json <private-workdir>/m1-launch-inputs.local.json --json
```

资源申请包会列出服务器、DNS/TLS、运行配置、密钥变量、RAG 数据、外部 API、验收、备份、监控和回滚准备项；非密钥 JSON 模板用于填写服务器、域名、备份、监控、负责人和预算等状态。它们只写变量名、状态和交付方式；真实密钥值必须留在服务器环境、CI secrets 或云密钥系统。

非密钥输入确认后，可以在只注入当前进程环境变量的情况下执行：

```sh
python scripts/check_m1_launch_inputs.py --json
```

该脚本不会读取 `.env` 文件，也不会回显变量值；它只能证明“范围、负责人、备份、监控、成本和验收窗口等非密钥输入已声明”，不能替代真实密钥、服务器健康或验收烟测。监控告警还可以单独执行前置检查：

```sh
python scripts/check_monitoring_alerting_readiness.py --json
```

该监控脚本默认不触网，只证明监控供应商、告警渠道和每日成本预算已声明；目标环境内需要显式追加 `--check-health-url` 才会探测公开 health endpoint（健康端点）。

安全发布也可以单独执行前置检查：

```sh
python scripts/check_security_release_readiness.py --json
```

该脚本不读取 `.env`，也不读取真实密钥；它只证明密钥托管、轮换周期、泄露响应负责人、浏览器 key 来源限制和高风险动作关闭声明已经准备。

外部 API 可靠性也可以单独执行前置检查：

```sh
python scripts/check_external_api_readiness.py --json
```

该脚本不读取 `.env`、不调用真实供应商，只证明必需/可选供应商、配额预算、控制台负责人、支持渠道、超时重试和降级策略已经声明。

外部依赖韧性记录用于正式收口 LLM、外部 API、成本和工具失败证据。它只读取私有 JSON 记录，不读取 `.env`、不调用供应商、不连 SSH、不启动服务：

```sh
python scripts/check_external_dependency_resilience_record.py --template --output <private-workdir>/external-dependency-resilience-record.local.json
python scripts/check_external_dependency_resilience_record.py --record-json <private-workdir>/external-dependency-resilience-record.local.json --output <private-workdir>/external-dependency-resilience-report.json
```

该记录必须明确超时/重试上限、降级演练、成本预算负责人、工具失败监控和“不承诺真实库存/锁价/支付/预订/履约”的边界；含真实 URL、IP、密钥形态或供应商原始响应正文时必须 `blocked`。

上线执行记录用于把一次真实 M1 rollout 从发布包、备份点、服务器预检、发布步骤、健康检查、问题处理到回滚准备串成可验收证据。`--draft-from-evidence` 可以先把 server preflight、PostgreSQL/Redis live probe 和私有流水线 workflow report 回填成草稿，但草稿不等于签核，仍需要人工补齐 owner、release artifact、部署步骤、问题复盘、回滚和数据安全确认。它只读取私有 JSON 记录，不执行部署、不连 SSH、不读 `.env`：

```sh
python scripts/check_m1_rollout_execution_record.py --template --output <private-workdir>/m1-rollout-execution-record.local.json
python scripts/check_m1_rollout_execution_record.py --draft-from-evidence --server-preflight-json <private-workdir>/server-preflight-report.json --postgres-redis-json <private-workdir>/postgres-redis-live-probe.json --workflow-report-json <private-workdir>/m1-live-evidence-workflow/workflow-report.json --output <private-workdir>/m1-rollout-execution-record.draft.json
python scripts/check_m1_rollout_execution_record.py --record-json <private-workdir>/m1-rollout-execution-record.local.json --output <private-workdir>/m1-rollout-execution-report.json
python scripts/collect_m1_go_no_go_evidence.py --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>/m1-rollout-execution-record.local.json --json
```

该记录必须保留 release artifact manifest、部署 phase、post-deploy health/smoke、issue log、rollback readiness 和 data safety；缺少任一关键环节时不能写成“已经真实上线”。

上线后还要补运维复盘记录，把磁盘、Docker 镜像、PostgreSQL、Redis、备份恢复、限流、外部 API、RAG、回滚和监控发现归类，记录根因、动作、复验和后续项：

```sh
python scripts/check_m1_operations_review_record.py --template --output <private-workdir>/m1-operations-review-record.local.json
python scripts/check_m1_operations_review_record.py --draft-from-evidence --rollout-report-json <private-workdir>/m1-rollout-execution-report.json --go-no-go-json <private-workdir>/m1-live-evidence-workflow/m1-go-no-go.private.json --external-dependency-json <private-workdir>/external-dependency-resilience-report.json --output <private-workdir>/m1-operations-review-record.draft.json
python scripts/check_m1_operations_review_record.py --record-json <private-workdir>/m1-operations-review-record.local.json --output <private-workdir>/m1-operations-review-report.json
python scripts/collect_m1_go_no_go_evidence.py --include-m1-operations-review-record --m1-operations-review-json <private-workdir>/m1-operations-review-record.local.json --json
```

`--draft-from-evidence` 只读取显式传入的私有 JSON 报告，拒绝仓库内、`.env`、`.runtime`、`.venv`、logs、vector store 或包含 raw URL/IP/密钥形态的证据。草稿只是减少重复录入，不替代人工复盘、风险接受、owner、lessons learned 和 follow-up signoff。

这份复盘记录不读取 live infrastructure（线上基础设施），也不替代真实监控；它的作用是把一次 M1 rollout 中“发现了什么、如何处理、如何避免再发生”沉淀成可检查的工程证据。

服务器 preflight 也可以单独执行前置检查：

```sh
python scripts/check_server_preflight_readiness.py --json
```

该脚本默认不启动服务、不写文件、不触网；只证明服务器、部署目录、域名、TLS、端口、反向代理和 Docker 状态声明已经准备。目标服务器内需要显式追加 `--check-docker --check-deploy-dir --check-disk --check-health-url` 才会检查 Docker 命令、部署目录存在性、部署目录所在磁盘水位和公开 health endpoint。

发布候选还可以执行聚合门禁：

```sh
python scripts/check_m1_deployment_gate.py --json
```

该命令聚合公开边界、M1 非密钥输入、服务器 preflight、备份恢复前置、外部 API 前置、监控告警前置、安全发布前置、Compose 配置和 production readiness。默认同样不读取 `.env`，因此本地没有真实环境注入时出现 `blocked` 是正确结果。

如需把门禁结果转成脱敏记录，可以执行：

```sh
python scripts/render_m1_acceptance_record.py
```

默认输出到终端；只有明确指定 `--output` 才写文件。记录里只保留状态、变量名、section 和阻塞摘要，不写真实密钥、`.env`、日志原文或客户资料。

部署后 smoke 证据也可以先生成执行计划：

```sh
python scripts/collect_m1_smoke_evidence.py --json
```

默认计划模式不触网、不跑真实 Agent、不调用外部 API，因此只能写 `not_checked`，不能写成目标环境已通过。

最终 M1 go/no-go 汇总也可以先生成计划态：

```sh
python scripts/collect_m1_go_no_go_evidence.py --json
python scripts/collect_m1_go_no_go_evidence.py --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>/external-dependency-resilience-record.local.json --json
```

它用于把 M1 gate、部署后 smoke、备份恢复、监控告警、事故回滚和外部依赖韧性证据放到同一份脱敏摘要中。生产放行口径按真实上线处理：被纳入的证据 section 如果还是 `not_checked`，最终就是 `no_go`，不能解释成“默认通过”。外部依赖韧性记录保留在私有证据目录，不要为了容器内 smoke 把它复制进公开仓库或部署容器。

真实线上证据建议用私有流水线统一收口。默认计划模式不写文件、不连 SSH、不触网、不登录、不跑聊天；执行模式必须指定仓库外私有目录：

```sh
python scripts/run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>/m1-live-evidence-workflow --include-standard-live-probes
python scripts/run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>/m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>/external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>/m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>/m1-operations-review-record.local.json --execute
```

该流水线会先检查变量级私有输入，缺公网 URL、SSH 目标、部署目录、备份目录或 probe 凭据时直接 `blocked`，且不会启动 live probe。计划模式加 `--markdown` 会输出一份脱敏 checklist，列出推荐执行顺序、live 输入、私有记录 JSON、阻断项和建议执行命令；它不写文件、不触网。推荐顺序会把 M1 输入声明、server preflight、PostgreSQL/Redis live probe、私有流水线预检、正式执行、rollout 草稿回填、人工 rollout 校验、运维复盘草稿回填、人工复盘校验和最终签核串起来。它还会检查被选择的私有记录 JSON：外部依赖韧性记录、上线执行记录、运维复盘记录或真实聊天探针审批 report 如果没有传路径、文件在 Git 工作区内、路径像 `.env` / `.runtime` / `.venv` / logs / vector store，或文件不存在，也会在执行前直接 `blocked`。通过输入门禁后，它会在私有目录中写 `m1-go-no-go.private.json`、`m1-live-evidence-summary.md`、`m1-evidence-bundle/` 和 `workflow-report.json`，并记录关键证据文件的 SHA-256 摘要。外部依赖韧性记录、上线执行记录和运维复盘记录都是非 live section：只有显式传对应 `--include-* --*-record-json` 才会读取该私有 JSON，并且不会因此触发 SSH、网络探针、部署、数据库查询或供应商调用。它仍然不读取 `.env`、不部署、不启动服务、不删除文件、不打印真实 URL、SSH 目标、部署路径、私有记录路径或凭据。只有在明确批准一轮真实聊天探针时，才额外加 `--include-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --execute-live-chat-probe`；这会创建探针会话，并可能调用 LLM/外部 API。

如果目标环境还没有探针账号，可以在仓库外私有执行目录准备以下三个变量，再显式允许注册探针用户：

```powershell
$env:ZHIXING_PROBE_USERNAME = "<probe-username>"
$env:ZHIXING_PROBE_PASSWORD = "<probe-password>"
$env:ZHIXING_PROBE_EMAIL = "<probe-email>"
uv run python scripts\check_live_chat_probe_execution_approval.py --template --output <private-workdir>\live-chat-probe-execution-approval.local.json
uv run python scripts\check_live_chat_probe_execution_approval.py --approval-json <private-workdir>\live-chat-probe-execution-approval.local.json --json --output <private-workdir>\live-chat-probe-execution-approval-report.json

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

`check_live_chat_probe_execution_approval.py` 只校验私有审批 JSON，不触网、不注册用户、不创建会话、不调用 LLM，也不读取 `.env`。审批 report 必须先 `passed`，才能执行后续带 `--execute-live-chat-probe` 的命令。

`--register-live-chat-probe-user` 是显式写入开关：它可能调用 `/api/v1/users/register` 写入一个测试用户；如果账号已存在，则用同一账号登录复用。随后会创建一条探针会话并发起一轮 SSE（服务器发送事件）聊天，可能调用 LLM（大语言模型）或外部 API。该探针只证明“线上认证、会话创建、聊天流式返回”这一条业务链路在采样窗口内通过；不证明高并发聊天吞吐、长稳压测、真实支付、真实预订、锁价、出票或履约。

如果没有执行 `--execute-live-chat-probe`，`live_chat_probe` 必须保持 `not_checked`，最终 `go/no-go` 仍是 `no_go`；不能把公网健康接口通过解释成业务链路通过。

`m1-live-evidence-summary.md` 会把 live probes、外部依赖韧性记录、上线执行记录和运维复盘记录放在同一张脱敏证据矩阵里，便于复盘“发布步骤、降级演练、根因、处理动作、复验和后续项”。这份摘要仍然不能证明自动扩缩容、多地域高可用、长时间压测、真实支付或真实履约。

生成私有证据后，必须再做签核校验。该步骤只读取私有证据目录里的 `workflow-report.json`、引用的证据文件，以及人工校验后的 rollout / 运维复盘 report；它会校验标准 live sections、go/no-go 决策、证据哈希、仓库外目录、脱敏边界、rollout / 复盘 report 是否 `passed` 和 release-owner 签核；它不读取 `.env`、不跑探针、不连 SSH：

```sh
python scripts/check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>/m1-live-evidence-workflow/workflow-report.json --rollout-report-json <private-workdir>/m1-rollout-execution-report.json --operations-review-report-json <private-workdir>/m1-operations-review-report.json --signoff-owner <release-owner> --output <private-workdir>/m1-live-evidence-workflow/signoff.json
```

如果 go/no-go 只有 `conditional_go`，不能直接写成通过，必须显式记录风险接受范围：

```sh
python scripts/check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>/m1-live-evidence-workflow/workflow-report.json --rollout-report-json <private-workdir>/m1-rollout-execution-report.json --operations-review-report-json <private-workdir>/m1-operations-review-report.json --signoff-owner <release-owner> --release-decision conditional_go --allow-conditional-go --risk-acceptance "<accepted M1 degraded evidence scope>" --output <private-workdir>/m1-live-evidence-workflow/signoff.json
```

## 2. 发布候选准备

在本地或 CI（持续集成）环境准备发布候选时，先确认工作区只包含要发布的公开项目集合：

```powershell
git status --short --branch
uv run python scripts\check_public_release_boundary.py --json
uv run python scripts\check_release_candidate_freeze.py --json
uv run python scripts\render_release_candidate_freeze_record.py --markdown
uv run python scripts\check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json
uv run python scripts\render_m1_resource_request.py --markdown
uv run python scripts\check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\render_server_env_checklist.py --markdown
uv run python scripts\render_server_env_checklist.py --template
uv run python scripts\check_m1_first_deploy_dry_run.py --json
uv run python scripts\build_release_artifact.py --execute --output-dir <release-output-dir> --json
uv run python scripts\check_m1_rollout_execution_record.py --template --output <private-workdir>\m1-rollout-execution-record.local.json
uv run python scripts\check_m1_rollout_execution_record.py --draft-from-evidence --server-preflight-json <private-workdir>\server-preflight-report.json --postgres-redis-json <private-workdir>\postgres-redis-live-probe.json --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --output <private-workdir>\m1-rollout-execution-record.draft.json
uv run python scripts\check_m1_rollout_execution_record.py --record-json <private-workdir>\m1-rollout-execution-record.local.json --output <private-workdir>\m1-rollout-execution-report.json
uv run python scripts\check_m1_operations_review_record.py --template --output <private-workdir>\m1-operations-review-record.local.json
uv run python scripts\check_m1_operations_review_record.py --draft-from-evidence --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --external-dependency-json <private-workdir>\external-dependency-resilience-report.json --output <private-workdir>\m1-operations-review-record.draft.json
uv run python scripts\check_m1_operations_review_record.py --record-json <private-workdir>\m1-operations-review-record.local.json --output <private-workdir>\m1-operations-review-report.json
uv run python scripts\check_m1_launch_inputs.py --json
uv run python scripts\check_server_preflight_readiness.py --json
uv run python scripts\check_postgres_redis_recovery_record.py --template --output <private-workdir>\postgres-redis-recovery-record.local.json
uv run python scripts\check_postgres_redis_recovery_record.py --record-json <private-workdir>\postgres-redis-recovery-record.local.json --output <private-workdir>\postgres-redis-recovery-report.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --template --output <private-workdir>\concurrency-rate-limit-record.local.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --record-json <private-workdir>\concurrency-rate-limit-record.local.json --output <private-workdir>\concurrency-rate-limit-report.json
uv run python scripts\check_backup_restore_readiness.py --json
uv run python scripts\collect_backup_restore_drill_evidence.py --json
uv run python scripts\check_external_api_readiness.py --json
uv run python scripts\check_monitoring_alerting_readiness.py --json
uv run python scripts\collect_monitoring_alerting_evidence.py --json
uv run python scripts\check_external_dependency_resilience_record.py --template --output <private-workdir>\external-dependency-resilience-record.local.json
uv run python scripts\check_external_dependency_resilience_record.py --record-json <private-workdir>\external-dependency-resilience-record.local.json --output <private-workdir>\external-dependency-resilience-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --json
uv run python scripts\check_security_release_readiness.py --json
uv run python scripts\collect_incident_rollback_evidence.py --json
uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\check_m1_deployment_gate.py --json
uv run python scripts\collect_m1_smoke_evidence.py --json
uv run python scripts\collect_m1_go_no_go_evidence.py --json
uv run python scripts\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes
uv run python scripts\check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-owner <release-owner> --output <private-workdir>\m1-live-evidence-workflow\signoff.json
uv run python scripts\render_m1_deployment_evidence_matrix.py --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json --markdown --output <private-workdir>\m1-deployment-evidence-matrix.md
git diff --check
uv run python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
uv run python -m pytest -q
```

最终证据矩阵只汇总已有私有报告，不运行 live probe，也不读取 `.env`。它把 M1 输入、go/no-go、上线执行、运维复盘和私有签核压成一张表；任一必需报告缺失、blocked、版本不匹配、落在 Git 工作区或包含 raw URL/IP/密钥形态文本，矩阵都会 `blocked`。

发布包只应包含源码、依赖声明、配置样例、数据库迁移、正式文档、部署脚本和安全样例数据。生成发布包前必须先让 `scripts/check_release_candidate_freeze.py --json` 返回 `status=passed`。不要把 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`、日志、数据库备份或真实运行证据打包进发布物。发布包 manifest 至少记录 commit、tree、tracked file count 和 archive `sha256`；没有 manifest 的 tar 不能作为正式 M1 发布候选。

## 3. 服务器初始化

服务器初始化只做基础运行条件，不写真实密钥到 Git：

```sh
sudo apt-get update
sudo apt-get install -y git curl ca-certificates
docker --version
docker compose version
```

建立部署目录时使用环境变量记录，不把机器敏感路径写入公开文档：

```sh
export ZHIXING_DEPLOY_DIR=/opt/langgraph-travel-planner
sudo mkdir -p "$ZHIXING_DEPLOY_DIR"
mkdir -p "$ZHIXING_DEPLOY_DIR/shared"
sudo chown "$USER":"$USER" "$ZHIXING_DEPLOY_DIR"
```

如果服务器使用托管 PostgreSQL 或托管 Redis，需要确认安全组、白名单、TLS（传输层安全协议）和最小权限账号已经配置完成。

## 4. 密钥和配置注入

目标环境的 `.env` 只在服务器或密钥系统中维护，不进入 Git。M1 默认放在 `$ZHIXING_DEPLOY_DIR/shared/.env`，可对照仓库内 `.env.example` 的变量名在服务器上创建，或由密钥系统注入；必须替换所有生产必需项：

```sh
install -m 600 /dev/null "$ZHIXING_DEPLOY_DIR/shared/.env"
chmod 600 "$ZHIXING_DEPLOY_DIR/shared/.env"
```

M1 必需配置：

```text
APP_ENV=staging
DASHSCOPE_API_KEY=<managed-secret-value>
JWT_SECRET_KEY=<long-random-secret>
POSTGRES_HOST=<postgres-host>
POSTGRES_PORT=<postgres-port>
POSTGRES_DB=<postgres-db>
POSTGRES_USER=<postgres-user>
POSTGRES_PASSWORD=<managed-secret-value>
REDIS_HOST=<redis-host>
REDIS_PORT=<redis-port>
REDIS_PASSWORD=<managed-secret-value-if-enabled>
AMAP_API_KEY=<managed-secret-value>
ZHIXING_PUBLIC_BASE_URL=https://<your-domain>
ZHIXING_EVAL_BASE_URL=https://<your-domain>
ZHIXING_SITE_ADDRESS=<your-domain>
```

填写完成后在目标服务器或受控 shell 中做文件级校验。该脚本只输出缺失、空值、明显占位符、重复变量和权限状态，不打印真实值，也不打印 `.env` 文件路径：

```sh
python scripts/check_server_env_file.py --env-file "$ZHIXING_DEPLOY_DIR/shared/.env" --json
```

检查配置时只看变量名和 readiness 输出，不打印 `.env` 内容。真实值一旦出现在终端、日志或聊天记录中，应立即轮换。

如果历史部署还停留在 root `.env`，先用收敛脚本 dry-run 检查布局，不打印配置值、不复制文件：

```sh
python scripts/converge_server_shared_env.py \
  --ssh-target <ssh-user>@<server-host> \
  --deploy-dir <deploy-dir> \
  --markdown
```

确认 root `.env` 存在、权限收敛且 `shared/.env` 缺失后，再由运维负责人显式批准执行。执行模式仍不打印 `.env` 内容、不覆盖已存在的 `shared/.env`、不重启服务：

```sh
python scripts/converge_server_shared_env.py \
  --ssh-target <ssh-user>@<server-host> \
  --deploy-dir <deploy-dir> \
  --execute \
  --approval-token APPROVE_SHARED_ENV_CONVERGENCE \
  --markdown
```

## 5. 首次发布和基础服务启动

首次发布先上传 Git archive、manifest 和服务器侧脚本，再在服务器上先 dry-run、后显式执行。脚本会用 manifest 里的 archive `sha256` 校验上传包，把代码解压到 `releases/<release-id>`，把 `current` 切到新版本，并把 `.env`、向量库、日志和备份保留在 `shared/` 下：

```sh
sh /tmp/zhixing-first-deploy.sh \
  --archive /tmp/zhixing-release-<commit>.tar \
  --archive-sha256 <archive-sha256> \
  --deploy-dir "$ZHIXING_DEPLOY_DIR"
```

确认 dry-run 输出符合预期后执行：

```sh
sh /tmp/zhixing-first-deploy.sh \
  --execute \
  --start-services \
  --archive /tmp/zhixing-release-<commit>.tar \
  --archive-sha256 <archive-sha256> \
  --deploy-dir "$ZHIXING_DEPLOY_DIR"
cd "$ZHIXING_DEPLOY_DIR/current"
docker compose ps
```

如果使用托管 PostgreSQL / Redis，应调整 `.env` 和 Compose 配置，避免容器内服务与托管服务混用造成误判。

## 6. 数据库和 RAG 初始化

以下 `docker compose` 命令默认在当前 release 目录执行：

```sh
cd "$ZHIXING_DEPLOY_DIR/current"
```

数据库初始化：

```sh
docker compose exec -T backend python -m scripts.init_db --mode bootstrap
```

RAG（检索增强生成）向量库初始化：

```sh
docker compose exec -T backend python -m scripts.init_rag
```

注意：`data/vectorstore/` 和 `data/vectorstore_internal/` 是运行时生成数据，只留在服务器或受控备份中，不进入 Git。若更换语料、embedding（向量嵌入）模型或 collection（集合）名称，必须重新跑 RAG readiness 和召回评测。release-symlink 布局下，`collect_live_server_probe.py` 会把 `<deploy-dir>/shared/data/vectorstore/chroma.sqlite3` 和 `<deploy-dir>/shared/data/vectorstore_internal/chroma.sqlite3` 缺失视为阻断；这可以提前发现“容器启动但 `/health/ready` 因 RAG shared mount 为空而失败”的部署问题。如果同一布局下只有 root `.env` 而没有 `shared/.env`，probe 会标记为 `degraded`，表示当前服务可能可用，但下次标准部署前应收敛运行时配置位置。

## 7. 分层验收

先确认 M1 非密钥输入已经齐备：

```sh
docker compose exec -T backend python scripts/check_m1_launch_inputs.py --json
```

再确认服务器 `.env` 文件本身没有明显缺项或占位符：

```sh
python scripts/check_server_env_file.py \
  --env-file "$ZHIXING_DEPLOY_DIR/shared/.env" \
  --json
```

再确认服务器 preflight，并打开目标环境探测：

```sh
docker compose exec -T backend python scripts/check_server_preflight_readiness.py \
  --check-docker \
  --check-deploy-dir \
  --check-disk \
  --check-health-url \
  --json
```

再确认备份目标、保留策略和 RAG 恢复策略。默认命令只检查声明；服务器上可以加 `--check-filesystem` 验证备份目录可写：

```sh
docker compose exec -T backend python scripts/check_backup_restore_readiness.py \
  --check-filesystem \
  --json
```

发布前备份和非生产恢复演练完成后，收集脱敏证据。该步骤不会输出真实备份路径、dump 文件名或日志原文；`--check-pg-restore-list` 只证明 dump catalog 可读，完整恢复仍以非生产库恢复演练和后续 smoke 为准：

```sh
docker compose exec -T backend python scripts/collect_backup_restore_drill_evidence.py \
  --include-readiness \
  --check-backup-dir \
  --check-latest-dump \
  --check-pg-restore-list \
  --require-restore-drill-declaration \
  --json
```

再确认外部 API 可靠性声明：

```sh
docker compose exec -T backend python scripts/check_external_api_readiness.py \
  --json
```

再确认监控告警声明，并探测公开 health endpoint：

```sh
docker compose exec -T backend python scripts/check_monitoring_alerting_readiness.py \
  --check-health-url \
  --json
```

告警演练完成后，收集投递和指标证据。该脚本不会主动发送测试告警，必须先在监控平台侧触发或确认，再把状态声明进目标环境：

```sh
docker compose exec -T backend python scripts/collect_monitoring_alerting_evidence.py \
  --include-readiness \
  --check-health-url \
  --require-alert-delivery-declaration \
  --require-metric-declaration \
  --json
```

再确认安全发布状态，不读取真实密钥：

```sh
docker compose exec -T backend python scripts/check_security_release_readiness.py \
  --check-public-boundary \
  --json
```

回滚演练和事故复盘完成后，收集脱敏证据。该脚本不会执行回滚，不会启动服务，也不会删除数据；真实回滚必须按部署手册和备份恢复手册人工执行：

```sh
docker compose exec -T backend python scripts/collect_incident_rollback_evidence.py \
  --require-ownership-declaration \
  --require-rollback-drill-declaration \
  --require-incident-review-declaration \
  --include-post-rollback-smoke-evidence \
  --check-health-url \
  --run-gate \
  --json
```

再跑 M1 聚合门禁，并把 acceptance preflight（验收预检）也纳入检查：

```sh
docker compose exec -T backend python scripts/check_m1_deployment_gate.py \
  --include-acceptance \
  --check-backend \
  --check-server-docker \
  --check-server-deploy-dir \
  --check-server-disk \
  --check-server-health-url \
  --check-backup-filesystem \
  --check-monitoring-health-url \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

将当前门禁结果整理成脱敏 M1 记录：

```sh
docker compose exec -T backend python scripts/render_m1_acceptance_record.py \
  --include-acceptance \
  --check-backend \
  --base-url "$ZHIXING_PUBLIC_BASE_URL"
```

再把部署后 health、M1 gate 和 acceptance smoke 收束成同一份脱敏证据。该命令会触网，并且 `--run-acceptance-smoke` 可能消耗 LLM 和外部 API 预算，必须在目标环境准备完成后显式执行：

```sh
docker compose exec -T backend python scripts/collect_m1_smoke_evidence.py \
  --check-health-url \
  --run-gate \
  --run-acceptance-smoke \
  --timeout-seconds 900 \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

最后生成 M1 go/no-go 总判定。该命令不会执行回滚或启动服务，但会把所有请求的证据 section 严格合并：任一必需 section 为 `not_checked`、`blocked`、`failed`、`unknown` 或 `skipped` 时，`decision` 必须是 `no_go`：

```sh
docker compose exec -T backend python scripts/collect_m1_go_no_go_evidence.py \
  --include-all-declared-evidence \
  --include-server-preflight-evidence \
  --check-server-docker \
  --check-server-deploy-dir \
  --check-server-disk \
  --check-health-url \
  --run-gate \
  --run-acceptance-smoke \
  --timeout-seconds 900 \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

如果外部依赖韧性记录保存在本地私有证据目录，不要复制到服务器容器；在运维本机或私有证据工作区另跑以下命令，把该记录作为独立 section 纳入同一类 go/no-go 判定：

```sh
python scripts/collect_m1_go_no_go_evidence.py \
  --include-external-dependency-resilience-record \
  --external-dependency-record-json <private-workdir>/external-dependency-resilience-record.local.json \
  --json
```

先跑生产配置 readiness：

```sh
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
```

后续命令如果要使用 `.env` 里的公开访问地址，先在当前 shell 中加载变量。该操作不应打印 `.env` 内容：

```sh
set -a
. ./.env
set +a
```

再检查真实后端 readiness：

```sh
docker compose exec -T backend python scripts/check_runtime_readiness.py \
  --target acceptance \
  --check-backend \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

再跑最小 acceptance smoke（验收冒烟）：

```sh
docker compose exec -T backend python scripts/run_evaluation_scenarios.py \
  --acceptance-smoke \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

如果变更涉及 RAG 语料、检索逻辑或安全边界，追加：

```sh
docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --json
docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

如果变更涉及图片、音频或视频等多模态 RAG，且目标环境已经准备真实样例和模型密钥，追加：

```sh
docker compose exec -T backend python scripts/check_runtime_readiness.py \
  --target production \
  --json \
  --check-rag-multimodal-e2e
```

## 8. 前端和外部访问检查

服务器内检查：

```sh
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

外部访问检查：

```sh
curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/live"
curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/ready"
```

前端报告渲染变更需要在发布候选阶段完成本地脚本验证：

```powershell
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
```

M1 只证明结构化报告可以展示、复制摘要和导出 HTML（超文本标记语言），不证明订单、合同、支付、库存或履约真实存在。

## 9. 脱敏证据记录

每次试运行至少记录以下脱敏摘要：

| 证据 | 记录内容 | 不记录 |
|---|---|---|
| 发布候选 | commit、发布时间、变更范围、回滚版本 | 本地草稿、未整理 prompt、私有路径 |
| M1 记录 | `render_m1_acceptance_record.py` 输出的状态、section、阻塞项和边界说明 | `.env`、密钥值、目标 URL 原文、日志原文 |
| M1 smoke 证据 | `collect_m1_smoke_evidence.py` 输出的 health、gate、acceptance smoke 状态和数量摘要 | 真实 URL 原文、`.env`、原始日志、完整对话或 `.runtime` 快照 |
| M1 go/no-go 总判定 | `collect_m1_go_no_go_evidence.py` 输出的 `decision`、section 状态、阻塞项和缺失输入 | 真实 URL 原文、`.env`、密钥、原始日志、备份文件或供应商截图 |
| M1 证据包 | `build_m1_evidence_bundle.py` 输出的 manifest、artifact sha256、脱敏 go/no-go JSON 和脱敏 Markdown 摘要 | 原始 go/no-go JSON、真实 URL 原文、`.env`、密钥、日志、备份文件或供应商截图 |
| readiness | 顶层 `status`、`blocked_reasons`、`repair_suggestions`、目标环境 | `.env`、密钥值、完整 token |
| acceptance | 场景数量、通过/阻塞数量、失败分类 | 用户隐私、原始对话全文 |
| RAG | 文档数量、场景数量、召回指标、安全门结果 | 向量库文件、内部敏感原文 |
| 外部 API | 启用服务、失败率、降级说明 | 供应商密钥、真实客户订单 |
| 运维 | 备份时间、恢复演练结果、回滚负责人 | 数据库备份文件、真实日志原文 |
| 备份恢复演练 | 最新 dump 元数据、`pg_restore --list` 结果、恢复演练声明和数据丢失窗口 | 真实备份路径、dump 文件名、dump 内容、恢复日志原文 |
| 监控告警 | health/readiness 投递状态、错误率/P95/工具失败/成本/备份/日志脱敏监控状态 | 真实通知内容、手机号、邮箱、群机器人地址、截图原文 |
| 事故/回滚 | 负责人、回滚目标、回滚后 health/gate/smoke、事故响应和复盘状态 | 原始工单、原始日志、截图、用户对话、真实通知内容 |
| 监控告警 | 健康检查、readiness、P95、工具失败率、成本配额和告警状态 | 原始日志、密钥、完整用户对话 |
| 安全发布 | 公开发布边界、密钥托管、轮换记录和泄露响应准备状态 | 真实密钥、`.env`、完整连接串 |

建议按 `docs/部署与运行/m1-acceptance-record-template.md` 填写验收记录。该模板只保留状态、数量、失败分类、修复建议和剩余风险，不保存真实密钥、日志原文或用户隐私。

## 10. 回滚

每次发布前确认已有代码备份、数据库备份和迁移回退策略。代码回滚示例见 `docs/部署与运行/deployment-readiness.md`。

回滚原则：

- 不删除 `.env`、数据库卷、Redis 卷、日志目录或向量库目录。
- 数据恢复前必须先按 `docs/部署与运行/backup-restore-runbook.md` 在非生产环境完成恢复演练。
- 数据库 schema（结构）变更必须先看迁移记录和备份状态，不能盲目覆盖。
- 如果事故来自外部 API 或密钥异常，优先降级或关闭对应能力，而不是回滚全部系统。
- 回滚后重新跑 `/health/ready` 和 acceptance smoke，确认状态真实恢复。
- 回滚后用 `collect_incident_rollback_evidence.py` 记录脱敏摘要；没有摘要时只能写 `not run` 或 `blocked`。

## 11. 退出 M1 的条件

以下条件全部满足后，才能考虑从 M1 受控试运行进入 M2 有限生产：

- 连续多次发布都能完成 readiness、acceptance smoke、RAG 安全门和回滚演练。
- PostgreSQL 备份恢复演练通过，并有明确保留周期。
- 集中日志、基础指标和告警已经可用。
- 外部 API 有超时、限流、重试、降级和配额告警。
- Prompt（提示词）、模型、RAG 语料和工具策略有版本记录。
- 若要接真实支付、预订、短信或客户资料导出，必须先完成 HITL（人类在环）审批、权限、幂等和审计闭环。

没有以上证据时，结论继续保持 M1 或 `blocked`，不写成生产可用。
