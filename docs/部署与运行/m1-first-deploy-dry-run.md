# M1 First Deploy Dry Run（首次部署预演）

本文用于在真正连接服务器、上传发布包或启动服务之前，先做一次安全 dry-run（预演）。它回答的问题是：本机是否具备打包/上传/部署的前置条件，目标服务器输入是否齐备，当前工作区是否适合生成发布包。

## 1. 安全边界

`scripts/check_m1_first_deploy_dry_run.py` 默认只做本地检查和命令计划：

- 不读取 `.env`。
- 不连接 SSH。
- 不执行 `scp` 上传。
- 不生成发布归档。
- 不启动 Docker 服务。
- 不回显服务器用户名、服务器地址、部署目录或公网 URL。

执行命令：

```powershell
uv run python scripts\check_m1_first_deploy_dry_run.py --json
```

当前工作区如果有未提交改动，脚本会输出 `status=blocked`。这是生产口径下的正确结果：不能从脏工作区直接创建生产发布包。

## 2. 需要的目标输入

这些值只作为本机环境变量或 CI secrets 存在，不写进公开文档：

| 变量 | 用途 |
|---|---|
| `ZHIXING_DEPLOY_USER` | SSH 部署用户 |
| `ZHIXING_DEPLOY_HOST` | SSH 目标服务器 |
| `ZHIXING_DEPLOY_DIR` | 服务器绝对部署目录 |
| `ZHIXING_PUBLIC_BASE_URL` | 公开 HTTPS 地址 |

脚本输出会把这些值替换成 `<ssh-user>`、`<server-host>`、`<deploy-dir>` 和 `<public-url>`。

## 3. Dry-run 检查项

| Section | 检查内容 | 阻塞含义 |
|---|---|---|
| `target_inputs` | 目标用户、主机、部署目录、公网 URL | 缺目标服务器输入，不能进入上传阶段 |
| `local_tools` | `git`、`ssh`、`scp`、`docker`、`docker compose` 是否可用 | 本机缺发布/部署工具 |
| `git_worktree` | `git status --short --branch` 是否干净 | 当前工作区不能生成生产发布包 |
| `compose_config` | `docker compose --env-file .env.example config --quiet` | Compose 模板不能渲染 |
| `public_release_boundary` | 公开发布边界扫描 | 候选发布物含禁止路径或敏感内容 |

## 4. 命令计划

dry-run 只输出计划，不执行远端动作。真正进入部署前，还需要人工确认，并把服务器侧脚本也先跑一遍 dry-run：

```text
python scripts/build_release_artifact.py --execute --output-dir <release-output-dir> --json
scp <temp-release-archive> <ssh-user>@<server-host>:/tmp/<release-archive>
scp <release-manifest> <ssh-user>@<server-host>:/tmp/<release-manifest>
scp deploy/first-deploy.sh <ssh-user>@<server-host>:/tmp/zhixing-first-deploy.sh
ssh <ssh-user>@<server-host> "sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>"
ssh <ssh-user>@<server-host> "sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>"
```

`scripts/build_release_artifact.py` 只从干净的 Git `HEAD` 构建发布包，并生成包含 commit、tree、tracked file count 和 archive `sha256` 的 manifest。`deploy/first-deploy.sh` 的默认模式仍然是 `dry_run`；提供 `--archive-sha256` 时会在服务器侧解压前校验上传包。只有显式追加 `--execute` 才会创建 release 目录、解压发布包、切换 `current` 符号链接并运行 Compose 配置检查；只有再追加 `--start-services` 才会执行 `docker compose up -d --build`。脚本会拒绝发布包中的 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`、日志和 `__pycache__`，并把向量库、日志和备份目录放到服务器 `shared/` 下，而不是跟随代码 release 被覆盖。

如果线上探测报告 `release_layout.layout_mode=legacy_flat`，说明目标服务器仍是旧平铺布局。此时不要直接把 `--start-services` 套到新 `shared/current` 结构上；先选择“兼容旧布局更新”或“迁移到 `shared/current` 布局”。迁移路线必须先在服务器侧准备 `<deploy-dir>/shared/.env` 和 `<deploy-dir>/shared/data`，且不打印 `.env` 内容、不删除原有向量库或 Docker 卷。若报告 `blocked_current_not_symlink`，先停下检查 `current` 路径，不能让发布脚本覆盖一个真实目录。

远端部署后继续执行：

```powershell
uv run python scripts\collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url <public-url> --json
```

## 5. 当前不能证明的事

dry-run 不能证明：

- SSH 认证已成功。
- 发布包已经上传或解压。
- 服务器 `.env` 或密钥系统已有真实有效值。
- 目标服务器 Docker 服务已经启动。
- 数据库迁移、RAG 初始化、备份、告警或 acceptance smoke 已经执行。
- 系统可以处理真实支付、预订、锁价、出票或履约。
