"""Collect redacted incident response and rollback drill evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_m1_smoke_evidence import build_m1_smoke_evidence_report  # noqa: E402
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


INCIDENT_ROLLBACK_EVIDENCE_VERSION = "incident_rollback_evidence.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
DEGRADED_VALUES = {"degraded", "partial", "warning", "not measured", "not_measured", "pending"}


OWNERSHIP_DECLARATIONS = (
    ("ZHIXING_ROLLBACK_OWNER", "Rollback owner", False),
    ("ZHIXING_INCIDENT_OWNER", "Incident owner", False),
)
ROLLBACK_DRILL_DECLARATIONS = (
    ("ZHIXING_ROLLBACK_DRILL_STATUS", "Rollback drill status", True),
    ("ZHIXING_ROLLBACK_TARGET_STATUS", "Rollback target status", True),
    ("ZHIXING_POST_ROLLBACK_HEALTH_STATUS", "Post-rollback health status", True),
    ("ZHIXING_POST_ROLLBACK_SMOKE_STATUS", "Post-rollback smoke status", True),
    ("ZHIXING_ROLLBACK_DATA_SAFETY_STATUS", "Rollback data safety status", True),
)
INCIDENT_REVIEW_DECLARATIONS = (
    ("ZHIXING_INCIDENT_RESPONSE_STATUS", "Incident response status", True),
    ("ZHIXING_INCIDENT_REVIEW_STATUS", "Incident review status", True),
    ("ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS", "Incident severity policy status", True),
    ("ZHIXING_INCIDENT_COMMUNICATION_STATUS", "Incident communication status", True),
)


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _safe_payload(value: Any, *, public_url: str = "") -> Any:
    def sanitize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): sanitize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [sanitize(value) for value in item]
        if isinstance(item, tuple):
            return [sanitize(value) for value in item]
        if isinstance(item, str):
            text = item
            if public_url:
                text = text.replace(public_url, PUBLIC_URL_PLACEHOLDER)
            return redact_text(text)
        return item

    return redact_data(sanitize(value))


def _declaration_check(
    *,
    environ: Mapping[str, str],
    env_var: str,
    label: str,
    required_ready: bool,
) -> dict[str, Any]:
    value = _value(environ, env_var)
    item = {
        "env_var": env_var,
        "label": label,
        "value_echoed": False,
    }
    if not value or _looks_placeholder(value):
        return {**item, "status": "blocked", "finding": "Missing or placeholder incident/rollback declaration."}
    if not required_ready:
        return {**item, "status": "passed", "finding": "Declared."}

    lowered = value.lower()
    if lowered in READY_VALUES:
        return {**item, "status": "passed", "finding": "Declared as passed/ready."}
    if lowered in DEGRADED_VALUES:
        return {**item, "status": "degraded", "finding": "Declared as degraded or pending."}
    return {**item, "status": "blocked", "finding": "Expected passed/ready/completed declaration."}


def _build_declaration_section(
    *,
    environ: Mapping[str, str],
    declarations: tuple[tuple[str, str, bool], ...],
    checked: bool,
    label: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": checked,
        "value_echoed": False,
        "checks": [],
        "finding": f"{label} declaration not requested.",
    }
    if not checked:
        return report

    checks = [
        _declaration_check(
            environ=environ,
            env_var=env_var,
            label=item_label,
            required_ready=required_ready,
        )
        for env_var, item_label, required_ready in declarations
    ]
    statuses = [str(item.get("status") or "unknown") for item in checks]
    if any(status in {"blocked", "failed", "unknown"} for status in statuses):
        status = "blocked"
    elif any(status in {"degraded", "not_checked"} for status in statuses):
        status = "degraded"
    else:
        status = "passed"
    report.update(
        {
            "status": status,
            "checks": checks,
            "blocked_reasons": [item for item in checks if item["status"] == "blocked"],
            "degraded_reasons": [item for item in checks if item["status"] == "degraded"],
            "finding": f"{label} declaration completed.",
        }
    )
    return report


def _command_plan() -> list[dict[str, Any]]:
    return [
        {
            "key": "rollback_owner",
            "command": "confirm rollback owner, incident owner, and escalation path",
            "runs_when": "--require-ownership-declaration",
        },
        {
            "key": "rollback_drill",
            "command": "execute an approved rollback window, then validate the private record with scripts/check_rollback_execution_record.py",
            "runs_when": "manual rollback drill",
        },
        {
            "key": "non_destructive_rollback_rehearsal",
            "command": (
                "python scripts/check_rollback_rehearsal_status.py --deploy-dir <deploy-dir> "
                "--backup-dir <rollback-backup-dir> --release-archive <release-archive> "
                "--check-health --check-mock-checkout --json"
            ),
            "runs_when": "before a real rollback window",
        },
        {
            "key": "post_rollback_validation",
            "command": "run health/readiness, M1 gate and mock checkout boundary after rollback; record the results in the private rollback record",
            "runs_when": "--include-post-rollback-smoke-evidence",
        },
        {
            "key": "incident_review",
            "command": "python scripts/check_incident_tabletop_status.py --record-json <private-tabletop-record.json> --json",
            "runs_when": "--require-incident-review-declaration",
        },
    ]


def _overall_status(sections: Mapping[str, Mapping[str, Any]], *, any_requested: bool) -> str:
    if not any_requested:
        return "not_checked"
    statuses = [str(section.get("status") or "unknown") for section in sections.values()]
    if any(status in {"blocked", "failed", "unknown"} for status in statuses):
        return "blocked"
    if any(status in {"degraded", "not_checked"} for status in statuses):
        return "degraded"
    return "passed"


def build_incident_rollback_evidence_report(
    *,
    environ: Mapping[str, str] | None = None,
    require_ownership_declaration: bool = False,
    require_rollback_drill_declaration: bool = False,
    require_incident_review_declaration: bool = False,
    include_post_rollback_smoke_evidence: bool = False,
    check_health_url: bool = False,
    run_gate: bool = False,
    run_acceptance_smoke: bool = False,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Build a redacted incident response and rollback evidence report."""

    env = environ if environ is not None else os.environ
    public_url = _value(env, "ZHIXING_PUBLIC_BASE_URL")
    sections: dict[str, dict[str, Any]] = {}

    if require_ownership_declaration:
        sections["ownership_declaration"] = _build_declaration_section(
            environ=env,
            declarations=OWNERSHIP_DECLARATIONS,
            checked=True,
            label="Ownership",
        )
    if require_rollback_drill_declaration:
        sections["rollback_drill_declaration"] = _build_declaration_section(
            environ=env,
            declarations=ROLLBACK_DRILL_DECLARATIONS,
            checked=True,
            label="Rollback drill",
        )
    if require_incident_review_declaration:
        sections["incident_review_declaration"] = _build_declaration_section(
            environ=env,
            declarations=INCIDENT_REVIEW_DECLARATIONS,
            checked=True,
            label="Incident review",
        )
    if include_post_rollback_smoke_evidence:
        smoke = build_m1_smoke_evidence_report(
            environ=env,
            check_health_url=check_health_url,
            run_gate=run_gate,
            run_acceptance_smoke=run_acceptance_smoke,
            timeout_seconds=timeout_seconds,
        )
        sections["post_rollback_smoke_evidence"] = _safe_payload(smoke, public_url=public_url)

    any_requested = bool(
        require_ownership_declaration
        or require_rollback_drill_declaration
        or require_incident_review_declaration
        or include_post_rollback_smoke_evidence
    )
    report = {
        "version": INCIDENT_ROLLBACK_EVIDENCE_VERSION,
        "status": _overall_status(sections, any_requested=any_requested),
        "policy": {
            "reads_dotenv": False,
            "executes_rollback": False,
            "starts_services": False,
            "does_not_echo_values": True,
            "may_call_external_apis": bool(include_post_rollback_smoke_evidence and run_acceptance_smoke),
            "post_rollback_smoke_requested": include_post_rollback_smoke_evidence,
        },
        "target": {
            "public_base_url_present": bool(public_url),
            "public_base_url_echoed": False,
        },
        "command_plan": _command_plan(),
        "section_statuses": {
            name: str(section.get("status") or "unknown")
            for name, section in sections.items()
        },
        "sections": sections,
        "not_proven_by_this_report": [
            "Plan-only mode proves no rollback or incident response result.",
            "Declaration sections are operator evidence; keep raw incident tickets, logs and screenshots outside Git.",
            "This script does not execute rollback, modify services, delete data or restore databases.",
            "Post-rollback smoke may call real LLM/external APIs only when explicitly requested.",
            "A passed rollback drill does not permit real payment, booking, price lock, ticketing or fulfillment.",
        ],
    }
    return _safe_payload(report, public_url=public_url)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_incident_rollback_evidence_markdown(report: Mapping[str, Any]) -> str:
    safe_report = redact_data(dict(report))
    if not isinstance(safe_report, Mapping):
        safe_report = {}
    lines = [
        "# Incident Rollback Evidence（事故响应与回滚演练证据）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Reads `.env` | `{_markdown_cell((safe_report.get('policy') or {}).get('reads_dotenv'))}` |",
        f"| Executes rollback | `{_markdown_cell((safe_report.get('policy') or {}).get('executes_rollback'))}` |",
        f"| Public URL echoed | `{_markdown_cell((safe_report.get('target') or {}).get('public_base_url_echoed'))}` |",
        "",
        "## Section 状态",
        "",
        "| Section | Status |",
        "|---|---|",
    ]
    statuses = safe_report.get("section_statuses") or {}
    if isinstance(statuses, Mapping) and statuses:
        for section, status in sorted(statuses.items()):
            lines.append(f"| {_markdown_cell(section)} | {_markdown_cell(status)} |")
    else:
        lines.append("| - | not_checked |")

    lines.extend(["", "## 执行计划", "", "| Key | Command | Runs when |", "|---|---|---|"])
    for item in safe_report.get("command_plan") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"`{_markdown_cell(item.get('command'))}` | "
            f"{_markdown_cell(item.get('runs_when'))} |"
        )

    lines.extend(["", "## 边界", ""])
    for item in safe_report.get("not_proven_by_this_report") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is human Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    parser.add_argument("--require-ownership-declaration", action="store_true", help="Require rollback and incident owner declarations.")
    parser.add_argument("--require-rollback-drill-declaration", action="store_true", help="Require rollback drill status declarations.")
    parser.add_argument("--require-incident-review-declaration", action="store_true", help="Require incident response/review declarations.")
    parser.add_argument("--include-post-rollback-smoke-evidence", action="store_true", help="Embed post-rollback smoke evidence.")
    parser.add_argument("--check-health-url", action="store_true", help="Probe public health endpoints inside post-rollback smoke evidence.")
    parser.add_argument("--run-gate", action="store_true", help="Run M1 gate inside post-rollback smoke evidence.")
    parser.add_argument("--run-acceptance-smoke", action="store_true", help="Run live acceptance smoke after rollback. This may call LLM/external APIs.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout for optional probes.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_incident_rollback_evidence_report(
        require_ownership_declaration=args.require_ownership_declaration,
        require_rollback_drill_declaration=args.require_rollback_drill_declaration,
        require_incident_review_declaration=args.require_incident_review_declaration,
        include_post_rollback_smoke_evidence=args.include_post_rollback_smoke_evidence,
        check_health_url=args.check_health_url,
        run_gate=args.run_gate,
        run_acceptance_smoke=args.run_acceptance_smoke,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_incident_rollback_evidence_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(output_text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
