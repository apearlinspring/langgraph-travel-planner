# M1 Controlled Trial Historical Snapshot（受控试运行历史快照）

- 证据日期：2026-07-03
- 证据范围：仓库外私有目标环境记录；未绑定当前 commit
- 当前版本验证：pending（待复验）

本文归档 2026-07-03 M1 受控试运行目标版本的公开摘要。真实服务器坐标、域名、SSH（安全外壳协议）目标、`.env`、备份文件、探针账号、聊天内容和私有证据 JSON 均保留在仓库外。由于摘要没有绑定当前 commit，且当前工作树已经变化，下面的通过状态不能继承为当前版本结论。

## 结论

基于当时的私有记录，2026-07-03 目标版本可以声明为 `controlled-trial ready`（受控试运行就绪）；当前版本只能声明“存在历史 M1 证据，待按当前 commit 复验”，不能声明为完整生产就绪。

已验证的范围是：一次正式部署切换、健康与就绪检查、PostgreSQL（关系型数据库）/ Redis（缓存数据库）运行探针、备份新鲜度、一次 PostgreSQL 非生产恢复演练、外部依赖降级演练、短窗口并发与限流探针、服务器容量快照、上线执行记录、运维复盘记录、私有签核矩阵，一轮线上认证 + live chat SSE（服务器发送事件）业务链路，以及一次 chat 链路小流量并发采样。

仍不能承诺：真实支付、真实预订、真实库存锁定、出票、履约、长时间压测、多机高可用、自动扩缩容、异地灾备、完整外部告警送达、供应商 SLA（服务等级协议）或长期稳定性。

## 当时记录为通过的证据

证据分两层记录：

- 基线签核矩阵：覆盖 M1 正式部署切换、健康检查、PostgreSQL / Redis、备份、恢复演练、低风险并发/限流、容量、上线记录、运维复盘和私有签核。
- 补充验收记录：覆盖后续增加的 chat 小流量并发采样。它会进入矩阵的 supplemental evidence（补充证据）区域，并可导入独立补充 workflow/signoff（工作流/签核）做一致性校验，但不反向扩大旧 private signoff（私有签核）的覆盖范围。

| 方向 | 2026-07-03 历史状态 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 正式部署切换 | `passed` | 发布目录切换到 M1 执行 release，后端和反向代理按新版本运行 | 不证明未来每次发布都无风险 |
| 健康检查 | `passed` | `health` 和 `ready` 端点在采样窗口内返回 2xx | 不证明复杂业务链路和外部 API 全部稳定 |
| PostgreSQL / Redis live probe | `passed` | 数据库、缓存、容器状态和运行连接在采样窗口可用 | 不证明长期容量、主从复制或托管级 SLA |
| 备份与非生产恢复演练 | `passed` | PostgreSQL dump 非空且新鲜，`pg_restore --list` 可读，且已恢复到临时非生产 PostgreSQL 容器并清理容器 | 不证明 PITR（时间点恢复）、异地灾备、多可用区高可用或自动故障转移 |
| 外部依赖韧性 | `passed` | LLM / 地图等必需依赖有 readiness 声明，成本预算 guard、工具失败监控、timeout / retry 上限和超时 / 429 / 5xx 降级场景已收束为脱敏记录 | 不证明供应商 SLA、真实配额强约束、所有可选供应商已启用或长期稳定性 |
| 并发与限流 | `passed` | 低风险 GET endpoint 的短窗口并发和 Redis 限流可观测，429 与重试头可验证 | 不证明 chat 高并发、LLM 长尾延迟或压测容量 |
| Docker 磁盘治理 | `passed` | 具备只读清理计划和删除边界，避免误删 volume / `.env` / vector store | 不证明长期镜像增长不会复发 |
| 上线执行记录 | `passed` | release、阶段、健康检查、问题处理、回滚准备和数据安全边界有脱敏记录 | 不替代自动化 CD（持续交付）平台 |
| 运维复盘记录 | `passed` | 已把 Compose project 冲突、备份空 dump、限流探针误判等问题记录为根因、修复和后续项 | 不代表没有其他未知线上问题 |
| 认证 + live chat SSE | `passed` | 线上可以注册/复用探针用户、登录、创建会话，并完成一轮流式聊天返回 | 不证明真实用户规模、长会话稳定性或供应商配额充足 |
| chat 小流量并发采样 | `passed` | 3 个 chat SSE 探针请求、并发 2，均完成流式返回；脱敏记录包含总耗时 P95 和首 token P95；已作为 supplemental evidence 接入矩阵，并通过独立补充 workflow/signoff 导入校验 | 不证明高并发压测、长时间 soak（浸泡测试）、自动扩缩容、供应商长期 SLA，也不扩大旧私有签核范围 |
| 私有签核矩阵 | `passed` | 私有证据链通过脱敏边界、哈希、go/no-go 决策和 release-owner 签核 | 不证明 full production ready |

## 本次暴露并修复的问题

| 问题 | 现象 | 处理 | 沉淀 |
|---|---|---|---|
| Compose project name 漂移 | 从 `current` 目录执行 Compose 时，项目名推断错误，固定容器名与既有 PostgreSQL / Redis 容器冲突 | 部署脚本固定 `COMPOSE_PROJECT_NAME`，并只重建 backend / caddy，保留数据库和缓存 volume | 生产部署不能依赖当前目录名推断 Compose project |
| 备份空 dump | 备份调度存在，但最新 PostgreSQL dump 为 0 字节 | 手动执行一次备份并复跑备份新鲜度探针 | 备份是否存在不够，必须验证大小、新鲜度和 catalog 可读性 |
| 限流串行探针误判 | 串行请求跨过 60 秒窗口，可能看不到 429 | 增加 burst concurrency（并发突发）探针，验证 200 / 429 分布和限流头 | 限流验收要匹配窗口语义，不能只看总请求数 |
| 探针注册输入校验 | 第一次测试邮箱域名不符合线上校验，返回 `HTTP 422` | 换成标准邮箱格式后注册、登录、SSE 探针通过 | 探针账号也要按真实 API schema（接口结构）准备 |
| 恢复演练只做 catalog 不够 | 只检查 dump catalog 不能证明可恢复 | 增加临时 PostgreSQL 容器恢复演练，恢复出 public schema 表并清理临时容器 | 备份验收要覆盖“可读”和“可恢复”两层 |
| 外部依赖不能只说“有密钥” | 只声明 API Key 存在不能证明降级策略 | 增加外部 API readiness、成本预算 guard、工具失败监控和超时 / 429 / 5xx 降级演练记录 | 外部依赖验收要写清楚超时、重试、人工核验和不编造库存/锁价 |

## 当前引用这份历史快照时的公开口径

可以说：

- 2026-07-03 的目标版本曾完成一次 M1 受控试运行部署切换，并在仓库外保存脱敏证据；当前 commit 仍需复验。
- PostgreSQL / Redis、备份、非生产恢复演练、外部依赖降级、限流、短窗口并发、健康检查、一轮真实 chat SSE 链路和一次 chat 小流量并发链路都跑过采样验证。
- 上线中遇到过 Compose project name 冲突、备份空 dump、限流探针误判和探针注册校验问题，并分别形成脚本修复或运维复盘记录。
- M1 只支持站内模拟订单确认，不接真实支付、库存锁定、出票或履约。
- chat 小流量并发采样属于补充验收证据，矩阵会单独列出；它可以有独立补充 workflow/signoff，但不写成旧 private signoff 已覆盖的新范围。

不能说：

- 这是完整生产系统。
- 已经具备高并发 chat 压测结论。
- 已经完成异地灾备、PITR 或完整跨机器恢复演练。
- 已经接入完整 APM（应用性能监控）、外部告警送达和供应商 SLA。
- 已经证明供应商真实 SLA、真实配额强约束或所有可选供应商长期稳定。
- 支持真实支付、真实预订、真实锁价或真实订单履约。

## 该历史快照记录的后续优先级

| 优先级 | 下一步 | 验收方式 |
|---|---|---|
| P0 | 把恢复演练候选写入正式运维声明和复盘矩阵 | owner 确认 `ZHIXING_POSTGRES_BACKUP_STATUS` / `ZHIXING_POSTGRES_RESTORE_DRILL_STATUS`，并重新生成 PostgreSQL / Redis ops summary |
| P0 | 把外部依赖韧性记录并入正式上线复盘矩阵 | 外部依赖 resilience report 纳入 `m1_operations_review_record` 或最终 evidence matrix |
| P0 | 如需完全统一基线签核链，重跑包含 chat 并发 section 的完整 workflow + signoff | 新 workflow-report、signoff、evidence matrix 三者哈希和 section 一致 |
| P1 | 把 chat 小流量采样升级为持续监控或更长窗口采样 | 只对白名单探针账号执行，记录 P95、错误率、blocked/degraded 原因，并继续声明不是压测结论 |
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
