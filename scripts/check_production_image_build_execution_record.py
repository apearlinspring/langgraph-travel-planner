"""Validate a redacted production image build execution record.

The checker validates an operator-filled JSON record. It does not run Docker,
connect SSH, inspect logs, read `.env`, or start services.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_IMAGE_BUILD_EXECUTION_RECORD_VERSION = "production_image_build_execution_record.v1"
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
VALID_MODES = {"remote_background_build"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy-", "build id", "owner role", "image id", "release label")
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)://[^/\s]+:[^@\s]+@"),
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("Production image build execution record must be a JSON object.")
    return payload


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _looks_placeholder(value: Any) -> bool:
    lowered = str(value or "").strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES) or any(
        fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS
    )


def _has_final_text(value: Any) -> bool:
    return _has_text(value) and not _looks_placeholder(value)


def _is_ready(value: Any) -> bool:
    return str(value or "").strip().lower() in READY_VALUES


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _check(
    *,
    status: str,
    finding: str,
    value_echoed: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {"status": status, "finding": finding, "value_echoed": value_echoed, **extra}


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "build_id",
        "record_version",
        "mode",
        "started_at",
        "ended_at",
        "release_label",
        "build_reason",
    )
    missing = [field for field in required if not _has_final_text(record.get(field))]
    if record.get("record_version") != PRODUCTION_IMAGE_BUILD_EXECUTION_RECORD_VERSION:
        missing.append("record_version")
    mode = str(record.get("mode") or "").strip()
    if mode not in VALID_MODES:
        missing.append("mode")
    duration = record.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
        missing.append("duration_seconds")
    return _check(
        status="blocked" if missing else "passed",
        missing_fields=sorted(set(missing)),
        mode=mode if mode in VALID_MODES else "unknown",
        finding="Required build execution fields are present."
        if not missing
        else "Required build execution fields are missing.",
    )


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = _as_mapping(record.get("owners"))
    required = ("build_owner", "release_owner", "verifier")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return _check(
        status="blocked" if missing else "passed",
        owner_roles_present=len(required) - len(missing),
        missing_owner_roles=missing,
        finding="Required build owner roles are assigned."
        if not missing
        else "Required build owner roles are missing.",
    )


def _background_execution_check(record: Mapping[str, Any]) -> dict[str, Any]:
    execution = _as_mapping(record.get("background_execution"))
    missing = []
    wrapper = str(execution.get("wrapper") or "").lower()
    if not any(token in wrapper for token in ("nohup", "systemd", "tmux")):
        missing.append("wrapper")
    for key in ("pid_recorded", "log_path_recorded", "log_redacted", "started_in_background", "exit_code_recorded"):
        if not _is_ready(execution.get(key)):
            missing.append(key)
    if execution.get("exit_code") != 0:
        missing.append("exit_code")
    if execution.get("timed_out") is not False:
        missing.append("timed_out")
    timeout = execution.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 900:
        missing.append("timeout_seconds")
    return _check(
        status="blocked" if missing else "passed",
        missing_fields=sorted(set(missing)),
        finding="Remote background build execution is recorded."
        if not missing
        else "Remote background build execution is incomplete.",
    )


def _package_mirror_check(record: Mapping[str, Any]) -> dict[str, Any]:
    mirror = _as_mapping(record.get("package_mirror"))
    missing = []
    for key in ("pip_index_url_configured", "pip_trusted_host_policy_recorded", "mirror_used_recorded"):
        if not _is_ready(mirror.get(key)):
            missing.append(key)
    if mirror.get("secret_values_in_url") is not False:
        missing.append("secret_values_in_url")
    if not _has_final_text(mirror.get("mirror_failure_policy")):
        missing.append("mirror_failure_policy")
    return _check(
        status="blocked" if missing else "passed",
        missing_fields=sorted(set(missing)),
        finding="Package mirror policy was observed without exposing private values."
        if not missing
        else "Package mirror execution evidence is incomplete.",
    )


def _runtime_input_check(record: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _as_mapping(record.get("runtime_input"))
    required_ready = (
        "runtime_requirements_used",
        "dockerfile_runtime_input_verified",
        "runtime_dependency_scope_passed",
    )
    missing = [key for key in required_ready if not _is_ready(runtime.get(key))]
    required_false = ("full_requirements_used", "dev_dependencies_installed", "optional_gpu_stack_installed")
    unsafe = [key for key in required_false if runtime.get(key) is not False]
    blocked = missing + unsafe
    return _check(
        status="blocked" if blocked else "passed",
        missing_or_unsafe_fields=sorted(set(blocked)),
        finding="Runtime-only build input is recorded."
        if not blocked
        else "Runtime-only build input evidence is incomplete or unsafe.",
    )


def _image_evidence_check(record: Mapping[str, Any]) -> dict[str, Any]:
    image = _as_mapping(record.get("image_evidence"))
    missing = []
    for key in ("image_id_before_present", "image_id_after_present", "image_size_recorded"):
        if not _is_ready(image.get(key)):
            missing.append(key)
    if image.get("image_changed") is not True:
        missing.append("image_changed")
    size = image.get("image_size_mb_after")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or size <= 0:
        missing.append("image_size_mb_after")
    return _check(
        status="blocked" if missing else "passed",
        missing_fields=sorted(set(missing)),
        finding="Image ID and size evidence is recorded."
        if not missing
        else "Image ID and size evidence is incomplete.",
    )


def _safety_check(record: Mapping[str, Any]) -> dict[str, Any]:
    safety = _as_mapping(record.get("safety"))
    required_ready = (
        "disk_guard_passed",
        "current_release_unchanged_until_success",
        "no_runtime_data_modified",
    )
    missing = [key for key in required_ready if not _is_ready(safety.get(key))]
    required_false = (
        "used_docker_system_prune",
        "deleted_docker_volume",
        "deleted_env_file",
        "deleted_vectorstore",
        "deleted_backup",
        "used_bulk_delete",
    )
    unsafe = [key for key in required_false if safety.get(key) is not False]
    blocked = missing + unsafe
    return _check(
        status="blocked" if blocked else "passed",
        missing_or_unsafe_fields=sorted(set(blocked)),
        finding="Build safety boundary is recorded."
        if not blocked
        else "Build safety boundary is incomplete or unsafe.",
    )


def _post_build_check(record: Mapping[str, Any]) -> dict[str, Any]:
    post = _as_mapping(record.get("post_build_verification"))
    required_ready = ("compose_ps_status", "health_live_status", "health_ready_status")
    missing = [key for key in required_ready if not _is_ready(post.get(key))]
    mock_status = str(post.get("mock_checkout_status") or "").strip().lower()
    mock_reason = _has_text(post.get("mock_checkout_reason"))
    if mock_status in READY_VALUES:
        pass
    elif mock_status in {"not_applicable", "not applicable", "skipped"}:
        if not mock_reason:
            missing.append("mock_checkout_reason")
    else:
        missing.append("mock_checkout_status")
    return _check(
        status="blocked" if missing else "passed",
        missing_fields=sorted(set(missing)),
        finding="Post-build runtime verification passed or is explicitly scoped."
        if not missing
        else "Post-build runtime verification is incomplete.",
    )


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blocked = []
    for key in (
        "raw_logs_included",
        "raw_urls_included",
        "ssh_target_included",
        "deploy_dir_included",
        "secret_values_included",
        "customer_pii_included",
    ):
        if boundary.get(key) is not False:
            blocked.append({"field": f"redaction_boundary.{key}", "finding": "Redaction boundary must be false."})
    for pattern in SECRET_PATTERNS:
        if pattern.search(raw_text):
            blocked.append({"field": "record_text", "finding": "Record contains a secret-looking value pattern."})
            break
    return _check(
        status="blocked" if blocked else "passed",
        blocked_reasons=blocked,
        finding="Record declares no raw logs, raw URLs, private paths, PII or secret values."
        if not blocked
        else "Record redaction boundary is incomplete.",
        record_text_echoed=False,
    )


def _status_from_checks(checks: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    blockers = []
    for name, check in checks.items():
        if check.get("status") != "blocked":
            continue
        for item in check.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                blockers.append({"check": name, **dict(item)})
        if not check.get("blocked_reasons"):
            blockers.append({"check": name, "finding": check.get("finding") or "blocked"})
    return ("blocked" if blockers else "passed", blockers)


def build_production_image_build_execution_record_report(
    record: Mapping[str, Any],
    *,
    raw_text: str = "",
) -> dict[str, Any]:
    """Build a redacted validation report for one production image build record."""

    checks = {
        "required_fields": _required_fields_check(record),
        "owners": _owners_check(record),
        "background_execution": _background_execution_check(record),
        "package_mirror": _package_mirror_check(record),
        "runtime_input": _runtime_input_check(record),
        "image_evidence": _image_evidence_check(record),
        "safety": _safety_check(record),
        "post_build_verification": _post_build_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    return {
        "version": PRODUCTION_IMAGE_BUILD_EXECUTION_RECORD_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "runs_docker": False,
            "starts_services": False,
            "deletes_docker_resources": False,
            "reads_runtime_dirs": False,
            "record_text_echoed": False,
            "raw_logs_allowed": False,
        },
        "record_summary": {
            "build_id_present": _has_text(record.get("build_id")),
            "mode": checks["required_fields"].get("mode"),
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "duration_recorded": isinstance(record.get("duration_seconds"), (int, float)),
            "image_size_recorded": checks["image_evidence"].get("status") == "passed",
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_PRODUCTION_IMAGE_BUILD_EXECUTION_STATUS": "passed"
            if checks["required_fields"]["status"] == "passed"
            and checks["background_execution"]["status"] == "passed"
            else "blocked",
            "ZHIXING_PRODUCTION_IMAGE_RUNTIME_INPUT_STATUS": "passed"
            if checks["runtime_input"]["status"] == "passed"
            else "blocked",
            "ZHIXING_PRODUCTION_IMAGE_EVIDENCE_STATUS": "passed"
            if checks["image_evidence"]["status"] == "passed"
            else "blocked",
            "ZHIXING_PRODUCTION_IMAGE_SAFETY_STATUS": "passed"
            if checks["safety"]["status"] == "passed" and checks["redaction_boundary"]["status"] == "passed"
            else "blocked",
            "ZHIXING_PRODUCTION_IMAGE_POST_BUILD_HEALTH_STATUS": "passed"
            if checks["post_build_verification"]["status"] == "passed"
            else "blocked",
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided build execution record; it does not run Docker or connect SSH.",
            "A passed record proves one sampled build window, not long-term build reliability or vulnerability status.",
            "A passed build record does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
            "Raw build logs, SSH targets, deploy directories, image tags, private URLs and secret values must stay outside Git.",
        ],
    }


def build_production_image_build_execution_record_markdown(report: Mapping[str, Any]) -> str:
    checks = report.get("checks") if isinstance(report.get("checks"), Mapping) else {}
    lines = [
        "# Production Image Build Execution Record",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- This report does not run Docker, connect SSH, read `.env` or echo private values.",
        "",
        "| Check | Status | Finding |",
        "|---|---|---|",
    ]
    for name, check in checks.items():
        if isinstance(check, Mapping):
            finding = str(check.get("finding") or "-").replace("|", "\\|")
            lines.append(f"| `{name}` | `{check.get('status')}` | {finding} |")
    blockers = report.get("blocked_reasons") or []
    if blockers:
        lines.extend(["", "## Blocked Reasons", ""])
        for item in blockers:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('check')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _template_record() -> dict[str, Any]:
    return {
        "record_version": PRODUCTION_IMAGE_BUILD_EXECUTION_RECORD_VERSION,
        "build_id": "<production-image-build-YYYYMMDD>",
        "mode": "remote_background_build",
        "started_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "ended_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "duration_seconds": 1200,
        "release_label": "<release label>",
        "build_reason": "<runtime dependency split or production image refresh>",
        "owners": {
            "build_owner": "<build owner role>",
            "release_owner": "<release owner role>",
            "verifier": "<post-build verifier role>",
        },
        "background_execution": {
            "wrapper": "nohup",
            "timeout_seconds": 1800,
            "pid_recorded": "passed",
            "log_path_recorded": "passed",
            "log_redacted": "passed",
            "started_in_background": "passed",
            "exit_code_recorded": "passed",
            "exit_code": 0,
            "timed_out": False,
        },
        "package_mirror": {
            "pip_index_url_configured": "passed",
            "pip_trusted_host_policy_recorded": "passed",
            "mirror_used_recorded": "passed",
            "secret_values_in_url": False,
            "mirror_failure_policy": "retry configured mirror; fallback requires operator note",
        },
        "runtime_input": {
            "runtime_requirements_used": "passed",
            "dockerfile_runtime_input_verified": "passed",
            "runtime_dependency_scope_passed": "passed",
            "full_requirements_used": False,
            "dev_dependencies_installed": False,
            "optional_gpu_stack_installed": False,
        },
        "image_evidence": {
            "image_id_before_present": "passed",
            "image_id_after_present": "passed",
            "image_changed": True,
            "image_size_recorded": "passed",
            "image_size_mb_after": 1500,
        },
        "safety": {
            "disk_guard_passed": "passed",
            "current_release_unchanged_until_success": "passed",
            "no_runtime_data_modified": "passed",
            "used_docker_system_prune": False,
            "deleted_docker_volume": False,
            "deleted_env_file": False,
            "deleted_vectorstore": False,
            "deleted_backup": False,
            "used_bulk_delete": False,
        },
        "post_build_verification": {
            "compose_ps_status": "passed",
            "health_live_status": "passed",
            "health_ready_status": "passed",
            "mock_checkout_status": "not_applicable",
            "mock_checkout_reason": "Image build verification scoped to runtime health; checkout smoke is run in rollout record.",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "raw_urls_included": False,
            "ssh_target_included": False,
            "deploy_dir_included": False,
            "secret_values_included": False,
            "customer_pii_included": False,
        },
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private image build execution JSON record.")
    parser.add_argument("--template", action="store_true", help="Print a private-record template.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        payload: Mapping[str, Any] = _template_record()
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        exit_code = 0
    else:
        if args.record_json is None:
            raise SystemExit("--record-json is required unless --template is used")
        raw_text = args.record_json.read_text(encoding="utf-8")
        record = _read_json(args.record_json)
        report = build_production_image_build_execution_record_report(record, raw_text=raw_text)
        output = (
            json.dumps(report, ensure_ascii=False, indent=2)
            if args.json and not args.markdown
            else build_production_image_build_execution_record_markdown(report)
        )
        exit_code = 2 if report["status"] == "blocked" else 0
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + ("" if output.endswith("\n") else "\n"), encoding="utf-8")
    else:
        print(output, end="" if output.endswith("\n") else "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
