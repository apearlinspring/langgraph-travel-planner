# RAG Runtime Contract（检索增强生成运行时契约）

本文记录公开目的地知识和内部旅行社知识从初始化、readiness（就绪检查）到运行时工具检索必须共享的路径、collection（集合）和 metadata（元数据）契约。

## 固定契约

| 知识库 | 路径变量 | 默认路径 | collection 变量 | 默认 collection | knowledge_base |
|---|---|---|---|---|---|
| 公开目的地攻略 | `RAG_VECTORSTORE_PATH` | `data/vectorstore` | `RAG_COLLECTION_NAME` | `travel_guides` | `public_destination_guides` |
| 内部旅行社知识 | `RAG_INTERNAL_VECTORSTORE_PATH` | `data/vectorstore_internal` | `RAG_INTERNAL_COLLECTION_NAME` | `agency_internal_knowledge` | `agency_internal_knowledge` |

初始化入口 `scripts.init_rag`、readiness 入口 `scripts/check_runtime_readiness.py` 和运行时工具 `app/tools/rag_tools.py` 都必须读取同一组配置。运行时不应静默创建新的向量库来掩盖配置错误；缺失或不匹配时返回可诊断的空证据契约。

`scripts.init_rag` 默认采用幂等刷新：先在 `data/.rag-vectorstore-builds/` 构建并校验新库，通过后再替换 `data/vectorstore/` 与 `data/vectorstore_internal/`。旧库会移动到 `data/.rag-vectorstore-backups/`；若替换后 readiness（就绪检查）失败，新库会移动到 `data/.rag-vectorstore-faileds/` 并回滚旧库。三个隐藏目录均为本地生成数据，已被 Git（版本控制）忽略。

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

内部产品类文档（`category=products`）还必须带产品匹配字段：

- `product_id`
- `destination`
- `theme`
- `duration`
- `audience`
- `service_level`
- `price_band`
- `source`
- `evidence_type`

运行时会把其中的 `product_id`、`destination`、`theme`、`duration`、`audience`、`service_level`、`price_band`、`evidence_type` 以及可选的 `service_boundary`、`quote_basis`、`verification_items` 写入检索证据。原始 `source` 仍保留为 Markdown 文件路径，产品目录来源会映射为 `product_source`，避免覆盖可追溯文件路径。

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

内部产品文档额外检查产品匹配字段；例如产品 chunk（切片）缺少 `product_id`、`destination` 或 `evidence_type` 时，也会返回 `metadata_missing`，并在 `details.missing_metadata` 中列出缺失字段。`collection_missing`、`metadata_missing` 和 `metadata_mismatch` 是部署排障时最优先区分的三类问题。

最小运行时探针覆盖：

- 公开攻略：目的地攻略、目的地美食。
- 内部知识：`products`、`sop`、`pricing`、`risk`、`report` 五类；产品探针同时检查 `product_id`、路线、适合人群和服务边界等产品化表达是否存在。

## 产品检索输出边界

`search_agency_product_templates` 会在标准证据契约后附加 2-3 个产品化方向，字段包括：

- 适用人群。
- 服务边界。
- 报价口径。
- 待核验项。

这些方向只代表虚构内部产品模板和成熟路线结构，不能解释为真实供应商、真实客户、真实库存、锁价或履约承诺。用户不接受产品化方向时，Agent（智能体）必须明确切回自由规划，只保留路线、预算、住宿区域和核验建议，不继续强推旅行社方案。

## 运行命令

```powershell
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python scripts\validate_rag_knowledge.py --json
.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --json
```

不要提交 `data/vectorstore`、`data/vectorstore_internal`、`.env` 或 `.runtime`。真实密钥只放在本机 `.env` 或部署密钥系统中。
