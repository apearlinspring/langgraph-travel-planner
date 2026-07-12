# report_data 结构化交付契约与前端验证边界

本文档用于公开说明知行前台如何消费 `report_data`（结构化报告数据）、如何导出 HTML（超文本标记语言）报告，以及当前演示能证明什么、不能承诺什么。它是 `docs/前端与演示/frontend-report-experience.md` 的交付契约补充，不替代后端报告模型或前端实现代码。

## 结论

`report_data` 是最终旅游报告的主交付契约。前端、导出、评估和演示都应优先围绕它验证，而不是从助手自然语言正文里猜结构。

当前公开演示可以证明：

- 后端可以把规划结果整理为结构化报告数据。
- 前端可以识别结构化来源并渲染为报告卡片、每日行程、预算明细、路线预览和风险提醒。
- 导出的 HTML 报告会保留结构化来源、报告正文、待核验项和交付边界。
- 验证脚本可以用脱敏 fixture（固定测试数据）复跑报告渲染和浏览器导出。

当前公开演示不能承诺：

- 不代表真实支付成功。
- 不代表真实预订、出票、短信通知或供应链下单成功。
- 不代表真实库存可用、价格锁定或履约完成。
- 不代表实时天气、门票、酒店、车票、航班、演出或排队状态已经最终确认。

## 交付契约

`report_data` 面向前端时应承担三件事：

- 报告结构：`overview`、`itinerary`、`budget_breakdown`、`map_routes`、`route_map`、`risks` 等字段用于稳定渲染，而不是让前端解析散文。
- 核验边界：交通、住宿、门票、天气、库存、价格和路线距离/时长等动态信息必须保留待核验语义。
- 演示边界：如果报告来自脱敏样例或估算规则，必须避免暗示真实客户、真实订单、真实支付、真实预订或真实锁价。

前端展示的结构化报告根节点应保留 `data-report-source="structured"`。这个标记是浏览器回归和导出验证判断“当前报告来自结构化 `report_data`”的关键证据。

## 前端消费路径

公开演示链路按以下路径理解：

1. 后端对话链路生成最终报告时，把 `report_data` 放进助手消息的额外信息里。
2. 前端收到或加载历史消息后，把 `reportData` 传给 `renderAssistantText`。
3. `frontend/report-renderer.js` 优先渲染结构化报告，并在报告节点上标记 `data-report-source="structured"`。
4. `frontend/report-data-view-model.js`、`frontend/report-data-panels.js`、`frontend/report-data-itinerary.js` 等模块把预算、行程、路线、风险和交付状态拆成用户可读卡片。
5. `frontend/report-actions.js` 提供复制交付摘要、定位路线地图和导出报告入口。
6. `frontend/report-export.js` 克隆当前报告节点，生成可离线查看的 HTML 报告。

这条路径强调“结构化报告驱动前端”，不是“前端从聊天文本里临时猜测报告格式”。

## 导出 HTML 边界

HTML 导出是前端当前报告视图的静态快照。导出时应满足：

- 保留 `data-report-source="structured"`，让导出件仍能证明来源是结构化 `report_data`。
- 在正文前增加“报告交付摘要”，说明来源、导出时间、关键要素、核心内容和待核验项。
- 删除按钮、地图切换、复制、导出等交互控件，避免离线文件看起来还能发起真实操作。
- 保留“导出不代表真实支付、预订、出票、锁价或履约完成”的边界文案。
- 不请求真实支付网关，不创建真实订单，不调用真实供应链下单。

导出文件适合用于项目演示、方案转发和回归证据，不适合作为交易凭证、订单凭证或履约凭证。

## 脱敏 fixture

报告前端验证默认读取：

- `tests/fixtures/report_data/agency_plan_desensitized.json`
- `tests/fixtures/report_data/free_planning_desensitized.json`

这些 fixture 只能包含脱敏演示数据。不得写入真实姓名、手机号、证件号、订单号、支付信息、内部客户资料、真实密钥或本机敏感路径。

如果必须新增 fixture，应放在 `tests/fixtures/report_data/`，并继续满足：

- 使用模拟路线、模拟预算和公开可展示的地点信息。
- 明确写出待核验项和不可承诺边界。
- 不依赖 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/` 或 `data/vectorstore_internal/`。

## 验收命令

轻量结构化渲染验证：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
node scripts\verify_frontend_report_renderer.js
```

真实浏览器 E2E（端到端）回归：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
node scripts\verify_frontend_browser_regression.js
```

浏览器脚本依赖 Playwright（浏览器自动化测试框架）和 Chromium（谷歌开源浏览器内核）。本地缺少依赖时脚本会明确 skip（跳过）；在 `CI=true` 或 `ZHIXING_FRONTEND_BROWSER_STRICT=1` 时，缺依赖应作为失败处理。

## 公开口径

对外介绍时推荐这样说：

> 知行的最终交付不是一段聊天散文，而是结构化 `report_data`。前端、导出和验收脚本都围绕这个契约复跑，因此可以证明报告结构、预算边界、待核验项和导出结果是可检查的。但当前公开演示不接真实支付、真实预订、真实库存或真实锁价，所有动态服务仍需出发前或成交前人工确认。

避免这样说：

- “系统已经完成支付/预订/出票。”
- “这个价格已经锁定。”
- “库存一定可用。”
- “导出报告就是订单或合同。”
- “所有交通、酒店、天气和门票状态都是实时确认结果。”
