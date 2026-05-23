# ZhiXing Travel Planner

ZhiXing Travel Planner is a multi-agent travel planning system built with FastAPI (快速应用接口框架), LangGraph (图式智能体编排框架), LangChain (大模型应用编排框架), RAG (检索增强生成), MCP (模型上下文协议), PostgreSQL (关系型数据库), Redis (缓存数据库) and a lightweight single-page frontend.

The product goal is a conversational travel consultant that can collect requirements, choose between personalized free planning and agency-style packaged planning, query external travel capabilities when available, and render a structured itinerary report.

## Features

- Dual planning workflows: free planning with staged destination, transport, accommodation, food, itinerary and budget steps; agency planning with product matching, draft refinement and report delivery.
- Streaming chat API through SSE (服务器发送事件), including tool-call events, structured report data and timeout fallback behavior.
- RAG-backed public destination knowledge and demo agency knowledge for route templates, pricing rules, risk notes, service SOP (标准作业流程) and report standards.
- MCP integrations for weather, search, maps, train, flight and hotel capabilities, with service-level degradation when optional services are unavailable.
- Structured report contract, deterministic report quality scoring and frontend report rendering.
- Docker (容器化平台) deployment template with PostgreSQL, Redis, backend and Caddy (反向代理服务器).

## Repository Scope

This public repository contains the minimum maintainable project set:

- Source code: `app/`, `frontend/`, `scripts/`.
- Tests and fixtures: `tests/`.
- Dependency and runtime definitions: `pyproject.toml`, `uv.lock`, `Dockerfile`, `docker-compose.yml`, `deploy/`.
- Safe sample knowledge and evaluation data: `data/documents/`, `data/evaluation/`.
- Formal documentation: `docs/`.
- Configuration template: `.env.example`.

It does not include real secrets, local runtime state, database dumps, vector stores, logs, screenshots, private deployment coordinates, chat records, prompt drafts, interview materials or personal preparation files.

## Database Boundary

The application uses PostgreSQL and pgvector (PostgreSQL 向量扩展). The repository stores database models and initialization scripts, not a real database instance.

- Local or server databases live in Docker volumes or external managed databases.
- Real database data, backups and dumps should stay outside Git.
- Use `.env.example` as the public configuration reference and keep real `.env` files local.

Initialize database tables:

```powershell
uv run python -m scripts.init_db
```

Initialize RAG vector stores from the safe sample knowledge files:

```powershell
uv run python -m scripts.init_rag
```

Generated vector stores under `data/vectorstore/` and `data/vectorstore_internal/` are ignored.

## Quick Start

Prerequisites:

- Python `>=3.12`
- Node.js (for frontend validation scripts)
- PostgreSQL with pgvector and Redis, or Docker Compose
- `uv` Python package manager

Install dependencies:

```powershell
uv sync
```

Create local configuration:

```powershell
Copy-Item .env.example .env
```

Fill in the required model, database, Redis and optional external API settings in `.env`.

Start the backend:

```powershell
uv run python main.py
```

Open the frontend from `frontend/zhixing.html`, or serve it through the Caddy service in Docker.

## Docker

Create `.env` from `.env.example`, then start the stack:

```powershell
docker compose up -d --build
```

The Compose stack defines:

- `backend`
- `postgres`
- `redis`
- `caddy`

Database and Redis data are stored in Docker volumes and should not be committed.

## Validation

Common local checks:

```powershell
uv run python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
uv run python -m pytest -q
```

RAG retrieval evaluation:

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

Integration tests that require real LLM (大语言模型), MCP services or external APIs are marked separately and are not part of the default fast regression set.

## Documentation

Start from [docs/README.md](docs/README.md). The most useful public entries are:

- [Architecture overview](docs/架构与流程/architecture-overview.md)
- [Planning mode boundary](docs/架构与流程/planning-mode-boundary.md)
- [RAG demo and evaluation guide](docs/RAG与知识库/rag-demo-evaluation-guide.md)
- [Evaluation system](docs/评估与验收/evaluation-system.md)
- [Deployment template](docs/部署与运行/deployment-readiness.md)
- [Frontend report experience](docs/前端与演示/frontend-report-experience.md)

## Security

- Never commit `.env`, production secrets, API keys, database dumps, generated vector stores or runtime logs.
- Keep private deployment hostnames, IP addresses and SSH details outside the public repository.
- Do not present demo route templates as real inventory, guaranteed group availability or locked pricing.
- When real external services are unavailable, the system should disclose uncertainty instead of fabricating travel inventory, ticket prices or hotel availability.
