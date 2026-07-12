# Travel Multimodal Data Source Plan（旅行多模态数据来源计划）

本文给 RAG（检索增强生成）和多模态演示补强建立可复跑、可审计、可公开说明的数据来源边界。它不是采集脚本，也不保存原始大规模数据；正式落地前必须逐项检查许可、归因、数据量、更新频率和隐私风险。

## 1. 目标

M1 数据补强只解决三件事：

- 让目的地知识更像真实旅行顾问资料，而不是少量手写样例。
- 让图片、POI（兴趣点）和文本能形成可追溯证据链。
- 让评测能复跑，并明确 `passed` / `blocked` 的真实含义。

M1 不做以下承诺：

- 不抓取小红书、携程、马蜂窝、公众号、旅游社群等版权或平台条款不清晰内容进入公开仓库。
- 不把公开攻略直接改写成“真实库存、真实锁价、真实订单或供应商确认”。
- 不把大规模原始图片、OSM（OpenStreetMap，开放街图）导出库或下载缓存提交到 Git。

## 2. 候选数据源矩阵

当前可进入 M1 审查的数据源统一登记在 `data/documents/source_registry.json`。新增来源前必须先更新 registry，再运行 `scripts/check_travel_data_sources.py`。本文中的公开许可边界参考了 Wikivoyage 的 CC BY-SA 4.0 许可说明、OpenStreetMap 的 ODbL（开放数据库许可）说明、Natural Earth 的 public domain（公有领域）说明和 GeoNames 的 CC BY（署名）说明。

| 来源 | 可用内容 | 适合用途 | 许可/边界 | M1 建议 |
|---|---|---|---|---|
| [Wikivoyage API](https://enterprise.wikimedia.com/project-data/wikivoyage-api/) / [Wikivoyage reuse guide](https://en.wikivoyage.org/wiki/Wikivoyage:How_to_re-use_Wikivoyage_guides) | 城市旅行指南、地区介绍、交通、景点、注意事项 | 目的地概览、季节风险、路线背景材料 | 文本按 CC BY-SA 4.0 复用；需要保留许可和归因；衍生内容需注意 share-alike（相同方式共享） | P0：优先选 5-10 个城市做小规模归因样例 |
| [Wikimedia Commons](https://commons.wikimedia.org/wiki/Main_Page) / [Structured data](https://commons.wikimedia.org/wiki/Commons:Structured_data) | 景点图片、作者、许可、坐标和结构化元数据 | 多模态卡片、景点图像检索样例、报告图片归因 | 文件许可以每个文件描述页为准；结构化数据 CC0；非结构化文本通常 CC BY-SA；必须记录作者、许可和来源页 | P1：只选少量有清晰许可的图片，不热链、不批量下载 |
| [OpenStreetMap tourism key](https://wiki.openstreetmap.org/wiki/Key:tourism) + [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) | 景点、博物馆、住宿、游客信息、坐标、标签 | POI 元数据、路线节点、地图候选、地理过滤 | OSM 数据采用 ODbL（开放数据库许可）；需要归因，派生数据库要注意 share-alike；公共 Overpass 服务有使用限制 | P0：只做按城市小范围查询和元数据缓存 |
| [OpenStreetMap copyright](https://www.openstreetmap.org/copyright) | OSM 归因和许可说明 | 前端地图与数据来源说明 | 需要标注 OpenStreetMap contributors，不能把 OSM 数据包装成自有闭源数据库 | P0：前端和导出报告保留来源说明 |
| [Google Landmarks Dataset v2](https://github.com/cvdfoundation/google-landmark) / [CVPR 2020 paper page](https://openaccess.thecvf.com/content_CVPR_2020/html/Weyand_Google_Landmarks_Dataset_v2_-_A_Large-Scale_Benchmark_for_Instance-Level_CVPR_2020_paper.html) | 约 500 万 landmark 图片、识别/检索标签 | 离线图像检索 benchmark（基准测试）、多模态召回实验 | 数据规模大，图片来源和使用边界要逐项核验；不适合作为 M1 默认业务数据 | P2：只作为离线研究或模型评测候选，不进入默认发布包 |

## 3. M1 最小数据集设计

建议先做小规模、可解释、可验收的公开样例：

| 数据包 | 内容 | 落地位置 | 验收 |
|---|---|---|---|
| `public_destination_guides` | 5-10 个城市的 Wikivoyage 摘要、来源 URL、许可、更新时间 | `data/documents/destinations/` 下的人工整理 Markdown | 每篇有 `source_url`、`license`、`attribution` |
| `public_poi_metadata` | OSM/Overpass 小范围 tourism POI：名称、坐标、类型、来源 | 后续可放 `data/documents/pois/` 或 generated data，不直接提交大导出 | 每条有 `source=OpenStreetMap` 和查询范围 |
| `public_image_cards` | Wikimedia Commons 少量景点图片元数据：文件页、作者、许可、缩略图 URL | 建议先做 metadata 文档，不提交原图 | 每张图许可可追踪，导出报告能显示归因 |
| `rag_eval_scenarios` | 覆盖城市概览、亲子/老人、雨天 Plan B、交通提醒、图片/POI 组合问题 | `data/evaluation/` | `evaluate_rag_retrieval.py --json` 能区分 passed / blocked |

原始下载缓存、临时 API 响应和大文件都应放在 `.runtime/` 或服务器 generated data 目录；不进入 Git。

## 4. 采集与清洗规则

1. 先记录来源和许可，再清洗正文。
2. 每条材料保留 `source_url`、`source_name`、`license`、`attribution`、`retrieved_at`、`visibility`。
3. 图片只保存元数据和可验证来源；是否下载缩略图另行审批。
4. OSM 数据只做小范围、低频查询；避免把公共 Overpass 当生产高频在线依赖。
5. 不混入个人游记、平台帖子、评论区、酒店真实订单、供应商底价或用户聊天记录。
6. 多模态评测只证明“候选能召回和归因”，不证明景点开放、票价、库存或服务履约。

## 5. 验收命令

当前默认验收：

```powershell
uv run python scripts\check_travel_data_sources.py
uv run python scripts\evaluate_rag_retrieval.py --json
uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
uv run python scripts\check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e
```

需要扩充公开数据时，先生成私有候选包，不直接写入 `data/documents/`：

```powershell
uv run python scripts\collect_public_travel_data_candidates.py --city xian
uv run python scripts\collect_public_travel_data_candidates.py --city xian --city hangzhou --output-dir <private-workdir>\public-travel-candidates --execute
uv run python scripts\review_public_travel_data_candidates.py --candidate-json <private-workdir>\public-travel-candidates\public-travel-data-candidates.json
uv run python scripts\review_public_travel_data_candidates.py --candidate-json <private-workdir>\public-travel-candidates\public-travel-data-candidates.json --review-json <private-workdir>\public-travel-candidate-review.json --output-dir <private-workdir>\approved-public-travel-candidates --execute
```

`collect_public_travel_data_candidates.py` 默认只输出计划，不联网、不写文件。显式 `--execute` 后会调用 Wikivoyage、Overpass / OpenStreetMap 和 Wikimedia Commons 的公开接口，生成 `public-travel-data-candidates.json` 与 `README.md`，并默认阻止写入 Git 工作区。候选项全部标记 `review_required=true`、`commit_ready=false`，人工确认许可、归因、内容质量和演示边界后，才可以整理成小规模 Markdown / metadata 样例。

`review_public_travel_data_candidates.py` 只读取私有候选包和人工 review JSON，不联网、不下载、不构建向量库。没有 review JSON 时只返回 `ready_for_review`；只有显式批准且 `license_reviewed`、`attribution_reviewed`、`content_quality_reviewed`、`boundary_reviewed` 全部为 `true` 的候选，才会在私有目录生成 `approved-public-travel-candidates.json` 和 `destination-guides/` 草稿。草稿仍需最后人工检查后才可复制进 `data/documents/`。

数据源落地后再补：

```powershell
uv run python scripts\check_rag_multimodal_readiness.py --json
uv run python scripts\accept_rag_multimodal_e2e.py --json
```

通过标准：

- `passed` 只表示当前公开样例、当前索引和当前场景通过。
- `check_travel_data_sources.py` 的 `passed` 只表示 registry 和目的地 Markdown 已声明来源、许可、归因和演示边界；它不下载数据、不证明事实新鲜度。
- `collect_public_travel_data_candidates.py` 的 `passed` 只表示候选摘要已写入私有目录；它不等于候选可直接进仓库，也不证明事实新鲜度、图片版权复核完成或线上检索通过。
- `review_public_travel_data_candidates.py` 的 `passed` 只表示人工审查条件齐备、批准候选已被 staging；它不证明最终入库、向量库重建、召回评测或线上 RAG 通过。
- `blocked` 表示缺数据、缺真实向量库、许可归因缺失、混合库安全失败或运行前置不足。
- 不把离线评测通过写成真实线上 Agent 通过。

## 6. 公开展示口径

可以说：

> 数据层采用公开许可旅行文本、开放地图 POI 和少量可归因图片元数据，重点证明 RAG 证据链和多模态检索思路。

不能说：

> 系统拥有真实旅行社库存、全网攻略数据库、真实图片版权库或实时景区/酒店/机票确认能力。

## 7. 后续任务

| 优先级 | 任务 | 输出 |
|---|---|---|
| P0 | 选定 5-10 个城市，整理 Wikivoyage + OSM 小样本 | Markdown 文档、来源元数据、召回场景 |
| P0 | 为现有 `data/documents/destinations/` 增加来源和许可字段 | 文档 front matter 或统一元数据表 |
| P1 | 增加 Wikimedia Commons 图片元数据卡片 | `public_image_cards` 样例和前端展示边界 |
| P1 | 扩展 RAG mixed-corpus safety 场景 | 防止内部材料、未授权材料和公开材料混淆 |
| P2 | 评估 GLDv2 是否只用于离线视觉检索实验 | 单独实验计划，不进 M1 发布包 |
