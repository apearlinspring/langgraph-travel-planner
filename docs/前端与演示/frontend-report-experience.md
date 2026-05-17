# 前端报告体验与导出验证

模块 H 的前端目标是把 `report_data` 当作报告主契约，而不是从助手自然语言正文里猜结构。当前前端在存在结构化数据时会优先渲染：

- 规划模式标签：自由规划 / 旅行社顾问方案。
- 预算置信度：已确认 / 可追溯、规则估算、待核验。
- 待核验清单和不支持承诺。
- 方案依据与模式依据。
- 产品与报价规则：`agency_product`、`quote_policy` 继续保留估算报价、不锁价、不承诺库存的边界。
- 预算明细：按交通、住宿、餐饮、景点/体验、服务/预留、其他六类表格展示；不会默认展示“每人/人均”，除非未来结构明确声明金额口径为人均。
- 每日行程与 `map_routes`、可选 `route_map.days` 的路线草图联动；`route_map.days` 会保留 Day 编号、路线点、景点/体验/商业街区/美食等类型标签和简短说明。
- Day 级补齐：当前端发现结构化数据里有 Day 2/Day 3 但缺 Day 1 或末日时，会按总天数补出“待补齐当天安排”卡片，避免导出件漏天。
- 人工确认边界：`tool_audit_summary.approval` 或 `evidence_bundle.approval_governance` 会渲染为“人工确认与不可承诺项”，明确订单号或报告导出不代表真实支付、真实预订、真实锁价或履约成功。

导出的 HTML（超文本标记语言）报告会克隆当前结构化报告节点，因此会保留这些章节；导出时会移除按钮、地图切换控件等交互元素。地图定位入口只保留在整份报告、住宿周边、景点路线和分日路线等适合地图的位置，交通卡和预算卡不显示地图按钮。

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
```

浏览器验证建议：

- 轻量静态回归继续运行 `node scripts\verify_frontend_report_renderer.js`，用于确认 `renderAssistantText` 对结构化 `report_data` 的 HTML 输出仍包含关键章节。
- 也可以使用统一的 npm（Node.js 包管理器，Node.js 是 JavaScript 运行时）入口：`npm run verify:frontend-renderer`、`npm run verify:frontend-browser`，或一次性运行 `npm run verify:frontend`。
- 轻量静态回归和真实浏览器 E2E（端到端）回归都读取 `tests/fixtures/report_data/` 下的脱敏 fixture（固定测试数据），不依赖真实 `.env`、真实用户、真实订单、真实支付或真实外部库存。
- 真实浏览器 E2E 回归运行 `node scripts\verify_frontend_browser_regression.js`。脚本使用 Playwright（浏览器自动化测试框架）启动 Chromium（谷歌开源浏览器内核）无头浏览器，分别覆盖 `1440x1000` 桌面视口和 `390x900` 移动视口。
- 浏览器脚本会加载真实 `frontend/zhixing.html`，模拟 ready check（就绪检查）成功、会话列表和人工确认数据，验证登录入口、主界面、治理台人话说明、工具审计展示语义、运行摘要、报告卡片、预算、风险、待核验清单、地图预览入口和报告导出。导出校验会读取浏览器下载的 HTML，确认结构化报告章节被保留，并确认导出件不保留交互按钮。
- 脚本会收集 console error（控制台错误）和页面异常；如果缺少 Playwright 或 Chromium，会明确输出安装命令。本地默认标记为 skip（跳过），`CI=true` 或 `ZHIXING_FRONTEND_BROWSER_STRICT=1` 时会失败退出，避免关键门禁被静默跳过。
- 截图产物输出到 `.runtime/`，当前包括 `frontend-browser-regression-desktop.png`、`frontend-browser-regression-desktop-report.png`、`frontend-browser-regression-mobile.png`、`frontend-browser-regression-mobile-report.png` 和 `frontend-browser-regression-mobile-governance.png`，属于本地临时验证文件，不纳入提交。

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
