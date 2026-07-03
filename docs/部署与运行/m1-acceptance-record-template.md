# M1 Acceptance Record Template（受控试运行验收记录模板）

本文是 M1 受控试运行的脱敏验收记录模板。它用于记录真实环境执行结果、阻塞项、降级项、回滚准备和下一步动作，不用于保存 `.env`、日志原文、数据库备份、向量库文件、真实密钥、真实客户资料或聊天全文。

## 1. 基本信息

| 字段 | 内容 |
|---|---|
| Record ID |  |
| Date |  |
| Recorder |  |
| Release commit |  |
| Environment | staging / production |
| Public URL | 只写域名，不写账号口令 |
| M1 audience | 内部测试 / 白名单用户 |
| Trial boundary | 不开放真实支付、真实预订、真实锁价、真实出票 |
| Rollback owner |  |
| Backup owner |  |

## 2. 输入确认

| 输入项 | 状态 | 说明 |
|---|---|---|
| 服务器和域名 | ready / blocked |  |
| PostgreSQL | ready / blocked |  |
| Redis | ready / blocked |  |
| DashScope | ready / blocked |  |
| 高德地图 | ready / blocked |  |
| 可选搜索 | enabled / disabled / blocked |  |
| 可选航班 | enabled / disabled / blocked |  |
| 可选酒店 | enabled / disabled / blocked |  |
| 脱敏业务数据 | ready / blocked |  |
| 验收账号 | ready / blocked | 不写账号口令 |
| API 预算 | ready / blocked |  |
| M1 资源申请包 | `ready_to_collect_resources` / `not run` | `python scripts/render_m1_resource_request.py --markdown` 的脱敏摘要 |
| M1 首部署 dry-run | `passed` / `blocked` / `not run` | `python scripts/check_m1_first_deploy_dry_run.py --json` 的 section 摘要 |
| 发布包 manifest | `passed` / `blocked` / `not run` | `python scripts/build_release_artifact.py --execute --output-dir <release-output-dir> --json` 的 commit、tree、sha256 摘要 |
| 服务器首部署脚本 | `dry-run only` / `passed` / `blocked` / `not run` | `deploy/first-deploy.sh` 的服务器 dry-run / `--execute --start-services` 摘要 |
| RAG 数据源治理 | `passed` / `blocked` / `not run` | `python scripts/check_travel_data_sources.py` 的 source registry、目的地文档来源/许可/归因和边界摘要 |
| 公开数据候选采集 | `passed` / `degraded` / `blocked` / `not run` | `python scripts/collect_public_travel_data_candidates.py --execute` 的私有候选包摘要；候选不直接入库 |
| 公开数据候选审查 | `passed` / `ready_for_review` / `ready_to_write` / `blocked` / `not run` | `python scripts/review_public_travel_data_candidates.py` 的人工审查和私有 staging 摘要；staging 草稿仍需最终检查 |
| M1 非密钥输入脚本 | `passed` / `blocked` / `not run` | `python scripts/check_m1_launch_inputs.py --json` 的脱敏摘要 |
| 服务器 preflight 脚本 | `passed` / `blocked` / `not run` | `python scripts/check_server_preflight_readiness.py --json` 的脱敏摘要 |
| 备份恢复前置脚本 | `passed` / `blocked` / `not run` | `python scripts/check_backup_restore_readiness.py --json` 的脱敏摘要 |
| 备份恢复演练证据脚本 | `passed` / `blocked` / `not_checked` / `not run` | `python scripts/collect_backup_restore_drill_evidence.py --json` 的脱敏摘要 |
| 外部 API 前置脚本 | `passed` / `blocked` / `degraded` / `not run` | `python scripts/check_external_api_readiness.py --json` 的脱敏摘要 |
| 监控告警前置脚本 | `passed` / `blocked` / `not run` | `python scripts/check_monitoring_alerting_readiness.py --json` 的脱敏摘要 |
| 监控告警证据脚本 | `passed` / `blocked` / `degraded` / `not_checked` / `not run` | `python scripts/collect_monitoring_alerting_evidence.py --json` 的脱敏摘要 |
| 安全发布前置脚本 | `passed` / `blocked` / `not run` | `python scripts/check_security_release_readiness.py --json` 的脱敏摘要 |
| 事故/回滚证据脚本 | `passed` / `blocked` / `degraded` / `not_checked` / `not run` | `python scripts/collect_incident_rollback_evidence.py --json` 的脱敏摘要 |
| M1 部署总门禁 | `passed` / `blocked` / `not run` | `python scripts/check_m1_deployment_gate.py --json` 的 section 摘要 |
| M1 记录生成器 | `passed` / `blocked` / `not run` | `python scripts/render_m1_acceptance_record.py` 的脱敏 Markdown |
| M1 smoke 证据收集器 | `passed` / `blocked` / `not_checked` / `not run` | `python scripts/collect_m1_smoke_evidence.py --json` 或目标环境显式 smoke 的脱敏摘要 |
| M1 go/no-go 总判定 | `go_for_m1_controlled_trial` / `conditional_go` / `no_go` / `not_checked` | `python scripts/collect_m1_go_no_go_evidence.py --json` 的 `decision` 和阻塞摘要 |
| Probe 认证检查 | `passed` / `degraded` / `blocked` / `not run` | `python scripts/check_probe_auth_readiness.py --markdown` 或 go/no-go 中 `probe_auth_readiness` section 的脱敏摘要；不写 URL、token、账号、密码或 user id |
| M1 线上证据摘要 | `rendered` / `blocked` / `not run` | `python scripts/render_m1_live_evidence_summary.py --go-no-go-json <private-go-no-go.json> --output <private-workdir>\m1-live-evidence-summary.md` 的脱敏 Markdown |
| M1 证据包归档 | `passed` / `blocked` / `not run` | `python scripts/build_m1_evidence_bundle.py --go-no-go-json <private-go-no-go.json> --output-dir <private-workdir>\m1-evidence-bundle --execute` 的 manifest 摘要；证据包留在私有目录 |

## 3. 发布候选检查

| 检查 | 命令或证据 | 结果 |
|---|---|---|
| 工作区边界 | `git status --short --branch` | passed / blocked / not run |
| M1 资源申请包 | `uv run python scripts\render_m1_resource_request.py --markdown` | ready_to_collect_resources / not run |
| M1 首部署 dry-run | `uv run python scripts\check_m1_first_deploy_dry_run.py --json` | passed / blocked / not run |
| 发布包 manifest | `uv run python scripts\build_release_artifact.py --execute --output-dir <release-output-dir> --json` | passed / blocked / not run |
| 服务器首部署脚本 | `sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>`；`sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>` | dry-run only / passed / blocked / not run |
| RAG 数据源治理 | `uv run python scripts\check_travel_data_sources.py` | passed / blocked / not run |
| 公开数据候选采集 | `uv run python scripts\collect_public_travel_data_candidates.py --city xian --output-dir <private-workdir>\public-travel-candidates --execute` | passed / degraded / blocked / not run |
| 公开数据候选审查 | `uv run python scripts\review_public_travel_data_candidates.py --candidate-json <private-workdir>\public-travel-candidates\public-travel-data-candidates.json --review-json <private-workdir>\public-travel-candidate-review.json --output-dir <private-workdir>\approved-public-travel-candidates --execute` | passed / ready_for_review / ready_to_write / blocked / not run |
| M1 输入边界 | `uv run python scripts\check_m1_launch_inputs.py --json` | passed / blocked / not run |
| 服务器 preflight | `uv run python scripts\check_server_preflight_readiness.py --json` | passed / blocked / not run |
| 备份恢复前置 | `uv run python scripts\check_backup_restore_readiness.py --json` | passed / blocked / not run |
| 备份恢复演练证据计划 | `uv run python scripts\collect_backup_restore_drill_evidence.py --json` | not_checked / blocked / not run |
| 外部 API 前置 | `uv run python scripts\check_external_api_readiness.py --json` | passed / blocked / degraded / not run |
| 监控告警前置 | `uv run python scripts\check_monitoring_alerting_readiness.py --json` | passed / blocked / not run |
| 监控告警证据计划 | `uv run python scripts\collect_monitoring_alerting_evidence.py --json` | not_checked / blocked / not run |
| 安全发布前置 | `uv run python scripts\check_security_release_readiness.py --json` | passed / blocked / not run |
| 事故/回滚证据计划 | `uv run python scripts\collect_incident_rollback_evidence.py --json` | not_checked / blocked / not run |
| M1 部署总门禁 | `uv run python scripts\check_m1_deployment_gate.py --json` | passed / blocked / not run |
| M1 记录生成器 | `uv run python scripts\render_m1_acceptance_record.py` | passed / blocked / not run |
| M1 smoke 证据计划 | `uv run python scripts\collect_m1_smoke_evidence.py --json` | not_checked / blocked / not run |
| M1 go/no-go 计划 | `uv run python scripts\collect_m1_go_no_go_evidence.py --json` | not_checked / blocked / not run |
| Probe 认证检查 | `uv run python scripts\check_probe_auth_readiness.py --base-url <public-url> --username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD --markdown` | passed / degraded / blocked / not run |
| M1 线上证据摘要 | `uv run python scripts\render_m1_live_evidence_summary.py --go-no-go-json <private-go-no-go.json> --output <private-workdir>\m1-live-evidence-summary.md` | rendered / blocked / not run |
| M1 证据包归档 | `uv run python scripts\build_m1_evidence_bundle.py --go-no-go-json <private-go-no-go.json> --output-dir <private-workdir>\m1-evidence-bundle --execute` | passed / blocked / not run |
| 格式检查 | `git diff --check` | passed / blocked / not run |
| Python 编译 | `uv run python -m compileall app tests scripts` | passed / blocked / not run |
| 后端测试 | `uv run python -m pytest -q` | passed / blocked / not run |
| 前端语法 | `node --check frontend\app.js` | passed / blocked / not run |
| 报告渲染 | `node scripts\verify_frontend_report_renderer.js` | passed / blocked / not run |
| 浏览器回归 | `node scripts\verify_frontend_browser_regression.js` | passed / blocked / not run |

未运行原因：

```text

```

## 4. 目标环境 readiness

| 检查 | 命令 | 结果 | 摘要 |
|---|---|---|---|
| Production readiness | `python scripts/check_runtime_readiness.py --target production --json` | passed / blocked / degraded / not run |  |
| Acceptance preflight | `python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url <public-url> --json` | passed / blocked / degraded / not run |  |
| Server preflight | `python scripts/check_server_preflight_readiness.py --check-docker --check-deploy-dir --check-disk --check-health-url --json` | passed / blocked / warning / not run |  |
| Monitoring readiness | `python scripts/check_monitoring_alerting_readiness.py --check-health-url --json` | passed / blocked / not run |  |
| M1 smoke evidence | `python scripts/collect_m1_smoke_evidence.py --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json` | passed / blocked / degraded / not run |  |
| Probe auth readiness | `python scripts/check_probe_auth_readiness.py --base-url <public-url> --username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD --execute-login --markdown` | passed / blocked / degraded / not run |  |
| M1 go/no-go evidence | `python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json` | go_for_m1_controlled_trial / conditional_go / no_go / not_checked |  |
| M1 evidence bundle | `python scripts/build_m1_evidence_bundle.py --go-no-go-json <private-go-no-go.json> --output-dir <private-workdir>\m1-evidence-bundle --execute` | passed / blocked / not run |  |
| Health live | `GET /health/live` | passed / blocked / not run |  |
| Health ready | `GET /health/ready` | passed / blocked / degraded / not run |  |

Blocked reasons summary:

```text

```

Repair suggestions summary:

```text

```

## 5. Acceptance smoke

| 项目 | 结果 |
|---|---|
| Command | `python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url <public-url> --json` |
| Evidence collector | `python scripts/collect_m1_smoke_evidence.py --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json` |
| Scenario count |  |
| Passed |  |
| Blocked |  |
| Failed |  |
| Degraded |  |
| Not run |  |

失败或阻塞分类：

```text

```

## 6. RAG 和报告验收

| 检查 | 命令 | 结果 | 摘要 |
|---|---|---|---|
| RAG retrieval | `python scripts/evaluate_rag_retrieval.py --json` | passed / blocked / not run |  |
| Mixed-corpus safety | `python scripts/evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json` | passed / blocked / not run |  |
| Multimodal RAG deep gate | `python scripts/check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e` | passed / blocked / not run |  |
| Structured report | 前端报告渲染和导出验证 | passed / blocked / not run |  |

注意：离线 RAG `passed` 不能替代真实向量库 `configured`，也不能替代在线 Agent 验收。

## 7. 外部 API 状态

| 服务 | 状态 | 影响 | 降级策略 | 后续动作 |
|---|---|---|---|---|
| DashScope | ready / blocked / degraded |  |  |  |
| 高德地图 | ready / blocked / degraded |  |  |  |
| Tavily | enabled / disabled / blocked / degraded |  |  |  |
| VariFlight | enabled / disabled / blocked / degraded |  |  |  |
| aigohotel | enabled / disabled / blocked / degraded |  |  |  |
| 12306 MCP | enabled / disabled / blocked / degraded |  |  |  |
| LangSmith | enabled / disabled / blocked / degraded |  |  |  |

外部 API 事故记录链接或编号：

```text

```

## 8. 备份和回滚

| 项目 | 状态 | 说明 |
|---|---|---|
| 代码回滚版本 | ready / blocked |  |
| PostgreSQL 备份 | ready / blocked / not run |  |
| PostgreSQL 恢复演练 | passed / blocked / not run |  |
| 备份恢复演练证据 | passed / blocked / not_checked / not run | 不写真实备份路径或 dump 文件名 |
| Redis 持久化 | ready / blocked / not run |  |
| RAG 向量库备份或重建路径 | ready / blocked / not run |  |
| 回滚命令已验证 | passed / blocked / not run |  |
| 回滚演练证据 | passed / blocked / degraded / not_checked / not run | 不写原始工单、日志或截图 |
| 可接受数据丢失窗口 | ready / blocked |  |

回滚触发条件：

```text

```

## 9. 监控告警

| 项目 | 状态 | 说明 |
|---|---|---|
| Health check alert | passed / blocked / not measured |  |
| Readiness alert | passed / blocked / not measured |  |
| Alert delivery evidence | passed / blocked / degraded / not_checked / not run | 不写真实通知内容 |
| P95 first token | measured / not measured |  |
| P95 turn elapsed | measured / not measured |  |
| Tool failure rate | measured / not measured |  |
| External API incident tracking | ready / blocked / not measured |  |
| Cost and quota budget | ready / warning / exceeded / not measured |  |
| Backup alert | ready / blocked / not measured |  |
| Log redaction sample | passed / blocked / not checked |  |

## 10. 安全发布和密钥轮换

| 项目 | 状态 | 说明 |
|---|---|---|
| Public release boundary | passed / blocked / not run |  |
| Secret store | ready / blocked |  |
| JWT secret | ready / rotated / blocked |  |
| Provider API keys | ready / rotated / blocked |  |
| PostgreSQL secret | ready / rotated / blocked |  |
| Redis secret | ready / rotated / blocked |  |
| Leak response owner | ready / blocked |  |
| Last rotation summary | recorded / not recorded | 只写变量名和结果 |

## 11. 最终结论

| 字段 | 内容 |
|---|---|
| M1 trial status | passed / blocked / degraded / not run |
| M1 go/no-go decision | go_for_m1_controlled_trial / conditional_go / no_go / not_checked |
| Can open to whitelist users | yes / no |
| Can claim production-ready | no |
| Remaining P0 risks |  |
| Remaining P1 risks |  |
| Next action owner |  |
| Next review time |  |

结论摘要：

```text

```

## 12. 禁止写入本记录的内容

- 真实 API Key、Access Token、Refresh Token、Cookie、私钥或密码。
- `.env`、数据库连接串、SSH 私钥、浏览器 Cookie。
- 真实客户姓名、手机号、证件号、订单、支付、发票或合同。
- 原始聊天全文、日志原文、数据库备份、向量库文件或 `.runtime` 证据包。
- 未整理 prompt 草稿或本地临时路径。
