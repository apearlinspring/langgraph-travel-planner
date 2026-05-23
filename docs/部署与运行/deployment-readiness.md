# Deployment Readiness（部署就绪模板）

This document is the public deployment template. Real production hostnames, IP addresses, SSH users, private keys, `.env` files and database contents must stay outside Git.

## Deployment Boundary

- Deploy only Git-tracked project files.
- Do not upload or print `.env`, `.runtime/`, `.venv/`, `data/vectorstore/`, `data/vectorstore_internal/`, logs, real secrets or personal data.
- Do not delete server database volumes, Redis volumes, `.env`, runtime directories or generated vector stores during a code update.
- PostgreSQL (关系型数据库) and Redis (缓存数据库) are runtime services. Their data belongs to Docker volumes or managed services, not to the repository.
- If database schema changes are introduced, prepare a migration and backup plan before deployment.

## Required Private Variables

Set these locally or in CI（持续集成）secrets before deploying:

```powershell
$env:ZHIXING_DEPLOY_USER = "<ssh-user>"
$env:ZHIXING_DEPLOY_HOST = "<server-host>"
$env:ZHIXING_DEPLOY_DIR = "/opt/langgraph-travel-planner"
$env:ZHIXING_PUBLIC_BASE_URL = "https://<your-domain>"
```

The public repository intentionally does not store these values.

## Local Gate

Run the relevant checks before creating a release archive:

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null

uv run python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
uv run python -m pytest -q
```

Readiness（就绪检查）and preflight（预检）can be run at different layers:

```powershell
uv run python scripts/check_runtime_readiness.py --target development --json
uv run python scripts/check_runtime_readiness.py --target local --json
uv run python scripts/check_runtime_readiness.py --target production --json
```

In JSON output, `component_readiness` identifies dependency state and `repair_suggestions` describes next recovery actions.

If RAG（检索增强生成）documents, retrieval code or metadata（元数据）contracts changed, also run:

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

CI（持续集成）should keep default checks free of real secrets. If a repository uses GitHub Actions（GitHub 自动化流水线）, heavier staging smoke（预生产冒烟）can be exposed through `workflow_dispatch` so maintainers trigger real-link checks manually.

If database schema changes are included and Alembic（数据库迁移工具）versioned migrations exist, run `alembic upgrade head` only after confirming backups and migration ownership.

## Create Release Archive

Start from a clean main branch:

```powershell
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status --short --branch

$commit = git rev-parse --short HEAD
$archive = Join-Path $env:TEMP "zhixing-release-$commit.tar"
git archive --format=tar -o $archive HEAD
Get-Item $archive
```

`git status --short --branch` should show no uncommitted files.

## Upload And Extract

```powershell
$target = "$env:ZHIXING_DEPLOY_USER@$env:ZHIXING_DEPLOY_HOST"
scp $archive "${target}:/tmp/zhixing-release-$commit.tar"
```

Backup the old code and extract the new archive:

```powershell
$remoteScript = @'
set -eu
cd "$ZHIXING_DEPLOY_DIR"
commit_file="$(ls -t /tmp/zhixing-release-*.tar | head -n 1)"
backup="/opt/zhixing-backup-$(date +%Y%m%d%H%M%S)"
mkdir -p "$backup"
cp -a AGENTS.md app deploy docker-compose.yml Dockerfile .dockerignore .env.example frontend main.py pyproject.toml README.md scripts tests uv.lock docs "$backup"/ 2>/dev/null || true
tar -xf "$commit_file" -C "$ZHIXING_DEPLOY_DIR"
chmod +x deploy/update-runtime-image.sh
echo "backup=$backup"
echo "release_extracted"
'@

$remoteScriptPath = Join-Path $env:TEMP "zhixing-deploy-extract.sh"
[System.IO.File]::WriteAllText($remoteScriptPath, $remoteScript, [System.Text.UTF8Encoding]::new($false))
scp $remoteScriptPath "${target}:/tmp/zhixing-deploy-extract.sh"
ssh $target "ZHIXING_DEPLOY_DIR='$env:ZHIXING_DEPLOY_DIR' sh /tmp/zhixing-deploy-extract.sh"
```

If the deployment target may contain files that have been removed from the public repository, delete only explicitly approved stale code paths after backup. Never use a broad cleanup that can remove `.env`, `data/`, `logs/` or Docker volumes.

## Refresh Runtime Image

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; sh deploy/update-runtime-image.sh"
```

The script builds a runtime overlay image and runs:

```sh
docker compose up -d --no-build backend caddy
docker compose ps
```

If the base image does not exist, schedule a full Docker build instead of deleting runtime data.

## Rebuild RAG Vector Stores

If this release changed `data/documents/`, RAG retrieval logic or product metadata, rebuild vector stores inside the backend container:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python -m scripts.init_rag; docker compose restart backend; docker compose ps"
```

The script builds new vector stores under generated data directories and swaps them into `data/vectorstore/` and `data/vectorstore_internal/`. These generated directories are runtime data and should not enter Git.

## Health Checks

Internal server checks:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose ps; curl -fsS http://127.0.0.1:8000/health/live; echo; curl -fsS http://127.0.0.1:8000/health/ready | head -c 3000; echo"
```

Public URL checks:

```powershell
@'
import json
import os
import urllib.request

base = os.environ["ZHIXING_PUBLIC_BASE_URL"].rstrip("/")
for path in ["/", "/docs", "/health/live", "/health/ready"]:
    url = base + path
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()
        print(url, resp.status, resp.headers.get("content-type"), len(data))
        if path.startswith("/health/"):
            payload = json.loads(data.decode("utf-8"))
            print("status=", payload.get("status"), "environment=", payload.get("environment"))
'@ | python -
```

Expected results:

- Root page and `/docs` return HTTP（超文本传输协议）200.
- `/health/live` returns `alive`.
- `/health/ready` returns `ready` or an explicitly understood degraded state.
- `backend`, `postgres` and `redis` containers are healthy.

## Optional Smoke

For releases touching chat, reports, RAG or MCP:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR'; docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --json | head -c 5000; echo"
```

Full acceptance runs can call real LLM（大语言模型） and external APIs. Run them only when release risk justifies the cost.

## Rollback

Each deployment should create a code backup. Rollback copies code back and refreshes runtime containers; it must not overwrite `.env`, database volumes or vector stores from a local machine.

```powershell
ssh $target "set -eu; backup=/opt/zhixing-backup-YYYYMMDDHHMMSS; cd '$env:ZHIXING_DEPLOY_DIR'; cp -a \"\$backup\"/. '$env:ZHIXING_DEPLOY_DIR'/; chmod +x deploy/update-runtime-image.sh; sh deploy/update-runtime-image.sh"
```
