# Deployment Readiness（部署就绪）

本文面向上线前检查，和 `docs/runtime-environment.md` 的 Runtime Config Readiness（运行配置就绪）契约保持一致。

## 上线前必须满足

1. `APP_ENV=production`，并确认 `.env` 或部署密钥系统没有使用 `your-*`、`change-me`、`test-key`、`dummy` 等占位值。
2. PostgreSQL（关系型数据库）可连接，业务表、LangGraph（图式智能体编排框架）Checkpointer（执行检查点）、Store（长期存储）和审批治理表已初始化。
3. Redis（内存数据结构存储）可连接，`SESSION_LOCK_BACKEND=auto` 或 `redis` 时不能降级为本地锁。
4. LLM（大语言模型）密钥是真实值，模型 profile（用途档位）仍统一通过 `app/utils/llm_factory.py` 创建。
5. Auth（认证）/ JWT（JSON Web Token，令牌认证）必须设置真实 `JWT_SECRET_KEY`，不能使用默认开发密钥、空值或 placeholder（占位）值。
6. RAG（检索增强生成）向量库已初始化，默认路径为 `data/vectorstore`，并且能只读打开 `chroma.sqlite3` 元数据和 `RAG_COLLECTION_NAME` 对应 collection（集合）。
7. 地图能力的 `AMAP_API_KEY` 是真实值；酒店、航班、搜索等可选能力如果缺失，用户侧必须保留“待二次核实”边界。
8. 至少有一个审批操作者或管理员账号，用户对象 `role` 或 `preferences.role` 为 `approver` / `admin`，普通用户不能批准、拒绝或手动过期审批。
9. `/health/ready` 返回 `ready` 或经确认可接受的 `degraded`；生产发布不接受 `not_ready`。

## 推荐验证命令

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target production --json
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-core --preflight-only --json
.\.venv\Scripts\python -m pytest -q
```

如果本地后端已经启动，再增加：

```powershell
.\.venv\Scripts\python scripts\check_runtime_readiness.py --target acceptance --check-backend --base-url http://127.0.0.1:8000 --json
```

## 结论语义

- `passed（通过）`：必需配置和目标检查全部满足。
- `degraded（降级）`：核心依赖可用，但存在可选服务缺失、MCP（模型上下文协议）服务降级或开发态 Redis 本地降级。
- `blocked（环境阻塞）`：缺必需配置、真实验收密钥或核心服务，不允许宣称验收/部署通过。
- `skipped（跳过）`：没有可执行场景或预检只生成不可判定摘要。

## 安全边界

- `.env.example` 只保留变量名、默认值和说明，不写真实密钥。
- 验收摘要、测试快照和提交说明不能包含真实密钥或真实个人信息；验收 live snapshot（真实链路快照）写盘前会做递归脱敏。
- SSE（服务器发送事件）、工具审计、审批理由、审批备注和错误响应不得暴露手机号、邮箱、身份证号、API Key（应用程序接口密钥）、token（令牌）或 secret（密钥）。
- 酒店、航班、火车、地图等外部能力失败时，报告只能写待核验和兜底估算，不能编造真实库存、锁价、余位、支付或客服信息。
- 客户资料导出仍是未来敏感动作占位；当前 `export_customer_profile` 工具策略为禁用，不得导出真实客户画像文件。
