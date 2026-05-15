# Demo Script（演示脚本）

这份脚本用于项目展示现场按时间顺序讲解。推荐总时长 20 到 35 分钟；如果时间短，只讲路径一和核心架构；如果有真实环境，再走 acceptance-smoke（验收烟测）和前端报告。

## 开场 2 分钟

说法：

> 我演示的是一个旅行社智能顾问 Agent（智能体），不是普通 RAG（检索增强生成）问答。它用状态机推进旅行规划，用多 Agent 编排目的地和交通能力，用 MCP（模型上下文协议）接外部工具，用 HITL（人类在环）管理敏感动作，最后输出结构化 `report_data`（结构化报告数据），让评估和前端都能复用。

马上打开：

- `docs/project-demo-pack.md`
- `docs/project-capability-map.md`
- `app/core/state.py`
- `app/agents/handoffs/step_config.py`
- `app/tools/state_transition.py`

讲清楚边界：

- 不接真实支付。
- 不承诺真实库存或锁价。
- 外部查询失败必须待核验。
- 没有真实环境时不宣称 acceptance-smoke 通过。

## 路径一：本地纯讲解路径

适用时间：5 到 10 分钟。

依赖：不需要真实密钥，不需要后端启动。

命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python scripts\build_project_demo_pack.py --output .runtime\project-demo-pack
.\.venv\Scripts\python -m pytest tests\test_project_demo_pack.py -q
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run
```

讲解顺序：

1. 打开 `.runtime\project-demo-pack\manifest.json`。
2. 指出 `reads_env_files=false`、`copies_runtime_snapshots=false`、三条 `demo_paths`。
3. 打开 `redaction-check.txt`，说明演示包只保存脱敏材料。
4. 打开 `docs/project-capability-map.md`，用表格回答“为什么不是普通 RAG”。
5. 打开 `scripts\run_evaluation_scenarios.py --acceptance-smoke --dry-run` 输出，说明真实链路入口存在，但 dry-run 不调用后端。

推荐说法：

> 本地路径证明的是工程结构和复跑入口，不证明真实外部服务可用。它适合没有密钥的项目展示环境：我可以展示状态机、工具白名单、报告契约、验收场景和安全生成目录。

如果命令失败：

- 如果 `.venv` 不存在，说明当前机器没有安装项目依赖；可改用 `uv run --frozen python -m pytest tests\test_project_demo_pack.py -q`。
- 如果 dry-run 因依赖缺失失败，只展示 `docs/project-capability-map.md` 和代码定位，不把它说成验收通过。

## 路径二：acceptance-smoke 真实链路

适用时间：8 到 15 分钟。

依赖：

- `.env` 已配置真实 LLM（大语言模型）和外部 API（应用程序接口）。
- PostgreSQL（关系型数据库）和 Redis（内存数据结构存储）可用。
- 后端从当前工作树启动。

命令：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python main.py
```

另一个终端：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
```

讲解顺序：

1. 先讲 preflight（预检）：真实依赖不足时应该 blocked（环境阻塞），不能假通过。
2. 再讲 smoke（烟测）场景：当前最小场景覆盖旅行社报价解释。
3. 打开生成的摘要路径，但只展示脱敏摘要，不复制 `.runtime` 原始内容到提交。
4. 指出质量门禁维度：报告质量、RAG 质量、工具质量、运行预算、预算置信度、内部证据和工具审计。

推荐说法：

> acceptance-smoke 的目标不是跑很多场景，而是证明真实后端、真实模型、真实工具链可以闭环到 `report_data`。如果环境不满足，它必须明确 blocked；这比用 mock 数据假装通过更重要。

如果命令返回 degraded（降级）：

- 说明核心链路可运行，但部分 MCP、运行预算 warning（警告）或可选依赖有风险。
- 现场可以继续讲降级原因，但不要把 degraded 说成 passed（通过）。

如果命令返回 blocked：

- 展示 `missing_required` 或 preflight 失败项。
- 说明本项目把环境缺失当作验收不可判定，而不是业务通过。

## 路径三：前端报告可视化

适用时间：5 到 10 分钟。

依赖：后端已启动，并且至少有一次对话能生成最终 `report_data`。

命令：

```powershell
node scripts\verify_frontend_report_renderer.js
```

现场操作：

1. 打开 `frontend\zhixing.html`。
2. 登录或注册测试用户。
3. 创建会话。
4. 输入省心方案需求，例如：“我想从上海出发，找一个适合情侣的西安 3 天旅行社省心方案，预算舒适一点，帮我解释费用包含和待核验项。”
5. 等待最终报告。
6. 展示报告卡片：
   - 规划模式。
   - 每日行程。
   - 地图路线。
   - 预算置信度。
   - 待核验清单。
   - 不支持承诺。
   - 导出按钮。

推荐说法：

> 前端不是对助手自然语言做脆弱正则解析，而是优先消费后端输出的结构化 `report_data`。这让同一份结果可以被前端展示、导出、评估和审计复用。

如果前端没有最终报告：

- 回到后端聊天链路，确认 SSE（服务器发送事件）里是否出现 `report_data` 事件。
- 打开 `app/api/v1/chat.py`，说明保存助手消息时会把 `report_data` 写入 `extra_info`。
- 不要手写一个假报告冒充真实链路结果。

## 代码走读路线

按这个顺序打开文件：

1. `app/main.py`：应用入口和生命周期。
2. `app/api/v1/chat.py`：流式聊天和 `report_data` 事件。
3. `app/core/state.py`：`TravelState`。
4. `app/agents/handoffs/travel_agent.py`：主控 Agent 创建。
5. `app/agents/handoffs/step_config.py`：阶段 prompt 和工具配置。
6. `app/core/middleware.py`：动态注入 prompt、工具、记忆和意图。
7. `app/tools/state_transition.py`：状态迁移工具。
8. `app/tools/hotel_query.py`、`app/tools/transport_query.py`：真实查询和兜底。
9. `app/reports/builder.py`：最终报告契约。
10. `app/evaluation/acceptance_gate.py`：验收门禁。

## 常见追问速答

| 追问 | 30 秒回答 |
|---|---|
| Agent 和 workflow（工作流）怎么取舍？ | 旅行规划有明确阶段，所以用 workflow 控制阶段和状态；每个阶段内部保留 Agent 推理和工具选择弹性。 |
| 为什么要 `report_data`？ | 自然语言不可稳定评估和渲染；`report_data` 是后端、评估、前端导出的共同契约。 |
| 工具失败会不会影响体验？ | 会降级，但不能编造。失败进入待核验项，报告继续交付可执行方案。 |
| 怎么防止泄露密钥？ | `.env` 不提交，`.runtime` 原始产物不提交，生成演示包会扫描常见手机号、邮箱、JWT、Bearer token（持有者令牌）和赋值型密钥。 |
| CI/CD（持续集成/持续交付） 怎么讲？ | 默认 CI 跑本地回归和前端检查；真实 smoke 由手动 workflow_dispatch 触发，并使用 GitHub Secrets（GitHub 密钥管理项）。 |
| 目前最大短板是什么？ | 还没有真实供应链、支付和生产级分布式观测；这些需要在 HITL、权限、审计和供应链契约完备后再接。 |

## 结束 1 分钟

收束说法：

> 这个项目的亮点不是“模型会写旅游攻略”，而是把旅行社顾问流程工程化：阶段状态、工具边界、证据来源、结构化交付、前端消费、运行观测和验收门禁都在同一条链路里。它也明确承认当前不能做真实支付、锁价和履约，这些边界是 Agent 工程里非常关键的一部分。
