# Production Deployment Inputs（生产部署输入清单）

本文列出把 ZhiXing Travel Planner 推进到 M1 受控试运行前需要准备的环境、配置、数据和验收输入。它只记录变量名、资源类型和验收边界，不记录真实密钥、真实账号口令、真实客户资料或供应链内部数据。

## 目标范围

M1 受控试运行建议保持以下边界：

- 只面向内部人员或白名单用户。
- M1 只开放站内模拟订单确认跳转；不开放真实支付、真实下单、真实预订、真实锁价、真实出票或客服履约。
- 外部 API（应用程序接口）只用于查询和辅助生成报告，失败时必须降级或进入待核验。
- 所有真实密钥只进入服务器环境变量、CI secrets（持续集成密钥）或密钥管理系统，不写入 Git、不贴到文档、不贴到聊天记录。

PostgreSQL / Redis 的运行、并发、故障和扩容边界见 `docs/部署与运行/postgres-redis-ops-runbook.md`。本文只列输入项和验收前置，不替代运行手册。

## 1. 部署目标

| 输入项 | M1 建议 | 验收关注点 |
|---|---|---|
| 服务器形态 | 单台云服务器或虚拟机即可，优先 2-4 vCPU、8-16 GB RAM、80-160 GB SSD | 能运行后端、PostgreSQL、Redis、前端静态资源和基础日志 |
| 操作系统 | Ubuntu 22.04 / 24.04 或等价 Linux 发行版 | Python、Node.js、Docker / Docker Compose 可安装 |
| 网络入口 | 固定公网 IP，开放 80 / 443，SSH（安全外壳协议）受限访问 | 后端健康检查和前端页面可访问 |
| 域名 | 一个正式域名或子域名 | DNS（域名解析）指向目标服务器，TLS（传输层安全协议）证书可签发 |
| 部署目录 | 用变量记录，例如 `ZHIXING_DEPLOY_DIR` | 不在公开文档中记录机器敏感路径 |
| 反向代理 | Caddy、Nginx 或云厂商网关 | HTTPS、请求体限制、超时、日志和静态资源路径明确 |

## 2. 运行时服务

| 服务 | M1 选择 | 需要准备 |
|---|---|---|
| PostgreSQL（关系型数据库） | Docker Compose 或托管数据库 | 数据库名、只读/读写账号、备份策略、迁移窗口 |
| Redis（缓存数据库） | Docker Compose 或托管 Redis | 访问口令、持久化策略、内存上限、重启策略 |
| 后端应用 | `uvicorn` / 容器方式均可 | 环境变量、日志目录、健康检查、进程守护 |
| 前端静态资源 | 反向代理直接托管或静态站点服务 | 前端 API base URL、缓存策略、回滚方式 |
| 日志 | 先集中到服务器日志目录，后续接入日志平台 | 保留周期、脱敏规则、错误检索方式 |

## 3. 环境变量

真实值只能放到服务器环境、CI secrets 或密钥管理系统。沟通时只确认“已准备 / 未准备 / 使用哪个供应商”，不要发送真实值。

M1 非密钥输入可以用脚本检查。该脚本只读取当前进程环境变量，不读取 `.env` 文件，也不回显真实填写内容：

```powershell
uv run python scripts\check_m1_launch_inputs.py --json
```

如果资源还没有写入目标环境，可以先生成一份非密钥 JSON 模板，填写服务器、域名、公网 URL、备份、监控、负责人、预算和验收窗口等状态，再用同一套规则校验。填好的文件可能包含本地部署信息，建议保存在仓库外或本机临时目录，不提交到 Git：

```powershell
uv run python scripts\check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
```

这份 JSON 只允许写非密钥状态，不写真实 API key、密码、token、Cookie、私钥、客户资料或供应商私密数据。校验输出只回显变量名、状态和修复建议，不回显填写值。

如果要先把“需要你准备什么”整理成可发送的资源申请包，可以运行：

```powershell
uv run python scripts\render_m1_resource_request.py --markdown
```

该资源包列出服务器、DNS/TLS、运行配置、密钥变量、RAG 数据、外部 API、验收、备份、监控、回滚等准备项；它只写变量名和交付方式，不要求填写真实密钥值。

如果要在真实 M1 执行窗口前确认“还缺哪些私有输入”，先对照 `docs/部署与运行/m1-execution-input-gap-checklist.md`。该清单把 SSH 目标、公网 URL、部署目录、私有证据目录、probe 凭据、备份目录、预算、验收窗口和负责人映射到仓库外准备位置和对应校验命令。

也可以用机器检查器聚合这些缺口。它只读取当前进程环境变量和显式传入的私有 JSON，不读取 `.env`、不连 SSH、不触网、不回显真实值：

```powershell
uv run python scripts\prepare_m1_private_execution_workspace.py --private-workdir <private-workdir> --execute --markdown
uv run python scripts\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\m1-launch-inputs.local.json --markdown
```

服务器侧 `.env` 可以再生成专门清单。该脚本只读取公开 `.env.example` 的变量名，不读取 `.env`，不回显当前进程环境变量值：

```powershell
uv run python scripts\render_server_env_checklist.py --markdown
uv run python scripts\render_server_env_checklist.py --template
```

`--template` 输出的是占位符模板，只能作为服务器或密钥系统填写参考，不能把真实值提交到 Git。

服务器或密钥系统填好 `<deploy-dir>\shared\.env` 后，再在目标服务器或受控 shell 中做文件级校验。该脚本只输出缺失、空值、明显占位符、重复变量和权限状态，不打印真实值，也不打印 `.env` 文件路径；不要拿它读取仓库根目录的本地 `.env`：

```powershell
uv run python scripts\check_server_env_file.py --env-file <deploy-dir>\shared\.env --json
```

资源输入齐备后，可以先做首次部署 dry-run。它不会连接 SSH、不会上传文件、不会生成发布包，也不会启动服务：

```powershell
uv run python scripts\check_m1_first_deploy_dry_run.py --json
```

发布候选冻结后，再生成带 manifest 和 sha256 的发布包：

```powershell
uv run python scripts\build_release_artifact.py --execute --output-dir <release-output-dir> --json
```

发布前也可以用聚合门禁串起公开边界、M1 输入、Compose 配置和 production readiness：

```powershell
uv run python scripts\check_server_preflight_readiness.py --json
uv run python scripts\check_backup_restore_readiness.py --json
uv run python scripts\collect_backup_restore_drill_evidence.py --json
uv run python scripts\check_external_api_readiness.py --json
uv run python scripts\check_monitoring_alerting_readiness.py --json
uv run python scripts\collect_monitoring_alerting_evidence.py --json
uv run python scripts\check_security_release_readiness.py --json
uv run python scripts\collect_incident_rollback_evidence.py --json
uv run python scripts\check_m1_deployment_gate.py --json
```

门禁输出可以转成脱敏记录，默认打印到终端：

```powershell
uv run python scripts\render_m1_acceptance_record.py
```

部署后 smoke 证据可以用同一个收集器汇总。默认命令只输出执行计划，不触网、不调用外部 API：

```powershell
uv run python scripts\collect_m1_smoke_evidence.py --json
```

最终上线前总判定使用 go/no-go 汇总器。它默认只输出计划态；当使用 `--include-all-declared-evidence` 和 live smoke 参数时，会把 M1 gate、smoke、备份恢复、监控告警、事故回滚证据合并成一个脱敏 `decision`：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py --json
```

真实生产口径下，被纳入的证据 section 只要仍是 `not_checked` 或 `blocked`，最终必须写 `no_go`，不能写成已具备生产能力。

### M1 必需

| 变量 | 用途 | 说明 |
|---|---|---|
| `APP_ENV` | 环境标识 | 建议先用 `staging`，稳定后再切 `production` |
| `DASHSCOPE_API_KEY` | LLM（大语言模型）调用 | 需要配额、限流和账单告警 |
| `JWT_SECRET_KEY` | 登录态签名 | 必须是随机强密钥，禁止复用示例值 |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` | 数据库连接 | 只记录变量名，不记录真实连接串 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | 数据库账号 | M1 至少区分应用账号和维护账号 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | 缓存连接 | Redis 不应裸露公网 |
| `AMAP_API_KEY` | 高德地图后端服务 | 需要配置调用来源和配额 |
| `ZHIXING_PUBLIC_BASE_URL` | 对外访问地址 | 用于报告链接、回调或健康检查摘要 |
| `ZHIXING_EVAL_BASE_URL` | 验收脚本访问地址 | 通常与 `ZHIXING_PUBLIC_BASE_URL` 一致 |
| `ZHIXING_SITE_ADDRESS` | 部署站点标识 | 只写域名或服务名，不写敏感内网坐标 |

### 按场景启用

| 变量 | 用途 | 启用条件 |
|---|---|---|
| `AMAP_WEB_JS_KEY` | 前端地图展示 | 需要浏览器端地图能力时启用 |
| `TAVILY_API_KEY` | 搜索服务 | 需要联网搜索候选攻略或外部资料时启用 |
| `VARIFLIGHT_API_KEY` | 航班查询 | 需要真实航班候选查询时启用 |
| `AIGOHOTEL_API_KEY` | 酒店查询 | 需要真实酒店候选查询时启用 |
| `AIGOHOTEL_MCP_API` | 酒店 MCP 服务地址 | 使用外部酒店 MCP 服务时启用 |
| `AIGOHOTEL_SECRET_KEY` | 酒店服务签名 | 必须按供应商要求存入密钥系统 |
| `LANGSMITH_API_KEY` | LangSmith 观测 | 需要第三方 trace（链路追踪）时启用 |
| `LANGSMITH_PROJECT` | LangSmith 项目名 | 与 trace 配套使用 |
| `LANGSMITH_TRACING` | LangSmith 开关 | M1 可先关闭，验证期按需开启 |
| `EVAL_USERNAME` / `EVAL_PASSWORD` | 验收测试账号 | 用于验收脚本，不写入公开仓库 |

## 4. 数据输入

M1 可以准备脱敏后的业务材料，用来让报告更接近真实服务，但不能混入真实客户资料。

公开旅行文本、POI 和图片元数据的来源选择见 `docs/RAG与知识库/travel-multimodal-data-source-plan.md`。该计划只允许使用许可清晰、可归因、可复跑的数据源；原始下载缓存和大规模图片数据不得进入 Git。

| 数据类型 | 可以提供 | 不应提供 |
|---|---|---|
| 目的地资料 | 公开攻略、景点、交通建议、季节风险 | 内部未授权资料或不可公开复制内容 |
| 产品模板 | 脱敏后的路线结构、服务范围、可选升级项 | 真实库存、真实联系人、供应商底价 |
| 报价规则 | 区间价格、估算公式、成本项说明 | 锁价承诺、真实合同价、供应商结算单 |
| 风险 SOP（标准作业流程） | 天气、签证、老人儿童、改签退订提醒 | 真实客户投诉记录或员工处理记录 |
| 报告样式 | 脱敏报告模板、展示顺序、字段要求 | 真实订单、付款凭证、证件号、手机号 |

## 5. 验收输入

| 输入项 | 用途 | 要求 |
|---|---|---|
| 验收账号 | 跑登录、对话、报告和导出流程 | 账号口令放在服务器密钥或本机环境，不写进文档 |
| 验收场景 | 固定 M1 smoke（冒烟测试）和 core（核心验收）用例 | 至少覆盖自由规划、省心方案、工具失败降级、报告导出 |
| API 配额预算 | 控制 LLM、地图、搜索、航班、酒店调用成本 | 给出单日预算和失败告警阈值 |
| 可接受降级 | 明确哪些外部服务失败时可继续 | 例如搜索失败可提示待核验，支付/预订只允许站内模拟确认跳转 |
| 验收窗口 | 确定测试时间段 | 避免在密钥未开通、服务未部署时误判失败 |
| 验收记录 | 使用 `m1-acceptance-record-template.md` | 只写脱敏摘要、状态、数量和风险，不写日志原文 |

## 6. 运维输入

| 输入项 | M1 最低要求 |
|---|---|
| 负责人 | 明确谁能重启服务、更新环境变量、查看日志和执行回滚 |
| 备份 | PostgreSQL 至少每日备份一次，并完成一次恢复演练 |
| 备份目标 | 明确本机目录、云盘快照或对象存储，并确认加密和保留周期 |
| 回滚 | 每次发布保留上一版本代码、配置摘要和数据库迁移前备份 |
| 恢复演练状态 | 明确 PostgreSQL 备份、PostgreSQL 恢复演练、RAG 恢复演练和可接受数据丢失窗口 |
| 告警 | 至少覆盖健康检查失败、错误率升高、P95 耗时升高、外部 API 失败率升高 |
| 告警演练状态 | 明确 health/readiness 告警是否投递，错误率、P95、工具失败、成本、备份和日志脱敏监控是否已配置 |
| 日志保留 | 明确保留周期和脱敏规则，禁止记录真实密钥、Cookie 或完整 token |
| 事故沟通 | 明确服务不可用、外部服务异常、费用异常时通知谁 |
| 事故/回滚演练 | 明确 P0/P1 处理负责人、回滚目标、回滚后复验和事故复盘状态 |
| 成本配额 | 明确 LLM、地图、搜索、航班、酒店每日预算和负责人 |
| 密钥管理 | 明确使用服务器 `.env`、CI secrets 还是云密钥系统 |
| 密钥轮换 | 明确 JWT、LLM、地图、数据库、Redis 和供应商 key 的轮换负责人 |

## 7. 可发给维护者的非密钥表格

下面表格可以直接作为沟通模板。只填资源状态和选择，不填真实密钥或口令。

| 字段 | 示例写法 |
|---|---|
| `server_provider` | 云厂商名或“自有服务器” |
| `os_version` | Ubuntu 22.04 / Ubuntu 24.04 |
| `cpu_ram_disk` | 4 vCPU / 8 GB RAM / 100 GB SSD |
| `deploy_dir` | 服务器绝对部署目录，例如 `/opt/zhixing`，公开沟通时可只写“已准备” |
| `docker_status` | Docker 和 Docker Compose ready / blocked |
| `domain_ready` | 已准备 / 未准备 |
| `server_ports_status` | 80 / 443 已开放，SSH 受限 |
| `tls_status` | TLS 证书 ready / blocked |
| `reverse_proxy_status` | Caddy / Nginx / 网关 ready / blocked |
| `deploy_mode` | Docker Compose / 原生进程 / 待定 |
| `postgres_mode` | Compose / 托管数据库 / 待定 |
| `redis_mode` | Compose / 托管 Redis / 待定 |
| `llm_provider_ready` | 已准备 DashScope / 未准备 |
| `map_api_ready` | 已准备高德 / 未准备 |
| `optional_external_apis` | Tavily：有；航班：无；酒店：无 |
| `data_scope` | 只使用公开资料和脱敏产品模板 |
| `m1_audience` | 内部测试 / 白名单用户 |
| `real_payment_order_disabled` | 是，M1 只开放站内模拟确认跳转，不开放真实支付和预订 |
| `backup_target` | 本机磁盘 / 对象存储 / 待定 |
| `backup_retention` | 最近 7 天每日备份 + 最近 3 次发布前备份 |
| `rag_restore_strategy` | 备份向量库 / 从语料重建 |
| `postgres_backup_status` | passed / blocked / not run |
| `postgres_restore_drill_status` | passed / blocked / not run |
| `rag_restore_drill_status` | passed / blocked / not run |
| `restore_drill_owner` | 谁负责恢复演练 |
| `acceptable_data_loss` | M1 可接受最多丢失多少测试数据 |
| `observability_choice` | 服务器日志 / LangSmith / 云监控 / 待定 |
| `monitoring_provider` | 云监控 / 自建脚本 / Prometheus / 待定 |
| `alert_channel` | 邮件 / 短信 / 企业 IM / 电话 / 待定 |
| `health_alert_delivery_status` | passed / blocked / not run |
| `readiness_alert_delivery_status` | passed / blocked / not run |
| `alert_drill_owner` | 谁负责告警演练 |
| `alert_drill_window` | 告警演练时间窗口 |
| `error_rate_monitor_status` | passed / not measured / blocked |
| `p95_latency_monitor_status` | passed / not measured / blocked |
| `tool_failure_monitor_status` | passed / not measured / blocked |
| `cost_alert_status` | passed / not measured / blocked |
| `backup_alert_status` | passed / not measured / blocked |
| `log_redaction_sample_status` | passed / not measured / blocked |
| `daily_cost_budget` | LLM、地图、搜索、航班、酒店每日预算 |
| `secret_store` | 服务器 .env / CI secrets / 云密钥系统 |
| `secret_owner` | 谁能创建、查看、轮换密钥 |
| `rotation_cadence` | 30 天 / 90 天 / 试运行后 |
| `external_api_quota_budget` | LLM、地图、搜索、航班、酒店预算和配额摘要 |
| `provider_console_owner` | 谁能登录供应商控制台处理配额、白名单和账单 |
| `provider_support_channel` | 供应商工单、客服电话或内部负责人 |
| `external_api_degradation_policy` | 搜索可降级；航班/酒店待核验；支付/预订只走站内模拟确认 |
| `external_api_timeout_retry_policy` | timeout 和 retry 数值策略 |
| `tavily_service_status` | disabled / ready / degraded / blocked |
| `variflight_service_status` | disabled / ready / degraded / blocked |
| `aigohotel_service_status` | disabled / ready / degraded / blocked |
| `12306_mcp_status` | disabled / ready / degraded / blocked |
| `rollback_drill_status` | passed / degraded / blocked / not run |
| `rollback_target_status` | passed / blocked |
| `post_rollback_health_status` | passed / degraded / blocked |
| `post_rollback_smoke_status` | passed / degraded / blocked |
| `rollback_data_safety_status` | passed / blocked |
| `incident_response_status` | passed / blocked |
| `incident_review_status` | passed / blocked |
| `incident_severity_policy_status` | passed / blocked |
| `incident_communication_status` | passed / blocked |
| `leak_response_owner` | 谁负责密钥泄露响应和供应商撤销 |
| `jwt_secret_status` | ready / rotated / blocked |
| `provider_key_status` | ready / rotated / blocked |
| `database_secret_status` | ready / rotated / blocked |
| `redis_secret_status` | ready / rotated / blocked |
| `allowed_origins_status` | 高德浏览器 key 是否限制到目标域名 |
| `acceptance_window` | 计划测试日期和时间段 |
| `external_api_policy` | 搜索可降级；航班/酒店待核验；支付/预订只走站内模拟确认 |

## 8. M1 验收门槛

正式把状态从 `blocked` 改为 `passed` 前，至少需要在目标环境完成以下验证，并只保存脱敏摘要。

```powershell
uv run python scripts\check_runtime_readiness.py --target production --json
uv run python scripts\check_runtime_dependency_scope.py --json
uv run python scripts\check_production_image_build_policy.py --json
uv run python scripts\check_production_image_build_execution_record.py --template --output <private-workdir>\production-image-build-execution-record.local.json
uv run python scripts\prepare_production_image_build_execution.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --build-id <build-id> --release-label <release-label> --markdown --output <private-workdir>\production-image-build-execution-prep.md
uv run python scripts\check_production_image_build_execution_record.py --record-json <private-workdir>\production-image-build-execution-record.local.json --json
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\check_m1_launch_inputs.py --json
uv run python scripts\check_server_env_file.py --env-file <deploy-dir>\shared\.env --json
uv run python scripts\check_server_preflight_readiness.py --json
uv run python scripts\check_backup_restore_readiness.py --json
uv run python scripts\collect_backup_restore_drill_evidence.py --include-readiness --check-backup-dir --check-latest-dump --check-pg-restore-list --require-restore-drill-declaration --json
uv run python scripts\check_external_api_readiness.py --json
uv run python scripts\check_monitoring_alerting_readiness.py --json
uv run python scripts\collect_monitoring_alerting_evidence.py --include-readiness --check-health-url --require-alert-delivery-declaration --require-metric-declaration --json
uv run python scripts\check_security_release_readiness.py --json
uv run python scripts\collect_incident_rollback_evidence.py --require-ownership-declaration --require-rollback-drill-declaration --require-incident-review-declaration --include-post-rollback-smoke-evidence --check-health-url --run-gate --json
uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\check_m1_deployment_gate.py --json
uv run python scripts\render_m1_acceptance_record.py
uv run python scripts\collect_m1_smoke_evidence.py --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json
uv run python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <public-url> --json
uv run python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url <public-url> --json
node scripts\verify_frontend_browser_regression.js
```

验收结论必须按真实结果书写：

- 缺环境、缺密钥、服务不可达或外部 API 未开通时写 `blocked`。
- 只跑了 dry-run（空跑）时写 `dry-run only`。
- 只通过离线评测时写离线范围，不写线上通过。
- 只有在目标环境真实执行成功后，才写具体维度的 `passed`。

## 9. 进入执行前的确认

开始部署前，请先确认：

1. M1 是否坚持“只开放站内模拟订单确认跳转，不开放真实支付、真实预订、真实锁价、真实出票”。
2. 服务器、域名、PostgreSQL、Redis 和 LLM 密钥是否已准备。
3. 高德、搜索、航班、酒店等外部服务哪些启用，哪些暂时降级。
4. 是否已有脱敏业务资料和固定验收场景。
5. 谁负责备份、回滚、日志查看和异常响应。

以上输入齐备后，再按 `docs/部署与运行/m1-controlled-trial-runbook.md` 进入实际部署 runbook、服务器初始化、环境变量检查和目标环境验收。
