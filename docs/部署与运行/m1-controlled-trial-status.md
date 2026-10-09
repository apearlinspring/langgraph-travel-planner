# M1 受控试运行记录

- 证据日期：2026-07-03
- 证据范围：仓库外私有目标环境记录；未绑定当前 commit
- 当前版本验证：pending

本文记录 2026-07-03 的 M1 试运行。完整记录保存在仓库外，以下为公开摘要。摘要未绑定当前 commit，当前版本需要重新验收。

## 验证结果

当时的目标版本达到 `controlled-trial ready`。验证覆盖部署切换、健康与就绪检查、PostgreSQL / Redis、备份与非生产恢复、外部依赖降级、短窗口并发与限流、容量采样、上线复盘，以及认证和聊天链路。M1 不接真实支付、预订或履约。

证据分为基线签核矩阵和补充验收记录。chat 小流量并发采样作为 supplemental evidence 单独列出，使用独立补充 workflow/signoff；旧 private signoff 的范围保持不变。

| 项目 | 2026-07-03 状态 | 验证内容 |
|---|---|---|
| 部署切换 | `passed` | release 切换后，后端和反向代理运行新版本。 |
| 健康检查 | `passed` | 采样窗口内 `health`、`ready` 返回 2xx。 |
| PostgreSQL / Redis | `passed` | 数据库、缓存、容器和运行连接可用。 |
| 备份与恢复 | `passed` | dump 非空且新鲜，catalog 可读；已在临时 PostgreSQL 容器中恢复并清理容器。 |
| 外部依赖 | `passed` | 记录必需依赖、成本预算、失败监控和超时 / 429 / 5xx 降级演练。 |
| 并发与限流 | `passed` | 低风险 GET 接口的短窗口并发、Redis 限流、429 和重试头。 |
| Docker 磁盘治理 | `passed` | 只读清理计划及容器、卷、配置和向量库的保护规则。 |
| 上线与复盘 | `passed` | release、健康检查、问题处理、回滚准备，以及实际故障的根因与修复。 |
| 认证与聊天 | `passed` | 探针用户注册或复用、登录、创建会话和一轮 SSE 返回。 |
| chat 小流量并发采样 | `passed` | 3 个请求、并发 2，均完成 SSE 返回；记录总耗时 P95、首 token P95，完成补充签核。 |
| 私有签核矩阵 | `passed` | 脱敏检查、哈希、go/no-go 决策和负责人签核。 |

尚待补充长窗口压测、多实例运行、PITR / 异地恢复、外部告警投递及供应商长期服务数据。

## 本次暴露并修复的问题

| 问题 | 现象 | 处理 | 沉淀 |
|---|---|---|---|
| Compose project name 漂移 | 从 `current` 目录执行 Compose 时，项目名推断错误，固定容器名与既有 PostgreSQL / Redis 容器冲突 | 部署脚本固定 `COMPOSE_PROJECT_NAME`，并只重建 backend / caddy，保留数据库和缓存 volume | 生产部署不能依赖当前目录名推断 Compose project |
| 备份空 dump | 备份调度存在，但最新 PostgreSQL dump 为 0 字节 | 手动执行一次备份并复跑备份新鲜度探针 | 备份是否存在不够，必须验证大小、新鲜度和 catalog 可读性 |
| 限流串行探针误判 | 串行请求跨过 60 秒窗口，可能看不到 429 | 增加 burst concurrency 探针，验证 200 / 429 分布和限流头 | 限流验收要匹配窗口语义，不能只看总请求数 |
| 探针注册输入校验 | 第一次测试邮箱域名不符合线上校验，返回 `HTTP 422` | 换成标准邮箱格式后注册、登录、SSE 探针通过 | 探针账号也要按真实 API schema 准备 |
| 恢复演练只做 catalog 不够 | 只检查 dump catalog 不能证明可恢复 | 增加临时 PostgreSQL 容器恢复演练，恢复出 public schema 表并清理临时容器 | 备份验收要覆盖“可读”和“可恢复”两层 |
| 外部依赖不能只说“有密钥” | 只声明 API Key 存在不能证明降级策略 | 增加外部 API readiness、成本预算 guard、工具失败监控和超时 / 429 / 5xx 降级演练记录 | 外部依赖验收要写清楚超时、重试、人工核验和不编造库存/锁价 |

## 当前版本复验

重新验收时记录当前 commit、部署 release、时间窗口及测试结果。chat 并发项仍单独进入补充矩阵；如需统一签核，重跑包含该项的完整 workflow，并核对 workflow-report、signoff 与 evidence matrix 的哈希。

## 该历史快照记录的后续优先级

| 优先级 | 下一步 | 验收方式 |
|---|---|---|
| P0 | 把恢复演练候选写入正式运维声明和复盘矩阵 | owner 确认 `ZHIXING_POSTGRES_BACKUP_STATUS` / `ZHIXING_POSTGRES_RESTORE_DRILL_STATUS`，并重新生成 PostgreSQL / Redis ops summary |
| P0 | 把外部依赖韧性记录并入正式上线复盘矩阵 | 外部依赖 resilience report 纳入 `m1_operations_review_record` 或最终 evidence matrix |
| P0 | 如需完全统一基线签核链，重跑包含 chat 并发 section 的完整 workflow + signoff | 新 workflow-report、signoff、evidence matrix 三者哈希和 section 一致 |
| P1 | 把 chat 小流量采样升级为持续监控或更长窗口采样 | 对白名单探针账号执行，记录采样时长、P95、错误率和 blocked/degraded 原因 |
| P1 | 接入外部告警送达 | 文件 sink 之外的云监控、企业 IM、邮件或短信测试告警可达 |
| P1 | 回滚演练从记录升级为执行 | 回滚后 health、ready、mock checkout 和一轮低风险 smoke 通过 |
| P2 | 备案完成后补公网入口复核 | DNS/TLS/反向代理/health/ready/live chat 重新复验 |

## 关联文档

- `docs/部署与运行/deployment-readiness.md`
- `docs/部署与运行/m1-controlled-trial-runbook.md`
- `docs/部署与运行/m1-operations-evidence-playbook.md`
- `docs/部署与运行/postgres-redis-ops-runbook.md`
- `docs/部署与运行/backup-restore-runbook.md`
- `docs/部署与运行/external-api-failure-runbook.md`
- `docs/部署与运行/monitoring-alerting-runbook.md`
- `docs/部署与运行/production-readiness-gap.md`
