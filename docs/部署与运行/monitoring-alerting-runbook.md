# Monitoring and Alerting Runbook（监控告警手册）

本文定义 ZhiXing Travel Planner 在 M1 受控试运行中的监控、告警、运行指标和脱敏证据留存方式。M1 阶段目标不是一次性接入完整 APM（应用性能监控）或 OpenTelemetry（开放遥测标准），而是先把可用性、就绪状态、对话耗时、工具失败、外部 API、成本配额、备份恢复和日志脱敏纳入可执行运维闭环。

## 1. 当前可观测边界

当前已经具备的工程证据：

- `/health/live`：应用进程存活检查。
- `/health/ready`：数据库、Redis、RAG（检索增强生成）、LLM（大语言模型）、地图和运行依赖就绪检查。
- `turn_observability`：单轮对话的安全摘要，包括首响、总耗时、工具调用、工具失败、兜底、降级和 token（文本令牌）估算。
- `tool_audit`：工具调用的安全摘要，包括状态、耗时、重试、证据类型和需核验语义。
- `runtime_governance`：评估中的运行预算、慢路径、成本风险、工具压力和错误摘要。
- `check_runtime_readiness.py`：生产、验收和 RAG 安全门禁。
- `run_evaluation_scenarios.py`：acceptance smoke/core（验收冒烟/核心场景）入口。

当前尚未具备：

- 完整分布式 trace（链路追踪）。
- 指标数据库和可视化看板。
- 自动分页值班系统。
- 真实供应商账单归因系统。
- 多实例、跨区域和高可用告警。

因此 M1 监控口径应写成“轻量运行观测 + 健康检查 + 脱敏验收摘要”，不能写成完整生产 APM。

可以先生成监控告警证据计划。默认不读取 `.env`、不触发真实告警、不探测网络：

```sh
python scripts/collect_monitoring_alerting_evidence.py --json
```

目标环境完成告警演练后，再显式收集脱敏证据：

```sh
python scripts/collect_monitoring_alerting_evidence.py \
  --include-readiness \
  --check-health-url \
  --require-alert-delivery-declaration \
  --require-metric-declaration \
  --json
```

该脚本不会主动发送测试告警；真实投递需要在云监控、Prometheus、企业 IM、邮件或短信平台侧触发，再把状态写成变量声明。公开记录只写状态，不写真实通知内容、手机号、邮箱、群机器人地址或截图原文。

M1 如果还没有外部通知通道，可以先执行文件 sink（投递落盘）演练，证明 health/readiness 检查能生成并送达测试告警事件。该方式只能证明本机告警链路和证据留存，不等同于人工值班送达：

```sh
python scripts/run_health_alert_delivery_drill.py \
  --base-url http://127.0.0.1:8000 \
  --allow-local-base-url \
  --sink-file /absolute/path/outside/repo/health-readiness-alert-drill.jsonl \
  --json
```

如果脚本返回 `status=passed`，且 `delivery.delivered_events=2`，可以把 M1 的 `ZHIXING_HEALTH_ALERT_DELIVERY_STATUS` 和 `ZHIXING_READINESS_ALERT_DELIVERY_STATUS` 声明为 `passed`。公开记录仍要注明这是文件 sink 演练；进入 M2 前必须替换为云监控、企业 IM、邮件、短信或电话等真实外部通知通道。

M1 还可以执行轻量 runtime probe（运行探针）采样，记录 health/readiness 的错误率和 P95（第 95 百分位）延迟。该脚本只记录状态码和耗时，不记录响应正文、真实域名、密钥或用户数据：

```sh
python scripts/collect_m1_runtime_probe_metrics.py \
  --base-url http://127.0.0.1:8000 \
  --allow-local-base-url \
  --sample-count 20 \
  --interval-seconds 0.2 \
  --max-error-rate 0 \
  --max-p95-ms 1000 \
  --output /absolute/path/outside/repo/m1-runtime-probe-metrics.json \
  --json
```

如果脚本返回 `status=passed`，可以把 M1 的 `ZHIXING_ERROR_RATE_MONITOR_STATUS` 和 `ZHIXING_P95_LATENCY_MONITOR_STATUS` 声明为 `passed`，但记录中必须说明这是 health/readiness 探针指标，不等同于真实用户对话 P95、工具失败率、成本告警或完整 APM（应用性能监控）。

M1 日志脱敏抽样可以用最近 backend/caddy 日志作为输入，扫描常见 URL query 密钥、赋值型密钥、Bearer token（持有者令牌）、JWT（JSON Web Token，令牌认证）、手机号、邮箱和身份证号形态。脚本只输出统计和类别，不输出原始日志行：

```sh
docker compose logs --tail=500 backend caddy 2>&1 | \
  python scripts/check_log_redaction_sample.py \
    --stdin \
    --source-label m1_backend_caddy_recent_logs \
    --output /absolute/path/outside/repo/m1-log-redaction-sample.json \
    --json
```

如果脚本返回 `status=passed`，可以把 M1 的 `ZHIXING_LOG_REDACTION_SAMPLE_STATUS` 声明为 `passed`。该结果只证明本次样本未发现明显敏感形态，不等同于完整日志留存、全量 SIEM（安全信息与事件管理）或未来所有日志路径都安全。

## 2. M1 监控目标

| 目标 | 最低要求 |
|---|---|
| 可用性 | `/health/live` 和 `/health/ready` 有定时检查，异常能通知负责人 |
| 就绪状态 | readiness 输出 `blocked` 时阻断发布或暂停试运行 |
| 性能 | 记录任意首个助手片段、总耗时、P95（第 95 百分位）趋势和慢请求原因；首片段可能只是固定 ACK（确认收到） |
| 工具质量 | 记录工具调用数、失败数、降级数、需核验数和外部 API 分类 |
| 成本配额 | 记录 token 估算、LLM/地图/搜索/航班/酒店调用预算和配额告警 |
| 数据安全 | 日志和告警不包含密钥、Cookie、完整 token、PII（个人可识别信息）或用户原文 |
| 备份恢复 | 备份失败、恢复演练失败或备份过期必须告警 |
| 事故复盘 | 每次告警都有脱敏摘要、影响范围、处理动作和恢复判定 |

## 3. 指标和阈值

M1 建议从以下阈值开始，真实试运行后再按数据调整。

当前 API 可能先发送固定 ACK，因此 `first_token_seconds` 只表示连接后任意首个助手片段的等待时间。该指标适合监控网关、SSE 建连和请求接收，不代表 LLM 已开始输出有意义内容，也不能定位工具冷启动；完整业务延迟应看 `total_elapsed_seconds`，当前尚未单独采集首个有意义内容耗时。

| 指标 | Warning（预警） | Critical（严重） | 处理 |
|---|---|---|---|
| `/health/live` | 单次失败 | 连续 2 次失败 | 检查容器、进程、端口和反向代理 |
| `/health/ready` | `degraded` 持续 5 分钟 | `not_ready` 或 `blocked` | 暂停发布或试运行，按 `blocked_reasons` 修复 |
| 后端 5xx | 5 分钟内 > 1% | 5 分钟内 > 5% | 查看错误日志和最近发布 |
| 任意首个助手片段（可为 ACK） | P95 > 30 秒 | P95 > 60 秒 | 排查网关、网络、SSE 建连和请求接收；LLM / 工具慢点看单轮总耗时 |
| 单轮总耗时 | P95 > 180 秒 | 超过运行预算或大量超时 | 排查工具链、模型响应和状态循环 |
| 工具失败率 | 10 分钟内 > 10% | 10 分钟内 > 30% | 按外部 API 故障手册降级 |
| fallback 次数 | 明显高于基线 | 连续多轮兜底 | 检查 prompt、工具、RAG 和外部 API |
| token 估算 | 达到日预算 80% | 达到日预算 100% | 暂停高成本验收或切换低成本场景 |
| 外部 API 401/403 | 任意出现 | 连续出现 | 检查密钥、权限、白名单 |
| 外部 API 429 | 单次出现 | 持续限流 | 降并发、换窗口、申请配额 |
| 磁盘使用率 | > 80% | > 90% | 清理可删除运行产物，扩容或迁移备份 |
| PostgreSQL 备份 | 超过 24 小时未成功 | 发布前无备份 | 阻断发布 |
| 恢复演练 | 未完成 | 恢复失败 | 不得进入 M2 有限生产 |

## 4. 采集方式

M1 可以先用服务器定时任务、云监控或轻量脚本采集。不要为了 M1 强行引入复杂平台，但要保证检查可重复。

### 4.1 健康检查

```sh
curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/live"
curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/ready"
```

### 4.2 Readiness 和验收

```sh
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
docker compose exec -T backend python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url "$ZHIXING_PUBLIC_BASE_URL" --json
docker compose exec -T backend python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url "$ZHIXING_PUBLIC_BASE_URL" --json
```

### 4.3 容器和资源

```sh
docker compose ps
docker stats --no-stream
df -h
```

### 4.4 日志

```sh
docker compose logs --since=10m backend
docker compose logs --since=10m caddy
```

日志只能用于排障，不直接粘贴到公开验收记录。若日志中出现疑似密钥、Cookie、完整 token 或用户隐私，应先脱敏再摘要。

### 4.5 备份告警状态

备份告警状态用 `scripts/check_backup_alert_status.py` 采集。脚本只检查备份目录是否在 Git 工作区外、最近 PostgreSQL dump 是否新鲜且非空、RAG（检索增强生成）恢复演练产物是否包含公开和内部 Chroma（向量库）文件；它不读取 `.env`，不读取备份内容，也不在报告中输出真实路径或文件名。

```sh
python scripts/check_backup_alert_status.py \
  --backup-dir "<backup-dir-outside-git>" \
  --max-age-hours 48 \
  --min-size-bytes 1024 \
  --require-rag-restore-artifact \
  --output "<private-evidence-dir>/m1-backup-alert-status.json" \
  --json
```

当报告 `status=passed` 时，可以把 `ZHIXING_BACKUP_ALERT_STATUS` 声明为 `passed`。这只证明 M1 备份新鲜度和恢复演练产物形态已检查，不证明异地备份、加密对象存储、长期 retention（保留策略）或完整灾备演练。

### 4.6 工具失败率监控

工具失败率用 `scripts/check_tool_failure_monitor_status.py` 从 `tool_audit_event` 表采集。脚本只读取工具名、原始状态、错误分类、证据类型、耗时和时间窗口，不读取工具入参、工具出参、`.env` 或数据库连接串，也不输出真实数据库地址。

这里的 failure rate（失败率）专指 hard failure rate（硬失败率）。分类先看显式 `semantic_status`，再看 `error_type`，最后才用原始 `status` 兜底：只有 `service_exception` 进入分子；没有更具体语义时，原始 `failed`、`failure`、`timeout`、`error` 才归为 `service_exception`。因此 `failed + empty_*_result` 仍属于 `not_found`，只进入 `fallback_count`；`needs_verification`、参数不足、`skipped` 和 `approval_required` 只进入 `degraded_count`。报告同时保留 raw `status_counts`（原始状态分布）和 `semantic_status_counts`（语义状态分布），方便排查但不改变告警阈值。`warn_failure_rate` 和 `max_failure_rate` 必须是有限数，且满足 `0 <= warn <= max <= 1`；`NaN` 和正负无穷会被 CLI（命令行接口）直接拒绝。

```sh
python scripts/check_tool_failure_monitor_status.py \
  --lookback-hours 24 \
  --min-sample-count 1 \
  --warn-failure-rate 0.2 \
  --max-failure-rate 0.5 \
  --allow-empty-sample \
  --output "<private-evidence-dir>/m1-tool-failure-monitor.json" \
  --json
```

`--allow-empty-sample` 只适合 M1 受控试运行早期，用来证明监控查询链路可用但近期没有工具样本；这不能证明真实用户工具质量。进入 M2 前，应取消该选项或提高 `--min-sample-count`，并把高失败率作为 P1/P2 运维问题处理。

## 5. 告警分级

| 等级 | 触发条件 | 响应 |
|---|---|---|
| P0 | 服务不可用、主链路 blocked、数据损坏、密钥泄露、备份不可恢复 | 立即暂停试运行，负责人处理，恢复后复跑 readiness 和 smoke |
| P1 | 外部必需 API 不可用、错误率明显升高、P95 严重超阈值、发布后回归 | 降级或回滚，记录影响范围和修复动作 |
| P2 | 可选工具降级、观测平台不可用、成本接近预算 | 保持服务，记录风险，安排修复 |
| P3 | 文档、看板、低频提醒或趋势类问题 | 进入后续改进 |

## 6. 处理流程

1. 确认告警是否真实：检查健康接口、readiness、容器状态和最近发布。
2. 判断影响范围：全站、单接口、单外部供应商、单验收场景，还是单个用户。
3. 先保护用户：对可选能力降级，对高风险动作保持禁用，对主链路 blocked 暂停试运行。
4. 修复或回滚：优先配置修复，其次应用回滚；数据恢复必须按备份恢复手册执行。
5. 复跑验证：至少跑 `/health/ready`；影响核心链路时跑 acceptance smoke。
6. 记录摘要：按 M1 验收记录模板写状态、影响、处理、结果和剩余风险。

## 7. 日志脱敏边界

允许记录：

- `turn_id`、场景 id、状态码、耗时、错误类型、服务名、工具名、脱敏后的阻塞原因。
- 聚合指标：错误率、P95、失败数量、预算使用比例、备份状态。

禁止记录：

- API Key、Access Token、Refresh Token、Cookie、私钥、密码。
- 完整 `.env`、数据库连接串、SSH 私钥。
- 真实客户姓名、手机号、证件号、订单、付款凭证、合同。
- 完整聊天全文、完整工具入参、完整供应商响应、未脱敏异常堆栈。

## 8. 成本和配额监控

M1 阶段至少需要人工或供应商控制台跟踪：

| 项目 | 关注点 |
|---|---|
| LLM | 日调用量、token 估算、真实账单、失败率、限流 |
| 地图 | 后端 API 调用量、前端 key 限制、额度和 429 |
| 搜索 | 调用次数、失败率、额度 |
| 航班/酒店 | 测试额度、QPS、签名错误、供应商故障 |
| LangSmith | trace 量、采样策略、是否含敏感数据 |

注意：项目内 token 目前是字符近似估算，不等于真实账单。真实成本必须以供应商控制台或账单为准。

M1 成本告警状态可以用 `scripts/check_cost_alert_status.py` 留存脱敏证据。脚本支持两种输入：一是传入私有账单或人工估算的 `--actual-spend-cny` / `--estimated-spend-cny`；二是在 M1 早期通过 `--check-db-activity --allow-zero-traffic-estimate` 只读查询近期 `message` 和 `tool_audit_event` 计数，证明当前窗口没有 App 对话和工具审计流量，从而允许 0 CNY 估算。

```sh
python scripts/check_cost_alert_status.py \
  --daily-budget-cny "<daily-budget-cny>" \
  --check-db-activity \
  --lookback-hours 24 \
  --owner-declared \
  --manual-check-status passed \
  --allow-zero-traffic-estimate \
  --output "<private-evidence-dir>/m1-cost-alert-status.json" \
  --json
```

这个检查不读取 `.env`、不读取消息正文、不读取供应商账单原文，也不会输出数据库连接串。`--allow-zero-traffic-estimate` 只适合 M1 无真实流量窗口；进入 M2 前必须换成供应商账单导出、控制台截图或 API 采集结果，并验证真实预算告警或配额上限。

外部依赖韧性记录会把成本告警状态、工具失败监控、外部 API readiness、超时重试策略和降级演练放在一份私有记录中做最终校验：

```sh
python scripts/check_external_dependency_resilience_record.py \
  --template \
  --output "<private-evidence-dir>/external-dependency-resilience-record.local.json"

python scripts/check_external_dependency_resilience_record.py \
  --record-json "<private-evidence-dir>/external-dependency-resilience-record.local.json" \
  --output "<private-evidence-dir>/external-dependency-resilience-report.json" \
  --json
```

该记录必须留在私有证据目录，不提交 Git。校验通过只能说明 M1 的外部依赖降级、预算和监控证据已脱敏收口；不能写成完整 APM（应用性能监控）、供应商 SLA、自动配额 enforcement（强制执行）或长期稳定性证明。

## 9. 需要用户准备的信息

请只确认状态，不发送真实密钥：

| 字段 | 示例 |
|---|---|
| `monitoring_provider` | 云监控 / 自建脚本 / Prometheus / 待定 |
| `alert_channel` | 邮件 / 短信 / 企业 IM / 电话 / 待定 |
| `alert_owner` | 谁接收 P0/P1 告警 |
| `log_retention` | 7 天 / 14 天 / 30 天 |
| `metric_retention` | 7 天 / 30 天 / 待定 |
| `daily_cost_budget` | LLM、地图、搜索、航班、酒店每日预算 |
| `quota_owner` | 谁能登录供应商控制台处理配额 |
| `incident_review_cadence` | 每次 P0/P1 后复盘 / 每周汇总 |

## 10. 验收记录字段

M1 验收记录中至少补充：

| 字段 | 内容 |
|---|---|
| `health_check_status` | passed / degraded / blocked |
| `readiness_status` | passed / degraded / blocked |
| `p95_first_token_seconds` | 数值或 not measured；只代表任意首个助手片段，可能是固定 ACK |
| `p95_turn_elapsed_seconds` | 数值或 not measured |
| `tool_failure_rate` | 百分比或 not measured |
| `external_api_incidents` | 无 / 有，引用脱敏编号 |
| `cost_budget_status` | ok / warning / exceeded / not measured |
| `backup_alert_status` | ok / warning / blocked |
| `log_redaction_status` | passed / blocked / not checked |

没有监控平台时，可以先写 `not measured`，不能写成 `passed`。

## 11. 进入 M2 前的最低门槛

从 M1 进入 M2 有限生产前，至少需要：

- 健康检查和 readiness 告警自动化。
- 错误率、P95、工具失败率和外部 API 失败率可观测。
- 备份失败和恢复演练失败可告警。
- 成本和配额有阈值和负责人。
- P0/P1 事故有脱敏复盘记录。
- 日志脱敏规则经过抽样检查。
- `collect_monitoring_alerting_evidence.py` 已显式执行并保留脱敏摘要。

缺少这些证据时，结论继续保持 M1 或 `blocked`，不写“生产可用”。
