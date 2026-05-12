# Deployment Readiness（部署就绪）

本文面向上线前检查，和 `docs/runtime-environment.md` 的 Runtime Config Readiness（运行配置就绪）契约保持一致。

本项目的 CI/CD（持续集成/持续交付）入口在 `.github/workflows/ci.yml`。默认 push（推送）和 pull request（合并请求）只运行不依赖真实密钥的静态检查、单元测试、前端报告渲染验证和 development（开发）运行配置预检；真实验收只通过 GitHub Actions（GitHub 自动化流水线）的 `workflow_dispatch`（手动触发）入口运行。

## 上线前必须满足

1. `APP_ENV=production`，并确认 `.env` 或部署密钥系统没有使用 `your-*`、`change-me`、`test-key`、`dummy` 等占位值。
2. PostgreSQL（关系型数据库）可连接，业务表已通过 Alembic（数据库迁移工具）迁移到 `head`；LangGraph（图式智能体编排框架）Checkpointer（执行检查点）、Store（长期存储）和审批治理表已按 `docs/db-migration-readiness.md` 的边界初始化。
3. Redis（内存数据结构存储）可连接，`SESSION_LOCK_BACKEND=auto` 或 `redis` 时不能降级为本地锁。
4. LLM（大语言模型）密钥是真实值，模型 profile（用途档位）仍统一通过 `app/utils/llm_factory.py` 创建。
5. Auth（认证）/ JWT（JSON Web Token，令牌认证）必须设置真实 `JWT_SECRET_KEY`，不能使用默认开发密钥、空值或 placeholder（占位）值。
6. RAG（检索增强生成）向量库已初始化，默认路径为 `data/vectorstore`，并且能只读打开 `chroma.sqlite3` 元数据和 `RAG_COLLECTION_NAME` 对应 collection（集合）。
7. 地图能力的 `AMAP_API_KEY` 是真实值；酒店、航班、搜索等可选能力如果缺失，用户侧必须保留“待二次核实”边界。
8. 至少有一个审批操作者或管理员账号，用户对象 `role` 或 `preferences.role` 为 `approver` / `admin`，普通用户不能批准、拒绝或手动过期审批。
9. `/health/ready` 返回 `ready` 或经确认可接受的 `degraded`；生产发布不接受 `not_ready`。

## 推荐验证命令

### 本地开发

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_script_entrypoints.py tests\test_runtime_readiness.py -q
node scripts\verify_frontend_report_renderer.js
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target development --json
```

本地默认可以使用 `.env.example` 中的变量名做参照，但真实 `.env` 不应进入提交、日志或测试快照。

### CI 默认门禁

GitHub Actions（GitHub 自动化流水线）默认门禁等价于：

```powershell
python -m compileall app tests scripts
python -m pytest --collect-only -q
python -m pytest -q
node scripts\verify_frontend_report_renderer.js
python scripts\check_runtime_readiness.py --target development --json
```

这组命令只使用测试占位配置，不读取真实外部 API（应用程序接口）密钥，不发起真实 LLM（大语言模型）、MCP（模型上下文协议）或供应链调用。

CI（持续集成）默认不连接真实 PostgreSQL（关系型数据库），也不执行 `alembic upgrade head`；迁移就绪只通过 `check_runtime_readiness.py` 的静态 `database_migrations` 区块验证。真实数据库迁移放到 staging（预生产）和 production（生产）发布步骤中执行。

### Staging 预生产

预生产先跑 preflight（预检），不消耗真实对话配额：

```powershell
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url https://staging.example.com --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url https://staging.example.com --json
```

只有 preflight（预检）通过后，才手动运行 live acceptance（在线验收）：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url https://staging.example.com --summary-dir .runtime\acceptance
```

GitHub Actions（GitHub 自动化流水线）中对应 `workflow_dispatch`（手动触发）：默认只跑 `Manual Acceptance Preflight`，只有把 `run_live_acceptance=true` 时才会运行真实场景。

本地复跑时，如果还没有 `.venv`，先用 `uv run python scripts\check_runtime_readiness.py --target development --json` 创建环境，再回到 `.venv\Scripts\python` 命令。真实验收前建议按这个顺序确认：

```powershell
.\.venv\Scripts\python -m scripts.init_db
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url http://127.0.0.1:8000 --json --no-summary
```

2026-05-11 本地复跑结果是 `blocked（环境阻塞）`：缺真实 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、LLM（大语言模型）、RAG（检索增强生成）向量库元数据、MCP（模型上下文协议）上游 API（应用程序接口）凭据和后端健康端点。完整记录见 `docs/live-acceptance-runbook.md`。

### Production 生产

生产发布前使用真实部署密钥系统注入环境变量，然后执行：

```powershell
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json
```

缺真实密钥、缺 RAG（检索增强生成）向量库、`JWT_SECRET_KEY` 仍是 placeholder（占位）或 `/health/ready` 返回 `not_ready` 时，命令必须返回 blocked（环境阻塞），不能当作通过。

如果生产或预生产后端已经启动，再增加：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url https://travel.403edr.cn --json
```

## Docker 与反向代理检查

- `Dockerfile` 和 `deploy/Dockerfile.runtime` 默认 `APP_ENV=production`，镜像内置 `/health/live` liveness（存活检查）。
- `docker-compose.yml` 显式暴露后端所需的 LLM（大语言模型）、PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG（检索增强生成）、MCP（模型上下文协议）/外部 API（应用程序接口）和 Auth（认证）/JWT（JSON Web Token，令牌认证）变量名。
- Compose（容器编排配置）后端健康检查使用 `/health/ready`，因此必需依赖缺失时 `backend` 不会被标记为 healthy（健康）。
- `.env` 在 Compose 中是可选文件，方便 CI（持续集成）解析配置；真实部署必须通过 `.env`、平台 secret（密钥）或托管配置系统覆盖占位默认值。
- Caddy（反向代理服务器）站点地址可通过 `ZHIXING_SITE_ADDRESS` 覆盖，本地可用 `:80`，生产可用真实域名。

## 结论语义

- `passed（通过）`：必需配置和目标检查全部满足。
- `degraded（降级）`：核心依赖可用，但存在可选服务缺失、MCP（模型上下文协议）服务降级或开发态 Redis 本地降级。
- `blocked（环境阻塞）`：缺必需配置、真实验收密钥或核心服务，不允许宣称验收/部署通过。
- `skipped（跳过）`：没有可执行场景或预检只生成不可判定摘要。

## 安全边界

- `.env.example` 只保留变量名、默认值和说明，不写真实密钥。
- `.runtime/` 仅用于本地 live acceptance（在线验收）快照、blocked（环境阻塞）摘要和启动日志；不得提交原始产物，只能把脱敏后的结论写入文档。
- 验收摘要、测试快照和提交说明不能包含真实密钥或真实个人信息；验收 live snapshot（真实链路快照）写盘前会做递归脱敏。
- SSE（服务器发送事件）、工具审计、审批理由、审批备注和错误响应不得暴露手机号、邮箱、身份证号、API Key（应用程序接口密钥）、token（令牌）或 secret（密钥）。
- 酒店、航班、火车、地图等外部能力失败时，报告只能写待核验和兜底估算，不能编造真实库存、锁价、余位、支付或客服信息。
- 客户资料导出仍是未来敏感动作占位；当前 `export_customer_profile` 工具策略为禁用，不得导出真实客户画像文件。
