# report_data 结构化交付契约与前端验证边界

本文说明前端如何消费 `report_data`、导出 HTML 报告及验证交付结果，补充 `docs/前端与演示/frontend-report-experience.md` 中的字段与展示约定。

## 结论

`report_data` 是最终旅行报告的主交付契约，前端、导出、评估与演示共用其结构和字段。

演示与回归覆盖：

- 后端可以把规划结果整理为结构化报告数据。
- 前端可以识别结构化来源并渲染为报告卡片、每日行程、预算明细、路线预览和风险提醒。
- 导出的 HTML 报告会保留结构化来源、报告正文、待核验项和交付边界。
- 验证脚本可以用脱敏 fixture 复跑报告渲染和浏览器导出。

报告用于方案展示与转发。支付、预订、出票、通知和履约尚未接入；库存、价格、天气、票务及排队等动态信息保留核验状态。

## 交付契约

`report_data` 面向前端时应承担三件事：

- 报告结构：`overview`、`itinerary`、`budget_breakdown`、`map_routes`、`route_map`、`risks` 等字段用于稳定渲染。
- 核验边界：交通、住宿、门票、天气、库存、价格和路线距离/时长等动态信息必须保留待核验语义。
- 来源说明：标明脱敏样例、工具结果与估算规则。

前端展示的结构化报告根节点应保留 `data-report-source="structured"`。这个标记是浏览器回归和导出验证判断“当前报告来自结构化 `report_data`”的关键证据。

## 前端消费路径

公开演示链路按以下路径理解：

1. 后端对话链路生成最终报告时，把 `report_data` 放进助手消息的额外信息里。
2. 前端收到或加载历史消息后，把 `reportData` 传给 `renderAssistantText`。
3. `frontend/report-renderer.js` 优先渲染结构化报告，并在报告节点上标记 `data-report-source="structured"`。
4. `frontend/report-data-view-model.js`、`frontend/report-data-panels.js`、`frontend/report-data-itinerary.js` 等模块把预算、行程、路线、风险和交付状态拆成用户可读卡片。
5. `frontend/report-actions.js` 提供复制交付摘要、定位路线地图和导出报告入口。
6. `frontend/report-export.js` 克隆当前报告节点，生成可离线查看的 HTML 报告。

前端从结构化字段生成报告视图，文本渲染用于兼容缺少结构化数据的回复。

## 导出 HTML 边界

HTML 导出是前端当前报告视图的静态快照。导出时应满足：

- 保留 `data-report-source="structured"`，让导出件仍能证明来源是结构化 `report_data`。
- 在正文前增加“报告交付摘要”，说明来源、导出时间、关键要素、核心内容和待核验项。
- 移除按钮、地图切换、复制与导出控件，生成静态文件。
- 保留报告用途和待核验说明。

导出件是当前报告视图的静态快照，用于演示、方案转发与回归记录。

## 脱敏 fixture

报告前端验证默认读取：

- `tests/fixtures/report_data/agency_plan_desensitized.json`
- `tests/fixtures/report_data/free_planning_desensitized.json`

fixture 使用模拟身份、路线、预算与订单，供渲染和导出回归复用。

如果必须新增 fixture，应放在 `tests/fixtures/report_data/`，并继续满足：

- 使用模拟路线、模拟预算和公开可展示的地点信息。
- 明确样例来源、估算与待核验项。
- 不依赖 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/` 或 `data/vectorstore_internal/`。

## 验收命令

轻量结构化渲染验证：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
node scripts\verify_frontend_report_renderer.js
```

真实浏览器 E2E 回归：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
node scripts\verify_frontend_browser_regression.js
```

浏览器脚本依赖 Playwright 和 Chromium。本地缺少依赖时脚本会明确 skip；在 `CI=true` 或 `ZHIXING_FRONTEND_BROWSER_STRICT=1` 时，缺依赖应作为失败处理。

## 公开口径

报告、前端展示与导出围绕同一份 `report_data` 验证，记录结构、预算来源、待核验项与静态导出结果。动态服务在出行或成交前按报告清单复核。
