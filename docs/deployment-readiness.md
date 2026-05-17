# Production Deployment Runbook（生产部署运行手册）

本文是更新线上服务的唯一部署入口。旧的多轮验收记录不再放在这里；历史证据继续保留在 `docs/acceptance-core-report.md`、`docs/predeploy-runtime-acceptance.md` 和 `docs/live-acceptance-runbook.md`。

## 当前生产环境

- 线上域名：`https://travel.403edr.cn`
- 公网 IP（互联网协议地址）：`8.145.46.253`
- SSH（安全外壳协议）用户：`root`
- 服务器代码目录：`/opt/langgraph-travel-planner`
- 容器入口：`docker-compose.yml`
- 快速更新脚本：`deploy/update-runtime-image.sh`
- 当前服务：`backend`、`caddy`、`postgres`、`redis`

SSH 主机指纹核验值：

```text
RSA     SHA256:gj2kqRfi7OMEufxE1Er0V84cIdU/0Ehk4BWK3oz1smc
ECDSA   SHA256:f+LO0DfognHXCUHanq5vA/69rO1bWD03TB4qRZHpW3w
ED25519 SHA256:F7jf3yJ4zU5C9YIqVlsUMKbQOpjJMQkHicF1T3wt+Ac
```

如果 SSH 提示 host key（主机密钥）变化，先用云控制台或可信渠道核验，不要直接绕过。

## 安全边界

- 只发布 Git（版本控制）已跟踪文件。
- 不上传、不打印、不提交 `.env`、`.runtime/`、`.venv/`、`data/vectorstore/`、`data/vectorstore_internal/`、真实密钥或个人信息。
- 不删除服务器上的数据库卷、向量库目录、`.env` 或运行时目录。
- PowerShell（Windows 命令行环境）远程命令统一启用 UTF-8（统一码转换格式）输出，并用单引号包裹远端命令，避免本地提前展开 `$()`。
- 生产更新默认只做健康检查和轻量 smoke（冒烟验证）；完整 `acceptance-core`（核心验收）只在明确需要时运行。

## 一键更新流程

以下命令在本地仓库根目录执行。每次新对话更新服务，都从这组命令开始。

### 1. 对齐主线并生成发布包

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null

git fetch origin --prune
git switch main
git pull --ff-only origin main
git status --short --branch

$commit = git rev-parse --short HEAD
$archive = Join-Path $env:TEMP "zhixing-release-$commit.tar"
git archive --format=tar -o $archive HEAD
Get-Item $archive
```

`git status --short --branch` 应显示 `## main...origin/main`，且没有未提交文件。若有用户或其他分支未提交改动，先停下来确认，不要回滚。

### 2. 上传发布包

```powershell
scp $archive root@8.145.46.253:/tmp/zhixing-release-$commit.tar
```

### 3. 备份旧代码并解包

```powershell
ssh root@8.145.46.253 'set -eu; cd /opt/langgraph-travel-planner; commit_file="$(ls -t /tmp/zhixing-release-*.tar | head -n 1)"; backup="/opt/zhixing-backup-$(date +%Y%m%d%H%M%S)"; mkdir -p "$backup"; cp -a AGENTS.md alembic alembic.ini app deploy docker-compose.yml Dockerfile .dockerignore docs .env.example frontend .github main.py package.json package-lock.json pyproject.toml .python-version README.md requirements.txt scripts tests uv.lock "$backup"/ 2>/dev/null || true; echo "backup=$backup"; tar -xf "$commit_file" -C /opt/langgraph-travel-planner; chmod +x deploy/update-runtime-image.sh; echo "release_extracted"'
```

这一步只覆盖代码和文档，不会删除服务器上的 `.env`、`.runtime/`、向量库或 Docker（容器运行工具）卷。

### 4. 刷新运行时镜像

```powershell
ssh root@8.145.46.253 'set -eu; cd /opt/langgraph-travel-planner; sh deploy/update-runtime-image.sh'
```

脚本会基于服务器现有 `langgraph-travel-planner-backend:latest` 镜像构建运行时叠加镜像，然后执行：

```sh
docker compose up -d --no-build backend caddy
docker compose ps
```

如果脚本提示 base image（基础镜像）不存在，说明服务器还没有可复用的后端镜像，需要先安排一次完整镜像构建窗口，不要删除现有数据库卷。

## 发布后验证

### 1. 容器与内部健康检查

```powershell
ssh root@8.145.46.253 'set -eu; cd /opt/langgraph-travel-planner; docker compose ps; curl -fsS http://127.0.0.1:8000/health/live; echo; curl -fsS http://127.0.0.1:8000/health/ready | head -c 3000; echo'
```

期望结果：

- `zhixing-backend` 状态为 `healthy`
- `zhixing-postgres` 状态为 `healthy`
- `zhixing-redis` 状态为 `healthy`
- `/health/live` 返回 `{"status":"alive"}`
- `/health/ready` 返回 `status=ready`，环境为 `production`

### 2. 公网健康检查

Windows 自带 `curl.exe` 可能因 Schannel（Windows 安全通道）与服务器 TLS（传输层安全协议）协商失败而误报。优先用 Python（脚本语言运行时）验证：

```powershell
@'
import json
import urllib.request

for url in [
    "https://travel.403edr.cn/",
    "https://travel.403edr.cn/docs",
    "https://travel.403edr.cn/health/live",
    "https://travel.403edr.cn/health/ready",
]:
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()
        print(url, resp.status, resp.headers.get("content-type"), len(data))
        if url.endswith("/health/live") or url.endswith("/health/ready"):
            payload = json.loads(data.decode("utf-8"))
            print("status=", payload.get("status"), "environment=", payload.get("environment"))
'@ | .\.venv\Scripts\python.exe -
```

期望结果：

- 根页面返回 `200 text/html`
- `/docs` 返回 `200 text/html`
- `/health/live` 返回 `status=alive`
- `/health/ready` 返回 `status=ready` 和 `environment=production`

### 3. 日志抽查

```powershell
ssh root@8.145.46.253 'set -eu; cd /opt/langgraph-travel-planner; docker compose logs --tail=120 backend; docker compose logs --tail=80 caddy'
```

允许出现第三方依赖 deprecation warning（弃用警告）。不应出现启动失败、数据库连接失败、MCP（模型上下文协议）全量不可用、密钥原文或异常堆栈刷屏。

## 可选 smoke

如果只是把已验收的 `main` 更新到服务器，健康检查通过即可。若本次改动涉及聊天链路、报告、RAG（检索增强生成）或 MCP，可额外执行轻量 smoke：

```powershell
ssh root@8.145.46.253 'set -eu; cd /opt/langgraph-travel-planner; docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json | head -c 4000; echo'
```

完整 9 场景 `acceptance-core` 会消耗真实 LLM（大语言模型）和外部 API（应用程序接口）预算，只有发布前需要重新证明核心验收时再运行。

## 常见问题

### SSH host key 变化

不要直接 `ssh-keygen -R` 后重连。先执行：

```powershell
ssh-keyscan -t rsa,ecdsa,ed25519 8.145.46.253
```

再与本文记录的指纹或云控制台指纹比对。确认是同一台服务器后，才更新本机 `known_hosts`。

### 发布脚本出现 `set: -^M: invalid option`

这是 shell 脚本以 CRLF（Windows 换行）上传到 Linux（类 Unix 操作系统）导致。仓库已通过 `.gitattributes` 固定 `*.sh` 为 LF（Unix 换行）。若服务器上仍遇到旧文件，可临时处理：

```powershell
$src = Join-Path (Get-Location) 'deploy\update-runtime-image.sh'
$tmp = Join-Path $env:TEMP 'update-runtime-image.lf.sh'
$text = [System.IO.File]::ReadAllText($src, [System.Text.UTF8Encoding]::new($false))
$text = $text -replace "`r`n", "`n" -replace "`r", "`n"
[System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
scp $tmp root@8.145.46.253:/opt/langgraph-travel-planner/deploy/update-runtime-image.sh
ssh root@8.145.46.253 'set -eu; cd /opt/langgraph-travel-planner; chmod +x deploy/update-runtime-image.sh; sh deploy/update-runtime-image.sh'
```

### 公网 HTTP 自动跳转 HTTPS

Caddy（反向代理服务器）会把 HTTP（超文本传输协议）跳转到 HTTPS（安全超文本传输协议），看到 `308 Permanent Redirect` 是正常现象。公网验收以 `https://travel.403edr.cn/...` 为准。

### 回滚

服务器每次发布会在 `/opt/zhixing-backup-YYYYMMDDHHMMSS` 留一份代码备份。回滚只覆盖代码并重跑镜像刷新，不操作数据库卷：

```powershell
ssh root@8.145.46.253 'set -eu; backup=/opt/zhixing-backup-YYYYMMDDHHMMSS; cd /opt/langgraph-travel-planner; cp -a "$backup"/. /opt/langgraph-travel-planner/; chmod +x deploy/update-runtime-image.sh; sh deploy/update-runtime-image.sh'
```

回滚前先确认备份目录名，且不要把 `.env`、`.runtime/` 或向量库从本地覆盖到服务器。
