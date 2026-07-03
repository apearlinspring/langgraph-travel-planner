"""Render a redacted M1 deployment evidence matrix from private reports.

This renderer does not read `.env`, run probes, connect SSH, query databases,
read Redis keys, inspect logs, start services or print private paths. It only
reads explicitly provided JSON reports and summarizes whether the M1 deployment
evidence chain is ready for controlled-trial signoff.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
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

from scripts.export_acceptance_evidence import redact_text  # noqa: E402


M1_DEPLOYMENT_EVIDENCE_MATRIX_VERSION = "m1_deployment_evidence_matrix.v1"
EXPECTED_REPORTS = {
    "launch_inputs": {
        "label": "M1 launch inputs",
        "version": "m1_launch_inputs.v1",
        "required": True,
        "claim": "Non-secret M1 server, owner, backup, monitoring, budget and acceptance inputs are declared.",
    },
    "go_no_go": {
        "label": "M1 go/no-go",
        "version": "m1_go_no_go_evidence.v1",
        "required": True,
        "claim": "Requested evidence sections have been aggregated into a release decision.",
    },
    "rollout_execution": {
        "label": "Rollout execution",
        "version": "m1_rollout_execution_record.v1",
        "required": True,
        "claim": "The release artifact, deploy phases, health checks, rollback and data-safety record were validated.",
    },
    "operations_review": {
        "label": "Operations review",
        "version": "m1_operations_review_record.v1",
        "required": True,
        "claim": "Post-rollout issues, root cause, mitigation, verification, lessons and follow-ups were reviewed.",
    },
    "private_signoff": {
        "label": "Private evidence signoff",
        "version": "m1_private_evidence_signoff.v1",
        "required": True,
        "claim": "Private evidence hashes, go/no-go decision, review reports and release-owner signoff were validated.",
    },
}
BAD_STATUSES = {"blocked", "failed", "unknown", "skipped", "not_checked", "not_provided"}
DEGRADED_STATUSES = {"degraded", "warning", "conditional_go"}
FORBIDDEN_REPORT_PATH_PARTS = {".env", ".runtime", ".venv", "logs", "vectorstore", "vectorstore_internal"}
SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
    r"\s*[:=]\s*[^&\s,;]+"
)
URL_PATTERN = re.compile(r"https?://[^\s`'\"<>()\[\]{}|]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_forbidden_report_path(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_REPORT_PATH_PARTS)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _status_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"passed", "ready", "ok", "done", "completed", "verified"}:
        return "passed"
    if text in DEGRADED_STATUSES | BAD_STATUSES | {"not_applicable"}:
        return text
    return "unknown"


def _read_private_report(path: Path | None, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    status = {
        "label": label,
        "provided": path is not None,
        "path_echoed": False,
        "status": "not_provided",
    }
    if path is None:
        return {}, status
    resolved = path.resolve()
    if _is_relative_to(resolved, PROJECT_ROOT):
        status.update({"status": "blocked", "reason": "Private report JSON must stay outside the Git workspace."})
        return {}, status
    if _is_forbidden_report_path(resolved):
        status.update({"status": "blocked", "reason": "Private report path points to a forbidden runtime or secret-like location."})
        return {}, status
    try:
        raw_text = resolved.read_text(encoding="utf-8-sig")
    except OSError:
        status.update({"status": "blocked", "reason": "Private report JSON file cannot be read."})
        return {}, status
    if URL_PATTERN.search(raw_text) or IPV4_PATTERN.search(raw_text) or SECRET_PATTERN.search(raw_text):
        status.update({"status": "blocked", "reason": "Private report JSON contains raw URL, IP or secret-looking text."})
        return {}, status
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        status.update({"status": "blocked", "reason": "Private report JSON is not valid JSON."})
        return {}, status
    if not isinstance(payload, dict):
        status.update({"status": "blocked", "reason": "Private report JSON must be an object."})
        return {}, status
    status["status"] = "passed"
    return payload, status


def _signal_for_report(key: str, report: Mapping[str, Any]) -> str:
    if not report:
        return "missing"
    if key == "launch_inputs":
        return (
            f"passed={report.get('passed_count', '-')}/{report.get('input_count', '-')}, "
            f"blocked={report.get('blocked_count', '-')}, degraded={report.get('degraded_count', '-')}"
        )
    if key in {"go_no_go", "supplemental_go_no_go"}:
        section_statuses = _as_mapping(report.get("section_statuses"))
        return f"decision={report.get('decision') or '-'}, sections={len(section_statuses)}"
    if key == "rollout_execution":
        summary = _as_mapping(report.get("record_summary"))
        return (
            f"env={summary.get('environment') or '-'}, "
            f"phases={summary.get('deployment_phase_count') or '-'}, "
            f"issues={summary.get('issue_count', '-')}"
        )
    if key == "operations_review":
        summary = _as_mapping(report.get("record_summary"))
        return (
            f"issues_observed={summary.get('issues_observed')}, "
            f"issues={summary.get('issue_count', '-')}, "
            f"followups={summary.get('followup_count', '-')}"
        )
    if key == "private_signoff":
        signoff = _as_mapping(report.get("signoff"))
        checks = _as_mapping(report.get("checks"))
        review = _as_mapping(checks.get("private_review_reports"))
        return (
            f"release_decision={signoff.get('release_decision') or '-'}, "
            f"review_reports={review.get('status') or '-'}"
        )
    return "available"


def _row_status(
    *,
    key: str,
    expected: Mapping[str, Any],
    report: Mapping[str, Any],
    source_status: Mapping[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    source = _status_value(source_status.get("status"))
    if source != "passed":
        if expected.get("required") or source != "not_provided":
            blockers.append({
                "check": "source",
                "key": key,
                "finding": str(source_status.get("reason") or "Required private report is missing or blocked."),
            })
    if not report:
        return ("blocked" if blockers or expected.get("required") else "not_provided", blockers)
    if report.get("version") != expected.get("version"):
        blockers.append({"check": "version", "key": key, "finding": "Report version is not recognized."})
    report_status = _status_value(report.get("status"))
    if report_status in BAD_STATUSES:
        blockers.append({"check": "status", "key": key, "finding": f"Report status is {report_status}."})
    if key in {"go_no_go", "supplemental_go_no_go"}:
        decision = str(report.get("decision") or "")
        if decision == "no_go":
            blockers.append({"check": "decision", "key": key, "finding": "Go/no-go decision is no_go."})
        if decision == "conditional_go" and not blockers:
            return "degraded", blockers
    if blockers:
        return "blocked", blockers
    if report_status in DEGRADED_STATUSES:
        return "degraded", blockers
    return "passed", blockers


def _matrix_row(
    key: str,
    report: Mapping[str, Any],
    source_status: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    expected = EXPECTED_REPORTS[key]
    status, blockers = _row_status(
        key=key,
        expected=expected,
        report=report,
        source_status=source_status,
    )
    row = {
        "key": key,
        "label": expected["label"],
        "required": bool(expected["required"]),
        "present": bool(report),
        "status": status,
        "source_status": source_status.get("status"),
        "version_ok": bool(report) and report.get("version") == expected["version"],
        "report_status": report.get("status") if report else "missing",
        "signal": _signal_for_report(key, report),
        "claim": expected["claim"],
        "value_echoed": False,
    }
    return row, blockers


def _supplemental_go_no_go_row(
    *,
    index: int,
    report: Mapping[str, Any],
    source_status: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    expected = {
        "label": f"Supplemental go/no-go #{index}",
        "version": "m1_go_no_go_evidence.v1",
        "required": False,
        "claim": (
            "Supplemental post-signoff evidence is recorded separately; it does not "
            "extend the private signoff coverage."
        ),
    }
    status, blockers = _row_status(
        key="supplemental_go_no_go",
        expected=expected,
        report=report,
        source_status=source_status,
    )
    row = {
        "key": f"supplemental_go_no_go_{index}",
        "kind": "supplemental_go_no_go",
        "label": expected["label"],
        "required": False,
        "present": bool(report),
        "status": status,
        "source_status": source_status.get("status"),
        "version_ok": bool(report) and report.get("version") == expected["version"],
        "report_status": report.get("status") if report else "missing",
        "signal": _signal_for_report("supplemental_go_no_go", report),
        "claim": expected["claim"],
        "covered_by_private_signoff": False,
        "value_echoed": False,
    }
    for item in blockers:
        item["key"] = row["key"]
    return row, blockers


def build_m1_deployment_evidence_matrix_report(
    *,
    launch_inputs_report: Mapping[str, Any] | None = None,
    go_no_go_report: Mapping[str, Any] | None = None,
    rollout_report: Mapping[str, Any] | None = None,
    operations_review_report: Mapping[str, Any] | None = None,
    signoff_report: Mapping[str, Any] | None = None,
    supplemental_go_no_go_reports: Sequence[Mapping[str, Any]] | None = None,
    source_statuses: list[Mapping[str, Any]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted deployment evidence matrix from private reports."""

    reports = {
        "launch_inputs": _as_mapping(launch_inputs_report),
        "go_no_go": _as_mapping(go_no_go_report),
        "rollout_execution": _as_mapping(rollout_report),
        "operations_review": _as_mapping(operations_review_report),
        "private_signoff": _as_mapping(signoff_report),
    }
    source_status_by_label = {
        str(item.get("label") or ""): dict(item)
        for item in (source_statuses or [])
        if isinstance(item, Mapping)
    }
    source_label_for_key = {
        "launch_inputs": "launch_inputs_report_json",
        "go_no_go": "go_no_go_json",
        "rollout_execution": "rollout_report_json",
        "operations_review": "operations_review_report_json",
        "private_signoff": "signoff_report_json",
    }
    matrix = []
    supplemental_evidence = []
    blockers: list[dict[str, str]] = []
    for key in EXPECTED_REPORTS:
        source_status = source_status_by_label.get(
            source_label_for_key[key],
            {"label": source_label_for_key[key], "status": "passed" if reports[key] else "not_provided", "path_echoed": False},
        )
        row, row_blockers = _matrix_row(key, reports[key], source_status)
        matrix.append(row)
        blockers.extend(row_blockers)

    for index, report in enumerate(supplemental_go_no_go_reports or [], start=1):
        source_label = f"supplemental_go_no_go_json_{index}"
        source_status = source_status_by_label.get(
            source_label,
            {"label": source_label, "status": "passed" if report else "not_provided", "path_echoed": False},
        )
        row, row_blockers = _supplemental_go_no_go_row(
            index=index,
            report=_as_mapping(report),
            source_status=source_status,
        )
        supplemental_evidence.append(row)
        blockers.extend(row_blockers)

    all_rows = matrix + supplemental_evidence
    blocked_count = sum(1 for row in all_rows if row["status"] == "blocked")
    degraded_count = sum(1 for row in all_rows if row["status"] == "degraded")
    passed_count = sum(1 for row in all_rows if row["status"] == "passed")
    supplemental_blocked_count = sum(1 for row in supplemental_evidence if row["status"] == "blocked")
    supplemental_degraded_count = sum(1 for row in supplemental_evidence if row["status"] == "degraded")
    status = "blocked" if blocked_count else "degraded" if degraded_count else "passed"
    go_decision = str(_as_mapping(go_no_go_report).get("decision") or "unknown")
    signoff_status = _status_value(_as_mapping(signoff_report).get("status"))
    now = generated_at or datetime.now(UTC)
    return {
        "version": M1_DEPLOYMENT_EVIDENCE_MATRIX_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "runs_live_probes": False,
            "connects_ssh": False,
            "queries_database": False,
            "reads_redis_keys": False,
            "reads_raw_logs": False,
            "records_source_paths": False,
            "records_private_values": False,
        },
        "summary": {
            "required_report_count": len(EXPECTED_REPORTS),
            "supplemental_report_count": len(supplemental_evidence),
            "passed_count": passed_count,
            "degraded_count": degraded_count,
            "blocked_count": blocked_count,
            "supplemental_blocked_count": supplemental_blocked_count,
            "supplemental_degraded_count": supplemental_degraded_count,
            "go_no_go_decision": go_decision,
            "private_signoff_status": signoff_status,
            "can_claim_m1_controlled_trial_ready": (
                status in {"passed", "degraded"}
                and signoff_status == "passed"
                and supplemental_blocked_count == 0
            ),
            "can_claim_full_production_ready": False,
            "supplemental_evidence_extends_signoff": False,
        },
        "matrix": matrix,
        "supplemental_evidence": supplemental_evidence,
        "source_statuses": [dict(item) for item in (source_statuses or [])],
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This matrix summarizes existing reports; it does not run live checks or deploy code.",
            "Supplemental evidence is listed separately and does not extend the scope of an older private signoff.",
            "It does not prove autoscaling, multi-region HA, long-duration soak stability, real payment, booking, inventory lock, ticketing or fulfillment.",
            "Raw private evidence, screenshots, logs, .env files, vector stores and customer data must remain outside Git.",
        ],
    }


def build_m1_deployment_evidence_matrix_report_from_files(
    *,
    launch_inputs_report_json: Path | None = None,
    go_no_go_json: Path | None = None,
    rollout_report_json: Path | None = None,
    operations_review_report_json: Path | None = None,
    signoff_report_json: Path | None = None,
    supplemental_go_no_go_json: Sequence[Path] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    launch, launch_status = _read_private_report(launch_inputs_report_json, label="launch_inputs_report_json")
    go_no_go, go_status = _read_private_report(go_no_go_json, label="go_no_go_json")
    rollout, rollout_status = _read_private_report(rollout_report_json, label="rollout_report_json")
    operations, operations_status = _read_private_report(
        operations_review_report_json,
        label="operations_review_report_json",
    )
    signoff, signoff_status = _read_private_report(signoff_report_json, label="signoff_report_json")
    supplemental_reports: list[dict[str, Any]] = []
    supplemental_statuses: list[dict[str, Any]] = []
    for index, path in enumerate(supplemental_go_no_go_json or [], start=1):
        payload, status = _read_private_report(path, label=f"supplemental_go_no_go_json_{index}")
        supplemental_reports.append(payload)
        supplemental_statuses.append(status)
    return build_m1_deployment_evidence_matrix_report(
        launch_inputs_report=launch,
        go_no_go_report=go_no_go,
        rollout_report=rollout,
        operations_review_report=operations,
        signoff_report=signoff,
        supplemental_go_no_go_reports=supplemental_reports,
        source_statuses=[
            launch_status,
            go_status,
            rollout_status,
            operations_status,
            signoff_status,
            *supplemental_statuses,
        ],
        generated_at=generated_at,
    )


def _markdown_cell(value: Any) -> str:
    text = redact_text(str(value if value not in {None, ""} else "-"))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_m1_deployment_evidence_matrix_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 Deployment Evidence Matrix",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Generated at | `{_markdown_cell(report.get('generated_at'))}` |",
        f"| Reads `.env` | `{_markdown_cell(_as_mapping(report.get('policy')).get('reads_dotenv'))}` |",
        f"| Runs live probes | `{_markdown_cell(_as_mapping(report.get('policy')).get('runs_live_probes'))}` |",
        f"| Can claim M1 ready | `{_markdown_cell(_as_mapping(report.get('summary')).get('can_claim_m1_controlled_trial_ready'))}` |",
        f"| Can claim full production ready | `{_markdown_cell(_as_mapping(report.get('summary')).get('can_claim_full_production_ready'))}` |",
        "",
        "## Evidence Matrix",
        "",
        "| Evidence | Status | Present | Required | Signal | Claim |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("matrix") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(row.get('label'))} | "
            f"`{_markdown_cell(row.get('status'))}` | "
            f"`{_markdown_cell(row.get('present'))}` | "
            f"`{_markdown_cell(row.get('required'))}` | "
            f"{_markdown_cell(row.get('signal'))} | "
            f"{_markdown_cell(row.get('claim'))} |"
        )
    supplemental = report.get("supplemental_evidence") if isinstance(report.get("supplemental_evidence"), list) else []
    if supplemental:
        lines.extend(
            [
                "",
                "## Supplemental Evidence",
                "",
                "| Evidence | Status | Covered by signoff | Signal | Claim |",
                "|---|---|---|---|---|",
            ]
        )
        for row in supplemental:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(row.get('label'))} | "
                f"`{_markdown_cell(row.get('status'))}` | "
                f"`{_markdown_cell(row.get('covered_by_private_signoff'))}` | "
                f"{_markdown_cell(row.get('signal'))} | "
                f"{_markdown_cell(row.get('claim'))} |"
            )
    lines.extend(["", "## Blockers", "", "| Check | Key | Finding |", "|---|---|---|"])
    blockers = report.get("blocked_reasons") if isinstance(report.get("blocked_reasons"), list) else []
    if blockers:
        for item in blockers:
            if isinstance(item, Mapping):
                lines.append(
                    f"| {_markdown_cell(item.get('check'))} | {_markdown_cell(item.get('key'))} | {_markdown_cell(item.get('finding'))} |"
                )
    else:
        lines.append("| - | - | - |")
    lines.extend(["", "## Boundary", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-inputs-report-json", type=_path_arg, default=None)
    parser.add_argument("--go-no-go-json", type=_path_arg, default=None)
    parser.add_argument("--rollout-report-json", type=_path_arg, default=None)
    parser.add_argument("--operations-review-report-json", type=_path_arg, default=None)
    parser.add_argument("--signoff-report-json", type=_path_arg, default=None)
    parser.add_argument("--supplemental-go-no-go-json", type=_path_arg, action="append", default=[])
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_deployment_evidence_matrix_report_from_files(
        launch_inputs_report_json=args.launch_inputs_report_json,
        go_no_go_json=args.go_no_go_json,
        rollout_report_json=args.rollout_report_json,
        operations_review_report_json=args.operations_review_report_json,
        signoff_report_json=args.signoff_report_json,
        supplemental_go_no_go_json=args.supplemental_go_no_go_json,
    )
    output_text = (
        build_m1_deployment_evidence_matrix_markdown(report)
        if args.markdown and not args.json
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
