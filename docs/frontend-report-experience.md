# 前端报告体验与导出验证

模块 H 的前端目标是把 `report_data` 当作报告主契约，而不是从助手自然语言正文里猜结构。当前前端在存在结构化数据时会优先渲染：

- 规划模式标签：自由规划 / 旅行社顾问方案。
- 预算置信度：已确认 / 可追溯、规则估算、待核验。
- 待核验清单和不支持承诺。
- 方案依据与模式依据。
- 产品与报价规则：`agency_product`、`quote_policy` 继续保留估算报价、不锁价、不承诺库存的边界。
- 每日行程与 `map_routes` 的路线草图联动。
- 审批治理边界：`tool_audit_summary.approval` 或 `evidence_bundle.approval_governance` 会渲染为“审批治理与不可承诺项”，明确订单号或报告导出不代表真实支付、真实预订、真实锁价或履约成功。

导出的 HTML（超文本标记语言）报告会克隆当前结构化报告节点，因此会保留这些章节；导出时会移除按钮、地图切换控件等交互元素。

## 单页治理台

第三批前端在 `frontend/zhixing.html` 中新增右侧治理台，不引入大型前端框架，仍然复用现有静态单页结构。

治理台当前展示：

- `/health/ready` 的 ready check（就绪检查）摘要，区分 `ready`、`degraded` 和 `not_ready`，并展示 Checkpointer（执行检查点）、Store（长期存储）、MCP（模型上下文协议）、会话锁和审批治理状态。
- 审批记录和审批事件，支持查看当前用户记录；审批操作者或管理员账号可由后端权限决定是否能批准、拒绝或手动过期。
- “演示审批”入口只创建未来真实支付的占位审批记录，不接真实支付网关，不生成支付链接。
- 工具审计安全摘要，只展示工具名、状态、耗时、重试次数和证据类型。
- SSE（服务器发送事件）轮次观测摘要，只展示脱敏指标，不展示 PII（个人可识别信息）、密钥、完整工具输入或完整工具输出。

治理台是演示与排查入口，不改变聊天、报告渲染、地图预览和导出主链路；服务为 `degraded` 时允许继续演示核心链路，服务为 `not_ready` 时仍阻止登录、聊天和审批动作。

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

- 打开 `frontend/zhixing.html`。
- 跑自由规划和旅行社顾问方案各一轮最终报告。
- 检查报告第一屏规划模式标签、预算置信度、待核验清单、每日路线草图。
- 点击“导出报告”，打开导出的 HTML 文件，确认预算置信度和待核验章节仍在。

本次模块 H 自审还额外生成了 `.runtime/frontend-report-preview.html` 预览页，并用 Chrome headless（无界面浏览器模式）截图检查桌面和移动宽度。截图产物位于 `.runtime/`，属于本地临时验证文件，不纳入提交。
