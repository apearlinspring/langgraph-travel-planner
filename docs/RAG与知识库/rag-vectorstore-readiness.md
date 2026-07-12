# RAG Vector Store Readiness

本文档定义 RAG（检索增强生成）向量库初始化和 readiness（就绪状态）证据，供 acceptance-core（核心验收）preflight（预检）判断使用。所有命令都应在项目根目录执行，PowerShell（微软命令行 Shell）读取中文输出时使用 UTF-8。

## 固定契约

项目使用两套 Chroma（向量库组件）持久化目录：

| 用途 | 环境变量 | 默认路径 | collection（集合） | knowledge_base |
| --- | --- | --- | --- | --- |
| 公开目的地攻略 | `RAG_VECTORSTORE_PATH` | `data/vectorstore` | `RAG_COLLECTION_NAME=travel_guides` | `public_destination_guides` |
| 旅行社内部知识 | `RAG_INTERNAL_VECTORSTORE_PATH` | `data/vectorstore_internal` | `RAG_INTERNAL_COLLECTION_NAME=agency_internal_knowledge` | `agency_internal_knowledge` |

两套目录必须包含 `chroma.sqlite3`。就绪检查会确认 collection 存在、collection 内有 embeddings（嵌入向量），并抽样检查 embedding metadata（元数据）。

公开攻略 metadata 必须至少包含：

```text
contract_version, knowledge_base, source, source_type, category, visibility,
evidence_level, applicable_modes, constraints, last_reviewed
```

其中 `contract_version=rag.evidence.v1`、`knowledge_base=public_destination_guides`、`visibility=public`。

内部知识 metadata 必须至少包含：

```text
contract_version, knowledge_base, source, source_type, category, visibility,
evidence_level, applicable_modes, constraints, last_reviewed,
freshness_status, requires_verification
```

其中 `contract_version=rag.evidence.v1`、`knowledge_base=agency_internal_knowledge`、`visibility=internal`。

## 发布矩阵 / 证据层级

下面这张矩阵用于公开发布说明、PR（拉取请求）描述和验收记录。它的核心原则是：每一层只能证明自己实际运行过的范围，不能把离线召回评测包装成真实向量库或线上 Agent（智能体）验收。

| 层级 | 代表命令 | 成功状态 | 能证明什么 | 不能证明什么 | 失败或缺条件时怎么写 |
| --- | --- | --- | --- | --- | --- |
| 离线 BM25（词频检索）召回评测 | `uv run python scripts\evaluate_rag_retrieval.py --json` | `passed` | 本地 Markdown（标记文本）知识文档、metadata（元数据）标注和离线召回场景没有明显回退。 | 不能证明 Chroma 向量库已初始化，不能证明 embedding（嵌入向量）可用，不能证明真实 LLM（大语言模型）、外部 API（应用程序接口）或线上 Agent 通过。 | 写 `blocked` 或 `failed`，并记录失败指标；不要写“真实 RAG 通过”。 |
| mixed-corpus safety（公开+内部混合候选库安全门） | `uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json` | `passed` | 当前 11 条标注公开查询在离线混合候选库中没有返回场景禁止的内部产品、报价、SOP（标准作业流程）、风控或私有证据。 | 不能外推到未知查询、提示注入或真实向量检索，也不能证明线上工具链、后端健康检查或真实模型调用通过。 | 写 `blocked`，并列 `failed_scenarios`、forbidden 命中类别或 metadata 过滤问题。 |
| 真实 Chroma 向量库初始化 | `uv run python -m scripts.init_rag` | `configured` | public/internal 两套 Chroma collection（集合）存在，`chroma.sqlite3` 可读，embedding 数量非空，metadata 契约满足要求。 | 不能证明线上 Agent 已生成正确报告，也不能替代 acceptance preflight（验收预检）或 live smoke（线上冒烟验证）。 | 缺真实 `DASHSCOPE_API_KEY`、collection 缺失、metadata 损坏或探针无命中时写 `blocked`；开发环境可写 `not_configured`，但不能当作通过证据。 |
| acceptance preflight（验收预检） | `uv run python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary` | `passed` | 选中的 acceptance-core（核心验收）场景所需配置、真实依赖、RAG 安全门和必要后端探针满足运行前置条件。 | `--preflight-only` 是 dry-run（只预检不执行真实对话），不能证明 Agent 最终回答、工具调用质量或报告内容通过。 | 任一必需依赖缺失、后端不可达、RAG 安全门失败时写 `blocked`；不得改写成“可降级通过”。 |
| 线上 smoke/core | `uv run python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url ... --json` 或 core 场景命令 | `passed` | 目标环境后端、真实配置、选中场景、Agent 对话链路和验收门禁实际跑通。 | 不能自动证明全量城市、全量供应商、实时库存、真实价格或所有外部服务长期稳定。 | 写 `blocked` 或 `failed`，保留脱敏摘要；不要提交原始日志、真实密钥、运行时目录或向量库产物。 |

状态词统一口径：

- `passed`：该层命令真实执行且所有必需检查通过。用于离线评测、safety gate、preflight 和 live smoke/core 的结果。
- `configured`：配置或向量库物理证据存在且可读。它只说明依赖已就绪，不等于线上业务验收通过。
- `blocked`：必需依赖缺失、真实环境不可达、安全门失败或证据不足。发布说明应直接写阻断原因。
- `dry-run`：只做预检、命令展开或离线判断，没有执行真实 Agent 对话。dry-run 可以作为前置证据，不能作为最终线上验收。
- `not_configured`：开发或测试环境允许降级的未配置状态。公开发布不能把它写成通过。

推荐公开口径示例：

- 可以写：`offline retrieval: passed; mixed-corpus safety: passed; rag_vector_store: configured; acceptance preflight: passed; live smoke: not run`。
- 不要写：`RAG 全链路 passed`，除非真实向量库、acceptance preflight 和线上 smoke/core 都完成且通过。

## 初始化

初始化命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
uv run python -m scripts.init_rag
```

`scripts.init_rag` 需要真实 `DASHSCOPE_API_KEY`。该密钥用于 DashScope（阿里云灵积）`text-embedding-v2` embedding（向量嵌入）模型，也覆盖后续 LLM（大语言模型）相关 RAG 能力。缺失或仍是占位值时，脚本会返回 `blocked`（环境阻塞）信息，不会创建半成品向量库。

初始化完成后脚本会立即复用 readiness 检查，输出两套 collection 的路径、名称和 embedding 数量。若目录存在但 collection 缺失、SQLite 元数据不可读、embedding 为空或 metadata 损坏，会失败而不是误报 ready。

## Preflight 证据

运行配置检查：

```powershell
uv run python scripts\check_runtime_readiness.py --target acceptance --json
```

或直接跑核心验收预检：

```powershell
uv run python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

`rag_vector_store` 的状态含义：

- `configured`：public/internal 两套向量库都满足路径、collection、embedding 和 metadata 契约。
- `blocked`：staging（预发布环境）/ production（生产环境）/ acceptance-core 所需依赖缺失或损坏。
- `not_configured`：development（开发环境）或 test（测试环境）中可降级，但不能作为真实验收通过证据。

## 提交边界

不要提交 `data/vectorstore/` 或 `data/vectorstore_internal/` 原始产物；它们已在 `.gitignore` 中忽略。可提交的内容仅包括初始化脚本、契约检查代码、测试和脱敏文档。真实密钥只放在本机 `.env` 或部署密钥管理中，对外只引用 `.env.example`。
