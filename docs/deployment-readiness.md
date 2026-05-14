# Deployment Readiness（部署就绪）

本文面向上线前检查，和 `docs/runtime-environment.md` 的 Runtime Config Readiness（运行配置就绪）契约保持一致。

本项目的 CI/CD（持续集成/持续交付）入口分为两层：`.github/workflows/ci.yml` 是默认 push（推送）和 pull request（合并请求）门禁，只运行不依赖真实密钥的静态检查、单元测试、前端报告渲染验证、Playwright（浏览器自动化测试框架）浏览器回归和 development（开发）运行配置预检；`.github/workflows/staging-smoke.yml` 是 GitHub Actions（GitHub 自动化流水线）的 `workflow_dispatch`（手动触发）staging smoke（预生产冒烟）门禁，会在 runner（流水线执行机）内启动 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）和后端，再运行 `acceptance-smoke`（验收冒烟）。

## 上线前必须满足

1. `APP_ENV=production`，并确认 `.env` 或部署密钥系统没有使用 `your-*`、`change-me`、`test-key`、`dummy` 等占位值。
2. PostgreSQL（关系型数据库）可连接，业务表已通过 Alembic（数据库迁移工具）迁移到 `head`；LangGraph（图式智能体编排框架）Checkpointer（执行检查点）、Store（长期存储）和审批治理表已按 `docs/db-migration-readiness.md` 的边界初始化。
3. Redis（内存数据结构存储）可连接，`SESSION_LOCK_BACKEND=auto` 或 `redis` 时不能降级为本地锁。
4. LLM（大语言模型）密钥是真实值，模型 profile（用途档位）仍统一通过 `app/utils/llm_factory.py` 创建。
5. Auth（认证）/ JWT（JSON Web Token，令牌认证）必须设置真实 `JWT_SECRET_KEY`，不能使用默认开发密钥、空值或 placeholder（占位）值。
6. RAG（检索增强生成）向量库已初始化，公开攻略默认路径为 `data/vectorstore`，内部知识库默认路径为 `data/vectorstore_internal`；两者都必须能只读打开 `chroma.sqlite3` 元数据并找到对应 collection（集合）。
7. 地图能力的 `AMAP_API_KEY` 是真实值；酒店、航班、搜索等可选能力如果缺失，用户侧必须保留“待二次核实”边界。
8. 至少有一个审批操作者或管理员账号，用户对象 `role` 或 `preferences.role` 为 `approver` / `admin`，普通用户不能批准、拒绝或手动过期审批。
9. `/health/ready` 返回 `ready` 或经确认可接受的 `degraded`；生产发布不接受 `not_ready`。

## 三套检查命令

### Local 本地

本地只验证配置契约和可启动闭环，不代表真实部署通过。`local` 是 `development`（开发）档位别名：

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_script_entrypoints.py tests\test_runtime_readiness.py -q
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target local --json
docker compose up -d postgres redis
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --base-url http://127.0.0.1:8000 --json --no-summary
```

### Staging 预生产

预生产不在本文写真实服务器地址。把 `<staging-base-url>` 替换为部署平台或密钥系统中的地址，并只在运行环境中注入真实密钥：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <staging-base-url> --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --base-url <staging-base-url> --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url <staging-base-url> --summary-dir .runtime\acceptance-smoke --json
```

### Production 生产

生产只做 readiness（就绪检查）和 preflight（预检）确认，不把 smoke（冒烟测试）结果当成自动发布动作：

```powershell
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <production-base-url> --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url <production-base-url> --json --no-summary
```

`check_runtime_readiness.py` 的 JSON（JavaScript Object Notation，结构化数据格式）会同时输出旧的 `status=passed/degraded/blocked` 和部署口径 `readiness_status=ready/degraded/not_ready`。重点看：

- `target_readiness_statuses`：local、staging、production 的总体结论。
- `targets.<name>.component_readiness`：PostgreSQL、Redis、RAG、MCP、LLM 五项判定。
- `blocked_reasons`：阻塞原因，不含密钥值。
- `repair_suggestions`：可执行修复建议和复跑命令。

## ready / degraded / not_ready 判定

| 依赖 | ready | degraded | not_ready |
|---|---|---|---|
| PostgreSQL（关系型数据库） | 必填变量非占位，且后端 `/health/ready` 中 Checkpointer（执行检查点）和 Store（长期存储）均初始化。 | 不作为可选降级处理；local 只做静态配置时仍需后续 `scripts.init_db` 证明连通。 | 缺变量、占位值、TCP（传输控制协议）不可达、迁移/初始化失败，或 `/health/ready` 缺 `checkpointer` / `store`。 |
| Redis（内存数据结构存储） | 会话锁使用 Redis 且 `/health/ready` 显示 `session_lock.status=ready`。 | development（开发）允许降级为本地锁；MCP 以外的生产核心链路不接受 Redis 降级。 | staging/production 缺 Redis 配置、Redis 不可达，或 `SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL=false` 时锁不可用。 |
| RAG（检索增强生成） | 公开与内部 Chroma（向量库）`chroma.sqlite3` 都可读，collection（集合）、metadata（元数据）契约和最小检索探针均通过。 | development/test 可不初始化真实向量库，但不能声明真实验收通过。 | staging/production 缺目录、缺 collection、metadata 不匹配、探针无命中或初始化失败。 |
| MCP（模型上下文协议） | `/health/ready` 或 acceptance preflight 中所选场景要求的 MCP 服务均 healthy（健康）。 | 只有可选 MCP 服务不可用，且核心依赖 ready；smoke 摘要必须保留降级证据。 | 所选验收场景要求的 MCP 服务缺失、不健康，或后端 ready payload（就绪载荷）返回 `not_ready`。 |
| LLM（大语言模型） | `DASHSCOPE_API_KEY` 是真实值，模型仍通过 `app/utils/llm_factory.py` 创建。 | test（测试）或未启用真实验收时可 mock（模拟）/skip（跳过）。 | staging/production 使用空值、占位值或真实调用不可用；smoke 不得用 mock 假通过。 |

smoke（冒烟测试）失败时，`scripts/run_evaluation_scenarios.py --acceptance-smoke --json` 会输出 `blocking_reasons`、`failure_classification_counts` 和 `repair_suggestions`。常见分类如下：

| 分类 | 含义 | 修复方向 |
|---|---|---|
| `blocked` | preflight（预检）缺必需配置、真实密钥、RAG 或后端健康。 | 先跑 `check_runtime_readiness.py --target staging --json`，按 `repair_suggestions` 补齐环境。 |
| `timeout` / `global_timeout` | 场景或整批超时。 | 查后端日志、MCP 服务健康和模型延迟；理解依赖慢点后再调整 timeout（超时限制）。 |
| `conversation_busy` | 同一会话锁仍被占用。 | 等待锁过期，或确认没有运行中的验收后重启后端。 |
| `runtime_budget` | token（令牌）、首 token 延迟、工具调用数或错误事件超预算。 | 查 acceptance summary（验收摘要）里的 runtime metrics（运行指标），先修重复工具调用或慢依赖。 |
| `evidence_closure` / `acceptance_gate` | 缺 `report_data`、预算、风险、RAG、工具审计或确定性门禁失败。 | 打开 `.runtime/acceptance-smoke` 摘要和快照，按失败维度修复，不改成“通过”。 |

## 推荐验证命令

### 本地开发

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_script_entrypoints.py tests\test_runtime_readiness.py -q
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target development --json
```

本地默认可以使用 `.env.example` 中的变量名做参照，但真实 `.env` 不应进入提交、日志或测试快照。

首次运行前需要安装 npm（Node.js 包管理器，Node.js 是 JavaScript 运行时）前端依赖和 Chromium（浏览器内核）：

```powershell
npm install
npm run prepare:frontend-browser
```

### CI 默认门禁

GitHub Actions（GitHub 自动化流水线）默认 CI（持续集成）门禁等价于：

```powershell
python -m compileall app tests scripts
python -m pytest --collect-only -q
python -m pytest -q
npm ci
npx playwright install --with-deps chromium
node scripts\verify_frontend_report_renderer.js
npm run verify:frontend-browser
python scripts\check_runtime_readiness.py --target development --json
```

这组命令只使用测试占位配置，不读取真实外部 API（应用程序接口）密钥，不发起真实 LLM（大语言模型）、MCP（模型上下文协议）或供应链调用。前端浏览器回归只加载本地 `frontend/zhixing.html`，并在浏览器上下文中 stub（桩替换）ready check（就绪检查）、会话、审批和地图预览响应。

CI 中 `CI=true` 且显式设置 `ZHIXING_FRONTEND_BROWSER_STRICT=1`，因此缺少 npm 依赖、Playwright 或 Chromium 时必须失败并输出安装提示，不能当作跳过通过。截图产物仍只写入 `.runtime/`，该目录不纳入提交。

CI（持续集成）默认不连接真实 PostgreSQL（关系型数据库），也不执行 `alembic upgrade head`；迁移就绪只通过 `check_runtime_readiness.py` 的静态 `database_migrations` 区块验证。真实数据库迁移放到 staging（预生产）和 production（生产）发布步骤中执行。

### Staging 预生产

预生产先跑 preflight（预检），不消耗真实对话配额：

```powershell
docker compose up -d postgres redis
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python -m scripts.init_db --mode bootstrap
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\alembic current
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url <staging-base-url> --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <staging-base-url> --json
```

如果 Docker Desktop（Docker 桌面运行环境）未运行，`--check-docker` 必须返回 blocked（环境阻塞）；此时不要继续宣称 PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）已完成本地启动闭环。

`check_runtime_readiness.py` 的 JSON（JavaScript Object Notation，结构化数据格式）输出包含顶层 `blocked_reasons` 和 `repair_suggestions`。发布或验收 runbook（运行手册）应优先展示这两个字段：`missing_required` 只说明缺了哪些依赖，`blocked_reasons` 会说明缺变量、占位值、RAG（检索增强生成）metadata（元数据）不可读或 Docker daemon（后台服务）不可达等具体原因，`repair_suggestions` 给出下一步命令。

`scripts.init_db --mode bootstrap` 会先探测 PostgreSQL（关系型数据库）TCP（传输控制协议）端口，再执行业务 Alembic（数据库迁移工具）迁移、LangGraph（图式智能体编排框架）Checkpointer（执行检查点）/Store（长期存储）初始化和 pgvector（向量扩展）启用。依赖不可达时必须失败并输出可操作建议，例如启动 Docker Desktop、执行 `docker compose up -d postgres`、检查 `POSTGRES_HOST/PORT/DB/USER/PASSWORD` 和 pgvector 镜像；依赖可达时才允许宣称 bootstrap（引导初始化）完成。

只有 preflight（预检）通过后，才手动运行 live acceptance（在线验收）：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --base-url <staging-base-url> --summary-dir .runtime\acceptance
```

GitHub Actions（GitHub 自动化流水线）中的手动 staging smoke（预生产冒烟）门禁在 `.github/workflows/staging-smoke.yml`，触发方式是 Actions 页面选择 `Staging Smoke` 后点击 `Run workflow`。该 workflow（工作流）不会做服务器部署，不连接真实生产环境，只在 GitHub runner（流水线执行机）内完成以下步骤：

1. 校验必需 GitHub Secrets（密钥管理项），缺少任意一项立即失败。
2. 用 Docker（容器运行工具）启动 `pgvector/pgvector:pg17` PostgreSQL（关系型数据库）和 `redis:7-alpine` Redis（内存数据结构存储）。
3. 执行 `python -m scripts.init_db --mode bootstrap` 和 `python -m scripts.init_rag`。
4. 用 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` 启动后端。
5. 通过后端用户 API（应用程序接口）确认或创建 `ZHIXING_EVAL_USERNAME` 对应的评估用户。
6. 记录 `check_runtime_readiness.py --target acceptance --check-backend` 结果。
7. 运行 `python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --summary-dir .runtime/acceptance-smoke --summary-prefix staging-smoke --json`。

必需 Secrets（密钥管理项）清单：

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `DASHSCOPE_API_KEY`
- `AMAP_API_KEY`
- `TAVILY_API_KEY`
- `JWT_SECRET_KEY`
- `ZHIXING_EVAL_USERNAME`
- `ZHIXING_EVAL_PASSWORD`

可选 Secrets（密钥管理项）：`VARIFLIGHT_API_KEY`、`AIGOHOTEL_API_KEY`、`AIGOHOTEL_MCP_API`、`AIGOHOTEL_SECRET_KEY`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`。当前 `acceptance-smoke` 场景不强制航班或酒店密钥，但如果后续把相关场景加入 smoke（冒烟）集合，应同步提升为必需项。

`Ensure Evaluation User` 步骤会先用 `ZHIXING_EVAL_USERNAME` / `ZHIXING_EVAL_PASSWORD` 登录；临时 PostgreSQL（关系型数据库）中没有该用户时，才用 `users.noreply.github.com` 非个人域名生成邮箱并调用注册接口，再重新登录验证。该步骤不提交、不打印真实密码、JWT（JSON Web Token，令牌认证）或 `access_token`；如果用户名或邮箱已存在但密码不匹配，workflow（工作流）会明确失败，不会静默改密码或让 smoke（冒烟）假通过。

失败 / blocked（环境阻塞）语义：

- 必需 Secrets（密钥管理项）为空：`Validate Required Secrets` 步骤直接失败，后续服务不会启动。
- Secrets 存在但仍是占位值、RAG（检索增强生成）向量库初始化失败、后端 `/health/ready` 返回 `not_ready`、真实 LLM（大语言模型）或外部 API（应用程序接口）不可用：验收 preflight（预检）或 smoke（冒烟）命令必须以 blocked（环境阻塞）/失败退出，不能静默通过。
- 后端 `/health/ready` 因可选能力降级返回 `degraded` 时，workflow（工作流）允许继续进入 `acceptance-smoke`，由验收摘要保留降级证据；这不等同于 production（生产）发布通过。

artifact（构建产物）位置：workflow（工作流）始终上传 `.runtime/acceptance-smoke`，artifact 名称为 `staging-smoke-${{ github.run_id }}`，包含 runtime readiness（运行时就绪）摘要、验收摘要、后端日志和服务日志。`.runtime/` 已在 `.gitignore` 中忽略，原始产物不得提交。

本地复跑时，如果还没有 `.venv`，先用 `uv run python scripts\check_runtime_readiness.py --target development --json` 创建环境，再回到 `.venv\Scripts\python` 命令。真实验收前建议按这个顺序确认：

```powershell
.\.venv\Scripts\python -m scripts.init_db
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python main.py
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
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
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url <production-base-url> --json --no-summary
```

缺真实密钥、缺 RAG（检索增强生成）向量库、`JWT_SECRET_KEY` 仍是 placeholder（占位）或 `/health/ready` 返回 `not_ready` 时，命令必须返回 blocked（环境阻塞），不能当作通过。

生产和预生产共同要求：PostgreSQL（关系型数据库）必须显式配置 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`；Redis（内存数据结构存储）必须显式配置 `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`；LLM（大语言模型）、AMAP（高德地图）、JWT（JSON Web Token，令牌认证）必须使用真实值。搜索、航班、酒店等外部 API（应用程序接口）默认可降级，但一旦进入 acceptance-core（核心验收）场景需求，就会由 preflight（预检）升级为 hard blocker（硬阻塞项）。

如果生产或预生产后端已经启动，再增加：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url <production-base-url> --json
```

## Docker 与反向代理检查

- `Dockerfile` 和 `deploy/Dockerfile.runtime` 默认 `APP_ENV=production`，镜像内置 `/health/live` liveness（存活检查）。
- `docker-compose.yml` 默认按 `APP_ENV=staging` 启动本地预生产拓扑，显式暴露后端所需的 LLM（大语言模型）、PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、RAG（检索增强生成）、MCP（模型上下文协议）/外部 API（应用程序接口）、Auth（认证）/JWT（JSON Web Token，令牌认证）和启动超时变量名。
- RAG 初始化入口会读取 `RAG_VECTORSTORE_PATH`、`RAG_COLLECTION_NAME`、`RAG_INTERNAL_VECTORSTORE_PATH` 和 `RAG_INTERNAL_COLLECTION_NAME`，因此本地 staging（预生产）和容器运行时应保持这些路径一致。
- Compose（容器编排配置）后端健康检查使用 `/health/ready`，因此必需依赖缺失时 `backend` 不会被标记为 healthy（健康）。
- Compose 同时发布 `${POSTGRES_HOST_PORT:-5432}:5432` 和 `${REDIS_HOST_PORT:-6379}:6379`，保证宿主机上的 `scripts.init_db`、`scripts.init_rag` 和健康检查脚本能连到真实本地依赖。
- 后端同时映射 `${BACKEND_PORT:-8000}:${APP_PORT:-8000}`，即使 `/health/ready` 因真实密钥或外部依赖缺失返回 `not_ready`，也应能通过 `/health/live` 验证进程没有卡在 application startup（应用启动）。
- `.env` 在 Compose 中是可选文件，方便 CI（持续集成）解析配置；真实部署必须通过 `.env`、平台 secret（密钥）或托管配置系统覆盖占位默认值。
- Caddy（反向代理服务器）站点地址可通过 `ZHIXING_SITE_ADDRESS` 覆盖；提交文件只保留 `:80` 这类本地默认值，生产域名只在部署配置系统里设置。

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
