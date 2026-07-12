# Runtime Config Readiness（运行配置就绪）

本文定义运行环境档位、依赖矩阵、ready check（就绪检查）和降级边界。目标是让缺 `.env`、缺真实密钥、外部服务不可用时有统一工程契约，而不是在启动、测试和验收脚本里各自判断。

## 环境档位

| 档位 | 用途 | 密钥策略 | 典型结论 |
|---|---|---|---|
| `development` | 本地开发和调试 | 允许 mock（模拟）或占位值，但必需项要有配置 | 缺核心配置为 blocked（环境阻塞），缺可选能力不阻塞 |
| `test` | 单元测试和本地快速回归 | 允许 mock 或 skip（跳过）真实外部能力 | 默认不要求真实密钥 |
| `staging` | 验收和预生产验证 | 必需项必须是真实值 | 缺真实密钥必须 blocked，不能误报通过 |
| `production` | 生产部署 | 必需项必须是真实值，Redis 不允许静默本地降级 | 缺核心依赖必须 not_ready |

`APP_ENV` 支持别名归一化：`dev/local -> development`、`testing/tests -> test`、`stage -> staging`、`prod -> production`。

## 依赖矩阵

| 依赖 | development | test | staging | production | 说明 |
|---|---:|---:|---:|---:|---|
| PostgreSQL（关系型数据库） | required | optional | required | required | 业务表、checkpoint（执行检查点）、Store（长期存储）、审批审计 |
| Redis（内存数据结构存储） | optional | optional | required | required | 会话锁；开发可降级本地锁 |
| LLM（大语言模型） | required | optional | required | required | 主 Agent（智能体）、Router（路由器）、RAG 查询优化和报告 |
| RAG（检索增强生成）向量库 | optional | optional | required | required | `RAG_VECTORSTORE_PATH` 和 `RAG_INTERNAL_VECTORSTORE_PATH` 对应公开攻略与内部知识库；两者都需可读 Chroma metadata（元数据）和对应 collection（集合） |
| MCP（模型上下文协议）服务池 | optional | optional | optional | optional | 服务级降级，不拖垮核心会话 |
| 地图 / 高德 | optional | optional | required | required | 路线预览、地理编码、部分天气能力 |
| 搜索 / Tavily | optional | optional | optional | optional | 缺少时搜索能力降级 |
| 酒店 / aigohotel | optional | optional | optional | optional | 缺少时酒店真实候选标记待二次核实 |
| 航班 / VariFlight | optional | optional | optional | optional | 缺少时航班真实候选标记待二次核实 |
| 铁路 / 12306 MCP（模型上下文协议） | optional | optional | optional | optional | 可配置本地或远端服务；当前本地联调可使用非官方社区 sidecar，缺少或返回候选时都要标记待二次核实 |
| LangSmith（LangChain 可观测平台） | optional | optional | optional | optional | 缺少时降低排障可观测性 |
| Auth（认证）/ JWT（JSON Web Token，令牌认证） | optional | optional | required | required | 生产和验收必须使用非默认、非占位密钥 |

## Ready Check 契约

`GET /health/ready` 返回 `runtime_readiness.v1`：

- `status`：`ready`、`degraded` 或 `not_ready`。
- `environment`：归一化后的运行档位。
- `startup`：后台启动任务状态和每个启动步骤耗时，不包含密钥值。
- `dependencies`：按依赖矩阵列出每项 `requirement`、`status`、`env_vars`、`findings` 和无密钥值的 `details`。
- `missing_required`：阻塞当前档位的必需依赖。
- `blocked_reasons`：机器可读的阻塞原因，包含依赖 `key`、中文 `label`、脱敏 `findings`、涉及的环境变量名和目标档位。
- `repair_suggestions`：下一步修复建议，包含建议动作和可直接复跑的命令，不包含真实密钥值。
- `blocking_items`：当前导致 `not_ready` 的配置或服务项，例如 `postgresql`、`checkpointer`、`store`、`session_lock`、`approval_governance`。
- `degraded_optional`：可选但不可用或未配置的能力。
- `services`：底层服务快照，保留 `checkpointer`、`store`、`mcp`、`session_lock`、`approval_governance`。

整体判断：

- 必需依赖缺失、Checkpointer 或 Store 未初始化、生产 Redis 会话锁不可用、审批治理无法持久化时，返回 `not_ready`。
- `staging` 和 `production` 下，`JWT_SECRET_KEY` 为空、仍是默认开发密钥或明显 placeholder（占位）值时，Auth/JWT 依赖进入 `missing_required`。
- `staging` 和 `production` 下，公开攻略与内部知识 RAG 向量库必须能只读打开各自的 `chroma.sqlite3` 并找到 `RAG_COLLECTION_NAME` / `RAG_INTERNAL_COLLECTION_NAME` 对应 collection（集合），同时通过 metadata（元数据）契约和最小运行时检索探针；仅目录存在或非空不算 ready。
- RAG 向量库失败会在 `details.stores.<public|internal>.finding_code` 标明类型：`vectorstore_missing`、`collection_missing`、`metadata_missing`、`metadata_mismatch`、`retrieval_no_hit` 或 `metadata_unreadable`，用于区分路径、collection、metadata 和真实命中缺口。
- MCP 服务池或开发 Redis 降级时，核心依赖已就绪则返回 `degraded`。
- 可选外部 API 缺少密钥不会阻塞核心 ready，但会在依赖明细里显示 `not_configured`。

`GET /health/live` 是纯 liveness（存活检查）：应用进程进入 ASGI（异步服务器网关接口）服务状态后即可返回 `{"status":"alive"}`。PostgreSQL（关系型数据库）、Redis（内存数据结构存储）、MCP（模型上下文协议）或外部 API（应用程序接口）初始化改为后台执行；这些依赖失败只影响 `/health/ready`，不能把应用启动阶段卡死。

启动相关超时通过 `.env` 或部署环境配置：

```powershell
RUNTIME_STARTUP_DEPENDENCY_TIMEOUT_SECONDS=12
RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS=25
RUNTIME_MCP_OPTIONAL_STARTUP_TIMEOUT_SECONDS=25
POSTGRES_CONNECT_TIMEOUT_SECONDS=5
POSTGRES_POOL_TIMEOUT_SECONDS=5
POSTGRES_STATEMENT_TIMEOUT_SECONDS=10
RAG_VECTORSTORE_PATH=data/vectorstore
RAG_COLLECTION_NAME=travel_guides
RAG_INTERNAL_VECTORSTORE_PATH=data/vectorstore_internal
RAG_INTERNAL_COLLECTION_NAME=agency_internal_knowledge
```

`RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS` 是非密钥配置。acceptance-core（核心验收）会按所选场景声明高德、铁路、航班和酒店等 MCP 服务为必需或可选；地址既可以指向本地 sidecar（伴随服务），也可以由平台注入远端服务。当前本地铁路联调可使用第三方社区 12306 sidecar，它不是中国铁路 12306 官方服务或官方授权接口，输出只能作为待二次核验的候选。MCP 冷启动或握手偶尔会超过 8 秒，因此默认超时为 25 秒，避免把可恢复冷启动误判为 degraded（降级）；详细边界见 `docs/部署与运行/mcp-health-readiness.md`。

## 命令入口

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --check-docker --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e
.\.venv\Scripts\python scripts\check_runtime_dependency_scope.py --json
.\.venv\Scripts\python scripts\check_production_image_build_policy.py --json
.\.venv\Scripts\python scripts\check_production_image_build_execution_record.py --template
.\.venv\Scripts\python scripts\prepare_production_image_build_execution.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --build-id <build-id> --release-label <release-label> --markdown
```

`check_runtime_readiness.py` 不输出密钥值，只输出变量名、状态和修复方向。带 `--check-docker` 时会额外检查 Docker Desktop（Docker 桌面运行环境）、Docker daemon（后台服务）和 Docker Compose（容器编排）插件；如果 Docker Desktop 未运行，报告必须是 blocked（环境阻塞），不能把本地依赖启动伪装成通过。

带 `--check-rag-multimodal-e2e` 时会额外执行 RAG（检索增强生成）多模态端到端验收：准备好的图片、音频和视频样例会进入临时向量库，再通过检索链路确认能召回。该开关需要真实 LLM（大语言模型）密钥、可用 `ffmpeg` / `faster-whisper` 和 `.runtime` 下的本地样例，默认 CI（持续集成）不要启用；一旦显式启用，失败会让整体 readiness blocked（环境阻塞）。

`check_runtime_dependency_scope.py` 是生产镜像依赖范围门禁。它只读 `pyproject.toml`、`requirements.runtime.txt` 和 `Dockerfile` 这类显式输入，不读取 `.env`、`.runtime/`、日志、向量库或已安装包。默认 API 镜像只能安装 runtime-only requirements（仅运行时依赖）；`pytest` / `pytest-asyncio` 留在 dev dependency group（开发依赖组），`faster-whisper`、`imageio-ffmpeg` 和 `sentence-transformers` 留在 optional profile（可选能力组合）。如果这些包、`torch`、`triton`、`nvidia-*` 或 `av` 重新进入 `requirements.runtime.txt`，或者生产 Dockerfile 又安装完整 `requirements.txt`，报告必须是 blocked（环境阻塞）。

`check_production_image_build_policy.py` 是生产镜像构建策略门禁。它不运行 Docker、不连接 SSH（安全外壳远程连接）、不启动服务、不删除 Docker 资源、不读取 `.env`，只验证构建策略是否要求：包镜像源通过 `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` 配置，固定 `COMPOSE_PROJECT_NAME`（Compose 项目名），远程长时间构建使用后台 wrapper（包装命令），有超时、日志、PID（进程编号）、镜像 ID / size（大小）、`compose ps` 和 `/health/ready` 证据，并明确禁止 `docker system prune`、删除 volume（数据卷）、删除 `.env` 和删除向量库。

`check_production_image_build_execution_record.py` 是真实远程后台构建后的执行记录门禁。它只验证私有 JSON（结构化文本）记录，不运行 Docker、不连接 SSH、不读取 `.env`、不查看原始日志。通过时只说明某一次构建窗口已经记录后台执行、runtime-only 依赖输入、镜像 ID / size、磁盘与运行时数据安全边界、`compose ps`、`/health/live` 和 `/health/ready`；不能替代镜像漏洞扫描、长期构建稳定性或真实业务履约。

`prepare_production_image_build_execution.py` 是远程后台构建启动器。默认 dry-run（预演）只生成脱敏执行计划，不连接 SSH、不运行 Docker；只有显式 `--execute --approval-token APPROVE_PRODUCTION_IMAGE_BUILD_EXECUTION` 才会在服务器后台启动 `deploy/update-runtime-image.sh`。启动成功不等于构建通过，必须等后台任务完成后填写并校验执行记录。运行时镜像刷新脚本默认使用 `ZHIXING_COMPOSE_PROJECT_NAME=langgraph-travel-planner`，防止从 `current` release 目录运行时产生新的 Compose project 并撞固定容器名。

## Local / Staging 基线

真实 acceptance-core（核心验收）前，先把 `.env.example` 复制为本地 `.env`，只在 `.env` 或部署密钥系统中填真实值。不要把 `.env`、真实 API Key（应用程序接口密钥）、JWT（JSON Web Token，令牌认证）secret（密钥）或数据库密码写入文档、测试快照或提交说明。

本地 development（开发）可以保留部分占位值做静态检查，但只要要跑真实验收，就按 staging（预生产）口径处理：

| 依赖 | 必填变量 | 基线动作 |
|---|---|---|
| PostgreSQL（关系型数据库） | `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD` | `docker compose up -d postgres` 后执行 `.\.venv\Scripts\python -m scripts.init_db --mode bootstrap`。脚本会先探测 TCP（传输控制协议）连通性，不可达时输出 Docker、端口和凭据修复建议。 |
| Redis（内存数据结构存储） | `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`，如启用密码再填 `REDIS_PASSWORD` | `docker compose up -d redis`；staging/production 不应依赖本地锁降级。 |
| LLM（大语言模型） | `DASHSCOPE_API_KEY` | 必须是真实 DashScope（阿里云灵积模型服务）密钥；`your-*`、`change-me`、`test-key`、`dummy` 等都会 blocked（环境阻塞）。 |
| Auth/JWT（认证/令牌认证） | `JWT_SECRET_KEY`、`JWT_ALGORITHM` | `JWT_SECRET_KEY` 必须是长随机值；`JWT_ALGORITHM` 默认 `HS256`。 |
| 地图 / 高德 | `AMAP_API_KEY` | staging/production readiness（就绪检查）硬性要求；路线预览和地理编码依赖它。 |
| 搜索 / 航班 / 酒店 | `TAVILY_API_KEY`、`VARIFLIGHT_API_KEY`、`AIGOHOTEL_API_KEY` 或兼容酒店变量 | 默认是可选能力；当 selected acceptance scenario（已选择验收场景）声明需要对应外部 API 时，preflight（预检）会升级为 blocked。 |
| RAG（检索增强生成）向量库 | `RAG_VECTORSTORE_PATH`、`RAG_COLLECTION_NAME`、`RAG_INTERNAL_VECTORSTORE_PATH`、`RAG_INTERNAL_COLLECTION_NAME` | 执行 `.\.venv\Scripts\python -m scripts.init_rag`，并确认公开与内部 Chroma（向量库）metadata（元数据）都可读，且 `search_destination_guide` / `search_food_recommendations` 与内部知识类别探针可命中。 |

`scripts/check_runtime_readiness.py --target staging --json` 的顶层输出会汇总 `blocked_reasons` 和 `repair_suggestions`，方便 CI（持续集成）或人工 runbook（运行手册）直接展示“卡在哪里”和“下一步命令”。`--target acceptance --check-backend` 还会把 acceptance preflight（验收预检）的 backend（后端服务）和外部能力阻塞原因合并进同一个结构。

## CI/CD 与环境命令分层

| 场景 | 命令 | 真实密钥策略 | 预期用途 |
|---|---|---|---|
| 本地 development（开发） | `scripts\check_runtime_readiness.py --target development --json` | 可使用占位值或本地 `.env`，但必需变量名要配置 | 开发机快速发现缺核心配置 |
| CI（持续集成） | `python scripts/check_runtime_readiness.py --target development --json` | 只使用测试占位值，不读取真实密钥 | 合并前证明配置契约和脚本入口可重复运行 |
| 本地 staging（预生产）依赖启动 | `scripts\check_runtime_readiness.py --target staging --check-docker --json` | 真实值通过本地 `.env` 注入；Docker Desktop 未运行必须 blocked | 启动 PostgreSQL 和 Redis 前确认 Docker 闭环 |
| acceptance（验收）preflight（预检） | `scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json` | 必需项必须是真实值；缺失返回 blocked（环境阻塞） | 不消耗真实对话配额地检查验收条件 |
| production image dependency scope（生产镜像依赖范围） | `scripts\check_runtime_dependency_scope.py --json` | 不读取真实密钥，只检查默认依赖、`requirements.runtime.txt` 和 Dockerfile | 阻止测试框架、多模态深门禁、GPU/model 重依赖进入默认 API 镜像 |
| production image build policy（生产镜像构建策略） | `scripts\check_production_image_build_policy.py --json` | 不读取真实密钥，只检查构建策略和公开脚本契约 | 约束镜像源、Compose project 固定、后台构建、日志证据、磁盘保护和禁止清理边界 |
| production image build execution（生产镜像构建执行记录） | `scripts\check_production_image_build_execution_record.py --record-json <private-workdir>\production-image-build-execution-record.local.json --json` | 只读私有记录，不读取 `.env` 或原始日志 | 验收一次真实远程后台构建的耗时、镜像 ID、镜像大小、健康探针和安全边界 |
| production image build starter（生产镜像构建启动器） | `scripts\prepare_production_image_build_execution.py --ssh-target ... --deploy-dir ... --markdown` | dry-run 不连 SSH；execute 需要 approval token | 启动远程后台构建任务并生成后续执行记录所需的私有证据位置 |
| RAG multimodal deep gate（多模态深门禁） | `scripts\check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e` | 必须使用真实模型密钥和本地样例；不放默认 CI | 发布涉及图片、音频、视频抽取或召回时证明完整链路 |
| staging（预生产）live acceptance（在线验收） | `scripts\run_evaluation_scenarios.py --acceptance-core --base-url <staging-url>` | 真实密钥通过部署环境注入 | 手动触发真实链路验收 |
| production（生产）readiness（就绪） | `scripts\check_runtime_readiness.py --target production --json` | 必需项必须是真实值，不允许 placeholder（占位） | 发布前检查配置、RAG（检索增强生成）向量库和安全边界 |

数据库迁移另见 `docs/部署与运行/db-migration-readiness.md`。默认 CI（持续集成）不连接真实 PostgreSQL（关系型数据库），只通过 `check_runtime_readiness.py` 静态检查 Alembic（数据库迁移工具）配置、迁移文件和业务表边界；staging（预生产）和 production（生产）发布才执行 `alembic upgrade head` 与 `alembic current`。

内部 RAG（检索增强生成）知识库还有一个不依赖真实密钥的治理入口：

```powershell
.\.venv\Scripts\python scripts\validate_rag_knowledge.py
.\.venv\Scripts\python scripts\validate_rag_knowledge.py --json
```

它适合放在默认 CI（持续集成）中，阻断缺 metadata（元数据）、过期 `last_reviewed`、错误分类、内部知识误标为 `public` 以及疑似密钥片段进入知识库。该脚本只校验知识治理契约，不初始化向量库、不调用 LLM（大语言模型）、不访问 MCP（模型上下文协议）或外部 API（应用程序接口）。

GitHub Actions（GitHub 自动化流水线）的默认 CI（持续集成）门禁覆盖 development（开发）级配置预检和内部 RAG 知识库治理校验。手动 staging smoke（预生产冒烟）入口位于 `.github/workflows/staging-smoke.yml`，通过 `workflow_dispatch`（手动触发）启动 runner（流水线执行机）内的 PostgreSQL（关系型数据库）、Redis（内存数据结构存储）和后端，再运行 `acceptance-smoke`（验收冒烟）。缺少必需 GitHub Secrets（密钥管理项）、真实密钥仍为占位值或 `/health/ready` 返回 `not_ready` 时，结果必须失败或 blocked（环境阻塞）。
