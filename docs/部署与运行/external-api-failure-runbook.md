# External API Failure Runbook（外部 API 故障手册）

本文定义 ZhiXing Travel Planner 在 M1 受控试运行中遇到外部 API（应用程序接口）故障时的发现、分级、降级、修复和证据记录方式。目标是让系统在供应商不可用、密钥异常、配额耗尽或超时时保持诚实可控，而不是编造真实航班、酒店、地图、价格或库存。

## 1. 适用范围

| 能力 | 典型变量 | M1 要求 | 用户影响 |
|---|---|---|---|
| LLM（大语言模型） | `DASHSCOPE_API_KEY` | 必需 | 主对话、RAG 摘要、报告生成不可用或严重降级 |
| 地图 / 高德 | `AMAP_API_KEY`、`AMAP_WEB_JS_KEY` | 后端高德必需，前端 key 按需 | 地理编码、地图预览、部分天气和路线展示降级 |
| 搜索 / Tavily | `TAVILY_API_KEY` | 可选 | 外部攻略和实时资料补充降级 |
| 航班 / VariFlight | `VARIFLIGHT_API_KEY` | 可选，按验收场景升级 | 航班候选只能标记待核验 |
| 酒店 / aigohotel | `AIGOHOTEL_API_KEY`、`AIGOHOTEL_MCP_API`、`AIGOHOTEL_SECRET_KEY` | 可选，按验收场景升级 | 酒店候选只能标记待核验 |
| 铁路 / 12306 MCP | 由 MCP 服务配置决定 | 可选，按验收场景升级 | 高铁候选只能标记待核验 |
| LangSmith（LangChain 可观测平台） | `LANGSMITH_API_KEY`、`LANGSMITH_TRACING` | 可选 | 排障 trace（链路追踪）能力降级，不直接影响用户 |

## 2. 故障分级

| 等级 | 判定 | M1 处理 |
|---|---|---|
| S0 阻断 | LLM、PostgreSQL、Redis、Auth/JWT 或生产必需地图能力不可用，导致主链路无法可靠服务 | 暂停试运行或保持 `blocked`，不要对外声明通过 |
| S1 关键降级 | 航班、酒店、铁路、搜索等被当前验收场景声明为必需，但密钥、配额或服务不可用 | 该验收场景 `blocked`，其他不依赖场景可继续 |
| S2 可接受降级 | 可选外部服务失败，但核心规划、报告和待核验提示仍可工作 | 写 `degraded`，保留降级说明和后续修复项 |
| S3 观测降级 | LangSmith 或非必需 trace 不可用 | 不阻断试运行，但要记录排障能力下降 |

## 3. 发现信号

优先看以下无密钥证据：

```sh
docker compose ps
curl -fsS http://127.0.0.1:8000/health/ready
docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json
docker compose exec -T backend python scripts/check_runtime_readiness.py --target acceptance --check-backend --base-url "$ZHIXING_PUBLIC_BASE_URL" --json
docker compose exec -T backend python scripts/check_external_api_readiness.py --json
```

典型信号：

| 信号 | 可能原因 | 处理方向 |
|---|---|---|
| `401` / `403` | 密钥错误、签名错误、权限未开通、IP 白名单不匹配 | 检查密钥系统、供应商控制台和访问来源 |
| `429` | 配额耗尽、限流、突发请求过高 | 降低并发、缩小验收场景、申请配额或更换测试窗口 |
| `5xx` | 供应商故障或网络链路异常 | 进入降级，记录供应商状态和重试窗口 |
| timeout | 网络不稳、供应商响应慢、超时配置过短 | 检查超时预算、重试退避和服务健康 |
| `blocked` | readiness 判断必需依赖缺失 | 按 `repair_suggestions` 修复后复跑 |
| `degraded` | 可选能力缺失或不可探测 | 确认是否影响本次验收场景 |

不要通过打印 `.env`、复制完整请求头、复制 token 或粘贴密钥来排查。

## 4. 通用处理流程

1. 确认故障范围：只影响单个工具、单个供应商，还是影响主对话链路。
2. 确认是否必需：看当前 target、验收场景和 `readiness` 输出里的 requirement。
3. 先降级再修复：对可选能力先改为待核验，不阻塞无关链路。
4. 修复配置：只在密钥系统、服务器 `.env` 或 CI secrets 中更新真实值。
5. 复跑验收：至少复跑 readiness；影响用户链路时复跑 acceptance smoke。
6. 记录证据：只保存脱敏摘要、状态、错误类别、影响范围和下一步动作。

## 5. 各能力降级策略

| 能力 | 失败时用户可见口径 | 系统处理 | 复跑命令 |
|---|---|---|---|
| LLM | 当前智能规划服务暂不可用，稍后重试 | M1 直接 `blocked`，不生成伪报告 | `check_runtime_readiness.py --target production --json` |
| 高德地图 | 地图预览或路线距离暂待核验 | 保留文字行程，地图/距离字段标记待核验 | `check_runtime_readiness.py --target production --json` |
| 搜索 | 实时外部资料暂不可用，使用已有知识库和待核验提示 | RAG 本地知识继续，搜索证据降级 | `run_evaluation_scenarios.py --acceptance-smoke --base-url ... --json` |
| 航班 | 航班候选需人工二次核验 | 不写真实余票、锁价、出票承诺 | 当前航班验收场景 |
| 酒店 | 酒店价格和库存需人工二次核验 | 不写确认房态、锁价、预订成功 | 当前酒店验收场景 |
| 铁路 | 高铁班次需人工二次核验 | 不写真实余票或出票状态 | 当前铁路验收场景 |
| LangSmith | trace 暂不可用，使用本地日志和工具审计 | 不阻断用户链路 | 检查观测配置和日志 |

## 6. 修复检查清单

| 问题类型 | 检查项 |
|---|---|
| 密钥错误 | 变量名是否正确、是否仍是 placeholder（占位值）、是否写入目标容器、供应商权限是否开通 |
| 白名单错误 | 服务器出口 IP、域名、Referer、浏览器 key 限制是否和供应商控制台一致 |
| 配额问题 | 单日额度、QPS（每秒查询数）、并发限制、账单状态和告警阈值是否清楚 |
| 网络问题 | DNS（域名解析）、TLS、代理、防火墙、供应商状态页和跨区域访问是否异常 |
| 超时问题 | 应用超时、MCP 启动超时、供应商响应时间和重试退避是否匹配 |
| 数据可信问题 | 返回数据是否过期、字段是否缺失、是否需要人工核验 |

## 7. 需要用户准备的信息

沟通时只发状态，不发密钥值：

| 字段 | 示例 |
|---|---|
| `enabled_services` | DashScope：必需；高德：必需；Tavily：可选；航班：暂不启用；酒店：暂不启用 |
| `quota_budget` | LLM 每日预算、地图每日调用上限、搜索/航班/酒店测试额度 |
| `provider_console_owner` | 谁能登录供应商控制台处理配额、白名单和账单 |
| `support_channel` | 供应商工单、客服电话、内部负责人 |
| `allowed_degradation` | 搜索可降级，航班/酒店必须待核验，支付/预订保持禁用 |
| `incident_window` | 计划测试时段，避免在密钥未开通或供应商维护期误测 |

## 8. 发布前外部 API 门禁

发布候选阶段先跑声明检查：

```powershell
uv run python scripts\check_external_api_readiness.py --json
```

目标环境内也可以执行同一脚本：

```sh
docker compose exec -T backend python scripts/check_external_api_readiness.py --json
```

该脚本不读取 `.env`，不读取真实密钥，也不调用供应商。它只证明必需供应商 ready flag、可选服务状态、配额预算、控制台负责人、支持渠道、降级策略和 timeout/retry 策略已经声明。真实密钥是否有效、供应商是否能从目标服务器访问、配额是否实际生效，仍必须通过 `check_runtime_readiness.py`、acceptance smoke 和供应商控制台脱敏摘要确认。

外部依赖韧性记录用于把 readiness、成本预算、工具失败率、超时重试和降级演练收束到同一份私有 JSON。先生成模板，再把 `check_external_api_readiness.py`、`check_cost_alert_status.py`、`check_tool_failure_monitor_status.py` 的脱敏结果和人工降级演练结论填入私有目录：

```powershell
uv run python scripts\check_external_dependency_resilience_record.py --template --output <private-workdir>\external-dependency-resilience-record.local.json
uv run python scripts\check_external_dependency_resilience_record.py --record-json <private-workdir>\external-dependency-resilience-record.local.json --output <private-workdir>\external-dependency-resilience-report.json
```

该校验器不读取 `.env`、不调用供应商、不连 SSH（安全外壳协议）、不启动服务，也不会打印真实 URL、IP、密钥或供应商响应正文。它会阻断以下情况：超时/重试未设上限、成本预算缺负责人或超过阈值、工具失败监控 blocked、降级演练编造真实库存/锁价/预订、记录中含原始 URL/IP/密钥形态，或把 M1 证据夸大成供应商 SLA（服务等级协议）、强配额、完整生产高可用或长期压测证明。

当前 M1 已形成一份外部依赖韧性补充证据：外部 API readiness、成本预算 guard、工具失败监控、timeout / retry 上限，以及 provider timeout、provider rate limit 429、provider 5xx 三类降级场景均已通过校验。该证据是受控试运行级别，证明系统有“降级、人工核验、待确认、不编造库存/锁价/预订”的处理口径；它仍不证明供应商 SLA、真实配额强约束、所有可选供应商已启用、完整生产高可用或长期稳定性。

## 9. 证据记录模板

```text
Incident ID:
Time window:
Environment: staging | production
Affected service: LLM | AMap | Tavily | VariFlight | aigohotel | 12306 MCP | LangSmith
Severity: S0 | S1 | S2 | S3
User impact:
Detection source: readiness | health/ready | acceptance | user report | provider notice
Safe summary:
Action taken:
Current status: blocked | degraded | recovered | monitoring
Commands rerun:
- ...
Follow-up:
- ...
```

不得记录真实密钥、完整请求头、Cookie、完整 token、真实客户资料、订单号或供应商内部报价。

## 10. 恢复判定

只有满足以下条件，才能把外部 API 故障标记为恢复：

- 相关密钥、配额、网络或供应商状态已确认恢复。
- `health/ready` 不再把该能力列为阻断项。
- 受影响的 readiness 或 acceptance 场景已经复跑。
- 报告里不再把过期故障误写成当前事实。
- 脱敏事故记录已更新，剩余风险明确。

如果只是关闭可选能力绕过故障，结论应写 `degraded`，不能写 `passed`。
