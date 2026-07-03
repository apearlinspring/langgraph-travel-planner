"""Check private M1 execution input gaps without reading .env or running probes."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_launch_inputs import (  # noqa: E402
    M1_INPUT_SPECS,
    build_m1_launch_inputs_report,
    load_m1_launch_input_values,
)
from scripts.run_m1_private_live_evidence_workflow import (  # noqa: E402
    build_m1_private_live_evidence_workflow_report,
)


M1_EXECUTION_INPUT_GAP_VERSION = "m1_execution_input_gap.v1"
PRIVATE_WORKDIR_PLACEHOLDER = "<private-workdir>"
FORBIDDEN_PATH_PARTS = {
    ".env",
    ".runtime",
    ".venv",
    "logs",
    "vectorstore",
    "vectorstore_internal",
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


def _is_forbidden_path(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_PATH_PARTS)


def _private_workdir_status(private_workdir: Path | None) -> dict[str, Any]:
    if private_workdir is None:
        return {
            "key": "private_workdir",
            "status": "blocked",
            "finding": "Private workdir is missing.",
            "path_echoed": False,
            "action": "Pass --private-workdir pointing to a directory outside the Git workspace.",
        }
    inside_project = _is_relative_to(private_workdir, PROJECT_ROOT)
    forbidden = _is_forbidden_path(private_workdir)
    if inside_project:
        status = "blocked_sensitive_boundary"
        finding = "Private workdir must stay outside the Git workspace."
    elif forbidden:
        status = "blocked_sensitive_boundary"
        finding = "Private workdir points to a forbidden runtime or secret-like location."
    else:
        status = "passed"
        finding = "Private workdir is declared outside the Git workspace."
    return {
        "key": "private_workdir",
        "status": status,
        "finding": finding,
        "exists": private_workdir.exists(),
        "inside_project": inside_project,
        "forbidden_path": forbidden,
        "path_echoed": False,
        "action": "Use this directory only for private M1 JSON reports and redacted evidence bundles.",
    }


def _default_private_path(private_workdir: Path | None, filename: str) -> Path | None:
    return private_workdir / filename if private_workdir is not None else None


def _load_launch_report(
    *,
    environ: Mapping[str, str],
    m1_input_json: Path | None,
    private_workdir: Path | None,
) -> dict[str, Any]:
    source_path = m1_input_json
    if source_path is None:
        default_path = _default_private_path(private_workdir, "m1-launch-inputs.local.json")
        if default_path is not None and default_path.exists():
            source_path = default_path
    if source_path is None:
        return build_m1_launch_inputs_report(environ=environ, source="process_environment")
    if _is_relative_to(source_path, PROJECT_ROOT):
        return {
            "version": "m1_launch_inputs.v1",
            "status": "blocked",
            "source": f"input_json:{source_path.name}",
            "policy": {
                "reads_env_files": False,
                "reads_input_json": False,
                "does_not_echo_values": True,
                "checks_non_secret_inputs_only": True,
            },
            "input_count": len(M1_INPUT_SPECS),
            "passed_count": 0,
            "blocked_count": 1,
            "degraded_count": 0,
            "missing_or_blocked_env_vars": ["m1_input_json"],
            "blocked_reasons": [
                {
                    "key": "m1_input_json",
                    "finding": "M1 launch input JSON must stay outside the Git workspace.",
                    "path_echoed": False,
                }
            ],
            "repair_suggestions": [
                {
                    "key": "m1_input_json",
                    "action": "Move the filled M1 launch input JSON to <private-workdir> outside Git.",
                }
            ],
            "not_proven_by_this_check": [
                "The input JSON was accepted.",
                "Real secrets are present and valid.",
            ],
        }
    try:
        input_values = load_m1_launch_input_values(source_path)
    except ValueError as exc:
        return {
            "version": "m1_launch_inputs.v1",
            "status": "blocked",
            "source": f"input_json:{source_path.name}",
            "policy": {
                "reads_env_files": False,
                "reads_input_json": False,
                "does_not_echo_values": True,
                "checks_non_secret_inputs_only": True,
            },
            "input_count": len(M1_INPUT_SPECS),
            "passed_count": 0,
            "blocked_count": 1,
            "degraded_count": 0,
            "missing_or_blocked_env_vars": ["m1_input_json"],
            "blocked_reasons": [
                {
                    "key": "m1_input_json",
                    "finding": str(exc),
                    "path_echoed": False,
                }
            ],
            "repair_suggestions": [
                {
                    "key": "m1_input_json",
                    "action": "Create a valid non-secret M1 launch input JSON outside Git.",
                }
            ],
            "not_proven_by_this_check": [
                "The input JSON was accepted.",
                "Real secrets are present and valid.",
            ],
        }
    return build_m1_launch_inputs_report(
        input_values=input_values,
        source=f"input_json:{source_path.name}",
    )


def _launch_missing_inputs(launch_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for item in launch_report.get("blocked_reasons") or []:
        if not isinstance(item, Mapping):
            continue
        missing.append(
            {
                "category": item.get("category", "m1_launch_inputs"),
                "key": item.get("key") or item.get("env_var") or "m1_input_json",
                "env_var": item.get("env_var"),
                "finding": item.get("finding") or item.get("reason") or "Missing M1 launch input.",
                "value_echoed": False,
            }
        )
    return missing


def _classify_status(
    *,
    private_workdir_check: Mapping[str, Any],
    launch_report: Mapping[str, Any],
    workflow_report: Mapping[str, Any],
) -> str:
    if private_workdir_check.get("status") == "blocked_sensitive_boundary":
        return "blocked_sensitive_boundary"
    if _launch_report_has_sensitive_boundary(launch_report):
        return "blocked_sensitive_boundary"
    if _has_sensitive_path_blocker(workflow_report):
        return "blocked_sensitive_boundary"
    if launch_report.get("status") == "blocked":
        return "blocked_missing_private_input"
    if workflow_report.get("missing_inputs_for_user") or workflow_report.get("private_record_blockers"):
        return "blocked_missing_private_input"
    if private_workdir_check.get("status") != "passed":
        return "blocked_missing_private_input"
    return "ready_to_execute_private_m1"


def _launch_report_has_sensitive_boundary(launch_report: Mapping[str, Any]) -> bool:
    for item in launch_report.get("blocked_reasons") or []:
        if not isinstance(item, Mapping):
            continue
        finding = str(item.get("finding") or item.get("reason") or "").lower()
        if "git workspace" in finding or "forbidden" in finding:
            return True
    return False


def _has_sensitive_path_blocker(workflow_report: Mapping[str, Any]) -> bool:
    for item in workflow_report.get("private_record_blockers") or []:
        if not isinstance(item, Mapping):
            continue
        reason = str(item.get("reason") or "").lower()
        if "inside the git workspace" in reason or "forbidden runtime" in reason:
            return True
    return False


def _workflow_report_for_gap(
    *,
    environ: Mapping[str, str],
    private_workdir: Path | None,
    include_live_chat_probe: bool,
    require_external_dependency_record: bool,
    require_rollout_record: bool,
    require_operations_review_record: bool,
    external_dependency_record_json: Path | None,
    m1_rollout_record_json: Path | None,
    m1_operations_review_json: Path | None,
    generated_at: datetime,
) -> dict[str, Any]:
    workflow_dir = private_workdir / "m1-live-evidence-workflow" if private_workdir is not None else None
    external_record = external_dependency_record_json
    rollout_record = m1_rollout_record_json
    operations_record = m1_operations_review_json
    if private_workdir is not None:
        external_record = external_record or private_workdir / "external-dependency-resilience-record.local.json"
        rollout_record = rollout_record or private_workdir / "m1-rollout-execution-record.local.json"
        operations_record = operations_record or private_workdir / "m1-operations-review-record.local.json"
    return build_m1_private_live_evidence_workflow_report(
        environ=environ,
        output_dir=workflow_dir,
        execute=False,
        include_standard_live_probes=True,
        include_live_chat_probe=include_live_chat_probe,
        include_external_dependency_resilience_record=require_external_dependency_record,
        external_dependency_record_json=external_record,
        include_m1_rollout_execution_record=require_rollout_record,
        m1_rollout_record_json=rollout_record,
        include_m1_operations_review_record=require_operations_review_record,
        m1_operations_review_json=operations_record,
        generated_at=generated_at,
    )


def build_m1_execution_input_gap_report(
    *,
    environ: Mapping[str, str] | None = None,
    private_workdir: Path | None = None,
    m1_input_json: Path | None = None,
    include_live_chat_probe: bool = False,
    require_external_dependency_record: bool = True,
    require_rollout_record: bool = True,
    require_operations_review_record: bool = True,
    external_dependency_record_json: Path | None = None,
    m1_rollout_record_json: Path | None = None,
    m1_operations_review_json: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted execution-input gap report."""

    env = environ if environ is not None else os.environ
    now = generated_at or datetime.now(UTC)
    private_workdir_check = _private_workdir_status(private_workdir)
    launch_report = _load_launch_report(
        environ=env,
        m1_input_json=m1_input_json,
        private_workdir=private_workdir,
    )
    workflow_report = _workflow_report_for_gap(
        environ=env,
        private_workdir=private_workdir,
        include_live_chat_probe=include_live_chat_probe,
        require_external_dependency_record=require_external_dependency_record,
        require_rollout_record=require_rollout_record,
        require_operations_review_record=require_operations_review_record,
        external_dependency_record_json=external_dependency_record_json,
        m1_rollout_record_json=m1_rollout_record_json,
        m1_operations_review_json=m1_operations_review_json,
        generated_at=now,
    )
    status = _classify_status(
        private_workdir_check=private_workdir_check,
        launch_report=launch_report,
        workflow_report=workflow_report,
    )
    launch_missing = _launch_missing_inputs(launch_report)
    missing_private_inputs = workflow_report.get("missing_inputs_for_user") or []
    private_record_blockers = workflow_report.get("private_record_blockers") or []
    return {
        "version": M1_EXECUTION_INPUT_GAP_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "runs_live_probes": False,
            "connects_ssh": False,
            "starts_services": False,
            "deploys_code": False,
            "deletes_files": False,
            "does_not_echo_values": True,
            "records_public_url": False,
            "records_server_ip": False,
            "records_credentials": False,
        },
        "target": {
            "private_workdir": PRIVATE_WORKDIR_PLACEHOLDER if private_workdir is not None else None,
            "private_workdir_present": private_workdir is not None,
            "private_workdir_echoed": False,
            "m1_input_json": m1_input_json.name if m1_input_json is not None else None,
            "m1_input_json_echoed": False,
        },
        "checks": {
            "private_workdir": private_workdir_check,
            "m1_launch_inputs": {
                "status": launch_report.get("status"),
                "source": launch_report.get("source"),
                "passed_count": launch_report.get("passed_count"),
                "input_count": launch_report.get("input_count"),
                "missing_or_blocked_env_vars": launch_report.get("missing_or_blocked_env_vars", []),
            },
            "private_live_workflow_inputs": {
                "status": "blocked" if missing_private_inputs else "passed",
                "selected_sections": workflow_report.get("selected_sections", []),
                "missing_inputs_for_user": missing_private_inputs,
            },
            "private_record_inputs": {
                "status": "blocked" if private_record_blockers else "passed",
                "private_record_statuses": workflow_report.get("private_record_statuses", []),
                "private_record_blockers": private_record_blockers,
            },
        },
        "missing_for_user": {
            "m1_launch_inputs": launch_missing,
            "private_live_inputs": missing_private_inputs,
            "private_record_inputs": private_record_blockers,
        },
        "next_commands": [
            "uv run python scripts\\check_m1_launch_inputs.py --template --output <private-workdir>\\m1-launch-inputs.local.json",
            "uv run python scripts\\check_m1_launch_inputs.py --input-json <private-workdir>\\m1-launch-inputs.local.json --json --output <private-workdir>\\m1-launch-inputs-report.json",
            "uv run python scripts\\check_external_dependency_resilience_record.py --template --output <private-workdir>\\external-dependency-resilience-record.local.json",
            "uv run python scripts\\check_m1_rollout_execution_record.py --template --output <private-workdir>\\m1-rollout-execution-record.local.json",
            "uv run python scripts\\check_m1_operations_review_record.py --template --output <private-workdir>\\m1-operations-review-record.local.json",
            "uv run python scripts\\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\\m1-operations-review-record.local.json",
        ],
        "not_proven_by_this_check": [
            "Real secrets are present and valid.",
            "The target server is reachable.",
            "PostgreSQL, Redis, RAG, Docker, backup, and external API checks have passed.",
            "Any code has been deployed or services have been restarted.",
            "M1 is production-ready beyond controlled-trial scope.",
        ],
    }


def build_m1_execution_input_gap_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 Execution Input Gap",
        "",
        f"- Status: `{report.get('status')}`",
        "- Policy: does not read `.env`, does not echo values, does not run live probes.",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    checks = report.get("checks") or {}
    if isinstance(checks, Mapping):
        for key, item in checks.items():
            if not isinstance(item, Mapping):
                continue
            detail = item.get("finding") or item.get("source") or "-"
            lines.append(f"| `{key}` | `{item.get('status')}` | {str(detail).replace('|', '\\|')} |")
    lines.extend(["", "## Missing For User", "", "| Group | Item | Finding |", "|---|---|---|"])
    missing = report.get("missing_for_user") or {}
    wrote_missing = False
    if isinstance(missing, Mapping):
        for group, items in missing.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                wrote_missing = True
                label = item.get("env_var") or item.get("key") or item.get("label") or "-"
                finding = item.get("finding") or item.get("reason") or "Missing or blocked."
                lines.append(
                    f"| `{group}` | `{str(label).replace('|', '\\|')}` | {str(finding).replace('|', '\\|')} |"
                )
    if not wrote_missing:
        lines.append("| - | - | No missing inputs recorded. |")
    lines.extend(["", "## Next Commands", ""])
    for command in report.get("next_commands") or []:
        lines.extend(["```powershell", str(command), "```", ""])
    lines.extend(["## Not Proven", ""])
    for item in report.get("not_proven_by_this_check") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-workdir", type=_path_arg, default=None)
    parser.add_argument("--m1-input-json", type=_path_arg, default=None)
    parser.add_argument("--include-live-chat-probe", action="store_true")
    parser.add_argument("--no-external-dependency-record", action="store_true")
    parser.add_argument("--no-rollout-record", action="store_true")
    parser.add_argument("--no-operations-review-record", action="store_true")
    parser.add_argument("--external-dependency-record-json", type=_path_arg, default=None)
    parser.add_argument("--m1-rollout-record-json", type=_path_arg, default=None)
    parser.add_argument("--m1-operations-review-json", type=_path_arg, default=None)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_execution_input_gap_report(
        private_workdir=args.private_workdir,
        m1_input_json=args.m1_input_json,
        include_live_chat_probe=args.include_live_chat_probe,
        require_external_dependency_record=not args.no_external_dependency_record,
        require_rollout_record=not args.no_rollout_record,
        require_operations_review_record=not args.no_operations_review_record,
        external_dependency_record_json=args.external_dependency_record_json,
        m1_rollout_record_json=args.m1_rollout_record_json,
        m1_operations_review_json=args.m1_operations_review_json,
    )
    output_text = (
        build_m1_execution_input_gap_markdown(report)
        if args.markdown and not args.json
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    )
    if args.output is not None:
        if _is_forbidden_path(args.output):
            print("Refusing to write M1 execution input gap report to a forbidden path.", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output.name}")
    else:
        print(output_text)
    return 0 if report["status"] == "ready_to_execute_private_m1" else 2


if __name__ == "__main__":
    raise SystemExit(main())
