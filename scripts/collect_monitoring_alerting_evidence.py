"""Collect redacted monitoring and alerting evidence for M1 operations."""
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

from scripts.check_monitoring_alerting_readiness import (  # noqa: E402
    build_monitoring_alerting_readiness_report,
)
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


MONITORING_ALERTING_EVIDENCE_VERSION = "monitoring_alerting_evidence.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
NOT_MEASURED_VALUES = {"not measured", "not_measured", "not configured", "not_configured", "pending"}


ALERT_DELIVERY_DECLARATIONS = (
    ("ZHIXING_HEALTH_ALERT_DELIVERY_STATUS", "Health alert delivery status", True),
    ("ZHIXING_READINESS_ALERT_DELIVERY_STATUS", "Readiness alert delivery status", True),
    ("ZHIXING_ALERT_DRILL_OWNER", "Alert drill owner", False),
    ("ZHIXING_ALERT_DRILL_WINDOW", "Alert drill window", False),
)
METRIC_DECLARATIONS = (
    ("ZHIXING_ERROR_RATE_MONITOR_STATUS", "Error-rate monitor status", False),
    ("ZHIXING_P95_LATENCY_MONITOR_STATUS", "P95 latency monitor status", False),
    ("ZHIXING_TOOL_FAILURE_MONITOR_STATUS", "Tool-failure monitor status", False),
    ("ZHIXING_COST_ALERT_STATUS", "Cost alert status", False),
    ("ZHIXING_BACKUP_ALERT_STATUS", "Backup alert status", False),
    ("ZHIXING_LOG_REDACTION_SAMPLE_STATUS", "Log redaction sample status", False),
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
        return {**item, "status": "blocked", "finding": "Missing or placeholder monitoring evidence declaration."}
    if not required_ready and (env_var.endswith("_OWNER") or env_var.endswith("_WINDOW")):
        return {**item, "status": "passed", "finding": "Declared."}
    lowered = value.lower()
    if lowered in READY_VALUES:
        return {**item, "status": "passed", "finding": "Declared as passed/ready."}
    if lowered in NOT_MEASURED_VALUES and not required_ready:
        return {**item, "status": "degraded", "finding": "Declared as not measured or pending."}
    if required_ready:
        return {**item, "status": "blocked", "finding": "Expected passed/ready/completed declaration."}
    return {**item, "status": "degraded", "finding": "Declared but not confirmed as passed."}


def _status_from_checks(checks: list[dict[str, Any]]) -> str:
    statuses = [str(item.get("status") or "unknown") for item in checks]
    if not statuses:
        return "not_checked"
    if any(status in {"blocked", "failed", "unknown"} for status in statuses):
        return "blocked"
    if any(status in {"degraded", "not_checked"} for status in statuses):
        return "degraded"
    return "passed"


def build_alert_delivery_declaration(
    *,
    environ: Mapping[str, str],
    require: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": require,
        "value_echoed": False,
        "checks": [],
        "finding": "Alert delivery declaration not requested.",
    }
    if not require:
        return report
    checks = [
        _declaration_check(
            environ=environ,
            env_var=env_var,
            label=label,
            required_ready=required_ready,
        )
        for env_var, label, required_ready in ALERT_DELIVERY_DECLARATIONS
    ]
    blocked = [item for item in checks if item["status"] == "blocked"]
    report.update(
        {
            "status": _status_from_checks(checks),
            "checks": checks,
            "blocked_reasons": blocked,
            "finding": "Alert delivery declaration completed." if not blocked else "Alert delivery declaration is incomplete.",
        }
    )
    return report


def build_metric_monitoring_declaration(
    *,
    environ: Mapping[str, str],
    require: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": require,
        "value_echoed": False,
        "checks": [],
        "finding": "Metric monitoring declaration not requested.",
    }
    if not require:
        return report
    checks = [
        _declaration_check(
            environ=environ,
            env_var=env_var,
            label=label,
            required_ready=required_ready,
        )
        for env_var, label, required_ready in METRIC_DECLARATIONS
    ]
    report.update(
        {
            "status": _status_from_checks(checks),
            "checks": checks,
            "blocked_reasons": [item for item in checks if item["status"] == "blocked"],
            "degraded_reasons": [item for item in checks if item["status"] == "degraded"],
            "finding": "Metric monitoring declaration completed.",
        }
    )
    return report


def _command_plan() -> list[dict[str, Any]]:
    return [
        {
            "key": "monitoring_readiness",
            "command": "python scripts/check_monitoring_alerting_readiness.py --check-health-url --json",
            "runs_when": "before alert drill",
        },
        {
            "key": "health_alert_drill",
            "command": "trigger provider-side health/readiness alert test, then record delivery status",
            "runs_when": "manual alert drill",
        },
        {
            "key": "metric_alerts",
            "command": "confirm error-rate, P95 and log-redaction monitors",
            "runs_when": "--require-metric-declaration",
        },
        {
            "key": "cost_alert_status",
            "command": (
                "python scripts/check_cost_alert_status.py --check-db-activity "
                "--allow-zero-traffic-estimate --owner-declared --manual-check-status passed --json"
            ),
            "runs_when": "after daily budget and M1 activity window are declared",
        },
        {
            "key": "tool_failure_monitor_status",
            "command": (
                "python scripts/check_tool_failure_monitor_status.py --lookback-hours 24 "
                "--allow-empty-sample --json"
            ),
            "runs_when": "after tool_audit_event persistence is available",
        },
        {
            "key": "backup_alert_status",
            "command": (
                "python scripts/check_backup_alert_status.py --backup-dir <backup-dir> "
                "--require-rag-restore-artifact --json"
            ),
            "runs_when": "after backup and restore drill artifacts are available",
        },
        {
            "key": "post_fix_validation",
            "command": "rerun readiness and acceptance smoke after any P0/P1 alert fix",
            "runs_when": "incident recovery",
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


def build_monitoring_alerting_evidence_report(
    *,
    environ: Mapping[str, str] | None = None,
    include_readiness: bool = False,
    check_health_url: bool = False,
    require_alert_delivery_declaration: bool = False,
    require_metric_declaration: bool = False,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Build a redacted monitoring/alerting evidence report."""

    env = environ if environ is not None else os.environ
    public_url = _value(env, "ZHIXING_PUBLIC_BASE_URL")
    sections: dict[str, dict[str, Any]] = {}

    if include_readiness:
        readiness = build_monitoring_alerting_readiness_report(
            environ=env,
            check_health_url=check_health_url,
            timeout_seconds=timeout_seconds,
        )
        sections["monitoring_alerting_readiness"] = _safe_payload(readiness, public_url=public_url)
    if require_alert_delivery_declaration:
        sections["alert_delivery_declaration"] = build_alert_delivery_declaration(
            environ=env,
            require=True,
        )
    if require_metric_declaration:
        sections["metric_monitoring_declaration"] = build_metric_monitoring_declaration(
            environ=env,
            require=True,
        )

    any_requested = bool(
        include_readiness
        or require_alert_delivery_declaration
        or require_metric_declaration
    )
    report = {
        "version": MONITORING_ALERTING_EVIDENCE_VERSION,
        "status": _overall_status(sections, any_requested=any_requested),
        "policy": {
            "reads_dotenv": False,
            "sends_alerts": False,
            "network_probe_requested": check_health_url and include_readiness,
            "does_not_echo_values": True,
            "alert_delivery_declaration_required": require_alert_delivery_declaration,
            "metric_declaration_required": require_metric_declaration,
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
            "Plan-only mode proves no alert delivery or metric retention.",
            "Readiness health probes prove endpoint reachability only, not alert routing.",
            "Alert delivery declarations are operator evidence; keep provider screenshots and raw messages outside Git.",
            "Metric declarations do not prove long-term retention, paging escalation, or provider-side budget enforcement.",
            "This report does not send test alerts by itself and does not prove full APM or distributed tracing.",
        ],
    }
    return _safe_payload(report, public_url=public_url)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_monitoring_alerting_evidence_markdown(report: Mapping[str, Any]) -> str:
    safe_report = redact_data(dict(report))
    if not isinstance(safe_report, Mapping):
        safe_report = {}
    lines = [
        "# Monitoring Alerting Evidence（监控告警证据）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Reads `.env` | `{_markdown_cell((safe_report.get('policy') or {}).get('reads_dotenv'))}` |",
        f"| Sends alerts | `{_markdown_cell((safe_report.get('policy') or {}).get('sends_alerts'))}` |",
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
    parser.add_argument("--include-readiness", action="store_true", help="Embed monitoring/alerting readiness summary.")
    parser.add_argument("--check-health-url", action="store_true", help="Probe public health endpoints through readiness.")
    parser.add_argument("--require-alert-delivery-declaration", action="store_true", help="Require health/readiness alert delivery declarations.")
    parser.add_argument("--require-metric-declaration", action="store_true", help="Require metric/cost/backup/log-redaction declarations.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout for optional health probes.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_monitoring_alerting_evidence_report(
        include_readiness=args.include_readiness,
        check_health_url=args.check_health_url,
        require_alert_delivery_declaration=args.require_alert_delivery_declaration,
        require_metric_declaration=args.require_metric_declaration,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_monitoring_alerting_evidence_markdown(report)
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
