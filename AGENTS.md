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

The intended product assists travel advisors with requirement collection, product matching, proposal and quote preparation, order drafting and delivery. The current implementation is still a planning/delivery flow plus agency control plane: tenant, branch, membership, branch-role grant, agency-customer lifecycle, customer-claim invitation, append-only consent record, advisor assignment, current-branch transfer, branch lifecycle event, supplier-product, quote, order, bound internal order review, cancellation case, append-only manual compensation result, independent reconciliation, append-only event, idempotency, payment-attempt and fulfillment-record models exist. The authenticated API supports offline prospect registration, targeted secure customer claim, server-generated consent evidence, relationship activation/deactivation, advisor assignment, owner/admin customer transfer, branch drain/closure governance, quote/order flow, four-eyes internal review and a platform-outside manual cancellation-result workflow. Internal `approved` never means booked or paid. Cancellation `completed` means either that an approved, unexposed `draft`/`approved` order was directly cancelled internally, or that every server-derived required manual result has independent platform-side reconciliation. Live supplier booking/cancellation, payment/refund and notification are not integrated and remain fail-closed by default.

Branch authorization is application-layer row scoping, not PostgreSQL RLS. `owner` and `admin` are agency-wide. New work requires an active grant in the same `active` branch; an `inactive` branch is a drain period that blocks new customers, grants, claims, assignments, quotes, orders and approvals while retaining scoped reads and closeout operations such as transfer-out, grant/assignment cleanup, order-review rejection and cancellation handling. Advisors additionally require a current customer assignment. Order submission and cancellation-case creation require a dedicated approver distinct from the business requester and order customer; an open cancellation case blocks order submission. Revocation must preserve an eligible replacement for every pending order review and approval-pending cancellation case. `agency_membership` identity bindings are immutable. A customer manager can issue a targeted 256-bit high-entropy claim credential for an existing platform account; it expires after 24 hours, is revocable and single-use, and only its SHA-256 digest is stored. Only the authenticated target account can claim, and one agency cannot have multiple pending invitations for the same target account. The raw token is returned only by the first issue response after its transaction commits; an idempotent replay returns no token, so a lost response requires explicit revocation and reissue. Claim responses use no-store semantics and validation errors must not echo token input. Invitation delivery and customer notifications are not implemented.

An authenticated notice endpoint returns the fixed consent-notice Markdown, version, document SHA-256, evidence schema and channel. Consent writes require the client to echo the expected notice version and document digest so stale notice displays fail closed; clients cannot provide arbitrary evidence hashes. The server writes an append-only canonical consent record for each new decision. Binding provenance is explicit (`unbound`, `legacy_direct`, or `secure_claim`), as is consent-evidence provenance (`none`, `legacy_client_hash`, or `server_canonical`). Legacy direct bindings are not presented as secure claims: the existing account may still deny or revoke, but new activation, quote and order paths require `secure_claim` plus `server_canonical` consent. The customer model does not store customer names, phones, identity documents or contact details; claim and consent records do not prove real-world identity, sufficient legal notice or compliance. `blocked` is fail-closed until a future risk-review workflow, but a blocked or inactive relationship may be moved by an agency-wide owner/admin. A transfer is immediate and atomic, may optionally establish a target advisor only for an active customer, and changes only the customer's current service branch; invitation, consent, event, assignment and transaction rows retain their historical branch. Pending invitations or open quotes, orders, reviews or cancellation cases block transfer. It sends no notification and changes no external order. Branch status is `active -> inactive -> closed`: `inactive` stops new business and permits drain operations; `closed` is irreversible and requires every current customer of any status, pending invitation, active assignment/grant, pending review and open quote/order/cancellation case to be cleared. Cross-branch manager two-sided approval is not implemented; transfer is owner/admin-only. Never describe mock checkout or a generated `ORDER-` reference as a real transaction.

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
- `app/api/v1/agency_cancellations.py`: authenticated cancellation-case, manual-result and independent-reconciliation API; it records platform-outside outcomes but never invokes an external adapter.
- `app/core/`: state, workflow metadata, middleware, checkpoints, memory and intent policy.
- `app/models/agency_customer_lifecycle.py`: branch, customer lifecycle, branch-role grant, customer event and advisor-assignment schema.
- `app/models/agency_customer_identity.py`: secure claim invitation and append-only consent-record schema.
- `app/models/agency_transaction.py`: agency tenant, membership, quote, order, event and execution-ledger schema.
- `app/models/agency_cancellation.py`: cancellation case, append-only case event, manual compensation result and independent reconciliation schema.
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

The `0005` migration adds claim invitations and append-only consent records, preserves pre-existing direct bindings as explicit legacy provenance, and forbids presenting them as secure claims. Existing legacy users retain the ability to deny or revoke; after a legacy binding is securely claimed, its old consent projection is reset and an active relationship is made inactive before a fresh server-canonical grant and activation. New activation, quote and order writes require a secure claim and server-canonical consent. PostgreSQL guards make claim terminal state and consent records immutable, reject raw legacy-style binding/evidence on new writes, and retain pre-existing active legacy rows without silently validating them. Downgrade is blocked once any claim invitation, secure claim or server-canonical evidence exists. The `0006` migration fixes table-specific `NEW` field access in the shared deferred customer consistency trigger without rewriting the frozen `0005` revision.

The `0007` migration adds cancellation cases, append-only case events, manual compensation-result records and independent reconciliation records. Required supplier/refund evidence is derived from locked order/payment/fulfillment state; clients cannot select it, and the database insert guard independently recomputes the flags from the locked ledgers. Creating an open case immediately freezes the original payment/fulfillment ledgers so exposure cannot change before review. A same-branch dedicated `approver`, distinct from the requester and order customer, reviews the request; database guards verify this eligibility, keep a qualified replacement for pending work and prevent order submission while a cancellation case is open. If neither action is required, approval directly completes the case and internally cancels an eligible `draft`/`approved` order; otherwise `booking_operator` and `finance` record only their respective platform-outside result summaries, and a different `auditor` uses an auditor-only sanitized result queue to discover opaque record IDs before independently submitting observed refund amount/currency and evidence. Requesters/customers cannot self-approve and result recorders cannot self-reconcile. Unified responses omit internal actor account IDs. Every external-action flag remains false, raw provider references/evidence are not stored, and `refund_required` is an evidence/reconciliation gate rather than a platform refund command. Cancellation-case `requested_at` records case creation; order `cancellation_requested_at` is set only after approval enters order cancellation handling; order `cancelled_at` is reserved for true internal `cancelled`. Downgrade is fail-closed once `0007` business data exists.

The `0008` migration is the current business head. It adds customer current-branch transfer, branch lifecycle events and explicit `closed_at`; reshapes customer foreign keys and uniqueness so historical invitation, consent, event, assignment, quote, order and cancellation rows keep their event-time branch while the customer points to its current service branch; and adds database guards for transfer bindings, branch lifecycle, append-only records and irreversible closure. Downgrade is fail-closed after transfer/branch-lifecycle business data exists or historical child branches no longer match the current customer branch. `0008` has unit/API/static migration coverage in the current worktree, but fresh PostgreSQL 17 CI, target-environment migration/restore and concurrent lock-wait evidence are still pending and must not be claimed as passed.

Agency APIs use a function-scoped database dependency. The transaction commit and deferred PostgreSQL constraints must complete before a success response is sent; commit-stage integrity conflicts are mapped to a stable conflict response, and persistence failures must not leak a false `2xx`.

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
uv run python -m pytest --run-integration -q tests\test_agency_transaction_postgres_integration.py tests\test_agency_customer_lifecycle_postgres_integration.py tests\test_agency_customer_claim_postgres_integration.py tests\test_agency_branch_permissions_postgres_integration.py tests\test_agency_cancellation_postgres_integration.py tests\test_agency_branch_transfer_closure_postgres_integration.py
```

Implementation candidate `20ff71592096dfb4fc718cef050832a745bfe174` is
covered by GitHub Actions run
`https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30534862434`:
the default job reported 1713 passed and 34 deselected, while PostgreSQL 17
reported 10 passed across the three files (3 transaction, 5 customer lifecycle
and 2 branch permission tests). This is a pre-`0005`, CI-only baseline.
Implementation commit `b8b8bea29477b472c942b7df40e8da6e9dbf05ab` is covered by
GitHub Actions run
`https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30551146157`:
the default job reported 1738 passed and 39 deselected, while PostgreSQL 17
reported 15 passed across four files (3 transaction, 5 customer lifecycle,
5 customer claim and 2 branch permission tests). This proves the historical
ephemeral CI path for `0005 -> 0006`.
Implementation commit `e17b97d82c24b7f5271973cc8f18e884124b7d6b` is covered by
GitHub Actions run
`https://github.com/apearlinspring/langgraph-travel-planner/actions/runs/30602058425`:
the default job reported 1841 passed and 49 deselected, while PostgreSQL 17
reported 25 passed across five files (3 transaction, 5 customer lifecycle,
5 customer claim, 2 branch permission and 10 cancellation tests). This proves
the ephemeral CI migration and trigger path through `0007`; it does not prove
target-environment migration, recovery, lock-wait or external-provider
readiness.

The current candidate workflow runs all six PostgreSQL files, including the
`0008` branch-transfer and closure scenarios. Until that workflow completes,
the last confirmed PostgreSQL evidence remains the five-file `0007` run above;
do not report `0008` as PostgreSQL-verified from configuration or collection
alone.

For deployment, use `docs/部署与运行/deployment-readiness.md`. Public deployment docs are templates; private production coordinates must stay outside Git.
