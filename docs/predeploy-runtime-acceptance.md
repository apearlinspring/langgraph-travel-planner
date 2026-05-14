# Predeploy Runtime Acceptance（部署前运行时验收）

## 结论

- 状态：passed（通过）。
- 范围：部署前 readiness（就绪检查）和 `acceptance-smoke`（验收冒烟测试）最小链路。
- 日期：2026-05-14。
- 分支：`codex/predeploy-runtime-acceptance`。
- main 基线：从最新 `origin/main` 开始，本轮提交范围仅为脱敏文档、引用说明和核心报告恢复。
- core（核心验收）边界：本报告不能替代完整 9 场景 `acceptance-core`（核心验收）。完整 9/9 证据继续保留在 `docs/acceptance-core-report.md`。

本轮使用真实本机 `.env` 和真实本地依赖完成，但只记录变量名、状态和脱敏指标；未记录真实密钥、手机号、邮箱、JWT（JSON Web Token，令牌认证）或真实个人信息。

## Readiness 结果

| 检查项 | 结果 | 脱敏证据 |
|---|---:|---|
| RAG（检索增强生成）初始化 | passed（通过） | public collection（公开集合）18 个 embedding（嵌入向量）；internal collection（内部集合）61 个 embedding；metadata（元数据）契约通过 |
| staging readiness（预生产就绪检查） | ready | `check_runtime_readiness.py --target staging --json` 返回 `status=passed`、`readiness_status=ready` |
| 后端健康 | ready | 当前工作树后端 `/health/live=200`、`/health/ready=200` |
| PostgreSQL（关系型数据库） | ready | Checkpointer（执行检查点）和 Store（长期存储）初始化正常 |
| Redis（内存数据结构存储） | ready | 会话锁使用 Redis |
| MCP（模型上下文协议） | ready | 6 个服务 healthy，37 个 tools（工具） |
| LLM（大语言模型） | ready | `DASHSCOPE_API_KEY` 按真实值存在性校验通过，未输出密钥 |

本轮复跑时先发现 `8000` 端口存在旧工作树后端；已停止旧进程，再从当前工作树启动后端并复验 `/health/ready`。这一步避免了把其他本地工作树的 RAG（检索增强生成）路径误当成本分支证据。

## Smoke 结果

| 项目 | 值 |
|---|---:|
| 场景 | `pricing_agency_quote_explanation` |
| 状态 | passed（通过） |
| 场景数 | 1 / 1 |
| total elapsed（总耗时） | 395.967s |
| first token（首个文本令牌） | 58.040s |
| tool calls（工具调用） | 13 |
| tool failures（工具失败） | 7 |
| fallback（兜底） | 7 |
| estimated token（估算文本令牌） | 6189 |
| `report_data` | true |
| `evidence_closure.missing` | `[]` |
| runtime budget（运行预算） | passed（通过） |

smoke 中的工具失败和 fallback 计数代表外部能力或证据兜底被审计记录，并未触发确定性门禁失败；报告、预算、风险、待核验项、旅行社证据、工具审计和运行时门禁均通过。

## 本地原始证据

这些文件只保留在本机 `.runtime/`，不提交：

- `.runtime\readiness-staging.json`
- `.runtime\readiness-acceptance.json`
- `.runtime\acceptance-smoke\20260514-151605-acceptance-summary.json`
- `.runtime\acceptance-smoke\20260514-151605-acceptance-summary.md`

## 已运行验证

```powershell
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_runtime_readiness.py tests\test_acceptance_evidence_pack.py tests\test_evaluation_live_runner.py -q
.\.venv\Scripts\python -m pytest -q
git diff --check origin/main..HEAD
```

结果：

- `compileall`：退出码 `0`。
- 最小测试集：`61 passed`。
- 完整默认测试：`441 passed, 24 deselected`。
- diff check（差异格式检查）：通过。

## 发布前风险

- 本轮 smoke 1/1 passed 是部署前最小链路验收，不能替代主线已有 9 场景 acceptance-core（核心验收）。
- 生产发布前如果模型、RAG（检索增强生成）、MCP（模型上下文协议）、报告契约或外部 API（应用程序接口）配置变化，应重跑完整 acceptance-core。
- `.env`、`.runtime/`、`.venv/`、`data/vectorstore/` 和 `data/vectorstore_internal/` 不进入提交。
