# Deployment Readiness（部署就绪模板）

This document is the public deployment template. Real production hostnames, IP addresses, SSH users, private keys, `.env` files and database contents must stay outside Git. If operators maintain a private production runbook with concrete host, SSH and deployment values, map those values to the variables below during execution; do not copy them back into this public file.

For the current M1 controlled trial（受控试运行）status and public claim boundary, see `docs/部署与运行/m1-controlled-trial-status.md`. For M1 execution order, evidence boundaries and rollback gates, see `docs/部署与运行/m1-controlled-trial-runbook.md`. For release candidate freeze, see `docs/部署与运行/m1-release-candidate-freeze.md`; for public repository closure before a release candidate, see `docs/部署与运行/m1-public-release-closure.md`. For required server, secret, data and operations inputs, see `docs/部署与运行/production-deployment-inputs.md`; for the execution-time private input gap checklist, see `docs/部署与运行/m1-execution-input-gap-checklist.md`. For PostgreSQL / Redis runtime operations and concurrency boundaries, see `docs/部署与运行/postgres-redis-ops-runbook.md`. For the operational evidence storyline across PostgreSQL/Redis, concurrency, rate limit, Docker disk, backup and rollback, see `docs/部署与运行/m1-operations-evidence-playbook.md`. For backup, restore drill and data rollback boundaries, see `docs/部署与运行/backup-restore-runbook.md`. For monitoring, alerting and runtime metric thresholds, see `docs/部署与运行/monitoring-alerting-runbook.md`. For public release boundary, key rotation and leak response, see `docs/部署与运行/security-release-key-rotation-runbook.md`. Final M1 go/no-go aggregation is handled by `scripts/collect_m1_go_no_go_evidence.py`; requested evidence that remains `not_checked` blocks release.

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
$env:ZHIXING_EVAL_BASE_URL = "https://<your-domain>"
$env:ZHIXING_BACKUP_DIR = "<private-backup-dir-outside-git>"
# Fill probe credentials only in a private shell; do not copy values into Git.
# $env:ZHIXING_PROBE_ACCESS_TOKEN = <probe-user-bearer-token>
# $env:ZHIXING_PROBE_USERNAME = <probe-username>
# $env:ZHIXING_PROBE_PASSWORD = <probe-password>
```

The public repository intentionally does not store these values.

## Local Gate

Run the relevant checks before creating a release archive:

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null

uv run python -m compileall app tests scripts
uv run python scripts\check_release_candidate_freeze.py --check-public-closure --json
uv run python scripts\check_rate_limit_release_scope.py --json
uv run python scripts\render_release_candidate_freeze_record.py --markdown
uv run python scripts\check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json
uv run python scripts\render_release_candidate_stage_plan.py --record-json <filled-freeze-record.json> --markdown
uv run python scripts\check_release_candidate_stage_scope.py --record-json <filled-freeze-record.json> --json
uv run python scripts\check_public_release_boundary.py --json
uv run python scripts\check_m1_public_release_closure.py --json
uv run python scripts\check_runtime_dependency_scope.py --json
uv run python scripts\check_production_image_build_policy.py --template --output <private-workdir>\production-image-build-policy.local.json
uv run python scripts\check_production_image_build_policy.py --policy-json <private-workdir>\production-image-build-policy.local.json --json --output <private-workdir>\production-image-build-policy-report.json
uv run python scripts\check_production_image_build_execution_record.py --template --output <private-workdir>\production-image-build-execution-record.local.json
uv run python scripts\prepare_production_image_build_execution.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --build-id <build-id> --release-label <release-label> --markdown --output <private-workdir>\production-image-build-execution-prep.md
uv run python scripts\check_production_image_build_execution_record.py --record-json <private-workdir>\production-image-build-execution-record.local.json --json --output <private-workdir>\production-image-build-execution-report.json
uv run python scripts\render_m1_resource_request.py --markdown
uv run python scripts\prepare_m1_private_execution_workspace.py --private-workdir <private-workdir> --execute --markdown
uv run python scripts\check_m1_launch_inputs.py --input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\m1-launch-inputs.local.json --markdown
uv run python scripts\render_server_env_checklist.py --markdown
uv run python scripts\render_server_env_checklist.py --template
uv run python scripts\check_m1_first_deploy_dry_run.py --json
uv run python scripts\build_release_artifact.py --json
uv run python scripts\check_m1_rollout_execution_record.py --template --output <private-workdir>\m1-rollout-execution-record.local.json
uv run python scripts\check_m1_rollout_execution_record.py --draft-from-evidence --server-preflight-json <private-workdir>\server-preflight-report.json --postgres-redis-json <private-workdir>\postgres-redis-live-probe.json --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --output <private-workdir>\m1-rollout-execution-record.draft.json
uv run python scripts\check_m1_rollout_execution_record.py --record-json <private-workdir>\m1-rollout-execution-record.local.json --output <private-workdir>\m1-rollout-execution-report.json
uv run python scripts\check_m1_operations_review_record.py --template --output <private-workdir>\m1-operations-review-record.local.json
uv run python scripts\check_m1_operations_review_record.py --draft-from-evidence --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --external-dependency-json <private-workdir>\external-dependency-resilience-report.json --output <private-workdir>\m1-operations-review-record.draft.json
uv run python scripts\check_m1_operations_review_record.py --record-json <private-workdir>\m1-operations-review-record.local.json --output <private-workdir>\m1-operations-review-report.json
uv run python scripts\check_m1_launch_inputs.py --json
uv run python scripts\check_server_preflight_readiness.py --json
uv run python scripts\check_postgres_redis_ops_status.py --check-compose --json --output <private-workdir>\postgres-redis-ops-status.json
docker compose exec -T backend python scripts/check_postgres_redis_ops_status.py --json > <private-workdir>/postgres-redis-ops-status.live-env.json
uv run python scripts\render_postgres_redis_ops_declaration_request.py --ops-status-json <private-workdir>\postgres-redis-ops-status.live-env.json --live-probe-json <private-workdir>\postgres-redis-live-probe.json --markdown --output <private-workdir>\postgres-redis-ops-declaration-request.md
uv run python scripts\render_postgres_redis_ops_owner_questionnaire.py --request-json <private-workdir>\postgres-redis-ops-declaration-request.json --markdown --output <private-workdir>\postgres-redis-ops-owner-questionnaire.md
uv run python scripts\check_postgres_redis_ops_declaration_record.py --request-json <private-workdir>\postgres-redis-ops-declaration-request.json --draft-from-request --output <private-workdir>\postgres-redis-ops-declaration-record.draft.json
uv run python scripts\check_postgres_redis_ops_declaration_record.py --request-json <private-workdir>\postgres-redis-ops-declaration-request.json --record-json <private-workdir>\postgres-redis-ops-declaration-record.local.json --output <private-workdir>\postgres-redis-ops-declaration-record-report.json
uv run python scripts\render_postgres_redis_ops_env_patch.py --record-json <private-workdir>\postgres-redis-ops-declaration-record.local.json --record-report-json <private-workdir>\postgres-redis-ops-declaration-record-report.json --markdown --output <private-workdir>\postgres-redis-ops-env-patch.md
uv run python scripts\check_travel_data_sources.py
uv run python scripts\collect_public_travel_data_candidates.py --city xian --output-dir <private-workdir>\public-travel-candidates --execute
uv run python scripts\review_public_travel_data_candidates.py --candidate-json <private-workdir>\public-travel-candidates\public-travel-data-candidates.json --review-json <private-workdir>\public-travel-candidate-review.json --output-dir <private-workdir>\approved-public-travel-candidates --execute
uv run python scripts\collect_postgres_redis_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --output <private-workdir>\postgres-redis-live-probe.json
uv run python scripts\collect_docker_disk_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-candidates 20 --output <private-workdir>\docker-disk-cleanup-plan.json
uv run python scripts\execute_docker_disk_cleanup.py --plan-json <private-workdir>\docker-disk-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-delete-count 20 --markdown --output <private-workdir>\docker-disk-cleanup-dry-run.md
sh deploy/run-backup.sh --deploy-dir <deploy-dir> --backup-root <private-backup-dir-outside-git>
sh deploy/install-backup-cron.sh --deploy-dir <deploy-dir> --backup-root <private-backup-dir-outside-git> --schedule "17 3 * * *"
uv run python scripts\collect_backup_schedule_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --backup-dir <private-backup-dir-outside-git> --timeout-seconds 90
uv run python scripts\collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown --output <private-workdir>\server-capacity-snapshot.md
uv run python scripts\collect_live_concurrency_probe.py --base-url <public-url> --requests-per-endpoint 30 --concurrency 10 --timeout-seconds 5 --max-p95-ms 2000 --output <private-workdir>\live-concurrency-probe.json
uv run python scripts\collect_rate_limit_live_probe.py --base-url <public-url> --request-count 160 --concurrency 16 --timeout-seconds 10 --output <private-workdir>\rate-limit-live-probe.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --template --output <private-workdir>\concurrency-rate-limit-record.local.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --draft-from-probes --concurrency-probe-json <private-workdir>\live-concurrency-probe.json --rate-limit-probe-json <private-workdir>\rate-limit-live-probe.json --output <private-workdir>\concurrency-rate-limit-record.draft.json
uv run python scripts\check_concurrency_rate_limit_evidence_record.py --record-json <private-workdir>\concurrency-rate-limit-record.local.json --output <private-workdir>\concurrency-rate-limit-report.json
uv run python scripts\check_probe_auth_readiness.py --base-url <public-url> --username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD --markdown
uv run python scripts\collect_live_chat_probe.py --base-url <public-url> --access-token-env ZHIXING_PROBE_ACCESS_TOKEN --markdown
uv run python scripts\collect_live_chat_probe.py --base-url <public-url> --username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD --markdown
uv run python scripts\check_backup_restore_readiness.py --json
uv run python scripts\collect_backup_restore_drill_evidence.py --json
uv run python scripts\collect_postgres_restore_drill_live_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --backup-dir <private-backup-dir-outside-git> --timeout-seconds 300 --markdown --output <private-workdir>\postgres-restore-drill-live-probe.md
uv run python scripts\render_postgres_redis_backup_declaration_candidates.py --backup-schedule-json <private-workdir>\backup-schedule-live-probe.json --backup-restore-json <private-workdir>\postgres-restore-drill-live-probe.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility.json --markdown --output <private-workdir>\postgres-redis-backup-declaration-candidates.md
uv run python scripts\check_backup_alert_status.py --backup-dir <private-backup-dir-outside-git> --require-rag-restore-artifact --json
uv run python scripts\check_postgres_redis_recovery_record.py --template --output <private-workdir>\postgres-redis-recovery-record.local.json
uv run python scripts\check_postgres_redis_recovery_record.py --record-json <private-workdir>\postgres-redis-recovery-record.local.json --output <private-workdir>\postgres-redis-recovery-report.json
uv run python scripts\render_postgres_redis_ops_summary.py --ops-status-json <private-workdir>\postgres-redis-ops-status.json --live-probe-json <private-workdir>\postgres-redis-live-probe.json --recovery-record-json <private-workdir>\postgres-redis-recovery-report.json --json --output <private-workdir>\postgres-redis-ops-summary.json
uv run python scripts\render_postgres_redis_ops_summary.py --ops-status-json <private-workdir>\postgres-redis-ops-status.json --live-probe-json <private-workdir>\postgres-redis-live-probe.json --recovery-record-json <private-workdir>\postgres-redis-recovery-report.json --markdown --output <private-workdir>\postgres-redis-ops-summary.md
uv run python scripts\collect_m1_go_no_go_evidence.py --include-postgres-redis-ops-summary --postgres-redis-ops-summary-json <private-workdir>\postgres-redis-ops-summary.json --json
uv run python scripts\check_external_api_readiness.py --json
uv run python scripts\check_monitoring_alerting_readiness.py --json
uv run python scripts\check_cost_alert_status.py --daily-budget-cny <daily-budget-cny> --check-db-activity --owner-declared --manual-check-status passed --allow-zero-traffic-estimate --json
uv run python scripts\check_tool_failure_monitor_status.py --lookback-hours 24 --allow-empty-sample --json
uv run python scripts\check_external_dependency_resilience_record.py --template --output <private-workdir>\external-dependency-resilience-record.local.json
uv run python scripts\check_external_dependency_resilience_record.py --record-json <private-workdir>\external-dependency-resilience-record.local.json --output <private-workdir>\external-dependency-resilience-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --json
uv run python scripts\collect_monitoring_alerting_evidence.py --json
uv run python scripts\check_security_release_readiness.py --json
uv run python scripts\check_rollback_rehearsal_status.py --deploy-dir <deploy-dir> --backup-dir <rollback-backup-dir> --release-archive <release-archive> --expected-archive-sha256 <archive-sha256> --check-health --check-mock-checkout --json
uv run python scripts\check_rollback_execution_record.py --record-json <private-rollback-record.json> --json
uv run python scripts\check_incident_tabletop_status.py --record-json <private-tabletop-record.json> --json
uv run python scripts\collect_incident_rollback_evidence.py --json
uv run python scripts\check_m1_deployment_gate.py --m1-input-json <private-workdir>\m1-launch-inputs.local.json --json
uv run python scripts\check_m1_deployment_gate.py --json
uv run python scripts\render_m1_acceptance_record.py
uv run python scripts\collect_m1_smoke_evidence.py --json
uv run python scripts\collect_m1_go_no_go_evidence.py --json
uv run python scripts\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json
uv run python scripts\check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-owner <release-owner> --output <private-workdir>\m1-live-evidence-workflow\signoff.json
uv run python scripts\render_m1_deployment_evidence_matrix.py --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json --markdown --output <private-workdir>\m1-deployment-evidence-matrix.md
uv run python scripts\render_m1_live_evidence_summary.py --go-no-go-json <private-go-no-go.json> --output <private-workdir>\m1-live-evidence-summary.md
uv run python scripts\build_m1_evidence_bundle.py --go-no-go-json <private-go-no-go.json> --output-dir <private-workdir>\m1-evidence-bundle --execute
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
uv run python scripts/check_runtime_dependency_scope.py --json
uv run python scripts/check_production_image_build_policy.py --json
uv run python scripts/check_production_image_build_execution_record.py --template
uv run python scripts/prepare_production_image_build_execution.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --build-id <build-id> --release-label <release-label> --markdown
```

In JSON output, `component_readiness` identifies dependency state and `repair_suggestions` describes next recovery actions. Runtime readiness runs the deterministic RAG mixed-corpus safety gate by default and reports it under `rag_mixed_corpus_safety`.

`check_runtime_dependency_scope.py` is a static production-image dependency gate. It does not read `.env`, installed packages, logs, runtime directories or vector stores. The default production build input is `requirements.runtime.txt`, generated from the non-dev, non-optional dependency set. A `blocked` result means the runtime file or production Dockerfile has drifted back toward dev/test frameworks, multimodal deep-gate tooling, local embedding stacks or GPU/model transitive packages such as `torch`, `triton` and `nvidia-*`. Treat that as a release engineering blocker before the next full image rebuild.

`check_production_image_build_policy.py` is a static image-build policy gate. It does not run Docker, connect SSH, start services, delete Docker resources, read `.env` or echo mirror/private values. The gate requires production builds to use configurable `PIP_INDEX_URL` / `PIP_TRUSTED_HOST`, a pinned `COMPOSE_PROJECT_NAME`, a remote background wrapper such as `nohup` / `systemd-run` / `tmux`, a build timeout, redacted build logs, PID tracking, image ID and size evidence, post-build `compose ps` and `/health/ready` evidence, plus explicit safety boundaries: disk guard required, no `docker system prune`, no volume deletion, no `.env` deletion and no vectorstore deletion.

`check_production_image_build_execution_record.py` validates the private record after a real remote background image build. It still does not run Docker, connect SSH, start services, read `.env`, inspect raw logs or print private values. A passed report proves one sampled build window recorded background execution, runtime-only dependency input, image ID / size, disk and runtime-data safety, `compose ps`, `/health/live` and `/health/ready`; it does not prove vulnerability status, long-term build reliability or real booking/payment fulfillment.

`prepare_production_image_build_execution.py` is the approval-gated starter for that remote background build. Without `--execute`, it only renders a redacted dry-run plan. With `--execute --approval-token APPROVE_PRODUCTION_IMAGE_BUILD_EXECUTION`, it starts `deploy/update-runtime-image.sh` in a remote background wrapper and records private log/TSV paths on the server. Starting the job is not success; after it finishes, fill the private execution record and validate it with `check_production_image_build_execution_record.py`.

For releases touching multimodal RAG（多模态检索增强生成）extraction, add the explicit deep gate:

```powershell
uv run python scripts/check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e
```

This option runs the image/audio/video ingestion and retrieval acceptance under generated runtime data. It requires a real `DASHSCOPE_API_KEY`, usable `ffmpeg` / `faster-whisper`, and prepared local sample files. Keep the evidence redacted: record only the top-level status, key counters and blocked reasons; do not preserve `.runtime` contents, absolute local paths or raw model logs in public release notes. Default CI should not enable it.

If RAG（检索增强生成）documents, retrieval code or metadata（元数据）contracts changed, also run:

```powershell
uv run python scripts\evaluate_rag_retrieval.py --json
uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

The mixed-corpus command keeps public and internal documents in the same candidate set, then verifies that public scenarios do not return internal product, pricing or risk-control evidence.

CI（持续集成）should keep default checks free of real secrets. If a repository uses GitHub Actions（GitHub 自动化流水线）, heavier staging smoke（预生产冒烟）can be exposed through `workflow_dispatch` so maintainers trigger real-link checks manually.

For the full RAG release checklist, including default gates, multimodal deep gates and post-deployment readiness, see `docs/RAG与知识库/rag-release-checklist.md`.

If database schema changes are included and Alembic（数据库迁移工具）versioned migrations exist, run `alembic upgrade head` only after confirming backups and migration ownership.

## Create Release Archive

Start from a frozen and clean main branch:

```powershell
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status --short --branch
uv run python scripts\check_release_candidate_freeze.py --json
uv run python scripts\check_rate_limit_release_scope.py --json

$commit = git rev-parse --short HEAD
$releaseDir = Join-Path $env:TEMP "zhixing-release-$commit"
uv run python scripts\build_release_artifact.py --execute --output-dir $releaseDir --json
$archive = Join-Path $releaseDir "zhixing-release-$commit.tar"
$manifest = Join-Path $releaseDir "zhixing-release-$commit.manifest.json"
Get-Item $archive, $manifest
$archiveSha256 = (Get-Content -Raw -Encoding UTF8 $manifest | ConvertFrom-Json).artifact.archive_sha256
```

`git status --short --branch` should show no uncommitted files, and `scripts/check_release_candidate_freeze.py` should return `status=passed`. `scripts/build_release_artifact.py` refuses dirty worktrees, runs the public release boundary, builds the archive from Git `HEAD`, and records commit, tree, tracked file count and archive `sha256` in a manifest. It does not read `.env` and does not include runtime data outside Git.

## Upload And Extract

```powershell
$target = "$env:ZHIXING_DEPLOY_USER@$env:ZHIXING_DEPLOY_HOST"
scp $archive "${target}:/tmp/zhixing-release-$commit.tar"
scp $manifest "${target}:/tmp/zhixing-release-$commit.manifest.json"
```

### Existing Flat-Layout Targets

Some existing servers may still use a legacy flat layout, where `docker-compose.yml`, `.env`, `app/`, `frontend/` and generated `data/vectorstore*` directories live directly under `<deploy-dir>`. The newer release script creates `releases/`, `current` and `shared/` under the same deployment root. Treat these as two different layouts.

Before running `--execute --start-services`, run the redacted live probe and inspect `release_layout.layout_mode`:

```powershell
uv run python scripts\collect_live_server_probe.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --public-base-url <public-url> --markdown
```

If it reports `legacy_flat`, do not assume `<deploy-dir>/shared/.env` or `<deploy-dir>/shared/data` already contains the production runtime state. Use one of these explicit paths:

- Compatibility update: keep the existing flat layout for this release window, back up the current code, extract the clean Git archive into `<deploy-dir>`, and run `deploy/update-runtime-image.sh` from that directory. This follows the older update path and must not delete `.env`, Docker volumes, logs or vector stores.
- Layout migration: first create `<deploy-dir>/shared/`, copy the existing server-side `.env` and generated runtime data into the shared locations without printing file contents, then run `deploy/first-deploy.sh --env-file <deploy-dir>/shared/.env` in dry-run mode. Only after the dry-run, Compose config and live probe pass should `--execute --start-services` be used.

If the probe reports `blocked_current_not_symlink`, stop. A non-symlink `current` path can be overwritten by a release-switch operation; inspect and back it up manually before continuing.

If the probe reports release-symlink layout with root `.env` present but `shared/.env` missing, treat it as `degraded`: the current service may still be running with an explicitly supplied env file, but the next standard first-deploy path should converge runtime configuration into `<deploy-dir>/shared/.env` before relying on default deploy commands. Start with a dry-run convergence check:

```powershell
uv run python scripts\converge_server_shared_env.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --markdown
```

Actual convergence is approval-gated and refuses to overwrite an existing `shared/.env`. It copies the server-side root `.env` into `shared/.env`, sets owner-only permissions, does not print values, and does not restart services:

```powershell
uv run python scripts\converge_server_shared_env.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --execute --approval-token APPROVE_SHARED_ENV_CONVERGENCE --markdown
```

Backup the old code and extract the new archive:

```powershell
scp deploy\first-deploy.sh "${target}:/tmp/zhixing-first-deploy.sh"
ssh $target "sh /tmp/zhixing-first-deploy.sh --archive /tmp/zhixing-release-$commit.tar --archive-sha256 '$archiveSha256' --deploy-dir '$env:ZHIXING_DEPLOY_DIR'"
ssh $target "sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/zhixing-release-$commit.tar --archive-sha256 '$archiveSha256' --deploy-dir '$env:ZHIXING_DEPLOY_DIR'"
```

`deploy/first-deploy.sh` defaults to dry-run and requires `--execute` before it writes files. When `--archive-sha256` is provided, it verifies the uploaded archive before listing or extracting it. It creates immutable `releases/<release-id>` directories, keeps runtime `.env`, generated vector stores, logs and backups under `<deploy-dir>/shared/`, rejects forbidden archive entries such as `.env`, `.runtime/`, `.venv/`, `data/vectorstore/`, `data/vectorstore_internal/`, logs and `__pycache__`, then switches `<deploy-dir>/current` to the new release. Compose（容器编排）启动固定使用 `ZHIXING_COMPOSE_PROJECT_NAME`，默认 `langgraph-travel-planner`，避免从 `<deploy-dir>/current` 符号链接运行时被推断成 `current` 项目并与 `zhixing-*` 固定容器名冲突。During a legacy flat-layout migration, it may copy server-side `data/vectorstore/` and `data/vectorstore_internal/` into empty shared vector store directories if the shared `chroma.sqlite3` files are missing; it does not copy vector stores from Git and blocks instead of overwriting a non-empty partial shared target. If the deployment target may contain files that have been removed from the public repository, delete only explicitly approved stale code paths after backup. Never use a broad cleanup that can remove `.env`, `shared/`, Docker volumes or managed-service data.

After the server shared `.env` is created, validate it only on the target server or a secret-safe shell. The checker reports missing, empty, placeholder-looking, duplicate variables and permission status, but does not print values or the env file path:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; python scripts/check_server_env_file.py --env-file '$env:ZHIXING_DEPLOY_DIR/shared/.env' --json"
```

## Refresh Runtime Image

If the first deploy script was run with `--start-services`, this step has already run a full Compose build/start. Use the command below only for later runtime image refreshes. `deploy/update-runtime-image.sh` also pins `COMPOSE_PROJECT_NAME` through `ZHIXING_COMPOSE_PROJECT_NAME`, defaulting to the existing `langgraph-travel-planner` project; do not drop this when running from `<deploy-dir>/current`.

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; ZHIXING_DEPLOY_DIR='$env:ZHIXING_DEPLOY_DIR' sh deploy/update-runtime-image.sh"
```

Before Docker（容器运行工具）image inspection and build, `deploy/update-runtime-image.sh` runs a disk guard on the current deployment directory. Defaults are:

```powershell
$env:ZHIXING_DISK_GUARD_ENABLED = "1"
$env:ZHIXING_MIN_FREE_DISK_MB = "2048"
$env:ZHIXING_DISK_WARN_USED_PERCENT = "90"
$env:ZHIXING_DISK_FAIL_USED_PERCENT = "98"
```

The guard prints `disk_guard_available_mb`, `disk_guard_used_percent` and `disk_guard_status`. `warning` means the runtime refresh may continue but the M1 go/no-go evidence must still include a separate disk cleanup or capacity plan. `blocked` stops before any Docker build/export/import work. The guard never deletes Docker images, volumes, logs, `.env` files or vector stores. If it blocks, collect a Docker disk cleanup plan and execute only an explicitly approved cleanup or capacity expansion before retrying.

The cleanup plan is read-only evidence. It inspects Docker image metadata, protects images referenced by any container, redacts the SSH target and deploy directory, redacts image tag values, and reports virtual image sizes that can double-count shared layers. Use `--output` for private evidence files so Windows does not create UTF-16 redirected JSON. It does not run `docker image rm`, `docker system prune`, container deletion, volume deletion or log cleanup. A cleanup or capacity expansion must be approved as a separate operation before it can move a disk-related `conditional_go` to `go_for_m1_controlled_trial`.

Use the execution helper in dry-run mode first. It reads a private cleanup-plan JSON, or a private M1 go/no-go JSON that embeds `docker_disk_cleanup_plan`, rechecks all container-referenced images on the server, and still performs no deletion:

```powershell
uv run python scripts\execute_docker_disk_cleanup.py --plan-json <private-cleanup-plan-or-go-no-go-json> --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-delete-count 20 --markdown --output <private-workdir>\docker-disk-cleanup-dry-run.md
```

Before execution mode, validate the private approval gate. The checker reads only redacted JSON evidence and the private approval record; it does not connect SSH or delete anything. A `ready_for_explicit_approval` decision means the evidence can be submitted for approval, not that deletion has been approved:

```powershell
uv run python scripts\check_disk_remediation_approval.py --template --output <private-workdir>\docker-disk-remediation-approval.template.json
uv run python scripts\check_disk_remediation_approval.py --cleanup-plan-json <private-workdir>\docker-disk-cleanup-plan.json --dry-run-json <private-workdir>\docker-disk-cleanup-dry-run.json --capacity-json <private-workdir>\server-capacity-snapshot.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility.json --approval-record-json <private-workdir>\docker-disk-remediation-approval.local.json --markdown --output <private-workdir>\disk-remediation-approval-gate.md
uv run python scripts\render_disk_remediation_approval_request.py --approval-gate-json <private-workdir>\disk-remediation-approval-gate.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\disk-remediation-approval-request.md
uv run python scripts\check_disk_remediation_post_cleanup.py --execution-json <private-workdir>\docker-disk-cleanup-execution.json --before-capacity-json <private-workdir>\server-capacity-snapshot.json --after-capacity-json <private-workdir>\server-capacity-snapshot-post-cleanup.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility-post-cleanup.json --markdown --output <private-workdir>\disk-remediation-post-cleanup.md
uv run python scripts\collect_storage_expansion_readiness.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --required-free-mb 4096 --markdown --output <private-workdir>\storage-expansion-readiness.md
uv run python scripts\render_storage_expansion_request.py --storage-readiness-json <private-workdir>\storage-expansion-readiness.json --post-cleanup-json <private-workdir>\disk-remediation-post-cleanup.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\storage-expansion-request.md
```

If image cleanup has already reduced reclaimable images to zero but disk usage remains high, collect a separate Docker build-cache plan. This plan reads `docker system df`, records only aggregate build-cache size and reclaimable space, and does not delete build cache:

```powershell
uv run python scripts\collect_docker_build_cache_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --output <private-workdir>\docker-build-cache-cleanup-plan.json
uv run python scripts\collect_docker_build_cache_cleanup_plan.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --markdown --output <private-workdir>\docker-build-cache-cleanup-plan.md
uv run python scripts\execute_docker_build_cache_cleanup.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --markdown --output <private-workdir>\docker-build-cache-cleanup-dry-run.md
uv run python scripts\check_docker_build_cache_cleanup_approval.py --template --output <private-workdir>\docker-build-cache-cleanup-approval.template.json
uv run python scripts\check_docker_build_cache_cleanup_approval.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --dry-run-json <private-workdir>\docker-build-cache-cleanup-dry-run.json --capacity-json <private-workdir>\server-capacity-snapshot-post-image-cleanup.json --markdown --output <private-workdir>\docker-build-cache-cleanup-approval-gate.md
uv run python scripts\render_docker_build_cache_cleanup_approval_request.py --approval-gate-json <private-workdir>\docker-build-cache-cleanup-approval-gate.json --go-no-go-json <private-workdir>\m1-current-go-no-go.json --output <private-workdir>\docker-build-cache-cleanup-approval-request.md
```

`render_disk_remediation_approval_request.py` turns the redacted approval gate and go/no-go report into a human-readable approval request. It does not approve execution, connect SSH, delete images, run `docker system prune`, read `.env`, read logs or touch runtime data.

`check_disk_remediation_post_cleanup.py` validates whether an approved cleanup actually fixed the disk blocker. It reads only explicit JSON reports, compares before / after capacity, checks restore-drill feasibility and returns `storage_expansion_required` when cleanup does not free enough space. It does not connect SSH or delete anything.

`collect_storage_expansion_readiness.py` is a read-only topology probe for the expansion path. It checks filesystem capacity, mount sharing, Docker data-root placement and unmounted block-device availability without echoing device names, mount paths, SSH target or deploy directory. Use it when cleanup does not free enough space and the next decision is root-volume expansion versus attaching a new disk.

`render_storage_expansion_request.py` turns storage readiness, post-cleanup and go/no-go evidence into a redacted infrastructure change request. It does not expand cloud disks, mount filesystems or migrate Docker data; it only records the recommended path and post-change validation commands.

Only after explicit approval, run the execution mode. This command deletes only selected image IDs that are still not referenced by any container. It does not prune containers, volumes, logs, `.env`, backups or vector stores:

```powershell
uv run python scripts\execute_docker_disk_cleanup.py --plan-json <private-cleanup-plan-or-go-no-go-json> --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --max-delete-count 20 --execute --approval-token APPROVE_DOCKER_IMAGE_CLEANUP --markdown --output <private-workdir>\docker-disk-cleanup-execution.md
```

Only after separate build-cache approval, run the build-cache execution mode. It runs `docker builder prune -a -f` only; it does not run `docker system prune`, delete images, delete containers, delete volumes, read logs, read `.env`, touch backups or vector stores:

```powershell
uv run python scripts\execute_docker_build_cache_cleanup.py --plan-json <private-workdir>\docker-build-cache-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --execute --approval-token APPROVE_DOCKER_BUILD_CACHE_CLEANUP --markdown --output <private-workdir>\docker-build-cache-cleanup-execution.md
uv run python scripts\collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --markdown --output <private-workdir>\server-capacity-snapshot-post-build-cache-cleanup.md
uv run python scripts\check_restore_drill_feasibility.py --backup-schedule-json <private-workdir>\backup-schedule-live-probe.json --capacity-json <private-workdir>\server-capacity-snapshot-post-build-cache-cleanup.json --markdown --output <private-workdir>\restore-drill-feasibility-post-build-cache-cleanup.md
uv run python scripts\check_docker_build_cache_post_cleanup.py --execution-json <private-workdir>\docker-build-cache-cleanup-execution.json --before-capacity-json <private-workdir>\server-capacity-snapshot-post-image-cleanup.json --after-capacity-json <private-workdir>\server-capacity-snapshot-post-build-cache-cleanup.json --restore-feasibility-json <private-workdir>\restore-drill-feasibility-post-build-cache-cleanup.json --markdown --output <private-workdir>\docker-build-cache-post-cleanup.md
```

After any approved cleanup or capacity expansion, rerun the live server probe or server preflight with disk checks before changing the release decision.

The script builds a runtime overlay image and runs:

```sh
docker compose up -d --no-build backend caddy
docker compose ps
```

If the base image does not exist, schedule a full Docker build instead of deleting runtime data.

## Rebuild RAG Vector Stores

If this release changed `data/documents/`, RAG retrieval logic or product metadata, rebuild vector stores inside the backend container:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python -m scripts.init_rag; docker compose restart backend; docker compose ps"
```

The script builds new vector stores under generated data directories and swaps them into `data/vectorstore/` and `data/vectorstore_internal/`. These generated directories are runtime data and should not enter Git.

## Health Checks

Internal server checks:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose ps; curl -fsS http://127.0.0.1:8000/health/live; echo; curl -fsS http://127.0.0.1:8000/health/ready | head -c 3000; echo"
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

### Public Network Validation Notes

Public URL checks can fail from one validation machine while the application is healthy on the server. Treat local network errors as inconclusive until they are compared with server-side checks and a second network path:

- Windows `curl.exe` may report Schannel（Windows 安全通道） or TLS（传输层安全协议） handshake errors that are specific to the local client path. Recheck with Python `urllib`, browser access, or server-side `curl`.
- If a validation machine sees an ICP filing, SNI（服务器名称指示） or provider interception page, but server-side checks and a user browser can reach the HTTPS URL, record the result as "validation network path limited" rather than an application outage.
- HTTP to HTTPS `308 Permanent Redirect` is expected when the reverse proxy enforces HTTPS. Public acceptance should use the HTTPS base URL.
- Server-side internal checks remain authoritative for container, `/health/live` and `/health/ready` status. Public checks prove reachability for the sampled network path only.

Do not paste real domains, IP addresses, SSH targets or provider screenshots into this public file when recording these findings. Store raw screenshots, logs and cloud console evidence in the private operations workspace.

## Optional Smoke

For releases touching chat, reports, RAG or MCP:

Rollback execution records and incident tabletop records are private operational evidence. Validate them with the Local Gate commands and keep them outside the server smoke command block; do not copy private rollback/tabletop records to the deployment host.

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; python scripts/check_server_env_file.py --env-file '$env:ZHIXING_DEPLOY_DIR/shared/.env' --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_server_preflight_readiness.py --check-docker --check-deploy-dir --check-disk --check-health-url --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_postgres_redis_ops_status.py --check-compose --json | head -c 5000; echo"
uv run python scripts\check_m1_rollout_execution_record.py --record-json <private-workdir>\m1-rollout-execution-record.local.json --output <private-workdir>\m1-rollout-execution-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --json
uv run python scripts\check_m1_operations_review_record.py --record-json <private-workdir>\m1-operations-review-record.local.json --output <private-workdir>\m1-operations-review-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --json
uv run python scripts\collect_postgres_redis_live_probe.py --ssh-target $target --deploy-dir "$env:ZHIXING_DEPLOY_DIR" --timeout-seconds 90 --markdown
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; sh deploy/run-backup.sh --deploy-dir '$env:ZHIXING_DEPLOY_DIR' --backup-root '<private-backup-dir-outside-git>' | head -c 2000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; sh deploy/install-backup-cron.sh --deploy-dir '$env:ZHIXING_DEPLOY_DIR' --backup-root '<private-backup-dir-outside-git>' --schedule '17 3 * * *' | head -c 2000; echo"
uv run python scripts\collect_backup_schedule_live_probe.py --ssh-target $target --deploy-dir "$env:ZHIXING_DEPLOY_DIR" --backup-dir '<private-backup-dir-outside-git>' --timeout-seconds 90 --markdown
uv run python scripts\collect_server_capacity_snapshot.py --ssh-target $target --deploy-dir "$env:ZHIXING_DEPLOY_DIR" --timeout-seconds 90 --markdown
uv run python scripts\collect_live_concurrency_probe.py --base-url "$env:ZHIXING_PUBLIC_BASE_URL" --requests-per-endpoint 30 --concurrency 10 --timeout-seconds 5 --max-p95-ms 2000 --markdown --output <private-workdir>\live-concurrency-probe.md
uv run python scripts\collect_rate_limit_live_probe.py --base-url "$env:ZHIXING_PUBLIC_BASE_URL" --request-count 160 --concurrency 16 --timeout-seconds 10 --output <private-workdir>\rate-limit-live-probe.json
uv run python scripts\collect_rate_limit_live_probe.py --report-json <private-workdir>\rate-limit-live-probe.json --markdown --output <private-workdir>\rate-limit-live-probe.md
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/collect_backup_restore_drill_evidence.py --include-readiness --check-backup-dir --check-latest-dump --check-pg-restore-list --require-restore-drill-declaration --json | head -c 8000; echo"
uv run python scripts\collect_postgres_restore_drill_live_probe.py --ssh-target $target --deploy-dir "$env:ZHIXING_DEPLOY_DIR" --backup-dir '<private-backup-dir-outside-git>' --timeout-seconds 300 --markdown --output <private-workdir>\postgres-restore-drill-live-probe.md
ssh $target "set -eu; docker run --rm -w /app -v '<private-backup-dir-outside-git>:/backup:ro' langgraph-travel-planner-backend:latest /opt/venv/bin/python scripts/check_backup_alert_status.py --backup-dir /backup --require-rag-restore-artifact --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_external_api_readiness.py --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_monitoring_alerting_readiness.py --check-health-url --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_cost_alert_status.py --daily-budget-cny '<daily-budget-cny>' --check-db-activity --owner-declared --manual-check-status passed --allow-zero-traffic-estimate --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_tool_failure_monitor_status.py --lookback-hours 24 --allow-empty-sample --json | head -c 4000; echo"
uv run python scripts\check_external_dependency_resilience_record.py --record-json <private-workdir>\external-dependency-resilience-record.local.json --output <private-workdir>\external-dependency-resilience-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --json
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/collect_monitoring_alerting_evidence.py --include-readiness --check-health-url --require-alert-delivery-declaration --require-metric-declaration --json | head -c 8000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_security_release_readiness.py --check-public-boundary --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; python scripts/check_rollback_rehearsal_status.py --deploy-dir '$env:ZHIXING_DEPLOY_DIR/current' --backup-dir '<rollback-backup-dir>' --release-archive '<release-archive>' --expected-archive-sha256 '<archive-sha256>' --check-health --check-mock-checkout --json | head -c 4000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/collect_incident_rollback_evidence.py --require-ownership-declaration --require-rollback-drill-declaration --require-incident-review-declaration --include-post-rollback-smoke-evidence --check-health-url --run-gate --json | head -c 8000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/collect_m1_smoke_evidence.py --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url '$env:ZHIXING_PUBLIC_BASE_URL' --json | head -c 8000; echo"
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --timeout-seconds 900 --base-url '$env:ZHIXING_PUBLIC_BASE_URL' --json | head -c 8000; echo"
uv run python scripts\collect_m1_go_no_go_evidence.py --include-postgres-redis-live-probe --include-backup-schedule-live-probe --live-server-ssh-target $target --live-server-deploy-dir "$env:ZHIXING_DEPLOY_DIR" --live-backup-dir '<private-backup-dir-outside-git>' --timeout-seconds 90 --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-docker-disk-cleanup-plan --live-server-ssh-target $target --live-server-deploy-dir "$env:ZHIXING_DEPLOY_DIR" --docker-disk-cleanup-max-candidates 20 --timeout-seconds 90 --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-server-capacity-snapshot --live-server-ssh-target $target --live-server-deploy-dir "$env:ZHIXING_DEPLOY_DIR" --timeout-seconds 90 --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-restore-drill-feasibility --restore-drill-feasibility-json <private-workdir>\restore-drill-feasibility.json --include-postgres-restore-drill-live-probe --postgres-restore-drill-live-probe-json <private-workdir>\postgres-restore-drill-live-probe.json --include-disk-remediation-approval --disk-remediation-approval-json <private-workdir>\disk-remediation-approval-gate.json --include-docker-build-cache-cleanup-approval --docker-build-cache-cleanup-approval-json <private-workdir>\docker-build-cache-cleanup-approval-gate.json --include-docker-build-cache-post-cleanup --docker-build-cache-post-cleanup-json <private-workdir>\docker-build-cache-post-cleanup.json --json --output <private-workdir>\m1-current-go-no-go.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-rate-limit-live-probe --base-url "$env:ZHIXING_PUBLIC_BASE_URL" --rate-limit-request-count 160 --rate-limit-concurrency 16 --timeout-seconds 10 --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-probe-auth-readiness --execute-probe-auth-login --base-url "$env:ZHIXING_PUBLIC_BASE_URL" --probe-auth-username-env ZHIXING_PROBE_USERNAME --probe-auth-password-env ZHIXING_PROBE_PASSWORD --timeout-seconds 20 --json
uv run python scripts\check_live_chat_probe_execution_approval.py --template --output <private-workdir>\live-chat-probe-execution-approval.local.json
uv run python scripts\check_live_chat_probe_execution_approval.py --approval-json <private-workdir>\live-chat-probe-execution-approval.local.json --json --output <private-workdir>\live-chat-probe-execution-approval-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-live-chat-probe --execute-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --base-url "$env:ZHIXING_PUBLIC_BASE_URL" --live-chat-access-token-env ZHIXING_PROBE_ACCESS_TOKEN --timeout-seconds 90 --json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-live-chat-probe --execute-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --base-url "$env:ZHIXING_PUBLIC_BASE_URL" --live-chat-username-env ZHIXING_PROBE_USERNAME --live-chat-password-env ZHIXING_PROBE_PASSWORD --timeout-seconds 90 --json
uv run python scripts\render_m1_live_evidence_summary.py --go-no-go-json <private-go-no-go.json> --output <private-workdir>\m1-live-evidence-summary.md
uv run python scripts\build_m1_evidence_bundle.py --go-no-go-json <private-go-no-go.json> --output-dir <private-workdir>\m1-evidence-bundle --execute
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/evaluate_rag_retrieval.py --json | head -c 5000; echo"
```

For releases touching multimodal RAG extraction, run the deep gate only in an environment where the required sample files and real model credentials are already present:

```powershell
ssh $target "set -eu; cd '$env:ZHIXING_DEPLOY_DIR/current'; docker compose exec -T backend python scripts/check_runtime_readiness.py --target production --json --check-rag-multimodal-e2e | head -c 8000; echo"
```

Full acceptance runs can call real LLM（大语言模型） and external APIs. Run them only when release risk justifies the cost.

`collect_live_concurrency_probe.py` is a short-window GET-only probe for `/health/live`, `/health/ready` and the M1 mock checkout status endpoint. It does not call LLMs, external providers, payment, booking or fulfillment APIs. A passed result proves low-risk endpoint concurrency for the sampled window only; it does not prove chat throughput, autoscaling, long-duration soak stability or formal SLO compliance.

`collect_server_capacity_snapshot.py` is a point-in-time SSH（安全外壳协议）read-only resource snapshot. It records CPU count, load, memory, disk, required container states and one `docker stats --no-stream` sample. It does not read `.env`, logs, database rows, Redis keys, backups or vector stores, and it does not start, stop or restart services. Pair it with `collect_live_concurrency_probe.py`: the capacity snapshot explains host/container resource pressure, while the concurrency probe explains sampled low-risk HTTP behavior. Neither one proves full chat throughput, autoscaling or long-duration soak stability.

`collect_rate_limit_live_probe.py` is a short-window GET-only probe for the mock checkout status endpoint. Use `--concurrency` for a burst sample; a slow serial probe can cross the configured rate-limit window and miss the 429 boundary. The probe expects a successful response before the configured API rate limit is reached, then at least one HTTP 429 response with `Retry-After` / `X-RateLimit-*` headers. It does not call LLMs, external providers, payment, booking, inventory lock or fulfillment APIs. A passed result proves only that the sampled low-risk API path is protected by the deployed rate-limit middleware; it does not prove WAF rules, autoscaling, upstream quota protection or long-duration traffic shaping.

For a public demo deployment, keep self-service registration closed unless there is a specific review window: set `AUTH_REGISTRATION_ENABLED=false` after creating the intended demo or owner account. Keep API overload protection enabled with Redis, for example `API_RATE_LIMIT_ENABLED=true`, `API_RATE_LIMIT_BACKEND=redis`, and `API_RATE_LIMIT_LOCAL_FALLBACK=false`. To reduce LLM（大语言模型）spend exposure, also enable the chat-turn budget gate with `CHAT_TURN_QUOTA_ENABLED=true` and a small `CHAT_TURN_QUOTA_DAILY_LIMIT` such as `10` to `30` per user per day. These controls reduce casual abuse risk; they do not make an internet-facing demo abuse-safe and do not replace provider-console hard quotas, WAF（Web 应用防火墙）, security-group rules, bot protection, log monitoring or emergency key rotation.

The current API limiter uses a client identifier plus the full request path. Conversation-specific paths can therefore create separate buckets, and forwarded client addresses are trustworthy only when a controlled reverse proxy strips and rewrites `X-Forwarded-For`. Before describing the protection as per-user or global, add a path-independent authenticated-user limit, configure trusted proxies, cap request-body and chat-message length, enforce a model-input/token budget, and verify provider-side quotas. A daily turn count alone does not bound the cost of one oversized prompt.

`check_m1_rollout_execution_record.py` validates a private execution record for one M1 rollout. It checks release artifact manifest use, required deployment phases, server preflight, runtime service health, post-deploy health/smoke, issue handling, rollback readiness and runtime data safety. It does not deploy code, connect SSH, read `.env`, start services, restart containers, run smoke tests or print private values. A passed report proves the operator record is complete enough for M1 audit; it does not prove autoscaling, multi-region HA, long-duration soak, real payment, booking, inventory lock or fulfillment.

```powershell
uv run python scripts\check_m1_rollout_execution_record.py --template --output <private-workdir>\m1-rollout-execution-record.local.json
uv run python scripts\check_m1_rollout_execution_record.py --draft-from-evidence --server-preflight-json <private-workdir>\server-preflight-report.json --postgres-redis-json <private-workdir>\postgres-redis-live-probe.json --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --output <private-workdir>\m1-rollout-execution-record.draft.json
uv run python scripts\check_m1_rollout_execution_record.py --record-json <private-workdir>\m1-rollout-execution-record.local.json --output <private-workdir>\m1-rollout-execution-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --json
```

`--draft-from-evidence` reads only explicit private JSON reports, refuses `.env`, `.runtime`, `.venv`, logs, vector stores, Git-workspace evidence files and raw URL/IP/secret-looking content, then backfills server preflight, PostgreSQL/Redis and workflow-derived statuses into a draft rollout record. The draft still requires manual owner, release artifact, deployment step, issue review, rollback and data-safety confirmation before it can pass final validation.

`check_m1_operations_review_record.py` validates the post-rollout operations review: evidence references, issue categories, root cause, mitigation, verification, lessons, follow-up actions and M1 overclaim boundaries. It does not inspect live infrastructure, query PostgreSQL, read Redis keys, inspect logs, call providers or restart services. Use it after the rollout record to preserve what was learned from disk, Docker, PostgreSQL/Redis, backup, rate limit, external API, RAG, rollback or monitoring findings.

```powershell
uv run python scripts\check_m1_operations_review_record.py --template --output <private-workdir>\m1-operations-review-record.local.json
uv run python scripts\check_m1_operations_review_record.py --draft-from-evidence --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --external-dependency-json <private-workdir>\external-dependency-resilience-report.json --output <private-workdir>\m1-operations-review-record.draft.json
uv run python scripts\check_m1_operations_review_record.py --record-json <private-workdir>\m1-operations-review-record.local.json --output <private-workdir>\m1-operations-review-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --json
```

`--draft-from-evidence` reads only explicit private JSON reports, refuses `.env`, `.runtime`, `.venv`, logs, vector stores, Git-workspace evidence files and raw URL/IP/secret-looking content, then backfills rollout, go/no-go, external dependency, server capacity, PostgreSQL/Redis, backup, restore drill feasibility, rate-limit, Docker disk remediation approval and rollback evidence statuses into a draft operations review. The draft does not replace human review, signoff, risk acceptance, lessons learned or follow-up ownership.

`check_probe_auth_readiness.py` verifies the probe authentication path before running live chat. Without `--execute-login`, it only reports whether a probe token or username/password pair is present in the current process environment; it does not read `.env`. With `--execute-login`, it validates the token/login path by calling `/api/v1/users/login` when needed and then `/api/v1/users/me`. It does not create conversations, call SSE chat, call LLMs, call travel providers, payment, booking, inventory lock or fulfillment APIs, and it does not echo URL, token, username, password, user id or response body.

`collect_live_chat_probe.py` defaults to plan-only `not_checked`. With `--execute`, it creates one probe conversation and sends one authenticated SSE（服务器发送事件）chat turn to `/api/v1/chat/stream/{conversation_id}`. Authentication can use `ZHIXING_PROBE_ACCESS_TOKEN`, or a probe username/password pair that first calls `/api/v1/users/login` to obtain a short-lived bearer token. This may call the configured LLM（大语言模型） or external provider APIs and writes runtime conversation/message records, so run it only with private probe auth and explicit approval for one live chat turn. The report does not echo the public URL, access token, username, password, prompt, conversation id or assistant text. A passed result proves only one authenticated live chat turn in the sampled window; it does not prove chat concurrency, autoscaling, long-duration stability, real payment, booking, inventory lock, ticketing or fulfillment.

`check_external_dependency_resilience_record.py` validates a private rollup record for LLM and external API readiness, timeout/retry policy, degradation drills, cost guardrails and tool failure monitoring. It reads only the operator-filled JSON record, blocks raw URL/IP/secret-looking values, and does not read `.env`, call providers, connect network, connect SSH, start services or print private target values. A passed report is M1 evidence that degradation and cost boundaries were recorded; it still does not prove provider SLA, hard quota enforcement, production HA, long-duration soak, real payment, booking, inventory lock or fulfillment.

```powershell
uv run python scripts\check_external_dependency_resilience_record.py --template --output <private-workdir>\external-dependency-resilience-record.local.json
uv run python scripts\check_external_dependency_resilience_record.py --record-json <private-workdir>\external-dependency-resilience-record.local.json --output <private-workdir>\external-dependency-resilience-report.json
uv run python scripts\collect_m1_go_no_go_evidence.py --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --json
```

Keep the private record in the operator evidence workspace. Do not copy it into the public repository or deployment container just to make server-side smoke commands shorter.

`render_m1_live_evidence_summary.py` turns a private M1 go/no-go JSON into a redacted Markdown evidence summary. It does not run live probes, SSH, health checks, chat turns, deletion, backup or restore. It is meant to summarize already collected evidence across live server, PostgreSQL/Redis, backup schedule, restore drill feasibility, capacity snapshot, low-risk concurrency, rate limit, probe auth, live chat, Docker disk plan and remediation approval, external dependency resilience, rollout execution and post-rollout operations review sections. Keep the source JSON and rendered Markdown in a private workdir when they contain operational evidence; commit only the script and public template.

`build_m1_evidence_bundle.py` packages a private M1 go/no-go JSON into `m1-go-no-go.redacted.json`, `m1-live-evidence-summary.md`, `README.md` and `manifest.json` with SHA-256 digests. It does not run live probes, SSH, health checks, chat turns, deployment, deletion, backup or restore, and it does not read `.env`. By default it blocks writing inside the Git workspace; use a private output directory outside the repo for real evidence bundles. The bundle is an audit artifact, not proof that the live checks were executed.

`run_m1_private_live_evidence_workflow.py` is the private orchestration wrapper for live evidence collection. Plan mode writes nothing and runs no SSH, network probe, auth login or chat; add `--markdown` to render a redacted operator checklist that includes the recommended execution order, live inputs, private record JSON checks, blockers and the exact next command. Execute mode first checks variable-level private inputs; if the selected live sections lack `ZHIXING_PUBLIC_BASE_URL`, SSH target variables, deploy directory, backup directory or probe credentials, it returns `blocked` before starting live probes. It also checks selected private record JSON inputs for external dependency resilience, rollout execution, operations review and live chat execution approval: missing paths, files inside the Git workspace, secret-like/runtime paths such as `.env`, `.runtime`, `.venv`, logs or vector stores, and nonexistent files all block before live probes start. With `--execute --include-standard-live-probes`, it collects the selected live evidence, writes `m1-go-no-go.private.json`, renders `m1-live-evidence-summary.md`, records artifact SHA-256 digests, and builds an `m1-evidence-bundle/` under the explicit private output directory. It can also include `--include-external-dependency-resilience-record --external-dependency-record-json <private-record>`, `--include-m1-rollout-execution-record --m1-rollout-record-json <private-record>` and `--include-m1-operations-review-record --m1-operations-review-json <private-record>`; these read only private JSON records and are not live probes. It still does not read `.env`, deploy code, start services, delete files, print the public URL, print the SSH target, print the deploy directory, print private record paths or print credentials. `--execute-live-chat-probe` is separate and requires `--live-chat-probe-approval-json <private-approval-report-json>` because it creates one probe conversation and may call LLM/external APIs.

```powershell
uv run python scripts\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes
uv run python scripts\run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\m1-operations-review-record.local.json --execute
uv run python scripts\run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --execute --execute-probe-auth-login
uv run python scripts\run_m1_private_live_evidence_workflow.py --output-dir <private-workdir>\m1-live-evidence-workflow --include-standard-live-probes --include-live-chat-probe --live-chat-probe-approval-json <private-workdir>\live-chat-probe-execution-approval-report.json --execute --execute-probe-auth-login --execute-live-chat-probe
```

`check_m1_private_evidence_signoff.py` validates the private workflow output before M1 release-owner signoff. It reads only the private `workflow-report.json`, referenced evidence artifacts and optional rollout / operations review validation reports, verifies SHA-256 digests, requires the standard live sections by default, blocks evidence stored inside the Git workspace, blocks raw URL/IP/secret-looking values, and requires an explicit signoff owner. If the workflow selected rollout or operations review sections, the matching validation report must be provided and `passed`. It does not read `.env`, run live probes, connect SSH, start services or print private paths.

```powershell
uv run python scripts\check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-owner <release-owner> --output <private-workdir>\m1-live-evidence-workflow\signoff.json
uv run python scripts\check_m1_private_evidence_signoff.py --workflow-report-json <private-workdir>\m1-live-evidence-workflow\workflow-report.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-owner <release-owner> --release-decision conditional_go --allow-conditional-go --risk-acceptance "<accepted M1 degraded evidence scope>" --markdown
```

`render_m1_deployment_evidence_matrix.py` reads only explicit private JSON reports and renders a redacted evidence matrix across M1 launch inputs, go/no-go, rollout execution, operations review and private signoff. Missing, blocked, unsafe or version-mismatched reports block the matrix. A passed matrix supports M1 controlled-trial readiness only; it still does not prove full production HA, autoscaling, long-duration soak, real payment, booking, inventory lock, ticketing or fulfillment.

```powershell
uv run python scripts\render_m1_deployment_evidence_matrix.py --launch-inputs-report-json <private-workdir>\m1-launch-inputs-report.json --go-no-go-json <private-workdir>\m1-live-evidence-workflow\m1-go-no-go.private.json --rollout-report-json <private-workdir>\m1-rollout-execution-report.json --operations-review-report-json <private-workdir>\m1-operations-review-report.json --signoff-report-json <private-workdir>\m1-live-evidence-workflow\signoff.json --markdown --output <private-workdir>\m1-deployment-evidence-matrix.md
```

## Common Deployment Issues

- SSH host key changed: stop and compare the new fingerprint with the server console or private deployment record before updating `known_hosts`. Do not bypass the warning blindly.
- Shell script reports `set: -^M: invalid option`: the script was uploaded with CRLF（Windows 换行） to a Linux shell. Re-upload the repository version with LF（Unix 换行）, or convert the temporary server copy before rerunning.
- Public HTTP returns `308 Permanent Redirect`: this is normal when HTTPS is enforced by the reverse proxy. Use the HTTPS URL for public acceptance.
- Legacy flat deployment layout: if code, `.env`, runtime data and `docker-compose.yml` still live directly under `<deploy-dir>`, use the compatibility path or migrate to `current` / `shared` only after a dry run. Never let a release-switch operation overwrite runtime `.env`, vector stores, logs or database volumes.
- `Error response from daemon: Conflict. The container name "/zhixing-redis" is already in use`: check whether Compose inferred project `current` from the symlinked release directory. Set or preserve `ZHIXING_COMPOSE_PROJECT_NAME=langgraph-travel-planner`, then recreate only the affected stateless services such as `backend` / `caddy`; do not delete PostgreSQL / Redis volumes to resolve a project-name mismatch.

## Rollback

Each deployment should create a code backup. Rollback copies code back and refreshes runtime containers; it must not overwrite `.env`, database volumes or vector stores from a local machine.

```powershell
$remoteRollback = @'
set -eu
cd "$ZHIXING_DEPLOY_DIR"
previous="$(ls -dt releases/* | sed -n '2p')"
test -n "$previous"
ln -sfn "$previous" .current.rollback
mv -Tf .current.rollback current
cd current
ZHIXING_SHARED_DATA_DIR="$ZHIXING_DEPLOY_DIR/shared/data" \
ZHIXING_SHARED_LOG_DIR="$ZHIXING_DEPLOY_DIR/shared/logs" \
ZHIXING_SHARED_BACKUP_DIR="$ZHIXING_DEPLOY_DIR/shared/backups" \
  docker compose --env-file "$ZHIXING_DEPLOY_DIR/shared/.env" up -d --build backend caddy
ZHIXING_SHARED_DATA_DIR="$ZHIXING_DEPLOY_DIR/shared/data" \
ZHIXING_SHARED_LOG_DIR="$ZHIXING_DEPLOY_DIR/shared/logs" \
ZHIXING_SHARED_BACKUP_DIR="$ZHIXING_DEPLOY_DIR/shared/backups" \
  docker compose ps
'@

$remoteRollbackPath = Join-Path $env:TEMP "zhixing-rollback.sh"
[System.IO.File]::WriteAllText($remoteRollbackPath, $remoteRollback, [System.Text.UTF8Encoding]::new($false))
scp $remoteRollbackPath "${target}:/tmp/zhixing-rollback.sh"
ssh $target "ZHIXING_DEPLOY_DIR='$env:ZHIXING_DEPLOY_DIR' sh /tmp/zhixing-rollback.sh"
```
