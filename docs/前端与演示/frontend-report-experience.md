# 前端报告体验与导出验证

模块 H 的前端目标是把 `report_data` 当作报告主契约，而不是从助手自然语言正文里猜结构。当前前端在存在结构化数据时会优先渲染：

- 规划模式标签：个性化旅游规划 / 省心方案。
- 预算置信度：已确认 / 可追溯、规则估算、待核验。
- 待核验清单和不支持承诺。
- 方案依据与模式依据。
- 产品与报价规则：`agency_product`、`quote_policy` 继续保留估算报价、不锁价、不承诺库存的边界。
- 预算明细：按交通、住宿、餐饮、景点/体验、服务/预留、其他六类表格展示；不会默认展示“每人/人均”，除非未来结构明确声明金额口径为人均。
- 每日行程与 `map_routes`、可选 `route_map.days` 的路线草图联动；`route_map.days` 会保留 Day 编号、路线点、景点/体验/商业街区/美食等类型标签和简短说明。
- Day 级补齐边界：前端不再渲染“待补齐当天安排”这类占位日；结构化数据缺日时展示空状态或追问，避免把未规划内容伪装成正式安排。
- 人工确认边界：`tool_audit_summary.approval` 或 `evidence_bundle.approval_governance` 会渲染为“人工确认与不可承诺项”，明确订单号或报告导出不代表真实支付、真实预订、真实锁价或履约成功。
- 省心方案报告优先使用结构化卡片展示成熟路线、交通口径、住宿区域/档次与示例酒店、门票参考、餐饮、费用说明、涵盖服务和待核验项；Markdown（标记文本）表格只作为兜底，不作为主展示结构。

## 意图分流与进度台

普通用户前台只展示能理解的计划进度，不展示内部过程词：

- “意图分流”：用户尚未选择省心方案或个性化旅游规划时的初始阶段。
- “基础需求 / 匹配方案 / 方案草案 / 方案确认 / 报告生成”：省心方案 `agency_step` 阶段。
- “需求收集 / 目的地推荐 / 交通规划 / 住宿规划 / 餐饮规划 / 行程生成 / 预算汇总 / 报告生成”：个性化旅游规划 `current_step` 阶段。

右侧进度台展示：

- 当前阶段。
- 方案类型：待确认 / 省心方案 / 个性化旅游规划。
- 已确认信息：出发地、目的地、出发时间、人数、天数、预算口径等具体事实。
- 偏好记录：优先展示长期记忆中提取的稳定偏好；没有稳定偏好时展示本次已确认的风格、餐饮、住宿或特殊需求，避免显示“暂无稳定偏好”造成用户误解。
- 人工确认边界：说明当前不会自动支付、发短信或下单。

“已使用服务”从顶部信息块移到四个能力小卡片下方，默认展开、可折叠。每条服务同时展示用户可理解服务名和原始工具名，例如“产品模板检索 · search_agency_product_templates”，便于验收和排查。

## 省心方案前台展示边界

省心方案在需求收集阶段不要过早展示单项低价值预算，例如只有餐饮 600-700 元时，不渲染成“当前估算”大卡片，避免用户误以为已经形成完整报价。

省心方案卡片排版原则：

- 出发地、目的地、住宿商圈、门票参考等卡片尽量使用整行或均衡网格，不让右侧大片留白。
- 产品化方案中交通和住宿是“口径说明”，不是自由规划式逐项选择。
- 费用卡标题统一用“费用说明”，并要求按大交通、住宿、门票/体验、当地交通、餐饮和服务/机动拆分；如果只识别到总价，前端会提示预算分项待补齐。
- “涵盖服务”单独成卡，承接接送、预约、应急、人工确认和不包含项边界。
- 用户选择省心方案后，右侧方案类型必须同轮切到“省心方案”。
- 用户补日期、人数、预算等基础事实时，优先更新进度台已确认信息，不让用户重复输入首轮已给内容。
- 进度台事实合并采用“本轮最新用户事实优先”规则；例如用户新说“6月10日出发”，前端会先乐观更新出发日期，后端 SSE（服务器发送事件）进度快照也会用最新解析结果覆盖旧 `report_data` 或弱工具观测，避免显示历史日期。

## 圆周旅迹级旅程工作台

在最终报告前，前端可以消费 `journey_plan.v1` 草案和 `planning_trace`（规划过程轨迹）：

- `planning_trace` 渲染为可折叠“规划过程”，展示搜索公开攻略、收集地点、查天气、计算路线和编排每日行程等可审计进度；它不是模型内部推理。
- `journey_plan.v1` 渲染为可视化旅程工作台：路线地图、分日路线折叠面板、POI（兴趣点/地点）hover 名称、待核验项和后续交通/酒店/预算衔接提示；普通用户视图不再弹出底部 POI 详情卡。
- 地图预览 API（应用程序接口）会优先返回 `amap-js`（高德地图 JavaScript SDK，软件开发工具包）提供者；未配置公开浏览器 Key 时，前端继续使用 Leaflet（交互地图前端库）/ OSM（OpenStreetMap，开放街图）降级。
- 地图层默认展示每日路线叠加总览；路线预览顶部不再展示主路线/交通/住宿/日程节奏摘要卡，侧栏也不展示住宿周边、沿途看点或下一步提示，只保留“展开路线说明”和其中默认折叠的“分日路线”。展开分日路线后只显示少量地点和“路线参考”按钮。点击某个 Day 后，大图突出当天真实路线，其余天路线变淡；后端会把可用的高德路线折线传给前端，前端优先按真实路线折线连接当天点位，不再在每日行程卡或分日列表里渲染小地图。
- 全屏地图的 Day Tab（日期切换标签）由“行程天数 + 每日行程 + 地图路线层”合并生成；即使某天暂时没有成功地理编码，也保留 Day N 并展示“路线待核验”状态，不因为缺路线层而隐藏中间日期。
- 地图预览会保留可用点位并连接相邻有效点位；单个 POI（兴趣点）定位失败时只跳过该点，不删除整天路线，也不影响其他已定位景点之间的连线展示。
- 没有结构化点位时不请求真实地图，只显示“行程路线 / 路线总览”和清晰空状态；有点位时再请求 `/api/v1/maps/preview`。
- 前端地图请求需要有短超时和可读降级态；如果地图 180 秒仍未完成定位，会记录降级，UI 仍保留地图框架、路线说明和可继续查看的文字方案。
- 任意目的地会先生成可地理编码的通用种子点；高德地点搜索命中后可以把种子点替换为真实 POI 名称，并同步路线段起终点名称。
- `.env.example` 只放 `AMAP_WEB_JS_KEY` 占位符；真实 Web Key 放本地或部署环境变量，不写入仓库。
- 旅程草案不等于最终报告，不绕过出发城市、出发日期、交通、住宿、完整每日行程和预算门禁。

当前第一阶段不包含圆周旅迹式多人协作、打卡社区、完整攻略导入和分享页。这些功能需要独立的用户关系、内容审核、分享权限和导入解析链路，建议放到后续产品化阶段。

导出的 HTML（超文本标记语言）报告会克隆当前结构化报告节点，因此会保留这些章节；导出时会移除按钮、地图切换控件等交互元素。地图定位入口只保留在整份报告、住宿周边和景点路线等适合地图的位置；每日行程卡保持纯文字节奏，不再嵌入小地图，交通卡和预算卡也不显示地图按钮。

## 单页治理台

第三批前端在 `frontend/zhixing.html` 中新增右侧治理台，不引入大型前端框架，仍然复用现有静态单页结构。

治理台当前展示：

- `/health/ready` 的 ready check（就绪检查）摘要会转译成人话：可用能力、外部服务、人工确认边界和待关注项，不直接展示 `production`、持久化等工程词。
- 人工确认记录和事件，支持查看当前用户记录；当前不会真实下单，未来接入真实支付、短信通知或客户资料导出时才需要人工确认。
- “演示记录”入口只创建未来真实支付的占位记录，不接真实支付网关，不生成支付链接。
- 工具审计安全摘要只展示工具名、展示语义、耗时、重试次数和证据类型；展示语义统一为成功、需核验、未查到、参数不足、服务异常、已跳过。
- SSE（服务器发送事件）轮次观测摘要只展示脱敏指标，不展示 PII（个人可识别信息）、密钥、完整工具输入或完整工具输出；追踪码只作为弱化的排查信息展示。

治理台是演示与排查入口，不改变聊天、报告渲染、地图预览和导出主链路；服务为 `degraded` 时允许继续演示核心链路，服务为 `not_ready` 时仍阻止登录、聊天和人工确认动作。

## 本地验证

前端无工程化构建步骤，静态语法和结构化渲染可以用：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_visual_journey_browser.js
```

浏览器验证建议：

- 轻量静态回归继续运行 `node scripts\verify_frontend_report_renderer.js`，用于确认 `renderAssistantText` 对结构化 `report_data` 的 HTML 输出仍包含关键章节。
- 报告渲染会按标题、类型和正文做卡片去重；同一轮正文与结构化数据都包含“预算拆分与依据”时只保留一份。包含“下一步 / 请评价 / 满意 / 想调整”的内容会从普通卡片网格剥离，固定渲染在报告底部的独立确认区。
- 旅程工作台浏览器回归运行 `node scripts\verify_frontend_visual_journey_browser.js`，覆盖桌面和移动视口下的可视化旅程、地图推荐点、分日路线折叠、路线标签密度、POI 底部详情卡不展示和移动端地图截图。
- 也可以使用统一的 npm（Node.js 包管理器，Node.js 是 JavaScript 运行时）入口：`npm run verify:frontend-renderer`、`npm run verify:frontend-visual-journey`、`npm run verify:frontend-browser`，或一次性运行 `npm run verify:frontend`。
- 轻量静态回归和真实浏览器 E2E（端到端）回归都读取 `tests/fixtures/report_data/` 下的脱敏 fixture（固定测试数据），不依赖真实 `.env`、真实用户、真实订单、真实支付或真实外部库存。
- 真实浏览器 E2E 回归运行 `node scripts\verify_frontend_browser_regression.js`。脚本使用 Playwright（浏览器自动化测试框架）启动 Chromium（谷歌开源浏览器内核）无头浏览器，分别覆盖 `1440x1000` 桌面视口和 `390x900` 移动视口。
- 浏览器脚本会加载真实 `frontend/zhixing.html`，模拟 ready check（就绪检查）成功、会话列表和人工确认数据，验证登录入口、主界面、治理台人话说明、工具审计展示语义、运行摘要、报告卡片、预算、风险、待核验清单、地图预览入口和报告导出。导出校验会读取浏览器下载的 HTML，确认结构化报告章节被保留，并确认导出件不保留交互按钮。
- 脚本会收集 console error（控制台错误）和页面异常；如果缺少 Playwright 或 Chromium，会明确输出安装命令。本地默认标记为 skip（跳过），`CI=true` 或 `ZHIXING_FRONTEND_BROWSER_STRICT=1` 时会失败退出，避免关键门禁被静默跳过。
- 截图产物输出到 `.runtime/`，当前包括 `frontend-browser-regression-desktop.png`、`frontend-browser-regression-desktop-report.png`、`frontend-browser-regression-mobile.png`、`frontend-browser-regression-mobile-report.png`、`frontend-browser-regression-mobile-governance.png`、`frontend-visual-journey-desktop.png`、`frontend-visual-journey-mobile.png` 和 `frontend-visual-journey-mobile-map.png`，属于本地临时验证文件，不纳入提交。

首次运行前如果本机没有依赖，可执行：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
npm install
npm run prepare:frontend-browser
```

`npm run prepare:frontend-browser` 等价于 `npx playwright install chromium`。在 GitHub Actions（GitHub 自动化流水线）中使用 `npx playwright install --with-deps chromium`，同时安装 Linux（操作系统内核）运行 Chromium 所需的系统依赖。

如果只想让缺失浏览器依赖在本地也直接失败，可设置 `ZHIXING_FRONTEND_BROWSER_STRICT=1` 后再运行浏览器脚本。
