# M1 Release Candidate Freeze（发布候选冻结）

本文定义 M1 受控试运行前的发布候选冻结规则。它解决的问题是：在真实服务器部署前，必须先确认当前工作区哪些改动属于本次发布，哪些要延期，不能把一团未整理的本地改动直接打包上传。

## 结论规则

| 状态 | 含义 |
|---|---|
| `passed` | Git 工作区干净，可以从当前 `HEAD` 生成发布包。 |
| `blocked` | 存在未提交改动、禁入路径或未归属路径，不能生成正式发布包。 |
| `not_frozen` | 当前只是候选整理阶段，还没有进入可打包状态。 |

生产发布包只能由干净 Git `HEAD` 生成。只要冻结检查仍是 `blocked`，`scripts/build_release_artifact.py --execute` 就不应进入正式打包步骤。

## 检查命令

```powershell
uv run python scripts\check_release_candidate_freeze.py --json
```

该脚本默认只读取 `git status --short --branch`，不读取 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/` 的文件内容，不启动服务，也不写文件。

准备公开发布候选时，建议追加公开收口门禁：

```powershell
uv run python scripts\check_release_candidate_freeze.py --check-public-closure --json
```

此模式会额外调用 `scripts/check_m1_public_release_closure.py`，检查公开文档、公开脚本、真实坐标泄露和越界承诺；仍然不读取 `.env`、运行时目录、私有证据目录，不连接网络或 SSH。

生成可填写的冻结决策记录：

```powershell
uv run python scripts\render_release_candidate_freeze_record.py --check-public-closure --markdown
```

如果希望先生成带建议方向和证据模板的草稿，可以追加 `--with-suggestions`。建议字段只用于辅助填写，不等于签核，也不能替代负责人确认：

```powershell
uv run python scripts\render_release_candidate_freeze_record.py --check-public-closure --with-suggestions --markdown
```

如果希望先生成一份“发布控制基线拟填写稿”，可以使用 `--draft-baseline-decisions`。它会把发布控制、工具安全、测试验收和项目文档方向预填为 `include`，把其他方向预填为 `defer`，但仍保留空 `signoff`，且进入候选的方向必须由 release owner 补充真实验证结果和签核：

```powershell
uv run python scripts\render_release_candidate_freeze_record.py --check-public-closure --draft-baseline-decisions --json --output .runtime\release-freeze-baseline-draft.json
```

该草稿会标记 `candidate_profile=m1_deployment_control_baseline`，目标是先冻结公开部署控制基线：`deployment_runtime`、`tool_security_governance`、`project_docs` 和 `test_validation`。RAG、前端、业务 API、状态架构和依赖配置默认先 `defer`，后续再进入单独候选。

正式暂存前，可以先渲染只读暂存计划：

```powershell
uv run python scripts\render_release_candidate_stage_plan.py --record-json <filled-freeze-record.json> --markdown
```

该计划只输出应暂存的 `include` 路径、保持 defer 的路径和后续门禁命令，不执行 `git add`。

如需先保存机器检查结果，再从该结果生成记录：

```powershell
uv run python scripts\check_release_candidate_freeze.py --json > freeze.json
uv run python scripts\render_release_candidate_freeze_record.py --freeze-json freeze.json --output release-freeze-record.md
```

冻结记录填完后，用签核校验器检查所有进入候选的方向是否已经有决策、验证结果、验证证据摘要、风险结论和负责人签核：

```powershell
uv run python scripts\check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json
```

`--check-current-worktree` 只读取当前 `git status` 的路径和状态，不读取文件内容；它用于防止冻结记录生成后工作区又发生变化，导致旧签核记录误放行。

当冻结记录来自 `--check-public-closure` 的报告时，记录会带上 `public_release_closure_status`；签核校验器会阻断 `blocked` 或 `not_checked` 的公开收口状态。

提交前还必须校验暂存区只包含已签核为 `include` 的 workstream：

```powershell
uv run python scripts\check_release_candidate_stage_scope.py --record-json <filled-freeze-record.json> --json
```

该检查只读取 freeze record JSON 和 `git diff --cached --name-status` 的路径元数据，不读取文件内容、不 stage、不 commit。如果暂存区包含 `defer`、`remove`、未知路径或 `.env` / 运行时目录等禁入路径，会直接阻断。

## 分组口径

| Workstream | 典型范围 | 负责人 |
|---|---|---|
| `deployment_runtime` | `deploy/`、`docker-compose.yml`、部署脚本、M1 runbook、资源申请和验收收集器 | Coordinator / Deployment |
| `rag_evaluation` | `app/rag/`、`app/evaluation/`、`data/documents/`、`data/evaluation/`、RAG 文档和评测脚本 | RAG / Evaluation |
| `agent_state_architecture` | `app/core/`、`app/agents/handoffs/`、状态和流程文档 | Agent State / Architecture |
| `tool_security_governance` | `app/mcp_core/`、`app/tools/`、`app/utils/security.py`、治理与可观测文档 | Tool / Security |
| `report_frontend` | `app/reports/`、`frontend/`、前端与报告文档、前端回归脚本 | Report / Frontend |
| `business_api_runtime` | `app/api/`、`app/agency/`、`app/config.py`、业务 API 和运行配置 | Coordinator / Backend |
| `configuration_dependencies` | `pyproject.toml`、`requirements.txt`、`uv.lock`、CI 或迁移配置 | Coordinator / Runtime |
| `project_docs` | `README.md`、`docs/README.md`、项目总览和评估入口文档 | Coordinator / Docs |
| `test_validation` | 兜底测试和脚本改动 | Coordinator / QA |

未命中的路径会进入 `unknown_paths`。这类路径必须先人工归属或移出候选，否则冻结检查保持 `blocked`。

## 冻结步骤

1. 运行冻结检查，记录 `dirty_count`、`workstreams`、`unknown_paths` 和 `forbidden_paths`。
2. 生成冻结决策记录，对每个有改动的 workstream 做 include/defer/remove 决策：进入本次发布、拆到后续发布，或移出公开候选。
3. 针对每个 workstream 跑对应验证命令，并把结果写入验收记录或发布说明。
4. 运行签核校验器，确认所有进入候选的 workstream 都有 `decision`、`validation_status`、`validation_evidence`、`risk_status`、`remaining_risk` 和 `signoff`，并用 `--check-current-worktree` 确认记录仍匹配当前工作区。
5. 确认没有 `.env`、运行时目录、向量库、日志、数据库备份或本地私有资料进入候选。
6. 提交本次发布候选，让 `git status --short --branch` 只剩分支行。
7. 从干净 `HEAD` 运行发布包构建：

```powershell
uv run python scripts\build_release_artifact.py --execute --output-dir <release-output-dir> --json
```

## 推荐验证

冻结前至少执行：

```powershell
uv run python scripts\check_release_candidate_freeze.py --check-public-closure --json
uv run python scripts\render_release_candidate_freeze_record.py --check-public-closure --draft-baseline-decisions --markdown
uv run python scripts\check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json
uv run python scripts\render_release_candidate_stage_plan.py --record-json <filled-freeze-record.json> --markdown
uv run python scripts\check_release_candidate_stage_scope.py --record-json <filled-freeze-record.json> --json
uv run python scripts\check_public_release_boundary.py --json
uv run python scripts\check_m1_deployment_gate.py --json
git diff --check
uv run python -m compileall app tests scripts
uv run python -m pytest -q
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
```

RAG 方向有改动时额外执行：

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

部署方向有改动时额外执行：

```powershell
docker compose --env-file .env.example config --quiet
uv run python scripts\check_m1_first_deploy_dry_run.py --json
```

## 填写规则

- `Decision` 只能写 `include`、`defer` 或 `remove`。
- `Validation` 只能写 `passed`、`blocked`、`not_run` 或 `not_required`。
- 只要任一进入本次候选的 workstream 没有验收结果和验证证据摘要，不能生成正式发布包。
- `risk_status=low/accepted/mitigated` 时必须写 `remaining_risk`，不能只填一个风险状态。
- `--with-suggestions` 只生成建议方向和证据模板，不能直接当作 `decision` 或 `signoff`。
- `--draft-baseline-decisions` 只生成拟填写稿，不能替代真实验证结果、验证证据摘要和 release owner 签核。
- 签核记录必须和当前 Git 工作区的 `dirty_count`、workstream changed count 和路径列表一致；不一致时应重新生成记录或重新整理工作区。
- 暂存区必须通过 `scripts/check_release_candidate_stage_scope.py`，确保只提交已签核为 `include` 的路径。
- 冻结后必须重新运行 `scripts/check_release_candidate_freeze.py --check-public-closure --json`，直到 `status=passed`。

## 不能证明的事

冻结检查只证明发布候选整理状态，不证明以下事项：

- 代码审查已经完成。
- 发布包已经生成、上传或部署。
- 服务器 `.env`、密钥系统、数据库、Redis、RAG、外部 API、备份或监控已经可用。
- `deploy/first-deploy.sh --execute --start-services` 已经在服务器成功执行。
- health/readiness、acceptance smoke、备份恢复演练或 go/no-go 已通过。

这些必须在目标服务器和 M1 验收流程中另外取证。
