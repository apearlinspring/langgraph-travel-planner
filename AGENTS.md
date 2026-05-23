# Project Collaboration Guide

## Fixed Rules

- When handling Chinese text, use Unicode-safe mode. In PowerShell (Windows 命令行环境), explicitly use UTF-8:

  ```powershell
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  chcp 65001 | Out-Null
  Get-Content -Raw -Encoding UTF8 路径\文件名
  ```

- Explain English terms or abbreviations the first time they appear in user-facing Chinese text, for example SSE（服务器发送事件） and MCP（模型上下文协议）.
- Start each work session from the latest `origin/main`; do not rely on stale review findings or old conversation memory.
- Before editing, inspect the current working tree and avoid reverting changes made by other collaborators.
- After major feature changes, review related formal documentation and tests for drift.
- Do not read, print, copy, commit or deploy sensitive local content from `.env`, `.env.production`, `.runtime/`, `.venv/`, `data/vectorstore/` or `data/vectorstore_internal/`.
- Public commits and deployments should contain only the minimum public project set: source code, dependency definitions, configuration examples, database schema or initialization scripts, necessary tests, formal README and technical documentation, deployment templates and safe sample data. Do not commit real secrets, runtime artifacts, database instances or backups, vector stores, logs, raw evaluation evidence, chat records, unorganized prompts, draft plans, interview materials or personal preparation files.

## Project Summary

ZhiXing Travel Planner is a multi-agent travel planning system. The backend uses FastAPI (快速应用接口框架). The main conversation flow is coordinated by LangGraph (图式智能体编排框架) and LangChain (大模型应用编排框架). RAG (检索增强生成) provides local knowledge, MCP (模型上下文协议) connects optional external services, and PostgreSQL (关系型数据库) stores users, conversations, messages, checkpoints and long-term memory.

The product shape is a travel consultant that can collect requirements over multiple turns, split users into personalized free planning or agency-style packaged planning, query real candidates when configured, and generate structured travel reports.

## Key Directories

- `main.py`: local development entrypoint, delegating to `app.run`.
- `app/run.py`: Uvicorn (ASGI Web 服务器) startup script.
- `app/main.py`: FastAPI app, lifespan, routes and health checks.
- `app/api/`: HTTP API layer, including users, conversations, chat and map preview.
- `app/agents/handoffs/`: main travel agent and step configuration.
- `app/core/`: state, workflow metadata, middleware, checkpoints, memory and intent policy.
- `app/tools/`: agent tools for state transitions, transport, hotel, RAG, MCP and memory.
- `app/reports/`: final report contract, validation and Markdown rendering.
- `app/rag/`: document loading, splitting, retrieval, reranking, cache and pipeline code.
- `app/mcp_core/`: MCP client manager and local MCP servers.
- `app/evaluation/`: report quality, runtime metrics and scenario evaluation.
- `frontend/`: single-page frontend prototype.
- `scripts/`: initialization, validation, evaluation and deployment helper scripts.
- `data/documents/`: safe sample destination and agency knowledge.
- `data/evaluation/`: fixed evaluation scenarios.
- `docs/`: formal public documentation; start from `docs/README.md`.

## Core Workflow

The app is not a plain Q&A bot. It first selects a planning mode, then advances through the relevant workflow.

- `free_planning`: personalized planning controlled by `current_step`.
- `agency_plan`: packaged agency planning controlled by `agency_step`.

The free planning stages are defined in `app/core/workflow.py`. Stage prompts, tools and dependencies live in `app/agents/handoffs/step_config.py`.

When changing stages or report contracts, check the related state, middleware, transition tools, frontend progress display and tests together.

## Validation

Choose checks based on the scope of changes. Useful defaults:

```powershell
uv run python -m compileall app tests scripts
node --check frontend\app.js
node scripts\verify_frontend_report_renderer.js
node scripts\verify_frontend_browser_regression.js
uv run python -m pytest -q
```

For RAG changes:

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
```

For deployment, use `docs/部署与运行/deployment-readiness.md`. Public deployment docs are templates; private production coordinates must stay outside Git.
