# RAG Runtime Contract（检索增强生成运行时契约）

本文记录公开目的地知识和内部旅行社知识从初始化、readiness（就绪检查）到运行时工具检索必须共享的路径、collection（集合）和 metadata（元数据）契约。

## 固定契约

| 知识库 | 路径变量 | 默认路径 | collection 变量 | 默认 collection | knowledge_base |
|---|---|---|---|---|---|
| 公开目的地攻略 | `RAG_VECTORSTORE_PATH` | `data/vectorstore` | `RAG_COLLECTION_NAME` | `travel_guides` | `public_destination_guides` |
| 内部旅行社知识 | `RAG_INTERNAL_VECTORSTORE_PATH` | `data/vectorstore_internal` | `RAG_INTERNAL_COLLECTION_NAME` | `agency_internal_knowledge` | `agency_internal_knowledge` |

初始化入口 `scripts.init_rag`、readiness 入口 `scripts/check_runtime_readiness.py` 和运行时工具 `app/tools/rag_tools.py` 都必须读取同一组配置。运行时不应静默创建新的向量库来掩盖配置错误；缺失或不匹配时返回可诊断的空证据契约。

## Metadata 要求

公开与内部文档都必须带：

- `contract_version=rag.evidence.v1`
- `knowledge_base`
- `source`
- `source_type`
- `category`
- `visibility`
- `evidence_level`
- `applicable_modes`
- `constraints`
- `last_reviewed`

内部旅行社知识还必须带：

- `freshness_status`
- `requires_verification`

内部 Markdown（标记文本）文档的 front matter（头部元数据）仍由 `scripts/validate_rag_knowledge.py` 校验，避免分类错位、复审过期或内部资料误标为 public（公开）。

## Readiness 失败代码

`rag_vector_store.details.stores.public` 和 `rag_vector_store.details.stores.internal` 会暴露 `finding_code`：

| finding_code | 含义 |
|---|---|
| `vectorstore_missing` | 向量库目录或 `chroma.sqlite3` 缺失 |
| `collection_missing` | 配置的 collection 不存在 |
| `metadata_schema_missing` | Chroma metadata 表结构不完整 |
| `metadata_missing` | 样本文档缺少必需 metadata 字段 |
| `metadata_mismatch` | `contract_version`、`knowledge_base` 或 `visibility` 与契约不一致 |
| `retrieval_no_hit` | collection 有数据但最小运行时场景无法命中 |
| `metadata_unreadable` | `chroma.sqlite3` 无法只读解析 |

最小运行时探针覆盖：

- 公开攻略：目的地攻略、目的地美食。
- 内部知识：`products`、`sop`、`pricing`、`risk`、`report` 五类。

## 运行命令

```powershell
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python scripts\validate_rag_knowledge.py --json
```

不要提交 `data/vectorstore`、`data/vectorstore_internal`、`.env` 或 `.runtime`。真实密钥只放在本机 `.env` 或部署密钥系统中。
