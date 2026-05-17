# MCP Health Readiness

本文说明 MCP（模型上下文协议）服务级健康检查与 acceptance-core（核心验收场景集）preflight（预检）的映射关系。文档只列环境变量名，不写真实密钥，也不把供应商返回结果作为静态证据。

## 状态语义

| 状态 | 含义 | 是否阻断核心服务 |
| --- | --- | --- |
| `healthy` | 服务配置可用；如果执行了 live probe（在线探测），工具加载成功。 | 否 |
| `degraded` | 可选服务已配置但凭据缺失、探测失败或尚未达到可用状态。相关功能必须诚实降级，不能编造实时价格、库存、路线或天气。 | 否 |
| `blocked` | 当前验收场景声明该 MCP 服务为必需，但服务缺真实凭据、未配置或后端 `/health/ready` 暴露为非 `healthy`。 | 阻断 acceptance-core |
| `skipped` | 可选服务未配置且当前核心运行或场景没有要求它。 | 否 |

核心后端 readiness（就绪性）里，MCP 服务池整体仍是 optional（可选）：单个 MCP 失败只能让 `/health/ready` 返回 `degraded`，不能拖垮 FastAPI（快速应用接口框架）核心服务。acceptance-core 不同：场景 `requirements.mcp_servers` 声明的服务在 preflight 中临时提升为 required（必需），不是 `healthy` 就必须 `blocked`。

## 服务映射

| MCP 服务 | 上游能力 | 核心运行时 | acceptance-core | 关键环境变量 |
| --- | --- | --- | --- | --- |
| `weather` | 高德天气 | optional | 场景声明后 required | `AMAP_API_KEY` |
| `search` | Tavily 搜索 | optional | 场景声明后 required | `TAVILY_API_KEY` |
| `amap` | 高德地图 MCP | optional | 场景声明后 required | `AMAP_API_KEY` |
| `12306-mcp` | 铁路查询 MCP | optional | 场景声明后 required | 无本地密钥变量；依赖远端服务可达 |
| `VariFlight-Aviation` | 航班查询 MCP | optional | 场景声明后 required | `VARIFLIGHT_API_KEY` |
| `aigohotel-mcp` | 酒店查询 MCP | optional，按需启动 | 场景声明后 required | `AIGOHOTEL_API_KEY`，兼容 `AIGOHOTEL_MCP_API` 或 `AIGOHOTEL_SECRET_KEY` |

`aigohotel-mcp` 没有任一酒店凭据时不会进入核心启动列表，服务表显示 `skipped`；如果 acceptance-core 场景声明它必需，同样状态会映射为 `blocked`。

## 健康输出

`MCPClientManager.get_status_snapshot()` 现在同时暴露两层信息：

- `servers`：连接层状态，保留 `healthy`、`unavailable`、`uninitialized` 等历史字段，用于排查工具加载和进程连接。
- `service_health`：服务级状态表，只使用 `healthy`、`degraded`、`blocked`、`skipped`，用于 readiness 和 preflight 判断。

`service_health` 中的每个服务只暴露环境变量名和脱敏状态，例如 `credentials=missing`，不会输出真实密钥。`service_status_counts` 汇总四类服务状态，方便脚本和看板直接判断。

## Preflight 映射

`run_acceptance_preflight()` 会合并选中场景的 `requirements`：

1. `requirements.mcp_servers` 进入 `required_mcp_servers`。
2. 这些 MCP 服务在 preflight 的 `mcp_services` 表里标记为 `required`。
3. 缺少真实上游凭据、服务未配置或 live `/health/ready` 中状态不是 `healthy` 时，`real_mcp` 或 `backend_ready` check 返回 `blocked`。
4. 未被选中场景要求的 MCP 服务只会显示为 `degraded` 或 `skipped`，不会让该次验收 blocked。

验收入口：

```powershell
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json --no-summary
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --json
```

供应链真实性原则保持不变：真实查询失败时，报告和工具输出必须写“待二次核实”或给兜底方案，不能伪造真实班次、酒店库存、价格、评分、开放状态或地图结果。
