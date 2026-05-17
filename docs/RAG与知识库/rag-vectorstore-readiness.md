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

## 初始化

初始化命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python -m scripts.init_rag
```

`scripts.init_rag` 需要真实 `DASHSCOPE_API_KEY`。该密钥用于 DashScope（阿里云灵积）`text-embedding-v2` embedding（向量嵌入）模型，也覆盖后续 LLM（大语言模型）相关 RAG 能力。缺失或仍是占位值时，脚本会返回 `blocked`（环境阻塞）信息，不会创建半成品向量库。

初始化完成后脚本会立即复用 readiness 检查，输出两套 collection 的路径、名称和 embedding 数量。若目录存在但 collection 缺失、SQLite 元数据不可读、embedding 为空或 metadata 损坏，会失败而不是误报 ready。

## Preflight 证据

运行配置检查：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --json
```

或直接跑核心验收预检：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

`rag_vector_store` 的状态含义：

- `configured`：public/internal 两套向量库都满足路径、collection、embedding 和 metadata 契约。
- `blocked`：staging（预发布环境）/ production（生产环境）/ acceptance-core 所需依赖缺失或损坏。
- `not_configured`：development（开发环境）或 test（测试环境）中可降级，但不能作为真实验收通过证据。

## 提交边界

不要提交 `data/vectorstore/` 或 `data/vectorstore_internal/` 原始产物；它们已在 `.gitignore` 中忽略。可提交的内容仅包括初始化脚本、契约检查代码、测试和脱敏文档。真实密钥只放在本机 `.env` 或部署密钥管理中，对外只引用 `.env.example`。
