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

ZhiXing Travel Planner targets a travel-agency operations and delivery workbench, not a generic itinerary chatbot. The backend uses FastAPI (快速应用接口框架). The main conversation flow is one Travel Agent created with LangChain (大模型应用编排框架) and run on the LangGraph (图式智能体编排框架) runtime; a destination Router and nested transport Coordinator are invoked for bounded tasks. RAG (检索增强生成) provides local knowledge, MCP (模型上下文协议) connects optional external services, PostgreSQL (关系型数据库) stores durable business facts, checkpoints, long-term memory and the first-stage agency customer/transaction schema, and Redis (缓存数据库) handles locks, caches, rate-limit counters and short-lived runtime state.

The intended product assists travel advisors with requirement collection, product matching, proposal and quote preparation, order drafting and delivery. The current implementation is still a planning/delivery flow plus agency control plane: tenant, branch, membership, branch-role grant, agency-customer lifecycle, advisor assignment, supplier-product, quote, order, bound internal order review, append-only event, idempotency, payment-attempt and fulfillment-record models exist. The authenticated API supports offline prospect registration, linking an existing platform user, customer self-consent, relationship activation/deactivation, advisor assignment, quote/order flow and four-eyes internal review. Internal `approved` never means booked or paid: live supplier booking, payment, refund and notification are not integrated and remain fail-closed by default.

Branch authorization is application-layer row scoping, not PostgreSQL RLS. `owner` and `admin` are agency-wide; branch roles require an active grant in the same active branch, advisors additionally require a current customer assignment, and approvers can only review their branch. An order cannot be submitted unless its branch has at least one active dedicated approver, and the final approver cannot be revoked while a review is pending. An offline prospect can be linked to an existing user and an unconfirmed `invited + unknown` binding can be corrected, but the nominated user cannot read the relationship before recording a consent decision. Invitation delivery, cryptographic customer claim and customer notifications are not implemented. The customer model does not store customer names, phones, identity documents or contact details; consent evidence hashes are audit primitives, not legal compliance proof. `blocked` is fail-closed until a future risk-review workflow. Branch transfer and branch deactivate/close APIs are absent; database guards reject deactivation while active grants, customers, assignments or open transactions remain. Never describe mock checkout or a generated `ORDER-` reference as a real transaction.

When an active customer denies or revokes consent, or the relationship is deactivated, the same database transaction ends the current advisor assignment and closes only the internal transaction state: `draft`/`offered` quotes and an `accepted` quote without an order become internally `cancelled`; pristine `draft`/`approved` orders with no external, payment or fulfillment progress become internally `cancelled`; a `pending_review` order remains pending so an approver can reject it, while approval rechecks the active consented customer and must fail, and the customer cannot be reactivated until that stale review is rejected; ambiguous or potentially external order states move to `cancellation_pending` or remain marked for manual action. This does not call a supplier, cancel an external booking or confirm a refund.

## Key Directories

- `main.py`: local development entrypoint, delegating to `app.run`.
- `app/run.py`: Uvicorn (ASGI Web 服务器) startup script.
- `app/main.py`: FastAPI app, lifespan, routes and health checks.
- `app/api/`: HTTP API layer, including users, conversations, chat and map preview.
- `app/agents/handoffs/`: main travel agent and step configuration.
- `app/agency/`: deterministic customer lifecycle, branch authorization, quote/order services and fail-closed transaction execution policy.
- `app/api/v1/agency_customers.py`: authenticated branch, branch-role grant, customer lifecycle and advisor-assignment API.
- `app/api/v1/agency_transactions.py`: authenticated quote, order and internal order-review API; it stops before any external supplier or financial execution.
- `app/core/`: state, workflow metadata, middleware, checkpoints, memory and intent policy.
- `app/models/agency_customer_lifecycle.py`: branch, customer lifecycle, branch-role grant, customer event and advisor-assignment schema.
- `app/models/agency_transaction.py`: agency tenant, membership, quote, order, event and execution-ledger schema.
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

Planning workflow state, customer lifecycle state and transaction state are separate contracts. `agency_plan` produces a proposal and delivery report; it does not mean that a customer consented, a quote was issued, an order was internally approved, inventory was locked or money was collected. Agency-domain changes must be checked across SQLAlchemy models, Alembic migrations, migration ownership, branch/customer authorization, idempotency, revision/payload-hash validation, append-only events, external-action gates, formal docs and tests. Internal order approval is separate from platform Approval/HITL and never authorizes an external action. Real supplier/payment/refund/notification execution must remain disabled until its adapter, platform approval binding, compensation, reconciliation and target-environment evidence are complete.

The `0004` PostgreSQL mutation guards freeze quote/order tenant, branch, customer and account bindings; recheck active consented customers, active branches, quote validity and order/quote amount, currency and snapshot consistency; require each update to advance `revision` by exactly one; allow only declared status transitions; and keep new orders inert with `external_action_enabled=false`. Order and review terminal states are checked as a pair at transaction commit. Transaction writes follow the lock order `customer -> branch -> quote/order`; authorization-sensitive writes hold shared branch/membership scope locks so a concurrent grant revoke or branch-status change cannot create a time-of-check/time-of-use race.

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

For agency customer or transaction changes, use an isolated database whose
name contains a standalone `test` or `ci` segment:

```powershell
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py
```

The old `319ac26` PostgreSQL 17 result covers only the three pre-`0004`
transaction tests. The current workflow defines ten PostgreSQL integration
tests across the three files (3 transaction, 5 customer lifecycle and 2 branch
permission tests), but a change containing `0004` still requires a fresh CI run
and target-environment migration evidence before any readiness claim.

For deployment, use `docs/部署与运行/deployment-readiness.md`. Public deployment docs are templates; private production coordinates must stay outside Git.
