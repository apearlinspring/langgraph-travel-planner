# Incident Response and Rollback Runbook（事故响应与回滚演练手册）

本文定义 ZhiXing Travel Planner 在 M1 受控试运行中的 P0/P1 事故响应、发布回滚、回滚后复验和脱敏证据留存方式。它不是生产值班系统本身，而是把“出事后能否有人处理、能否回滚、回滚后是否复验”变成可检查的工程证据。

## 1. 边界

- 本项目当前不开放真实支付、真实预订、真实锁价、真实出票或自动履约。
- 回滚脚本和证据脚本不得删除 `.env`、数据库卷、Redis 卷、日志目录、向量库目录或备份目录。
- 原始事故工单、日志、截图、通知内容、用户对话和供应商响应不得进入 Git。
- 公开记录只写状态、负责人角色、影响范围、复验结果和剩余风险。

## 2. 证据收集器

可以先生成事故/回滚证据计划。默认不读取 `.env`、不执行回滚、不启动服务、不触网：

```sh
python scripts/collect_incident_rollback_evidence.py --json
```

目标环境完成回滚演练和事故复盘后，再显式收集脱敏证据：

```sh
python scripts/collect_incident_rollback_evidence.py \
  --require-ownership-declaration \
  --require-rollback-drill-declaration \
  --require-incident-review-declaration \
  --include-post-rollback-smoke-evidence \
  --check-health-url \
  --run-gate \
  --json
```

如果回滚后必须跑真实 acceptance smoke，再显式追加 `--run-acceptance-smoke`。该选项可能调用 LLM（大语言模型）和外部 API（应用程序接口），需要验收窗口和预算。

## 3. P0/P1 分级

| 等级 | 示例 | 立即动作 |
|---|---|---|
| P0 | 服务不可用、数据损坏、密钥泄露、备份不可恢复、主链路持续 blocked | 暂停试运行，负责人接管，保留现场，修复后复跑 smoke |
| P1 | 发布后回归、外部必需 API 不可用、错误率或 P95 明显异常 | 降级或回滚，记录影响范围和修复动作 |
| P2 | 可选工具降级、观测平台不稳定、成本接近阈值 | 保持服务，记录风险，安排修复 |

## 4. 回滚演练

回滚演练至少证明：

| 项目 | 要求 |
|---|---|
| 回滚负责人 | 已明确 |
| 事故负责人 | 已明确 |
| 回滚目标 | 上一版 release、镜像、归档或部署目录备份存在 |
| 数据安全 | 回滚不覆盖 `.env`、数据库卷、Redis 卷、向量库或日志目录 |
| 回滚后 health | `/health/live` 和 `/health/ready` 可解释 |
| 回滚后 smoke | M1 gate 或 acceptance smoke 已复跑 |
| 事故复盘 | 影响范围、根因、动作、预防项和剩余风险已脱敏记录 |

真实切换版本前，可以先跑非破坏式回滚演练，验证部署目录、回滚备份、发布包边界、当前 health 和 M1 模拟确认页红线。该检查不执行回滚、不重启服务、不删除文件：

```sh
python scripts/check_rollback_rehearsal_status.py \
  --deploy-dir "<deploy-dir>" \
  --backup-dir "<rollback-backup-dir>" \
  --release-archive "<release-archive>" \
  --expected-archive-sha256 "<archive-sha256>" \
  --check-health \
  --check-mock-checkout \
  --output "<private-evidence-dir>/m1-rollback-rehearsal.json" \
  --json
```

这条证据只能声明 `ZHIXING_ROLLBACK_TARGET_STATUS=passed` 和 `ZHIXING_ROLLBACK_DATA_SAFETY_STATUS=passed`。因为它没有真实切换版本，`ZHIXING_ROLLBACK_DRILL_STATUS` 仍只能保持 `degraded`，直到安排真实回滚窗口并完成回滚后 health/smoke。

## 5. 真实回滚窗口记录

真实回滚窗口必须在人工确认窗口内执行，并把执行过程整理成仓库外私有 JSON 记录。记录只写阶段摘要和状态，不写原始日志、截图、密钥、数据库内容或用户对话。

先生成私有记录模板：

```sh
python scripts/check_rollback_execution_record.py --template
```

真实回滚执行后，校验记录并输出脱敏证据：

```sh
python scripts/check_rollback_execution_record.py \
  --record-json "<private-rollback-record.json>" \
  --output "<private-evidence-dir>/m1-rollback-execution-evidence.json" \
  --json
```

校验通过后，才可以把以下声明写为 `passed`：

- `ZHIXING_ROLLBACK_DRILL_STATUS`
- `ZHIXING_ROLLBACK_TARGET_STATUS`
- `ZHIXING_POST_ROLLBACK_HEALTH_STATUS`
- `ZHIXING_POST_ROLLBACK_SMOKE_STATUS`
- `ZHIXING_ROLLBACK_DATA_SAFETY_STATUS`

这只证明 M1 回滚窗口、回滚后 health/smoke 和数据安全边界有脱敏记录，不证明自动故障转移、长期高可用、完整灾备或真实交易履约能力。

## 6. 桌面事故演练

没有真实 P0/P1 事故时，可以用桌面演练记录证明“发现、响应、沟通、复盘和预防项”这条管理闭环已经走过一遍。记录文件必须放在仓库外的私有目录，不得包含原始日志、截图、用户对话、供应商响应、`.env` 或密钥。

先生成私有记录模板：

```sh
python scripts/check_incident_tabletop_status.py --template
```

填写后校验并输出脱敏证据：

```sh
python scripts/check_incident_tabletop_status.py \
  --record-json "<private-tabletop-record.json>" \
  --output "<private-evidence-dir>/m1-incident-tabletop-evidence.json" \
  --json
```

校验通过后，可以把以下声明写为 `passed`：

- `ZHIXING_INCIDENT_RESPONSE_STATUS`
- `ZHIXING_INCIDENT_REVIEW_STATUS`
- `ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS`
- `ZHIXING_INCIDENT_COMMUNICATION_STATUS`

这只证明桌面演练记录完整，不证明真实事故已经发生、真实通知已经送达、真实回滚已经执行或回滚后 smoke 已通过。

## 7. 状态变量

请只确认状态，不发送真实日志、截图或工单链接。

| 变量 | 示例 |
|---|---|
| `ZHIXING_ROLLBACK_OWNER` | 发布/运维负责人角色 |
| `ZHIXING_INCIDENT_OWNER` | 事故负责人角色 |
| `ZHIXING_ROLLBACK_DRILL_STATUS` | passed / degraded / blocked / not run |
| `ZHIXING_ROLLBACK_TARGET_STATUS` | passed / blocked |
| `ZHIXING_POST_ROLLBACK_HEALTH_STATUS` | passed / degraded / blocked |
| `ZHIXING_POST_ROLLBACK_SMOKE_STATUS` | passed / degraded / blocked |
| `ZHIXING_ROLLBACK_DATA_SAFETY_STATUS` | passed / blocked |
| `ZHIXING_INCIDENT_RESPONSE_STATUS` | passed / blocked |
| `ZHIXING_INCIDENT_REVIEW_STATUS` | passed / blocked |
| `ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS` | passed / blocked |
| `ZHIXING_INCIDENT_COMMUNICATION_STATUS` | passed / blocked |

## 8. 回滚后复验

每次回滚后至少执行：

```sh
docker compose ps
curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/live"
curl -fsS "$ZHIXING_PUBLIC_BASE_URL/health/ready"
docker compose exec -T backend python scripts/check_m1_deployment_gate.py \
  --include-acceptance \
  --check-backend \
  --check-server-health-url \
  --check-monitoring-health-url \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

影响核心链路时追加：

```sh
docker compose exec -T backend python scripts/run_evaluation_scenarios.py \
  --acceptance-smoke \
  --base-url "$ZHIXING_PUBLIC_BASE_URL" \
  --json
```

## 9. 禁止事项

- 不用事故记录保存 `.env`、数据库连接串、真实密钥、供应商 token 或 Cookie。
- 不把原始日志、用户对话全文、通知截图、工单截图或数据库 dump 放进 Git。
- 不把“有负责人”写成“回滚演练通过”。
- 不把“回滚后 health 通过”写成“业务全链路恢复”，除非 smoke 和相关门禁也通过。
- 不用 `git reset --hard` 或批量删除目录来清理生产部署。
