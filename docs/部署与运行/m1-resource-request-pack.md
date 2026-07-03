# M1 Resource Request Pack（受控试运行资源申请包）

本文用于把 ZhiXing Travel Planner 推进到 M1 受控试运行前的资源需求一次性讲清楚。它可以发给部署负责人、云服务器负责人或运维同学填写状态，但不能填写真实密钥、账号口令、数据库连接串、客户资料或供应商内部数据。

最新版资源申请包可以由脚本生成。脚本只读取当前进程环境变量做状态摘要，不读取 `.env` 文件，不回显任何变量值：

```powershell
uv run python scripts\render_m1_resource_request.py --markdown
```

为了先收齐服务器、域名、备份、监控、负责人等非密钥状态，可以生成一份本地私有 JSON 模板。模板本身不含密钥；填好后的文件可能包含服务器和负责人信息，建议放在仓库外或本机临时目录，不提交到 Git：

```powershell
uv run python scripts\check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
```

`--input-json` 只读取这份非密钥状态文件，不读取 `.env`，也不会在输出里回显你填的 URL、负责人、预算或服务器信息。真实 API key、密码、token、Cookie、私钥仍只能放到服务器 `.env`、CI secrets 或云密钥系统。

服务器 `.env` 变量名、密钥交付方式和占位符模板可以由专门脚本生成。它只读取 `.env.example` 的变量名，不读取真实 `.env`，也不回显当前进程环境变量值：

```powershell
uv run python scripts\render_server_env_checklist.py --markdown
uv run python scripts\render_server_env_checklist.py --template
```

服务器或密钥系统写好 `<deploy-dir>/shared/.env` 后，可以在目标服务器或受控 shell 中追加校验。该校验只输出变量名级别的缺失、空值、占位符、重复声明和权限状态，不输出真实值，也不输出 `.env` 文件路径：

```powershell
uv run python scripts\check_server_env_file.py --env-file <deploy-dir>/shared/.env --json
```

如需保存到本地临时文件：

```powershell
uv run python scripts\render_m1_resource_request.py --markdown --output .runtime\m1-resource-request.md
```

`.runtime/` 是本地运行产物目录，不进入 Git。

## 1. 资源组

| 资源组 | 需要准备 | 可接受证据 |
|---|---|---|
| 服务器、公网域名和 TLS | 2-4 vCPU、8-16 GB RAM、80-160 GB SSD 的 Linux 服务器；开放 80/443；DNS 指向目标服务器；HTTPS 可签发 | 服务器规格、域名解析、TLS 状态、反向代理状态、公开 health URL |
| PostgreSQL、Redis 和部署目录 | 数据库/缓存采用 Compose 或托管服务；部署目录、持久化卷和迁移窗口明确 | 数据库/缓存模式、迁移结果、Docker Compose 状态、readiness 摘要 |
| 密钥托管和轮换 | 真实密钥放在服务器环境、CI secrets 或云密钥系统 | 密钥托管方式、负责人、轮换周期、泄露响应负责人 |
| RAG 数据和脱敏业务材料 | 公开资料、脱敏路线模板、风险 SOP、报告字段要求 | 数据来源、脱敏确认、RAG 初始化和召回评测摘要 |
| LLM、地图和可选外部 API | DashScope、高德，以及 Tavily、航班、酒店等服务状态、预算、降级策略 | 服务状态、控制台负责人、配额预算、timeout/retry 和降级策略 |
| 验收账号、场景和时间窗口 | 验收账号、固定 smoke 场景、API 预算、验收时间窗口 | acceptance preflight、acceptance smoke、M1 go/no-go 脱敏摘要 |
| 备份和恢复演练 | PostgreSQL 备份目录或对象存储；非生产恢复演练；可接受数据丢失窗口 | 备份策略、最新 dump 元数据、pg_restore catalog 可读性、恢复演练声明 |
| 监控告警和成本预算 | health/readiness、错误率、P95、工具失败、成本、备份、日志脱敏监控 | 告警投递声明、指标监控状态、成本预算、日志脱敏抽样结果 |
| 回滚和事故响应 | 回滚负责人、事故负责人、回滚目标、回滚后 smoke、事故复盘状态 | 回滚演练、回滚后 health/gate/smoke、事故分级和沟通状态 |

## 2. 密钥交付规则

只确认变量名和状态，不发送真实值：

| 变量 | 用途 | 交付方式 |
|---|---|---|
| `DASHSCOPE_API_KEY` | LLM 调用密钥 | 服务器 `.env`、CI secrets 或云密钥系统 |
| `JWT_SECRET_KEY` | 登录态签名密钥 | 服务器 `.env`、CI secrets 或云密钥系统 |
| `POSTGRES_PASSWORD` | 数据库账号密码 | 服务器 `.env`、CI secrets 或云密钥系统 |
| `REDIS_PASSWORD` | Redis 访问口令 | 服务器 `.env`、CI secrets 或云密钥系统 |
| `AMAP_API_KEY` | 高德地图后端 API key | 服务器 `.env`、CI secrets 或云密钥系统 |
| `TAVILY_API_KEY` / `VARIFLIGHT_API_KEY` / `AIGOHOTEL_API_KEY` | 可选搜索、航班、酒店服务 | 启用时再放入密钥系统 |
| `EVAL_USERNAME` / `EVAL_PASSWORD` | 验收账号 | 仅用于验收环境，不写入公开文档 |

真实值如果出现在 Git、文档、聊天记录、工单正文或截图里，应立即轮换。

## 3. 数据边界

可以提供：

- 公开目的地资料、交通建议、季节风险、景点说明。
- 脱敏路线模板、服务范围、可选升级项、报价区间。
- 脱敏报告样例、字段顺序、预算展示和待核验写法。

不能提供：

- 真实客户姓名、手机号、证件号、订单、合同、支付记录。
- 真实库存、真实锁价、供应商联系人、供应商底价。
- 原始聊天全文、运行日志原文、数据库备份、向量库文件。

## 4. 从资源到放行的命令顺序

资源收集完成后按以下顺序推进：

```powershell
uv run python scripts\check_m1_launch_inputs.py --template --output <private-workdir>\m1-launch-inputs.local.json
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\check_m1_launch_inputs.py --json
uv run python scripts\check_server_env_file.py --env-file <deploy-dir>/shared/.env --json
uv run python scripts\check_m1_first_deploy_dry_run.py --json
uv run python scripts\build_release_artifact.py --execute --output-dir <release-output-dir> --json
scp <release-archive> <ssh-user>@<server-host>:/tmp/<release-archive>
scp <release-manifest> <ssh-user>@<server-host>:/tmp/<release-manifest>
scp deploy/first-deploy.sh <ssh-user>@<server-host>:/tmp/zhixing-first-deploy.sh
ssh <ssh-user>@<server-host> "sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>"
ssh <ssh-user>@<server-host> "sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>"
uv run python scripts\check_m1_deployment_gate.py --json
uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-disk --json
```

目标环境真正部署完成、有公开 HTTPS 地址、且 API 预算允许后，才运行 live smoke：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json
```

只要请求的证据 section 仍是 `not_checked`、`blocked`、`failed`、`unknown` 或 `skipped`，最终结论必须是 `no_go`，不能写成生产可用。
