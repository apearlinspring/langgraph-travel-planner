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

产品样板如果要进入省心方案草案，正文还应提供“住宿示例候选”和“费用说明”两类可检索文本：住宿示例至少包含 1 家公开可查酒店名、所在区域、使用边界和二次核验要求；费用说明要能按大交通、住宿、门票/体验、当地交通、餐饮和服务/机动拆分。示例酒店只代表选址和档次参考，不能解释为真实库存、占房或锁价。

知识文档的 front matter（头部元数据）仍由 `scripts/validate_rag_knowledge.py` 校验，避免分类错位、复审过期或内部资料误标为 public（公开）。

## 文档格式与多模态入口

RAG 文档加载器支持以下文本格式：

- Markdown（标记文本）：`.md`、`.markdown`
- 纯文本：`.txt`、`.text`、`.rst`
- 结构化文本：`.json`、`.csv`
- 网页/办公文档：`.html`、`.htm`、`.docx`
- PDF（便携式文档格式）：`.pdf`，在本地具备 `fitz` 或 `pypdf` 可选解析库时提取正文；否则依赖同名说明文件

多模态文件当前支持作为“可检索文本代理”进入 RAG：

- 图片：`.jpg`、`.jpeg`、`.png`、`.webp`、`.gif`、`.bmp`、`.tif`、`.tiff`
- 音频：`.mp3`、`.wav`、`.m4a`、`.aac`、`.flac`、`.ogg`
- 视频：`.mp4`、`.mov`、`.avi`、`.mkv`、`.webm`

多模态文件必须优先配同名 sidecar（伴随说明文件），例如 `xian-map.png.md`、`guide.mp4.txt` 或 `hotel-room.jpg.json`。sidecar 里写图片描述、音频转写、视频字幕或人工摘要；RAG 会把这些内容和文件名、metadata 一起索引。没有 sidecar 时，文件仍会被识别，但只按文件名和 metadata 参与召回，不能视为真正理解了图像、音频或视频内容。

如果需要自动抽取多模态内容，可以开启：

```powershell
$env:RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT = "true"
```

开启后：

- 图片会调用 `vision` profile（视觉模型配置）生成中文描述，并尽量抽取可见文字/OCR（光学字符识别）内容。
- 视频会优先用 `ffmpeg` 抽取关键帧，再复用图片描述能力；项目依赖包含 `imageio-ffmpeg`，通常不需要额外手工安装系统级 `ffmpeg`。如果仍找不到 `ffmpeg`，会安全降级，继续尝试 sidecar 或转写命令。
- 音频和视频转写可通过 `RAG_MULTIMODAL_TRANSCRIPT_COMMAND` 接入本机受信任的转写命令。命令里用 `{input}` 表示文件路径。真实 ASR（自动语音识别）可使用 `scripts/rag_transcribe_whisper.py`，它基于 `faster-whisper` 把音频或视频中的语音转成文本；项目也保留 `scripts/rag_transcribe_sidecar.py` 作为 deterministic smoke（确定性冒烟验证）命令，它只读取同名 sidecar，不做真实语音识别。
- 自动抽取结果缓存到 `RAG_MULTIMODAL_CACHE_PATH`，默认 `.runtime/rag_multimodal_cache`，该目录不应提交。

相关配置：

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT` | `false` | 是否启用自动多模态抽取 |
| `RAG_MULTIMODAL_CACHE_PATH` | `.runtime/rag_multimodal_cache` | 自动抽取缓存目录 |
| `RAG_MULTIMODAL_MAX_IMAGE_BYTES` | `6000000` | 单张图片自动描述的最大字节数 |
| `RAG_MULTIMODAL_VIDEO_FRAME_COUNT` | `3` | 每个视频抽取的关键帧数量上限 |
| `RAG_MULTIMODAL_VIDEO_FRAME_WIDTH` | `640` | 视频关键帧缩放宽度 |
| `RAG_FFMPEG_PATH` | 空 | 可选的 `ffmpeg` 可执行文件路径；为空时从 PATH、项目本地工具目录或 `imageio-ffmpeg` 查找 |
| `RAG_MULTIMODAL_TRANSCRIPT_COMMAND` | 空 | 受信任的音频/视频转写命令 |
| `RAG_WHISPER_MODEL_SIZE` | `tiny` | `scripts/rag_transcribe_whisper.py` 使用的 Whisper 模型规格或本地模型路径 |
| `RAG_WHISPER_MODEL_CACHE` | `.runtime/rag_whisper_models` | Whisper 模型下载/缓存目录，不应提交 |
| `RAG_WHISPER_DEVICE` | `cpu` | Whisper 推理设备，例如 `cpu` 或 `cuda` |
| `RAG_WHISPER_COMPUTE_TYPE` | `int8` | Whisper 推理精度，CPU 默认用 `int8` 降低资源占用 |
| `RAG_WHISPER_LANGUAGE` | 空 | 可选语种代码，例如 `zh`、`en`；为空时自动识别 |

自动抽取不会绕过安全规则：无法抽取、缺少密钥、文件过大、`ffmpeg` 不存在或转写命令失败时，RAG 只写入失败状态 metadata，并继续使用 sidecar 或保守占位文本。

每个入库文档会额外写入：

- `source_format`：原始文件格式，例如 `md`、`json`、`png`
- `content_modality`：内容模态，例如 `text`、`image`、`audio`、`video`
- `extraction_method`：抽取方式，例如 `front_matter_text`、`json_text`、`image_sidecar`
- `sidecar_source`：如果使用了伴随说明文件，记录该文件路径
- `multimodal_auto_extract_status`、`auto_extraction_method`、`vision_model` 等可选运行态字段：用于追踪自动抽取是否成功、是否命中缓存、使用的模型或失败原因

## 查询增强与观测

运行时公开/内部 RAG 默认使用 `local_multi_query`，即本地规则查询扩展。它不会调用 LLM（大语言模型），会针对美食、住宿、景点、亲子、省心产品、预算、风险、报告等常见意图补充检索词，再由 BM25（词频检索算法）+ Dense（向量检索）进行跨查询 RRF（倒数排名融合）。

RRF 融合之后会应用轻量 query-aware boost（查询感知加权）：当用户查询明确提到图片、音频、视频、字幕、OCR（光学字符识别）等模态词，或查询中的长短语更精确命中文档正文/标题/source metadata 时，对应候选会小幅上浮。该规则只影响候选排序，不新增数据源、不绕过 metadata filter（元数据过滤），也不把低相关多模态文件强行召回。

每次检索会生成结构化 trace（链路记录），包含 query preview（查询预览）、metadata filter（元数据过滤）、是否命中缓存、查询变体数量、候选数、最终来源、耗时、visibility（可见性）和 category（分类）等信息。trace 只写入日志，不改变工具返回给 Agent（智能体）的证据契约。

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
- 住宿示例候选。
- 分项费用说明。
- 待核验项。

这些方向只代表虚构内部产品模板和成熟路线结构，不能解释为真实供应商、真实客户、真实库存、锁价或履约承诺。用户不接受产品化方向时，Agent（智能体）必须明确切回自由规划，只保留路线、预算、住宿区域和核验建议，不继续强推旅行社方案。

## 运行命令

```powershell
.\.venv\Scripts\python -m scripts.init_rag
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target staging --json
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e
.\.venv\Scripts\python scripts\check_rag_multimodal_readiness.py --json --no-dotenv
.\.venv\Scripts\python scripts\validate_rag_knowledge.py --json
.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --json
.\.venv\Scripts\python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

本地 smoke 验证可这样开启多模态抽取，并使用 sidecar 转写命令：

```powershell
$env:RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT = "true"
$env:RAG_MULTIMODAL_TRANSCRIPT_COMMAND = "uv run python scripts\rag_transcribe_sidecar.py {input}"
uv run python scripts\check_rag_multimodal_readiness.py --json --no-dotenv
```

`--no-dotenv` 用于公开 smoke（冒烟验证）和本地脱敏检查，它不会加载本机 `.env`，因此不能用来证明真实密钥或真实模型能力已经就绪。

真实音频/视频 ASR 验证可改用 Whisper 转写脚本：

```powershell
$env:RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT = "true"
$env:RAG_WHISPER_MODEL_SIZE = "tiny"
$env:RAG_WHISPER_DEVICE = "cpu"
$env:RAG_WHISPER_COMPUTE_TYPE = "int8"
$env:RAG_MULTIMODAL_TRANSCRIPT_COMMAND = "uv run python scripts\rag_transcribe_whisper.py {input}"
uv run python scripts\check_rag_multimodal_readiness.py --json
```

端到端多模态入库验收可以运行：

```powershell
uv run python scripts\accept_rag_multimodal_e2e.py --json
```

该脚本会读取 `.runtime/rag_web_acceptance/documents/destinations` 下的图片、音频和视频样例，把它们复制到 `.runtime/rag_e2e_acceptance`，再执行 `DocumentManager -> Splitter -> Chroma -> AdvancedRAGPipeline` 的完整链路。验收要求三类查询都以 rank 1 召回对应多模态证据，并把结果写入 `.runtime/rag_e2e_acceptance/acceptance_result.json`。它需要真实 `DASHSCOPE_API_KEY`、可用 `faster-whisper` 和已准备好的本地样例文件；缺少条件时会返回 `blocked`，不能当作通过证据。

如果希望在 readiness（就绪检查）里同时跑真实端到端验收，可以使用：

```powershell
uv run python scripts\check_rag_multimodal_readiness.py --json --check-e2e
uv run python scripts\check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e
```

`check_runtime_readiness.py` 默认会执行 mixed-corpus safety gate（公开+内部混合库安全门），并把结果写入 `rag_mixed_corpus_safety` 字段；失败会让顶层状态进入 `blocked`。这条门禁不需要真实密钥或临时向量库，主要防止公开场景召回内部产品、价格或风控资料。

默认不带 `--check-e2e` / `--check-rag-multimodal-e2e` 时，多模态 readiness 只检查配置、依赖和建议命令，不构建临时向量库；带上开关时，会额外执行上述入库召回验收，并把精简结果写入 `e2e_acceptance` 或 `rag_multimodal_e2e` 字段。整体 runtime readiness 显式启用深验收后，失败也会让顶层状态进入 `blocked`，便于发布前阻断。

完整发布前清单见 `docs/RAG与知识库/rag-release-checklist.md`。

不要提交 `data/vectorstore`、`data/vectorstore_internal`、`.env` 或 `.runtime`。真实密钥只放在本机 `.env` 或部署密钥系统中。
