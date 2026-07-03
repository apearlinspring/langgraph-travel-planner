"""Run or plan the private M1 live evidence workflow.

This workflow coordinates the existing M1 go/no-go collector, redacted live
evidence summary renderer and evidence bundle builder. It never reads `.env`
files. Plan mode performs no network, SSH, chat, backup, deployment or file
writes. Execute mode writes only to an explicit private output directory and
runs live probes only for the requested sections.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_m1_evidence_bundle import build_m1_evidence_bundle_report  # noqa: E402
from scripts.collect_m1_go_no_go_evidence import build_m1_go_no_go_report  # noqa: E402
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402
from scripts.render_m1_live_evidence_summary import (  # noqa: E402
    build_m1_live_evidence_summary_markdown,
)


M1_PRIVATE_LIVE_EVIDENCE_WORKFLOW_VERSION = "m1_private_live_evidence_workflow.v1"
DEFAULT_PUBLIC_BASE_URL_ENV = "ZHIXING_PUBLIC_BASE_URL"
DEFAULT_DEPLOY_USER_ENV = "ZHIXING_DEPLOY_USER"
DEFAULT_DEPLOY_HOST_ENV = "ZHIXING_DEPLOY_HOST"
DEFAULT_DEPLOY_DIR_ENV = "ZHIXING_DEPLOY_DIR"
DEFAULT_BACKUP_DIR_ENV = "ZHIXING_BACKUP_DIR"
DEFAULT_PROBE_ACCESS_TOKEN_ENV = "ZHIXING_PROBE_ACCESS_TOKEN"
DEFAULT_PROBE_USERNAME_ENV = "ZHIXING_PROBE_USERNAME"
DEFAULT_PROBE_PASSWORD_ENV = "ZHIXING_PROBE_PASSWORD"
PRIVATE_WORKDIR_PLACEHOLDER = "<private-workdir>"
LIVE_CHAT_PROBE_APPROVAL_REPORT_PLACEHOLDER = (
    f"{PRIVATE_WORKDIR_PLACEHOLDER}\\live-chat-probe-execution-approval-report.json"
)
LIVE_CHAT_CONCURRENCY_PROBE_REPORT_PLACEHOLDER = (
    f"{PRIVATE_WORKDIR_PLACEHOLDER}\\live-chat-concurrency-probe.json"
)
URL_PATTERN = re.compile(r"https?://[^\s`'\"<>()\[\]{}|]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
FORBIDDEN_PRIVATE_RECORD_FILE_PARTS = {
    ".env",
    ".runtime",
    ".venv",
    "logs",
    "vectorstore",
    "vectorstore_internal",
}
SENSITIVE_ENV_NAME_MARKERS = (
    "TOKEN",
    "PASSWORD",
    "SECRET",
    "COOKIE",
    "AUTH",
    "USERNAME",
    "EMAIL",
)

STANDARD_LIVE_SECTION_KEYS = {
    "live_server_probe",
    "postgres_redis_live_probe",
    "backup_schedule_live_probe",
    "docker_disk_cleanup_plan",
    "live_concurrency_probe",
    "probe_auth_readiness",
    "server_capacity_snapshot",
    "rate_limit_live_probe",
}
LIVE_PROBE_SECTION_KEYS = STANDARD_LIVE_SECTION_KEYS | {"live_chat_probe"}
SSH_SECTION_KEYS = {
    "live_server_probe",
    "postgres_redis_live_probe",
    "backup_schedule_live_probe",
    "docker_disk_cleanup_plan",
    "server_capacity_snapshot",
}
PUBLIC_URL_SECTION_KEYS = {
    "live_server_probe",
    "live_concurrency_probe",
    "probe_auth_readiness",
    "live_chat_probe",
    "rate_limit_live_probe",
}


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _value(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _sensitive_env_values(environ: Mapping[str, str]) -> tuple[str, ...]:
    values: set[str] = set()
    for key, raw_value in environ.items():
        if not any(marker in str(key).upper() for marker in SENSITIVE_ENV_NAME_MARKERS):
            continue
        value = str(raw_value).strip()
        if len(value) >= 8:
            values.add(value)
    return tuple(sorted(values, key=len, reverse=True))


def _redact_private_text(value: str, *, extra_secrets: Iterable[str] = ()) -> str:
    redacted = redact_text(str(value))
    for secret in extra_secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
    redacted = URL_PATTERN.sub("[REDACTED_URL]", redacted)
    return IPV4_PATTERN.sub("[REDACTED_IP]", redacted)


def _redact_private_data(value: Any, *, max_depth: int = 12, extra_secrets: Iterable[str] = ()) -> Any:
    value = redact_data(value, max_depth=max_depth)
    if max_depth < 0:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(key): _redact_private_data(item, max_depth=max_depth - 1, extra_secrets=extra_secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_private_data(item, max_depth=max_depth - 1, extra_secrets=extra_secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(
            _redact_private_data(item, max_depth=max_depth - 1, extra_secrets=extra_secrets)
            for item in value
        )
    if isinstance(value, str):
        return _redact_private_text(value, extra_secrets=extra_secrets)
    return value


def _json_dumps(value: Any, *, extra_secrets: Iterable[str] = ()) -> str:
    safe_value = _redact_private_data(value, extra_secrets=extra_secrets)
    return json.dumps(safe_value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else _redact_private_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _status_label(value: Any) -> str:
    return "yes" if value is True else "no" if value is False else _markdown_cell(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_ssh_target(
    *,
    environ: Mapping[str, str],
    ssh_target: str | None,
    deploy_user_env: str,
    deploy_host_env: str,
) -> str | None:
    if ssh_target and ssh_target.strip():
        return ssh_target.strip()
    deploy_user = _value(environ, deploy_user_env)
    deploy_host = _value(environ, deploy_host_env)
    if deploy_user and deploy_host:
        return f"{deploy_user}@{deploy_host}"
    return None


def _selected_sections(
    *,
    include_standard_live_probes: bool,
    include_live_server_probe: bool,
    include_postgres_redis_live_probe: bool,
    include_backup_schedule_live_probe: bool,
    include_docker_disk_cleanup_plan: bool,
    include_live_concurrency_probe: bool,
    include_probe_auth_readiness: bool,
    include_live_chat_probe: bool,
    include_live_chat_concurrency_probe: bool,
    include_server_capacity_snapshot: bool,
    include_rate_limit_live_probe: bool,
    include_external_dependency_resilience_record: bool,
    include_m1_rollout_execution_record: bool,
    include_m1_operations_review_record: bool,
    execute_probe_auth_login: bool,
    execute_live_chat_probe: bool,
) -> set[str]:
    sections: set[str] = set()
    if include_standard_live_probes:
        sections.update(STANDARD_LIVE_SECTION_KEYS)
    if include_live_server_probe:
        sections.add("live_server_probe")
    if include_postgres_redis_live_probe:
        sections.add("postgres_redis_live_probe")
    if include_backup_schedule_live_probe:
        sections.add("backup_schedule_live_probe")
    if include_docker_disk_cleanup_plan:
        sections.add("docker_disk_cleanup_plan")
    if include_live_concurrency_probe:
        sections.add("live_concurrency_probe")
    if include_probe_auth_readiness or execute_probe_auth_login:
        sections.add("probe_auth_readiness")
    if include_live_chat_probe or execute_live_chat_probe:
        sections.add("live_chat_probe")
        sections.add("probe_auth_readiness")
    if include_live_chat_concurrency_probe:
        sections.add("live_chat_concurrency_probe")
    if include_server_capacity_snapshot:
        sections.add("server_capacity_snapshot")
    if include_rate_limit_live_probe:
        sections.add("rate_limit_live_probe")
    if include_external_dependency_resilience_record:
        sections.add("external_dependency_resilience_record")
    if include_m1_rollout_execution_record:
        sections.add("m1_rollout_execution_record")
    if include_m1_operations_review_record:
        sections.add("m1_operations_review_record")
    return sections


def _required_env_vars(sections: set[str]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    if sections & PUBLIC_URL_SECTION_KEYS:
        requirements.append(
            {
                "env_var": DEFAULT_PUBLIC_BASE_URL_ENV,
                "label": "Public base URL",
                "value_echoed": False,
            }
        )
    if sections & SSH_SECTION_KEYS:
        requirements.extend(
            [
                {
                    "env_var": DEFAULT_DEPLOY_USER_ENV,
                    "label": "SSH deploy user",
                    "value_echoed": False,
                },
                {
                    "env_var": DEFAULT_DEPLOY_HOST_ENV,
                    "label": "SSH deploy host",
                    "value_echoed": False,
                },
                {
                    "env_var": DEFAULT_DEPLOY_DIR_ENV,
                    "label": "Remote deploy directory",
                    "value_echoed": False,
                },
            ]
        )
    if "backup_schedule_live_probe" in sections:
        requirements.append(
            {
                "env_var": DEFAULT_BACKUP_DIR_ENV,
                "label": "Remote backup directory",
                "value_echoed": False,
            }
        )
    if "probe_auth_readiness" in sections or "live_chat_probe" in sections:
        requirements.append(
            {
                "env_var": "ZHIXING_PROBE_ACCESS_TOKEN or ZHIXING_PROBE_USERNAME/ZHIXING_PROBE_PASSWORD",
                "label": "Private probe authentication",
                "value_echoed": False,
            }
        )
    return requirements


def _input_statuses(
    *,
    environ: Mapping[str, str],
    sections: set[str],
    resolved_base_url: str | None,
    base_url_env: str,
    resolved_ssh_target: str | None,
    deploy_user_env: str,
    deploy_host_env: str,
    resolved_deploy_dir: str | None,
    deploy_dir_env: str,
    resolved_backup_dir: str | None,
    backup_dir_env: str,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    if sections & PUBLIC_URL_SECTION_KEYS:
        statuses.append(
            {
                "key": "public_base_url",
                "env_var": base_url_env,
                "label": "Public base URL",
                "present": bool(resolved_base_url),
                "value_echoed": False,
            }
        )
    if sections & SSH_SECTION_KEYS:
        statuses.extend(
            [
                {
                    "key": "ssh_target",
                    "env_var": f"{deploy_user_env}+{deploy_host_env}",
                    "label": "SSH target",
                    "present": bool(resolved_ssh_target),
                    "value_echoed": False,
                },
                {
                    "key": "deploy_dir",
                    "env_var": deploy_dir_env,
                    "label": "Remote deploy directory",
                    "present": bool(resolved_deploy_dir),
                    "value_echoed": False,
                },
            ]
        )
    if "backup_schedule_live_probe" in sections:
        statuses.append(
            {
                "key": "backup_dir",
                "env_var": backup_dir_env,
                "label": "Remote backup directory",
                "present": bool(resolved_backup_dir),
                "value_echoed": False,
            }
        )
    if "probe_auth_readiness" in sections or "live_chat_probe" in sections:
        has_token = bool(_value(environ, DEFAULT_PROBE_ACCESS_TOKEN_ENV))
        has_user_password = bool(_value(environ, DEFAULT_PROBE_USERNAME_ENV)) and bool(
            _value(environ, DEFAULT_PROBE_PASSWORD_ENV)
        )
        statuses.append(
            {
                "key": "probe_auth",
                "env_var": (
                    f"{DEFAULT_PROBE_ACCESS_TOKEN_ENV} or "
                    f"{DEFAULT_PROBE_USERNAME_ENV}+{DEFAULT_PROBE_PASSWORD_ENV}"
                ),
                "label": "Private probe authentication",
                "present": has_token or has_user_password,
                "value_echoed": False,
            }
        )
    return statuses


def _missing_inputs(input_statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": item.get("key"),
            "env_var": item.get("env_var"),
            "label": item.get("label"),
            "value_echoed": False,
        }
        for item in input_statuses
        if not item.get("present")
    ]


def _is_forbidden_private_record_path(path: Path) -> bool:
    lowered_name = path.name.lower()
    if lowered_name.startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_PRIVATE_RECORD_FILE_PARTS)


def _private_record_input_statuses(
    *,
    sections: set[str],
    external_dependency_record_json: Path | None,
    m1_rollout_record_json: Path | None,
    m1_operations_review_json: Path | None,
    live_chat_probe_approval_json: Path | None,
    live_chat_concurrency_probe_json: Path | None,
    require_live_chat_probe_approval: bool,
) -> list[dict[str, Any]]:
    specs = [
        {
            "section": "external_dependency_resilience_record",
            "key": "external_dependency_record_json",
            "label": "External dependency resilience record JSON",
            "path": external_dependency_record_json,
        },
        {
            "section": "m1_rollout_execution_record",
            "key": "m1_rollout_record_json",
            "label": "M1 rollout execution record JSON",
            "path": m1_rollout_record_json,
        },
        {
            "section": "m1_operations_review_record",
            "key": "m1_operations_review_json",
            "label": "M1 operations review record JSON",
            "path": m1_operations_review_json,
        },
    ]
    if "live_chat_probe" in sections and (
        require_live_chat_probe_approval or live_chat_probe_approval_json is not None
    ):
        specs.append(
            {
                "section": "live_chat_probe",
                "key": "live_chat_probe_approval_json",
                "label": "Live chat probe execution approval report JSON",
                "path": live_chat_probe_approval_json,
            }
        )
    if "live_chat_concurrency_probe" in sections:
        specs.append(
            {
                "section": "live_chat_concurrency_probe",
                "key": "live_chat_concurrency_probe_json",
                "label": "Live chat concurrency probe JSON",
                "path": live_chat_concurrency_probe_json,
            }
        )
    statuses: list[dict[str, Any]] = []
    for spec in specs:
        if spec["section"] not in sections:
            continue
        path = spec["path"]
        resolved_path = path.resolve() if isinstance(path, Path) else None
        inside_project = _is_relative_to(resolved_path, PROJECT_ROOT) if resolved_path is not None else False
        forbidden_path = _is_forbidden_private_record_path(resolved_path) if resolved_path is not None else False
        statuses.append(
            {
                "section": spec["section"],
                "key": spec["key"],
                "label": spec["label"],
                "present": resolved_path is not None,
                "exists": resolved_path.exists() if resolved_path is not None else False,
                "inside_project": inside_project,
                "forbidden_path": forbidden_path,
                "path_echoed": False,
            }
        )
    return statuses


def _private_record_blockers(record_statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in record_statuses:
        base = {
            "section": item.get("section"),
            "key": item.get("key"),
            "label": item.get("label"),
            "path_echoed": False,
        }
        if not item.get("present"):
            blockers.append(
                {
                    **base,
                    "reason": "Selected private evidence record JSON path is missing.",
                }
            )
            continue
        if item.get("inside_project"):
            blockers.append(
                {
                    **base,
                    "reason": "Private evidence record JSON must stay outside the Git workspace.",
                }
            )
        if item.get("forbidden_path"):
            blockers.append(
                {
                    **base,
                    "reason": "Private evidence record JSON path points to a forbidden runtime or secret-like location.",
                }
            )
        if not item.get("exists"):
            blockers.append(
                {
                    **base,
                    "reason": "Private evidence record JSON file does not exist.",
                }
            )
    return blockers


def _build_command_plan(sections: set[str]) -> list[dict[str, Any]]:
    args = [
        "python scripts/run_m1_private_live_evidence_workflow.py",
        "--output-dir",
        f"{PRIVATE_WORKDIR_PLACEHOLDER}\\m1-live-evidence-workflow",
        "--include-standard-live-probes",
        "--execute",
    ]
    if "live_chat_probe" in sections:
        args.extend(
            [
                "--include-live-chat-probe",
                "--live-chat-probe-approval-json",
                LIVE_CHAT_PROBE_APPROVAL_REPORT_PLACEHOLDER,
                "--execute-live-chat-probe",
            ]
        )
    if "live_chat_concurrency_probe" in sections:
        args.extend(
            [
                "--include-live-chat-concurrency-probe",
                "--live-chat-concurrency-probe-json",
                LIVE_CHAT_CONCURRENCY_PROBE_REPORT_PLACEHOLDER,
            ]
        )
    if "external_dependency_resilience_record" in sections:
        args.extend(
            [
                "--include-external-dependency-resilience-record",
                "--external-dependency-record-json",
                f"{PRIVATE_WORKDIR_PLACEHOLDER}\\external-dependency-resilience-record.local.json",
            ]
        )
    if "m1_rollout_execution_record" in sections:
        args.extend(
            [
                "--include-m1-rollout-execution-record",
                "--m1-rollout-record-json",
                f"{PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-record.local.json",
            ]
        )
    if "m1_operations_review_record" in sections:
        args.extend(
            [
                "--include-m1-operations-review-record",
                "--m1-operations-review-json",
                f"{PRIVATE_WORKDIR_PLACEHOLDER}\\m1-operations-review-record.local.json",
            ]
        )
    return [
        {
            "key": "private_live_evidence_workflow",
            "command": " ".join(args),
            "runs_when": "after deployment, against a private live target with env vars already injected",
            "stores_outputs_in_git": False,
        }
    ]


def _build_execution_sequence_plan(sections: set[str]) -> list[dict[str, Any]]:
    """Build the recommended M1 execution order without running anything."""

    workflow_flags = [
        "--output-dir",
        f"{PRIVATE_WORKDIR_PLACEHOLDER}\\m1-live-evidence-workflow",
        "--include-standard-live-probes",
    ]
    if "external_dependency_resilience_record" in sections:
        workflow_flags.extend(
            [
                "--include-external-dependency-resilience-record",
                "--external-dependency-record-json",
                f"{PRIVATE_WORKDIR_PLACEHOLDER}\\external-dependency-resilience-record.local.json",
            ]
        )
    if "m1_rollout_execution_record" in sections:
        workflow_flags.extend(
            [
                "--include-m1-rollout-execution-record",
                "--m1-rollout-record-json",
                f"{PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-record.local.json",
            ]
        )
    if "m1_operations_review_record" in sections:
        workflow_flags.extend(
            [
                "--include-m1-operations-review-record",
                "--m1-operations-review-json",
                f"{PRIVATE_WORKDIR_PLACEHOLDER}\\m1-operations-review-record.local.json",
            ]
        )
    if "live_chat_probe" in sections:
        workflow_flags.append("--include-live-chat-probe")
    if "live_chat_concurrency_probe" in sections:
        workflow_flags.extend(
            [
                "--include-live-chat-concurrency-probe",
                "--live-chat-concurrency-probe-json",
                LIVE_CHAT_CONCURRENCY_PROBE_REPORT_PLACEHOLDER,
            ]
        )

    live_chat_approval_report = LIVE_CHAT_PROBE_APPROVAL_REPORT_PLACEHOLDER
    operations_review_draft_command_parts = [
        "uv run python scripts\\check_m1_operations_review_record.py --draft-from-evidence",
        f"--rollout-report-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-report.json",
        f"--go-no-go-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-live-evidence-workflow\\m1-go-no-go.private.json",
    ]
    if "external_dependency_resilience_record" in sections:
        operations_review_draft_command_parts.append(
            f"--external-dependency-json {PRIVATE_WORKDIR_PLACEHOLDER}\\external-dependency-resilience-report.json"
        )
    operations_review_draft_command_parts.append(
        f"--output {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-operations-review-record.draft.json"
    )
    signoff_command_parts = [
        "uv run python scripts\\check_m1_private_evidence_signoff.py",
        f"--workflow-report-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-live-evidence-workflow\\workflow-report.json",
    ]
    if "m1_rollout_execution_record" in sections:
        signoff_command_parts.append(
            f"--rollout-report-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-report.json"
        )
    if "m1_operations_review_record" in sections:
        signoff_command_parts.append(
            f"--operations-review-report-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-operations-review-report.json"
        )
    signoff_command_parts.extend(
        [
            "--signoff-owner <release-owner>",
            f"--output {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-live-evidence-workflow\\signoff.json",
        ]
    )

    sequence = [
        {
            "order": 1,
            "phase": "m1_launch_inputs_template",
            "command": (
                "uv run python scripts\\check_m1_launch_inputs.py --template "
                f"--output {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-launch-inputs.local.json"
            ),
            "purpose": "Create the non-secret M1 input template in a private workdir.",
            "writes_private_files": True,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
        {
            "order": 2,
            "phase": "m1_launch_inputs_validate",
            "command": (
                "uv run python scripts\\check_m1_launch_inputs.py "
                f"--input-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-launch-inputs.local.json --json"
            ),
            "purpose": "Validate server, domain, backup, monitoring, owner and budget declarations.",
            "writes_private_files": False,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
        {
            "order": 3,
            "phase": "server_preflight",
            "command": "uv run python scripts\\check_server_preflight_readiness.py --json",
            "purpose": "Validate server preflight declarations before any live probe.",
            "writes_private_files": False,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
        {
            "order": 4,
            "phase": "server_preflight_live",
            "command": (
                "uv run python scripts\\check_server_preflight_readiness.py "
                "--check-docker --check-deploy-dir --check-disk --check-health-url --json"
            ),
            "purpose": "Run explicit server and public health checks only after private env vars are injected.",
            "writes_private_files": False,
            "connects_ssh": False,
            "touches_network": True,
            "reads_dotenv": False,
        },
        {
            "order": 5,
            "phase": "postgres_redis_live_probe",
            "command": (
                "uv run python scripts\\collect_postgres_redis_live_probe.py "
                "--ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --timeout-seconds 90 --markdown"
            ),
            "purpose": "Collect redacted PostgreSQL / Redis container, health, mount and port evidence.",
            "writes_private_files": False,
            "connects_ssh": True,
            "touches_network": True,
            "reads_dotenv": False,
        },
        {
            "order": 6,
            "phase": "private_workflow_preflight",
            "command": "uv run python scripts\\run_m1_private_live_evidence_workflow.py --markdown "
            + " ".join(workflow_flags),
            "purpose": "Render the final private live evidence preflight checklist; no live probes are started.",
            "writes_private_files": False,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
        {
            "order": 7,
            "phase": "private_workflow_execute",
            "command": "uv run python scripts\\run_m1_private_live_evidence_workflow.py "
            + " ".join(workflow_flags)
            + " --execute",
            "purpose": "Collect selected live evidence and write the private go/no-go, summary and bundle artifacts.",
            "writes_private_files": True,
            "connects_ssh": bool(sections & SSH_SECTION_KEYS),
            "touches_network": bool(sections & (PUBLIC_URL_SECTION_KEYS | SSH_SECTION_KEYS)),
            "reads_dotenv": False,
        },
        {
            "order": 8,
            "phase": "rollout_record_draft_from_evidence",
            "command": (
                "uv run python scripts\\check_m1_rollout_execution_record.py --draft-from-evidence "
                f"--server-preflight-json {PRIVATE_WORKDIR_PLACEHOLDER}\\server-preflight-report.json "
                f"--postgres-redis-json {PRIVATE_WORKDIR_PLACEHOLDER}\\postgres-redis-live-probe.json "
                f"--workflow-report-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-live-evidence-workflow\\workflow-report.json "
                f"--output {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-record.draft.json"
            ),
            "purpose": "Backfill a private rollout execution record draft from collected evidence; manual signoff is still required.",
            "writes_private_files": True,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
        {
            "order": 9,
            "phase": "rollout_record_validate",
            "command": (
                "uv run python scripts\\check_m1_rollout_execution_record.py "
                f"--record-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-record.local.json "
                f"--output {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-rollout-execution-report.json"
            ),
            "purpose": "Validate the manually completed rollout execution record before using it as review evidence.",
            "writes_private_files": True,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
            "requires_manual_completion": True,
        },
        {
            "order": 10,
            "phase": "operations_review_draft_from_evidence",
            "command": " ".join(operations_review_draft_command_parts),
            "purpose": "Backfill a private post-rollout operations review draft from rollout, go/no-go and available external dependency evidence.",
            "writes_private_files": True,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
        {
            "order": 11,
            "phase": "operations_review_validate",
            "command": (
                "uv run python scripts\\check_m1_operations_review_record.py "
                f"--record-json {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-operations-review-record.local.json "
                f"--output {PRIVATE_WORKDIR_PLACEHOLDER}\\m1-operations-review-report.json"
            ),
            "purpose": "Validate the manually completed operations review before final evidence signoff.",
            "writes_private_files": True,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
            "requires_manual_completion": True,
        },
        {
            "order": 12,
            "phase": "private_evidence_signoff",
            "command": " ".join(signoff_command_parts),
            "purpose": "Verify evidence hashes, redaction boundary, private output location, review reports and release-owner signoff.",
            "writes_private_files": True,
            "connects_ssh": False,
            "touches_network": False,
            "reads_dotenv": False,
        },
    ]
    if "live_chat_probe" in sections:
        sequence[7:7] = (
            {
                "order": 7,
                "phase": "live_chat_probe_execution_approval_template",
                "command": (
                    "uv run python scripts\\check_live_chat_probe_execution_approval.py "
                    f"--template --output {PRIVATE_WORKDIR_PLACEHOLDER}\\live-chat-probe-execution-approval.local.json"
                ),
                "purpose": "Create the private approval template before any authenticated chat probe is allowed.",
                "writes_private_files": True,
                "connects_ssh": False,
                "touches_network": False,
                "reads_dotenv": False,
                "requires_manual_completion": True,
            },
            {
                "order": 8,
                "phase": "live_chat_probe_execution_approval_validate",
                "command": (
                    "uv run python scripts\\check_live_chat_probe_execution_approval.py "
                    f"--approval-json {PRIVATE_WORKDIR_PLACEHOLDER}\\live-chat-probe-execution-approval.local.json "
                    f"--json --output {live_chat_approval_report}"
                ),
                "purpose": "Validate explicit approval; this checker does not touch network, auth, chat or `.env`.",
                "writes_private_files": True,
                "connects_ssh": False,
                "touches_network": False,
                "reads_dotenv": False,
            },
            {
                "order": 9,
                "phase": "private_workflow_live_chat_execute",
                "command": "uv run python scripts\\run_m1_private_live_evidence_workflow.py "
                + " ".join(
                    workflow_flags
                    + [
                        "--live-chat-probe-approval-json",
                        live_chat_approval_report,
                    ]
                )
                + " --execute --execute-probe-auth-login --execute-live-chat-probe",
                "purpose": "Optional one-turn authenticated SSE chat probe; requires passed approval and may call LLM or external APIs.",
                "writes_private_files": True,
                "connects_ssh": bool(sections & SSH_SECTION_KEYS),
                "touches_network": True,
                "reads_dotenv": False,
                "may_call_external_apis": True,
            },
        )
        for index, item in enumerate(sequence, start=1):
            item["order"] = index
    return sequence


def _workflow_status(go_no_go_report: Mapping[str, Any], bundle_report: Mapping[str, Any]) -> str:
    if bundle_report.get("status") == "blocked":
        return "blocked"
    go_status = str(go_no_go_report.get("status") or "not_checked")
    if go_status in {"passed", "degraded", "warning"}:
        return "passed" if go_status == "passed" else "degraded"
    return "blocked"


def _mark_no_execution(report: dict[str, Any]) -> None:
    policy = report.get("policy")
    if not isinstance(policy, dict):
        return
    policy["runs_live_probes"] = False
    policy["connects_ssh"] = False
    policy["writes_files"] = False
    policy["may_call_auth_endpoint"] = False
    policy["may_call_external_apis"] = False
    policy["may_write_runtime_artifacts"] = False
    for key in (
        "reads_external_dependency_resilience_record",
        "reads_m1_rollout_execution_record",
        "reads_m1_operations_review_record",
        "reads_live_chat_probe_execution_approval",
        "reads_live_chat_concurrency_probe_evidence",
    ):
        if key in policy:
            policy[key] = False


def build_m1_private_live_evidence_workflow_markdown(report: Mapping[str, Any]) -> str:
    """Build a redacted operator checklist from a private workflow report."""

    safe_report = _redact_private_data(dict(report))
    if not isinstance(safe_report, dict):
        safe_report = {}
    policy = safe_report.get("policy") if isinstance(safe_report.get("policy"), Mapping) else {}
    target = safe_report.get("target") if isinstance(safe_report.get("target"), Mapping) else {}
    selected_sections = safe_report.get("selected_sections")
    section_count = len(selected_sections) if isinstance(selected_sections, list) else 0
    lines = [
        "# M1 Private Live Evidence Workflow Checklist（私有线上证据流水线预检）",
        "",
        "## 1. 总览",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Generated at | `{_markdown_cell(safe_report.get('generated_at'))}` |",
        f"| Selected sections | `{section_count}` |",
        f"| Output dir provided | `{_status_label(target.get('output_dir') is not None)}` |",
        f"| Output inside Git workspace | `{_status_label(target.get('output_dir_inside_project'))}` |",
        f"| Reads `.env` | `{_status_label(policy.get('reads_dotenv'))}` |",
        f"| Runs live probes | `{_status_label(policy.get('runs_live_probes'))}` |",
        f"| Connects SSH | `{_status_label(policy.get('connects_ssh'))}` |",
        f"| Writes files | `{_status_label(policy.get('writes_files'))}` |",
        f"| May call auth endpoint | `{_status_label(policy.get('may_call_auth_endpoint'))}` |",
        f"| May call external APIs | `{_status_label(policy.get('may_call_external_apis'))}` |",
        "",
        "## 2. 选择的证据项",
        "",
    ]
    if isinstance(selected_sections, list) and selected_sections:
        lines.extend(f"- `{_markdown_cell(section)}`" for section in selected_sections)
    else:
        lines.append("- No evidence sections selected.")

    lines.extend(
        [
            "",
            "## 3. 推荐执行顺序",
            "",
            "| 顺序 | 阶段 | 命令 | SSH | 网络 | 写私有文件 |",
            "|---|---|---|---|---|---|",
        ]
    )
    execution_sequence = safe_report.get("execution_sequence")
    if isinstance(execution_sequence, list) and execution_sequence:
        for item in execution_sequence:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('order'))} | "
                f"`{_markdown_cell(item.get('phase'))}` | "
                f"`{_markdown_cell(item.get('command'))}` | "
                f"`{_status_label(item.get('connects_ssh'))}` | "
                f"`{_status_label(item.get('touches_network'))}` | "
                f"`{_status_label(item.get('writes_private_files'))}` |"
            )
    else:
        lines.append("| - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 4. Live 输入检查",
            "",
            "| 输入 | 环境变量 | 是否已提供 | 值是否回显 |",
            "|---|---|---|---|",
        ]
    )
    input_statuses = safe_report.get("input_statuses")
    if isinstance(input_statuses, list) and input_statuses:
        for item in input_statuses:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('label'))} | "
                f"`{_markdown_cell(item.get('env_var'))}` | "
                f"`{_status_label(item.get('present'))}` | "
                f"`{_status_label(item.get('value_echoed'))}` |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.extend(
        [
            "",
            "## 5. 私有记录 JSON 检查",
            "",
            "| 记录 | 是否传入 | 文件存在 | 在 Git 工作区 | 敏感/运行时路径 | 路径是否回显 |",
            "|---|---|---|---|---|---|",
        ]
    )
    record_statuses = safe_report.get("private_record_statuses")
    if isinstance(record_statuses, list) and record_statuses:
        for item in record_statuses:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('label'))} | "
                f"`{_status_label(item.get('present'))}` | "
                f"`{_status_label(item.get('exists'))}` | "
                f"`{_status_label(item.get('inside_project'))}` | "
                f"`{_status_label(item.get('forbidden_path'))}` | "
                f"`{_status_label(item.get('path_echoed'))}` |"
            )
    else:
        lines.append("| - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 6. 阻断项",
            "",
            "| 类型 | Key | 说明 |",
            "|---|---|---|",
        ]
    )
    blockers_written = False
    blocked_reasons = safe_report.get("blocked_reasons")
    if isinstance(blocked_reasons, list):
        for item in blocked_reasons:
            if not isinstance(item, Mapping):
                continue
            blockers_written = True
            lines.append(
                "| "
                f"workflow | `{_markdown_cell(item.get('key'))}` | "
                f"{_markdown_cell(item.get('finding') or item.get('reason'))} |"
            )
    missing_inputs = safe_report.get("missing_inputs_for_user")
    if isinstance(missing_inputs, list):
        for item in missing_inputs:
            if not isinstance(item, Mapping):
                continue
            blockers_written = True
            lines.append(
                "| "
                f"live_input | `{_markdown_cell(item.get('key'))}` | "
                f"{_markdown_cell(item.get('label'))} is missing; value is not echoed. |"
            )
    record_blockers = safe_report.get("private_record_blockers")
    if isinstance(record_blockers, list):
        for item in record_blockers:
            if not isinstance(item, Mapping):
                continue
            blockers_written = True
            lines.append(
                "| "
                f"private_record | `{_markdown_cell(item.get('key'))}` | "
                f"{_markdown_cell(item.get('reason'))} |"
            )
    if not blockers_written:
        lines.append("| - | - | No blockers recorded. |")

    lines.extend(
        [
            "",
            "## 7. 本脚本建议命令",
            "",
        ]
    )
    command_plan = safe_report.get("command_plan")
    if isinstance(command_plan, list) and command_plan:
        for item in command_plan:
            if not isinstance(item, Mapping):
                continue
            lines.extend(
                [
                    f"- `{_markdown_cell(item.get('key'))}`",
                    "",
                    "```powershell",
                    _markdown_cell(item.get("command")),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("- No command plan generated.")

    lines.extend(
        [
            "## 8. 边界",
            "",
            "- 这份 checklist 不读取 `.env`，不打印真实 URL、SSH 目标、部署路径、私有记录路径或凭据。",
            "- 计划模式不证明服务器已部署成功；执行模式也不部署代码、不启动服务、不删除文件。",
            "- live chat 只有显式 `--execute-live-chat-probe` 才可能调用 LLM 或外部 API。",
            "- live chat concurrency 在本 workflow 中只导入已生成的私有脱敏 JSON，不重新执行并发 chat。",
            "- M1 仍不证明真实支付、真实预订、库存锁价、出票、履约、自动扩缩容、多地域高可用或长时间压测。",
            "",
        ]
    )
    return _redact_private_text("\n".join(lines))


def build_m1_private_live_evidence_workflow_report(
    *,
    environ: Mapping[str, str] | None = None,
    output_dir: Path | None = None,
    execute: bool = False,
    allow_project_output: bool = False,
    base_url: str | None = None,
    base_url_env: str = DEFAULT_PUBLIC_BASE_URL_ENV,
    live_server_ssh_target: str | None = None,
    deploy_user_env: str = DEFAULT_DEPLOY_USER_ENV,
    deploy_host_env: str = DEFAULT_DEPLOY_HOST_ENV,
    live_server_deploy_dir: str | None = None,
    deploy_dir_env: str = DEFAULT_DEPLOY_DIR_ENV,
    live_backup_dir: str | None = None,
    backup_dir_env: str = DEFAULT_BACKUP_DIR_ENV,
    include_standard_live_probes: bool = False,
    include_live_server_probe: bool = False,
    include_postgres_redis_live_probe: bool = False,
    include_backup_schedule_live_probe: bool = False,
    include_docker_disk_cleanup_plan: bool = False,
    include_live_concurrency_probe: bool = False,
    include_probe_auth_readiness: bool = False,
    include_live_chat_probe: bool = False,
    include_live_chat_concurrency_probe: bool = False,
    include_server_capacity_snapshot: bool = False,
    include_rate_limit_live_probe: bool = False,
    include_external_dependency_resilience_record: bool = False,
    external_dependency_record_json: Path | None = None,
    include_m1_rollout_execution_record: bool = False,
    m1_rollout_record_json: Path | None = None,
    include_m1_operations_review_record: bool = False,
    m1_operations_review_json: Path | None = None,
    live_chat_probe_approval_json: Path | None = None,
    live_chat_concurrency_probe_json: Path | None = None,
    execute_probe_auth_login: bool = False,
    execute_live_chat_probe: bool = False,
    concurrency_requests_per_endpoint: int = 30,
    concurrency_workers: int = 10,
    concurrency_max_p95_ms: float = 2000,
    rate_limit_request_count: int = 130,
    rate_limit_concurrency: int = 1,
    docker_disk_cleanup_max_candidates: int = 20,
    timeout_seconds: float = 90,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the private workflow report, optionally writing redacted artifacts."""

    env = environ if environ is not None else os.environ
    extra_secrets = _sensitive_env_values(env)
    now = generated_at or datetime.now(UTC)
    sections = _selected_sections(
        include_standard_live_probes=include_standard_live_probes,
        include_live_server_probe=include_live_server_probe,
        include_postgres_redis_live_probe=include_postgres_redis_live_probe,
        include_backup_schedule_live_probe=include_backup_schedule_live_probe,
        include_docker_disk_cleanup_plan=include_docker_disk_cleanup_plan,
        include_live_concurrency_probe=include_live_concurrency_probe,
        include_probe_auth_readiness=include_probe_auth_readiness,
        include_live_chat_probe=include_live_chat_probe,
        include_live_chat_concurrency_probe=include_live_chat_concurrency_probe,
        include_server_capacity_snapshot=include_server_capacity_snapshot,
        include_rate_limit_live_probe=include_rate_limit_live_probe,
        include_external_dependency_resilience_record=include_external_dependency_resilience_record,
        include_m1_rollout_execution_record=include_m1_rollout_execution_record,
        include_m1_operations_review_record=include_m1_operations_review_record,
        execute_probe_auth_login=execute_probe_auth_login,
        execute_live_chat_probe=execute_live_chat_probe,
    )
    resolved_output_dir = output_dir.resolve() if output_dir is not None else None
    output_inside_project = (
        _is_relative_to(resolved_output_dir, PROJECT_ROOT) if resolved_output_dir is not None else False
    )
    resolved_base_url = base_url or _value(env, base_url_env)
    resolved_ssh_target = _resolved_ssh_target(
        environ=env,
        ssh_target=live_server_ssh_target,
        deploy_user_env=deploy_user_env,
        deploy_host_env=deploy_host_env,
    )
    resolved_deploy_dir = live_server_deploy_dir or _value(env, deploy_dir_env)
    resolved_backup_dir = live_backup_dir or _value(env, backup_dir_env)
    input_statuses = _input_statuses(
        environ=env,
        sections=sections,
        resolved_base_url=resolved_base_url,
        base_url_env=base_url_env,
        resolved_ssh_target=resolved_ssh_target,
        deploy_user_env=deploy_user_env,
        deploy_host_env=deploy_host_env,
        resolved_deploy_dir=resolved_deploy_dir,
        deploy_dir_env=deploy_dir_env,
        resolved_backup_dir=resolved_backup_dir,
        backup_dir_env=backup_dir_env,
    )
    missing_inputs = _missing_inputs(input_statuses)
    private_record_statuses = _private_record_input_statuses(
        sections=sections,
        external_dependency_record_json=external_dependency_record_json,
        m1_rollout_record_json=m1_rollout_record_json,
        m1_operations_review_json=m1_operations_review_json,
        live_chat_probe_approval_json=live_chat_probe_approval_json,
        live_chat_concurrency_probe_json=live_chat_concurrency_probe_json,
        require_live_chat_probe_approval=execute_live_chat_probe,
    )
    private_record_blockers = _private_record_blockers(private_record_statuses)
    report: dict[str, Any] = {
        "version": M1_PRIVATE_LIVE_EVIDENCE_WORKFLOW_VERSION,
        "status": "ready_to_execute" if not execute else "running",
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "deploys_code": False,
            "deletes_files": False,
            "runs_live_probes": execute and bool(sections & LIVE_PROBE_SECTION_KEYS),
            "connects_ssh": execute and bool(sections & SSH_SECTION_KEYS),
            "writes_files": execute,
            "reads_external_dependency_resilience_record": (
                execute and "external_dependency_resilience_record" in sections
            ),
            "reads_m1_rollout_execution_record": (
                execute and "m1_rollout_execution_record" in sections
            ),
            "reads_m1_operations_review_record": (
                execute and "m1_operations_review_record" in sections
            ),
            "reads_live_chat_probe_execution_approval": (
                execute
                and "live_chat_probe" in sections
                and (execute_live_chat_probe or live_chat_probe_approval_json is not None)
            ),
            "reads_live_chat_concurrency_probe_evidence": (
                execute and "live_chat_concurrency_probe" in sections
            ),
            "requires_live_chat_probe_execution_approval": (
                execute and "live_chat_probe" in sections and execute_live_chat_probe
            ),
            "may_call_auth_endpoint": execute and execute_probe_auth_login,
            "may_call_external_apis": execute and execute_live_chat_probe,
            "may_write_runtime_artifacts": execute and execute_live_chat_probe,
            "records_public_url": False,
            "records_server_ip": False,
            "records_credentials": False,
            "output_should_remain_private": True,
        },
        "target": {
            "public_base_url_present": bool(resolved_base_url),
            "public_base_url_env": base_url_env,
            "public_base_url_echoed": False,
            "ssh_target_present": bool(resolved_ssh_target),
            "ssh_target_echoed": False,
            "deploy_dir_present": bool(resolved_deploy_dir),
            "deploy_dir_echoed": False,
            "backup_dir_present": bool(resolved_backup_dir),
            "backup_dir_echoed": False,
            "output_dir": PRIVATE_WORKDIR_PLACEHOLDER if output_dir is not None else None,
            "output_dir_inside_project": output_inside_project,
            "allow_project_output": allow_project_output,
        },
        "selected_sections": sorted(sections),
        "required_env_vars": _required_env_vars(sections),
        "input_statuses": input_statuses,
        "missing_inputs_for_user": missing_inputs,
        "private_record_statuses": private_record_statuses,
        "private_record_blockers": private_record_blockers,
        "command_plan": _build_command_plan(sections),
        "execution_sequence": _build_execution_sequence_plan(sections),
        "not_proven_by_this_workflow": [
            "Plan mode proves no live deployment result.",
            "A written evidence bundle does not deploy code or start services.",
            "Live chat evidence proves only one authenticated SSE turn when explicitly executed.",
            "This workflow does not prove full production-grade HA, autoscaling, long-duration soak stability, real payment, booking, inventory lock, ticketing or fulfillment.",
        ],
    }
    if not execute:
        return _redact_private_data(report, extra_secrets=extra_secrets)
    if resolved_output_dir is None:
        report["status"] = "blocked"
        _mark_no_execution(report)
        report["blocked_reasons"] = [
            {
                "key": "output_dir_required",
                "finding": "Pass --output-dir pointing to a private directory outside the Git workspace.",
            }
        ]
        return _redact_private_data(report, extra_secrets=extra_secrets)
    if output_inside_project and not allow_project_output:
        report["status"] = "blocked"
        _mark_no_execution(report)
        report["blocked_reasons"] = [
            {
                "key": "project_output_not_allowed",
                "finding": "Use a private output directory outside the Git workspace or pass --allow-project-output.",
            }
        ]
        return _redact_private_data(report, extra_secrets=extra_secrets)
    if private_record_blockers or missing_inputs:
        report["status"] = "blocked"
        _mark_no_execution(report)
        blocked_reasons: list[dict[str, Any]] = []
        if private_record_blockers:
            blocked_reasons.append(
                {
                    "key": "private_record_inputs_not_ready",
                    "finding": "Selected private evidence record JSON inputs are missing, unsafe, inside Git, or not readable.",
                    "value_echoed": False,
                }
            )
        if missing_inputs:
            blocked_reasons.append(
                {
                    "key": "missing_private_execution_inputs",
                    "finding": "Required private live evidence inputs are missing; live probes were not started.",
                    "value_echoed": False,
                }
            )
        report["blocked_reasons"] = blocked_reasons
        return _redact_private_data(report, extra_secrets=extra_secrets)

    go_no_go_report = build_m1_go_no_go_report(
        environ=env,
        base_url=resolved_base_url,
        include_live_server_probe="live_server_probe" in sections,
        include_postgres_redis_live_probe="postgres_redis_live_probe" in sections,
        include_backup_schedule_live_probe="backup_schedule_live_probe" in sections,
        include_docker_disk_cleanup_plan="docker_disk_cleanup_plan" in sections,
        include_live_concurrency_probe="live_concurrency_probe" in sections,
        include_probe_auth_readiness="probe_auth_readiness" in sections,
        include_live_chat_probe="live_chat_probe" in sections,
        include_live_chat_concurrency_probe="live_chat_concurrency_probe" in sections,
        live_chat_concurrency_probe_json=live_chat_concurrency_probe_json,
        include_server_capacity_snapshot="server_capacity_snapshot" in sections,
        include_rate_limit_live_probe="rate_limit_live_probe" in sections,
        include_external_dependency_resilience_record=(
            "external_dependency_resilience_record" in sections
        ),
        external_dependency_record_json=external_dependency_record_json,
        include_m1_rollout_execution_record="m1_rollout_execution_record" in sections,
        m1_rollout_record_json=m1_rollout_record_json,
        include_m1_operations_review_record="m1_operations_review_record" in sections,
        m1_operations_review_json=m1_operations_review_json,
        live_chat_probe_approval_json=live_chat_probe_approval_json,
        live_server_ssh_target=resolved_ssh_target,
        live_server_deploy_dir=resolved_deploy_dir,
        live_backup_dir=resolved_backup_dir,
        execute_probe_auth_login=execute_probe_auth_login,
        execute_live_chat_probe=execute_live_chat_probe,
        concurrency_requests_per_endpoint=concurrency_requests_per_endpoint,
        concurrency_workers=concurrency_workers,
        concurrency_max_p95_ms=concurrency_max_p95_ms,
        rate_limit_request_count=rate_limit_request_count,
        rate_limit_concurrency=rate_limit_concurrency,
        docker_disk_cleanup_max_candidates=docker_disk_cleanup_max_candidates,
        timeout_seconds=timeout_seconds,
    )
    safe_go_no_go = _redact_private_data(go_no_go_report, extra_secrets=extra_secrets)
    if not isinstance(safe_go_no_go, dict):
        safe_go_no_go = {}

    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    go_no_go_path = resolved_output_dir / "m1-go-no-go.private.json"
    summary_path = resolved_output_dir / "m1-live-evidence-summary.md"
    bundle_dir = resolved_output_dir / "m1-evidence-bundle"
    workflow_report_path = resolved_output_dir / "workflow-report.json"
    go_no_go_path.write_text(_json_dumps(safe_go_no_go, extra_secrets=extra_secrets), encoding="utf-8")
    summary = build_m1_live_evidence_summary_markdown(
        safe_go_no_go,
        generated_at=now,
        source_name=f"go_no_go_json:{go_no_go_path.name}",
    )
    summary_path.write_text(_redact_private_text(summary, extra_secrets=extra_secrets) + "\n", encoding="utf-8")
    bundle_report = build_m1_evidence_bundle_report(
        go_no_go_json=go_no_go_path,
        output_dir=bundle_dir,
        execute=True,
        allow_project_output=allow_project_output,
        generated_at=now,
    )
    safe_bundle_report = _redact_private_data(bundle_report, extra_secrets=extra_secrets)
    if not isinstance(safe_bundle_report, dict):
        safe_bundle_report = {}
    report["status"] = _workflow_status(safe_go_no_go, safe_bundle_report)
    report["go_no_go"] = {
        "status": safe_go_no_go.get("status"),
        "decision": safe_go_no_go.get("decision"),
        "section_statuses": safe_go_no_go.get("section_statuses", {}),
    }
    report["bundle"] = {
        "status": safe_bundle_report.get("status"),
        "manifest_sha256": safe_bundle_report.get("manifest_sha256"),
    }
    report["artifacts"] = [
        {"role": "private_go_no_go_json", "path": go_no_go_path.name, "sha256": _sha256_file(go_no_go_path)},
        {
            "role": "live_evidence_summary_markdown",
            "path": summary_path.name,
            "sha256": _sha256_file(summary_path),
        },
        {"role": "evidence_bundle_dir", "path": bundle_dir.name},
        {"role": "workflow_report_json", "path": workflow_report_path.name},
    ]
    bundle_manifest_path = bundle_dir / "manifest.json"
    if bundle_manifest_path.exists():
        report["artifacts"].append(
            {
                "role": "evidence_bundle_manifest",
                "path": f"{bundle_dir.name}/manifest.json",
                "sha256": _sha256_file(bundle_manifest_path),
            }
        )
    safe_report = _redact_private_data(report, extra_secrets=extra_secrets)
    workflow_report_path.write_text(_json_dumps(safe_report, extra_secrets=extra_secrets), encoding="utf-8")
    return safe_report if isinstance(safe_report, dict) else {}


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. This is the default output format.")
    parser.add_argument("--markdown", action="store_true", help="Print a redacted Markdown preflight checklist.")
    parser.add_argument("--output-dir", type=_path_arg, default=None, help="Private output directory outside Git.")
    parser.add_argument("--execute", action="store_true", help="Run selected probes and write private artifacts.")
    parser.add_argument("--allow-project-output", action="store_true", help="Allow writing under the Git workspace.")
    parser.add_argument("--base-url", default=None, help="Public base URL. Redacted from output; prefer env.")
    parser.add_argument("--base-url-env", default=DEFAULT_PUBLIC_BASE_URL_ENV)
    parser.add_argument("--live-server-ssh-target", default=None, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-user-env", default=DEFAULT_DEPLOY_USER_ENV)
    parser.add_argument("--deploy-host-env", default=DEFAULT_DEPLOY_HOST_ENV)
    parser.add_argument("--live-server-deploy-dir", default=None, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--deploy-dir-env", default=DEFAULT_DEPLOY_DIR_ENV)
    parser.add_argument("--live-backup-dir", default=None, help="Remote backup directory. Redacted from output.")
    parser.add_argument("--backup-dir-env", default=DEFAULT_BACKUP_DIR_ENV)
    parser.add_argument("--include-standard-live-probes", action="store_true")
    parser.add_argument("--include-live-server-probe", action="store_true")
    parser.add_argument("--include-postgres-redis-live-probe", action="store_true")
    parser.add_argument("--include-backup-schedule-live-probe", action="store_true")
    parser.add_argument("--include-docker-disk-cleanup-plan", action="store_true")
    parser.add_argument("--include-live-concurrency-probe", action="store_true")
    parser.add_argument("--include-probe-auth-readiness", action="store_true")
    parser.add_argument("--include-live-chat-probe", action="store_true")
    parser.add_argument("--include-live-chat-concurrency-probe", action="store_true")
    parser.add_argument("--live-chat-concurrency-probe-json", type=_path_arg, default=None)
    parser.add_argument("--include-server-capacity-snapshot", action="store_true")
    parser.add_argument("--include-rate-limit-live-probe", action="store_true")
    parser.add_argument("--include-external-dependency-resilience-record", action="store_true")
    parser.add_argument("--external-dependency-record-json", type=_path_arg, default=None)
    parser.add_argument("--include-m1-rollout-execution-record", action="store_true")
    parser.add_argument("--m1-rollout-record-json", type=_path_arg, default=None)
    parser.add_argument("--include-m1-operations-review-record", action="store_true")
    parser.add_argument("--m1-operations-review-json", type=_path_arg, default=None)
    parser.add_argument(
        "--live-chat-probe-approval-json",
        type=_path_arg,
        default=None,
        help="Private approval report JSON required before executing live chat probe. Path is not echoed.",
    )
    parser.add_argument("--execute-probe-auth-login", action="store_true")
    parser.add_argument("--execute-live-chat-probe", action="store_true")
    parser.add_argument("--concurrency-requests-per-endpoint", type=int, default=30)
    parser.add_argument("--concurrency-workers", type=int, default=10)
    parser.add_argument("--concurrency-max-p95-ms", type=float, default=2000)
    parser.add_argument("--rate-limit-request-count", type=int, default=130)
    parser.add_argument("--rate-limit-concurrency", type=int, default=1)
    parser.add_argument("--docker-disk-cleanup-max-candidates", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_private_live_evidence_workflow_report(
        output_dir=args.output_dir,
        execute=args.execute,
        allow_project_output=args.allow_project_output,
        base_url=args.base_url,
        base_url_env=args.base_url_env,
        live_server_ssh_target=args.live_server_ssh_target,
        deploy_user_env=args.deploy_user_env,
        deploy_host_env=args.deploy_host_env,
        live_server_deploy_dir=args.live_server_deploy_dir,
        deploy_dir_env=args.deploy_dir_env,
        live_backup_dir=args.live_backup_dir,
        backup_dir_env=args.backup_dir_env,
        include_standard_live_probes=args.include_standard_live_probes,
        include_live_server_probe=args.include_live_server_probe,
        include_postgres_redis_live_probe=args.include_postgres_redis_live_probe,
        include_backup_schedule_live_probe=args.include_backup_schedule_live_probe,
        include_docker_disk_cleanup_plan=args.include_docker_disk_cleanup_plan,
        include_live_concurrency_probe=args.include_live_concurrency_probe,
        include_probe_auth_readiness=args.include_probe_auth_readiness,
        include_live_chat_probe=args.include_live_chat_probe,
        include_live_chat_concurrency_probe=args.include_live_chat_concurrency_probe,
        live_chat_concurrency_probe_json=args.live_chat_concurrency_probe_json,
        include_server_capacity_snapshot=args.include_server_capacity_snapshot,
        include_rate_limit_live_probe=args.include_rate_limit_live_probe,
        include_external_dependency_resilience_record=args.include_external_dependency_resilience_record,
        external_dependency_record_json=args.external_dependency_record_json,
        include_m1_rollout_execution_record=args.include_m1_rollout_execution_record,
        m1_rollout_record_json=args.m1_rollout_record_json,
        include_m1_operations_review_record=args.include_m1_operations_review_record,
        m1_operations_review_json=args.m1_operations_review_json,
        live_chat_probe_approval_json=args.live_chat_probe_approval_json,
        execute_probe_auth_login=args.execute_probe_auth_login,
        execute_live_chat_probe=args.execute_live_chat_probe,
        concurrency_requests_per_endpoint=args.concurrency_requests_per_endpoint,
        concurrency_workers=args.concurrency_workers,
        concurrency_max_p95_ms=args.concurrency_max_p95_ms,
        rate_limit_request_count=args.rate_limit_request_count,
        rate_limit_concurrency=args.rate_limit_concurrency,
        docker_disk_cleanup_max_candidates=args.docker_disk_cleanup_max_candidates,
        timeout_seconds=args.timeout_seconds,
    )
    if args.markdown:
        print(build_m1_private_live_evidence_workflow_markdown(report))
    else:
        print(_json_dumps(report), end="")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
