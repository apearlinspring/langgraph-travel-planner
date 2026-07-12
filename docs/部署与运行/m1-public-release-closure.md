# M1 Public Release Closure（公开发布收口）

本文说明 M1 受控试运行材料在进入公开仓库前的收口边界。它不记录真实服务器地址、真实域名、SSH（安全外壳协议）用户、`.env`、探针账号、日志、数据库备份、向量库或私有证据路径。

## 目标

M1 公开发布收口要证明三件事：

- 公开仓库包含可复跑的部署脚本、验收脚本、runbook（运行手册）和模板。
- 私有线上证据、真实坐标和密钥不进入 Git。
- 公开口径必须绑定证据日期和适用版本：只有当前候选重新通过证据链时才能声明 `controlled-trial ready`（受控试运行就绪）；否则只能写“历史目标版本曾就绪，当前版本待复验”。任何情况下都不声明完整生产就绪、高并发压测完成或真实支付/预订/锁价/履约打通。

## 收口检查

执行：

```powershell
uv run python scripts\check_m1_public_release_closure.py --json
uv run python scripts\check_m1_public_release_closure.py --markdown
```

该检查器只读取公开仓库文件，不读取 `.env`、`.runtime/`、`.venv/`、日志、备份、向量库或私有证据目录；不连接网络、不连接 SSH、不启动服务、不删除文件。

它会检查：

| 检查项 | 说明 |
|---|---|
| `public_release_boundary` | 复用公开边界扫描，阻断 `.env`、运行时目录、真实 secret 或疑似 API Key |
| `required_public_docs` | 确认部署、运行、备份、监控、事故响应、安全发布、M1 状态和验收模板存在 |
| `required_public_scripts` | 确认 M1 gate、go/no-go、私有 workflow、signoff、证据矩阵、chat 探针、并发/限流、PostgreSQL/Redis、备份和安全脚本存在 |
| `claim_boundary` | 确认公开文档保留“不完整生产就绪、不真实支付、不高并发压测”的边界 |
| `public_coordinate_scan` | 阻断真实域名、真实服务器 IP、本机绝对路径、私有证据目录名和探针身份提示 |

## 通过后的含义

`status=passed` 只能说明公开仓库收口边界通过，可以进入 release candidate（发布候选）评审。它不证明：

- 当前服务器健康。
- 私有 M1 证据仍然存在或已经签核。
- chat 高并发、自动扩缩容或长时间 soak（浸泡测试）通过。
- 真实支付、真实预订、真实库存锁定、出票或履约已经打通。

真实上线证据仍以仓库外私有 evidence matrix（证据矩阵）、workflow-report、signoff、rollout record 和 operations review 为准。

## 发布前组合命令

公开版收口前建议至少跑：

```powershell
uv run python -m compileall app tests scripts
uv run python -m pytest tests\test_public_release_boundary.py tests\test_m1_public_release_closure.py -q
uv run python scripts\check_public_release_boundary.py --json
uv run python scripts\check_m1_public_release_closure.py --json
git diff --check
```

如果要生成公开 release artifact（发布包），还必须使用干净工作区执行 `scripts/build_release_artifact.py`。当前工作区存在未提交改动时，不应把临时状态写成正式公开发布完成。
