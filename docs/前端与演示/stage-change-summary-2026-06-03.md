# 2026-06-03 阶段性变更说明

本文用于汇总本轮围绕前台模块化、后台管理、安全收口和完整复测的阶段性成果，便于留档、交接和后续继续开发。

> 本文是 2026-06-03 的日期化阶段快照，不是当前架构或安全状态的权威说明。后续代码已经继续演化，引用“已完成”结论前必须对照当前源码、测试和 `docs/前端与演示/frontend-report-experience.md` 重新核验。

## 本轮目标

本轮的核心目标不是继续堆新功能，而是把项目从“单页原型堆叠”推进到“开始按职责拆分、可验证、可继续维护”的阶段状态：

- 前台主链路按请求、交互、渲染职责拆分。
- 后台管理从前台治理角落升级成独立管理台。
- 完成一轮阶段性安全改进，但不把它表述为公开上线安全闭环。
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

本轮已经从 `frontend/app.js` 拆出一批请求、交互和渲染模块，但主文件仍接近 7000 行，并未收缩成纯接线层。它除以下目标职责外，仍保留大量地图、治理、认证、会话和渲染遗留逻辑：

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

本轮完成的是一轮阶段性安全改进，不等价于生产安全或公开上线防护闭环。主要改动包括：

- 生产/预发环境禁止占位 JWT 密钥
- CORS（跨域资源共享）改为白名单
- 登录接口设置 `HttpOnly Cookie`，同时仍在响应 JSON 中返回 `access_token`，前端以进程内 Bearer token（持有者令牌）兼容调用；因此不能表述为 JavaScript 完全不可访问登录令牌
- 前台去掉 `localStorage` 持久化 token，刷新后优先通过 Cookie 恢复会话
- 增加登录失败限流和部分安全响应头；CSP（内容安全策略）仍是 Report-Only（仅报告不拦截）

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

本轮建立了第一批模块边界和自动化回归入口，但没有消除主文件巨石问题。前台部分职责已经可独立维护，`app.js` 和全局样式仍需要继续按高收益边界收敛。

仍需注意的现实情况：

- 还没有做一次更大范围的全量 pytest（单元测试框架）回归。
- 还没有接入真实支付、真实库存、真实履约，这一点依然是明确边界，不应对外夸大。
- 前台虽然已模块化，但不是构建化项目，后续新增模块时仍要严格维护脚本加载顺序。
- `app.js` 仍包含大量遗留交互与渲染逻辑，不能把“已拆出模块”写成“模块化重构已完成”。

## 下一步建议

建议优先顺序如下：

1. 暂停继续高频拆核心代码，避免进入“为了拆而拆”。
2. 如果进入交付阶段，优先使用本文和前端文档做阶段留档。
3. 如果继续工程推进，优先做一次更大范围测试，确认没有隐藏回归。
4. 如果继续前台演进，优先做性能和体验问题，而不是继续切碎现有模块。
