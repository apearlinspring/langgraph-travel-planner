# RAG 发布前验收 Checklist

本文列出 RAG 文档、召回逻辑、metadata、多格式解析、多模态抽取和向量库发布前的检查步骤。按改动范围执行离线评测、向量库检查、预检和线上验收。

## 0. 改动范围与文件检查

- [ ] 本次改动是否触及 `data/documents/`、`app/rag/`、`app/tools/rag_tools.py`、`app/evaluation/rag_retrieval.py`、RAG metadata 契约、多格式解析、多模态抽取或向量库初始化规则。
- [ ] 不提交 `.env`、`.runtime/`、`data/vectorstore/`、`data/vectorstore_internal/`、真实日志、真实密钥、本地转写缓存或生成向量库。
- [ ] 如果改了正式 RAG 行为，同步检查 `docs/RAG与知识库/rag-runtime-contract.md`、`docs/RAG与知识库/rag-retrieval-evaluation.md`、`docs/RAG与知识库/rag-vectorstore-readiness.md` 和部署文档是否过期。

## 1. 发布证据矩阵

详细定义见 `docs/RAG与知识库/rag-vectorstore-readiness.md`。

| 检查项 | 执行时机 | 记录状态 |
| --- | --- | --- |
| 离线 BM25 召回评测 | 知识文档、metadata 或召回逻辑变更前后 | `offline retrieval: passed` |
| mixed-corpus safety | 默认门禁和 acceptance preflight 前 | `mixed-corpus safety: passed` |
| Chroma 向量库初始化 | 发布前，改动涉及向量库、知识文档、metadata 或 embedding 时 | `rag_vector_store: configured` |
| acceptance preflight | 发布前或目标环境上线前，检查配置和依赖 | `acceptance preflight: passed`，注明 `dry-run` |
| 线上 smoke/core | 部署后按风险选择，检查真实对话与报告 | `live smoke: passed` 或 `acceptance core: passed` |

状态词约定：

- `passed`：该层命令真实执行，必需检查通过。
- `configured`：依赖、collection、embedding 和 metadata 物理证据可读。
- `blocked`：缺真实依赖、后端不可达、安全门失败或证据不足。
- `dry-run`：只做预检或计划展示，没有执行真实 Agent 对话。
- `not_configured`：依赖未配置，开发或测试环境可按规则降级。

## 2. 默认离线门禁

默认离线检查覆盖知识组织与召回，适用于本地和默认 CI；运行时无需模型密钥和外部 API。

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null

uv run python -m compileall app tests scripts
uv run python -m pytest tests\test_rag_retrieval_evaluation.py tests\test_rag_retriever.py tests\test_rag_document_formats.py -q
uv run python scripts\check_travel_data_sources.py
uv run python scripts\validate_rag_knowledge.py --json
uv run python scripts\evaluate_rag_retrieval.py --json
uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

`check_travel_data_sources.py` 在本地检查 `data/documents/source_registry.json` 和公开目的地 Markdown 的来源、许可、归因、review 日期及样例声明。内容新鲜度由数据源审查另行确认。

如本次发布需要扩充公开旅行数据，先生成私有候选包：

```powershell
uv run python scripts\collect_public_travel_data_candidates.py --city xian --output-dir <private-workdir>\public-travel-candidates --execute
uv run python scripts\review_public_travel_data_candidates.py --candidate-json <private-workdir>\public-travel-candidates\public-travel-data-candidates.json --review-json <private-workdir>\public-travel-candidate-review.json --output-dir <private-workdir>\approved-public-travel-candidates --execute
```

候选采集器默认不触网；显式 `--execute` 后也只写入私有目录。候选审查脚本要求人工 review JSON 明确批准 license、attribution、content quality 和 boundary 四项，才会生成私有 staging 草稿；草稿仍需最终人工检查后才能进入 `data/documents/`。

通过标准：

- [ ] `compileall` 无语法错误。
- [ ] RAG 定向测试通过。
- [ ] 数据源 registry 和公开目的地 Markdown 来源/许可/归因字段完整。
- [ ] 如生成公开数据候选包，确认输出留在私有目录，候选仍是 `commit_ready=false`，未直接进入 Git。
- [ ] 如 staging 审查通过候选，确认 review JSON 有四项明确批准，staged 草稿仍留在私有目录，未绕过最终人工检查。
- [ ] `validate_rag_knowledge.py` 没有契约错误。
- [ ] 普通召回评估的 source/category/source_type/visibility 指标没有明显回退。
- [ ] mixed-corpus safety gate 的 `safety_pass_rate` 为 `1.0`，`failed_scenarios` 为空。
- [ ] 记录离线召回与 mixed-corpus safety 的状态和指标。

## 3. 真实向量库 readiness

发布前检查 Chroma 向量库，目标环境或本机须配置 `DASHSCOPE_API_KEY`。

```powershell
uv run python -m scripts.init_rag
uv run python scripts\check_runtime_readiness.py --target staging --json
uv run python scripts\check_runtime_readiness.py --target production --json
```

通过标准：

- [ ] `scripts.init_rag` 完成后没有 `blocked`。
- [ ] `rag_vector_store.status = configured`。
- [ ] public/internal 两套 collection、embedding 数量和 metadata 契约可读。
- [ ] 如果 collection 缺失、metadata 损坏、探针无命中或缺真实 `DASHSCOPE_API_KEY`，写 `rag_vector_store: blocked`。
- [ ] 不提交 `data/vectorstore/`、`data/vectorstore_internal/` 或任何生成数据库文件。

## 4. Acceptance Preflight Dry-Run

`--preflight-only` 检查配置、后端 readiness、知识库门禁和场景前置条件。真实对话与报告由后续 smoke/core 执行。

发布前本地预检：

```powershell
uv run python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
```

目标环境预检：

```powershell
uv run python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url $env:ZHIXING_PUBLIC_BASE_URL --json
uv run python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url $env:ZHIXING_PUBLIC_BASE_URL --json --no-summary
```

通过标准：

- [ ] 顶层 `status = passed`，且 `blocked_reasons` 为空。
- [ ] `rag_mixed_corpus_safety.status = passed`。
- [ ] backend live/ready、必需 MCP 服务和真实外部 API 配置符合选中验收场景。
- [ ] 记录 `acceptance preflight: passed (dry-run)`。

## 5. 多格式与多模态深验收

只有本次改动触及图片、音频、视频、PDF、Office 文档解析、sidecar、ASR 或多模态缓存时才跑这层。

本地确定性 smoke：

```powershell
$env:RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT = "true"
$env:RAG_MULTIMODAL_TRANSCRIPT_COMMAND = "uv run python scripts\rag_transcribe_sidecar.py {input}"
uv run python scripts\check_rag_multimodal_readiness.py --json --no-dotenv
uv run python scripts\accept_rag_multimodal_e2e.py --json
```

真实音频/视频转写验收：

```powershell
$env:RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT = "true"
$env:RAG_WHISPER_MODEL_SIZE = "tiny"
$env:RAG_WHISPER_DEVICE = "cpu"
$env:RAG_WHISPER_COMPUTE_TYPE = "int8"
$env:RAG_MULTIMODAL_TRANSCRIPT_COMMAND = "uv run python scripts\rag_transcribe_whisper.py {input}"
uv run python scripts\check_rag_multimodal_readiness.py --json --check-e2e
uv run python scripts\check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e
```

`--no-dotenv` 跳过本机 `.env`，用于本地确定性 smoke。检查实际视觉模型、ASR 或部署配置时使用环境中的真实配置；运行摘要保留状态、关键指标和 blocked reason。

通过标准：

- [ ] `check_rag_multimodal_readiness.py` 的基础依赖、配置和样例发现均为 `passed`。
- [ ] `accept_rag_multimodal_e2e.py` 对图片、音频、视频三类查询都能 rank 1 召回对应证据。
- [ ] 显式启用 `--check-rag-multimodal-e2e` 后，runtime readiness 顶层不出现 `rag_multimodal_e2e` blocker。
- [ ] 缺模型密钥、`ffmpeg` / `faster-whisper` 或本地样例时记录 `blocked`。

## 6. 部署后线上 Smoke/Core

在 staging 或 production 环境使用实际部署配置执行线上验收。

如果发布改了 RAG 文档、metadata、召回逻辑或向量库初始化规则，先在目标环境重建向量库：

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python -m scripts.init_rag"
```

再跑线上 readiness、preflight 和按风险选择的 live 验收：

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json | head -c 8000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url '$env:ZHIXING_PUBLIC_BASE_URL' --json | head -c 8000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python scripts/run_evaluation_scenarios.py --acceptance-core --preflight-only --base-url '$env:ZHIXING_PUBLIC_BASE_URL' --json --no-summary | head -c 8000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url '$env:ZHIXING_PUBLIC_BASE_URL' --json | head -c 8000; echo"
```

通过标准：

- [ ] `production` readiness 没有 `blocked_reasons`。
- [ ] `rag_vector_store.status = configured`。
- [ ] acceptance preflight 的凭据、后端与 RAG 门禁检查全部通过。
- [ ] live smoke/core 的场景结果为 `passed`，并且确定性 acceptance gate 通过。
- [ ] 分别记录 preflight、live smoke/core 的状态；未执行的步骤记为 `not run`。

## 7. 常见阻断处理

| 阻断位置 | 典型含义 | 处理 |
|---|---|---|
| `rag_mixed_corpus_safety` | 公开查询可能召回内部产品、报价或风控证据 | 检查 `expected_visibilities`、`forbidden_*`、metadata filter 和 ranking boost |
| `rag_vector_store` | 向量库缺失、collection 不匹配、metadata 损坏或探针无命中 | 重新运行 `python -m scripts.init_rag`，再看 `details.stores.<public|internal>.finding_code` |
| `rag_multimodal_e2e` | 多模态样例、真实密钥、`ffmpeg`、`faster-whisper` 或临时入库召回失败 | 先跑 `check_rag_multimodal_readiness.py --json` 定位，再补样例或依赖 |
| `real_llm` / `external_api:*` | 验收场景需要真实模型或外部服务凭据 | 在本机安全配置、CI secrets 或部署密钥系统补真实值，不写进仓库 |
| `backend_live` / `backend_ready` | 后端服务不可达或 ready check 不通过 | 先看服务进程、数据库、Redis、MCP 服务和 `/health/ready` 明细 |

## 8. 可保留证据

- [ ] 只保留命令、顶层状态、关键指标和 blocked reason。
- [ ] 不保留 `.env`、真实密钥、完整运行日志、`.runtime` 证据目录或生成向量库。
- [ ] 如果要写进 PR 或发布说明，只写类似：`offline retrieval: passed; mixed-corpus safety: passed, safety_pass_rate=1.0; rag_vector_store: configured; acceptance preflight: passed (dry-run); live smoke: not run`。
