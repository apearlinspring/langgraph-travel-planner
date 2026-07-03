# Security Release and Key Rotation Runbook（安全发布与密钥轮换手册）

本文定义 ZhiXing Travel Planner 在 M1 受控试运行中的密钥管理、公开发布边界、最小权限、轮换和泄露响应。它只记录变量名、角色和操作顺序，不记录真实密钥、账号口令、Cookie、私钥或供应商控制台坐标。

## 1. 管理范围

| 类型 | 变量或对象 | M1 要求 |
|---|---|---|
| LLM（大语言模型） | `DASHSCOPE_API_KEY` | 必需，使用独立应用密钥和预算告警 |
| 地图 / 高德 | `AMAP_API_KEY`、`AMAP_WEB_JS_KEY` | 后端 key 必需；浏览器 key 需要来源限制 |
| 搜索 / 航班 / 酒店 | `TAVILY_API_KEY`、`VARIFLIGHT_API_KEY`、`AIGOHOTEL_API_KEY`、`AIGOHOTEL_SECRET_KEY` | 按场景启用，最小权限和配额限制 |
| Auth/JWT | `JWT_SECRET_KEY`、`JWT_ALGORITHM` | 必须使用长随机值；M1 单密钥轮换会让旧登录态失效 |
| PostgreSQL | `POSTGRES_USER`、`POSTGRES_PASSWORD` | 应用账号和维护账号分开 |
| Redis | `REDIS_PASSWORD` | 不暴露公网，密码进入密钥系统 |
| 验收账号 | `ZHIXING_EVAL_USERNAME`、`ZHIXING_EVAL_PASSWORD` | 仅用于验收脚本，不能写进公开文档 |
| 观测平台 | `LANGSMITH_API_KEY` | 可选，启用前确认采样和脱敏策略 |
| `.env` | 服务器本地配置文件 | 只存在服务器或密钥系统，`chmod 600`，不进入 Git |

## 2. 公开发布边界

发布前先跑公开边界检查：

```powershell
uv run python scripts\check_public_release_boundary.py --json
```

该脚本只扫描 Git 跟踪和未忽略的公开候选文件，遇到 `.env`、`.runtime/`、`.venv/`、`backups/`、`logs/`、`data/vectorstore/` 或 `data/vectorstore_internal/` 会直接标记 `blocked`，并且不会读取这些路径内容。

公开发布还必须确认：

- `.env`、`.env.production`、真实数据库连接串、SSH 私钥、浏览器 Cookie 不在 Git 中。
- 备份、日志、向量库、`.runtime` 原始证据包不在发布包中。
- 文档、日志和验收摘要只出现变量名，不出现真实值。
- 示例配置只使用 `.env.example` 和 placeholder（占位值）。

## 3. 密钥存储策略

M1 可选方案：

| 方案 | 适用 | 要求 |
|---|---|---|
| 服务器 `.env` | 单机受控试运行 | 文件权限 `600`，只有部署负责人可读 |
| CI secrets（持续集成密钥） | 手动 staging smoke 或发布流水线 | 只给手动工作流，默认 CI 不使用真实密钥 |
| 云厂商密钥系统 | 更接近生产 | 按应用和环境隔离，启用审计和轮换提醒 |

不推荐：

- 把真实密钥写进代码、文档、测试、提交说明或聊天记录。
- 多个环境复用同一组密钥。
- 前端浏览器 key 不做域名或来源限制。
- 把生产密钥发给不负责部署的人。

## 4. 最小权限

| 对象 | 最小权限建议 |
|---|---|
| DashScope | 独立应用 key，限制预算，关闭不需要的模型或能力 |
| 高德后端 key | 只开放所需 Web 服务 API，限制 IP 或调用来源 |
| 高德浏览器 key | 只允许目标域名，避免被其他站点复用 |
| Tavily / 搜索 | 限制日调用量和账单预算 |
| 航班 / 酒店 | 使用测试额度或受限账号，M1 不开通真实下单 |
| PostgreSQL 应用账号 | 只授予应用所需数据库权限，维护账号单独保管 |
| Redis | 内网访问，密码保护，不暴露公网 |
| LangSmith | 控制项目权限，避免上传用户隐私和完整 prompt |

## 5. 轮换频率

| 密钥 | 建议频率 | 触发条件 |
|---|---|---|
| `JWT_SECRET_KEY` | M1 可按发布窗口手动轮换 | 泄露、人员变更、环境切换 |
| `DASHSCOPE_API_KEY` | 30-90 天 | 泄露、账单异常、供应商安全要求 |
| `AMAP_API_KEY` / `AMAP_WEB_JS_KEY` | 30-90 天 | 泄露、来源限制变更、配额异常 |
| `POSTGRES_PASSWORD` | 30-90 天 | 人员变更、备份泄露、异常登录 |
| `REDIS_PASSWORD` | 30-90 天 | 人员变更、网络暴露、异常访问 |
| 可选供应商 key | 30-90 天 | 供应商要求、测试结束、额度异常 |
| 验收账号密码 | 每轮试运行后或每 30 天 | 账号共享、人员变更、测试窗口结束 |

## 6. 轮换流程

### 6.1 通用流程

1. 创建新密钥，但暂不删除旧密钥。
2. 写入服务器 `.env`、CI secrets 或密钥系统。
3. 重启后端或相关服务。
4. 运行 readiness 和 acceptance smoke。
5. 确认新密钥生效后，撤销旧密钥。
6. 记录脱敏摘要：变量名、轮换时间、负责人、验证命令、结果。

### 6.2 JWT 轮换

当前项目使用单 `JWT_SECRET_KEY`。轮换会让旧 token 失效，用户需要重新登录。

```sh
# 在密钥系统或服务器 .env 中更新 JWT_SECRET_KEY
docker compose restart backend
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
```

M1 轮换 JWT 前应通知白名单测试用户，并把“旧登录态失效”写入验收记录。

### 6.3 数据库密码轮换

Compose PostgreSQL 的密码轮换涉及数据库用户密码和后端 `.env` 同步。生产前必须先备份。

```sh
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER USER <app_user> WITH PASSWORD '<new-password>';"
# 更新服务器 .env 中的 POSTGRES_PASSWORD
docker compose restart backend
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
```

真实命令中的用户名和新密码不得写入公开文档或聊天记录。

### 6.4 Redis 密码轮换

Redis 密码变更后需要同步 `.env` 并重启 Redis 和后端。M1 要提前确认是否接受活跃会话锁短暂失效。

```sh
# 更新服务器 .env 中的 REDIS_PASSWORD
docker compose up -d redis backend
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
```

### 6.5 外部供应商 key 轮换

供应商 key 轮换后至少复跑：

```sh
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
docker compose exec -T backend python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url "$ZHIXING_PUBLIC_BASE_URL" --json
```

如果该供应商被验收场景声明为必需，还要复跑对应 acceptance 场景。

## 7. 泄露响应

一旦发现真实密钥出现在 Git、日志、聊天记录、截图、工单或公开页面：

1. 立即停止继续传播，不再复制原文。
2. 撤销或轮换对应密钥。
3. 检查使用记录、账单、异常 IP 和供应商控制台日志。
4. 清理公开位置；Git 历史泄露需要按仓库治理流程处理。
5. 复跑 readiness 和受影响验收。
6. 写脱敏事故记录，只写变量名、影响范围、动作和结果。

事故记录禁止写入泄露值本身。

## 8. 发布前安全门禁

M1 发布候选至少运行：

```powershell
uv run python scripts\check_public_release_boundary.py --json
uv run python scripts\check_security_release_readiness.py --json
git diff --check
uv run python scripts\check_runtime_readiness.py --target production --json
```

`check_security_release_readiness.py` 只读取当前进程环境变量中的状态声明，不读取 `.env`，不读取真实密钥，也不回显填写值。它检查 `ZHIXING_SECRET_STORE`、`ZHIXING_SECRET_OWNER`、`ZHIXING_SECRET_ROTATION_CADENCE`、`ZHIXING_LEAK_RESPONSE_OWNER`、`ZHIXING_JWT_SECRET_STATUS`、`ZHIXING_PROVIDER_KEY_STATUS`、`ZHIXING_DATABASE_SECRET_STATUS`、`ZHIXING_REDIS_SECRET_STATUS`、`ZHIXING_ALLOWED_ORIGINS_STATUS` 和 `ZHIXING_REAL_PAYMENT_ORDER_DISABLED`。

目标环境内可以追加公开边界扫描：

```sh
docker compose exec -T backend python scripts/check_security_release_readiness.py --check-public-boundary --json
```

如果涉及前端、报告、RAG 或验收，还要运行对应专项验证。任何门禁输出 `blocked` 时，不得声明发布可用。

## 9. 需要用户准备的信息

请只确认状态，不发送真实密钥：

| 字段 | 示例 |
|---|---|
| `secret_store` | 服务器 .env / CI secrets / 云密钥系统 |
| `secret_owner` | 谁能创建、查看、轮换密钥 |
| `rotation_cadence` | 30 天 / 90 天 / 试运行后 |
| `jwt_session_policy` | 轮换时允许用户重新登录 |
| `allowed_origins` | 前端域名和高德浏览器 key 来源限制 |
| `server_egress_ip` | 是否已有固定出口 IP 给供应商白名单 |
| `provider_key_owners` | DashScope、高德、搜索、航班、酒店负责人 |
| `leak_response_owner` | 谁负责泄露响应和供应商撤销 |
| `jwt_secret_status` | ready / rotated / blocked |
| `provider_key_status` | ready / rotated / blocked |
| `database_secret_status` | ready / rotated / blocked |
| `redis_secret_status` | ready / rotated / blocked |
| `allowed_origins_status` | restricted / blocked |

## 10. 验收记录字段

M1 验收记录中至少补充：

| 字段 | 内容 |
|---|---|
| `public_release_boundary` | passed / blocked |
| `security_release_readiness` | passed / blocked / not run |
| `secret_store_ready` | ready / blocked |
| `jwt_secret_status` | ready / rotated / blocked |
| `provider_key_status` | ready / rotated / blocked |
| `database_secret_status` | ready / rotated / blocked |
| `redis_secret_status` | ready / rotated / blocked |
| `leak_response_ready` | ready / blocked |
| `last_rotation_summary` | 只写变量名和结果，不写真实值 |

没有完成密钥托管和轮换流程时，M1 可以继续受控试运行，但不得写成完整生产安全能力。
