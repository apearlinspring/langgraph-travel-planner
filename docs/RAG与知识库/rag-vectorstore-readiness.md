# RAG Vector Store Readiness

本文说明 RAG 向量库的初始化、元数据要求和验收检查。命令在项目根目录执行，PowerShell 使用 UTF-8。

## 固定契约

项目使用两套 Chroma 持久化目录：

| 用途 | 环境变量 | 默认路径 | collection | knowledge_base |
| --- | --- | --- | --- | --- |
| 公开目的地攻略 | `RAG_VECTORSTORE_PATH` | `data/vectorstore` | `RAG_COLLECTION_NAME=travel_guides` | `public_destination_guides` |
| 旅行社内部知识 | `RAG_INTERNAL_VECTORSTORE_PATH` | `data/vectorstore_internal` | `RAG_INTERNAL_COLLECTION_NAME=agency_internal_knowledge` | `agency_internal_knowledge` |

两套目录必须包含 `chroma.sqlite3`。就绪检查会确认 collection 存在、collection 内有 embeddings，并抽样检查 embedding metadata。

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

## 验证步骤与状态

按下表依次检查知识文档、向量库和运行链路，分别记录结果。

| 步骤 | 命令 | 检查内容 |
|---|---|---|
| 离线召回 | `uv run python scripts\evaluate_rag_retrieval.py --json` | Markdown、metadata 标注和 BM25 召回场景。 |
| 混合库过滤 | `uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json` | 11 条公开查询对内部产品、报价、SOP、风控及私有证据的过滤。 |
| 向量库初始化 | `uv run python -m scripts.init_rag` | 两套 collection、SQLite、embedding 数量和 metadata。 |
| 验收预检 | `uv run python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary` | 配置、依赖、安全门及后端探针。 |
| 运行验收 | `uv run python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url ... --json` | 目标环境中的 Agent 对话、工具和报告。 |

结果状态：

- `passed`：该步骤执行成功，必需检查通过。
- `configured`：两套向量库及元数据就绪。
- `blocked`：依赖缺失、环境不可达或检查失败；同时记录原因。
- `dry-run`：完成预检或命令计划，尚未执行对话。
- `not_configured`：开发或测试环境中依赖未配置。

示例记录：`offline retrieval: passed; mixed-corpus safety: passed; rag_vector_store: configured; acceptance preflight: passed; live smoke: not run`。

## 初始化

初始化命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
uv run python -m scripts.init_rag
```

`scripts.init_rag` 需要真实 `DASHSCOPE_API_KEY`。该密钥用于 DashScope `text-embedding-v2` embedding 模型，也覆盖后续 LLM 相关 RAG 能力。缺失或仍是占位值时，脚本会返回 `blocked` 信息，不会创建半成品向量库。

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
- `blocked`：staging/ production/ acceptance-core 所需依赖缺失或损坏。
- `not_configured`：development 或 test 中允许依赖未配置。

## 生成文件

`data/vectorstore/` 和 `data/vectorstore_internal/` 是本地生成目录，已由 `.gitignore` 排除。配置填写在本机 `.env` 或部署密钥管理中，仓库提供 `.env.example`。
