# 2026-06-03 阶段性变更说明

本文用于汇总本轮围绕前台模块化、后台管理、安全收口和完整复测的阶段性成果，便于留档、交接和后续继续开发。

## 本轮目标

本轮的核心目标不是继续堆新功能，而是把项目从“单页原型堆叠”推进到“边界清晰、可验证、可维护”的阶段状态：

- 前台主链路按请求、交互、渲染职责拆分。
- 后台管理从前台治理角落升级成独立管理台。
- 安全基线补到可上线前的基本门槛。
- 用自动化脚本对主链路做完整复测。

## 前台完成情况

前台主链路已按职责拆成以下模块：

- `frontend/session-api.js`
- `frontend/conversation-api.js`
- `frontend/journey-api.js`
- `frontend/journey-editor.js`
- `frontend/journey-overlay.js`
- `frontend/map-controls.js`
- `frontend/journey-text-utils.js`
- `frontend/journey-map-data.js`
- `frontend/journey-map-view.js`
- `frontend/journey-map-focus.js`
- `frontend/journey-map-shell.js`
- `frontend/journey-poi-utils.js`
- `frontend/journey-poi-renderer.js`
- `frontend/report-budget.js`
- `frontend/report-renderer.js`
- `frontend/report-export.js`
- `frontend/report-actions.js`
- `frontend/governance-api.js`
- `frontend/governance-tools.js`
- `frontend/governance-progress.js`
- `frontend/governance-renderer.js`

当前 `frontend/app.js` 的职责已明显收缩，主要保留：

- 全局状态
- 页面初始化
- 模块接线
- 基础工具函数

页面加载顺序和报告渲染校验依赖已在以下位置维护：

- `frontend/zhixing.html`
- `scripts/verify_frontend_report_renderer.js`

相关维护说明已补充到：

- `docs/前端与演示/frontend-report-experience.md`

## 后台完成情况

后台已从单页治理区升级为独立管理台，核心文件包括：

- `app/api/v1/admin.py`
- `frontend/admin.html`
- `frontend/admin.js`
- `frontend/admin-api.js`

当前后台已具备：

- 概览、用户、会话、审批列表
- 搜索与筛选
- 用户详情、会话详情、审批事件联动
- 后台直接审批处理
- 待处理审批快捷视图

## 安全完成情况

本轮已完成一轮安全基线收口，核心包括：

- 生产/预发环境禁止占位 JWT 密钥
- CORS（跨域资源共享）改为白名单
- 登录态改为 `HttpOnly Cookie`
- 前台去掉 `localStorage` 持久化 token
- 登录限流与安全响应头补齐

相关核心文件：

- `app/config.py`
- `app/main.py`
- `app/api/v1/users.py`

## 本轮验证结果

本轮已通过以下完整验证：

```powershell
py -3 -m compileall app tests scripts
py -3 -m pytest -q tests\test_api_auth_security.py tests\test_api_admin_dashboard.py
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
node scripts\verify_admin_dashboard_browser.js
```

验证结论：

- Python 语法编译通过
- 关键安全与后台测试 `10 passed`
- 前台报告渲染回归通过
- 前台桌面 / 移动浏览器回归通过
- 后台管理台浏览器回归通过

## 当前项目状态判断

当前项目已经从“功能能跑，但耦合很重”进入到“主链路边界基本成型”的阶段。尤其是前台，后续再做性能优化、局部重构、故障排查时，成本会比之前明显下降。

仍需注意的现实情况：

- 还没有做一次更大范围的全量 pytest（单元测试框架）回归。
- 还没有接入真实支付、真实库存、真实履约，这一点依然是明确边界，不应对外夸大。
- 前台虽然已模块化，但不是构建化项目，后续新增模块时仍要严格维护脚本加载顺序。

## 下一步建议

建议优先顺序如下：

1. 暂停继续高频拆核心代码，避免进入“为了拆而拆”。
2. 如果进入交付阶段，优先使用本文和前端文档做阶段留档。
3. 如果继续工程推进，优先做一次更大范围测试，确认没有隐藏回归。
4. 如果继续前台演进，优先做性能和体验问题，而不是继续切碎现有模块。
