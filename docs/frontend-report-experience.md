# 前端报告体验与导出验证

模块 H 的前端目标是把 `report_data` 当作报告主契约，而不是从助手自然语言正文里猜结构。当前前端在存在结构化数据时会优先渲染：

- 规划模式标签：自由规划 / 旅行社顾问方案。
- 预算置信度：已确认 / 可追溯、规则估算、待核验。
- 待核验清单和不支持承诺。
- 方案依据与模式依据。
- 每日行程与 `map_routes` 的路线草图联动。

导出的 HTML（超文本标记语言）报告会克隆当前结构化报告节点，因此会保留这些章节；导出时会移除按钮、地图切换控件等交互元素。

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

当前工作区未能安装浏览器自动化依赖，因此截图回归仍需在本地浏览器手动补验。
