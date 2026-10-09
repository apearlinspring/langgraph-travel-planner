"""Collect redacted post-deployment M1 smoke evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_deployment_gate import build_m1_deployment_gate_report  # noqa: E402
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


M1_SMOKE_EVIDENCE_VERSION = "m1_smoke_evidence.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
HEALTH_ENDPOINTS = (
    ("health_live", "/health/live"),
    ("health_ready", "/health/ready"),
)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _resolved_base_url(
    *,
    environ: Mapping[str, str],
    base_url: str | None,
) -> tuple[str, str]:
    if base_url and base_url.strip():
        return base_url.strip(), "argument"
    env_value = _value(environ, "ZHIXING_PUBLIC_BASE_URL")
    if env_value:
        return env_value, "environment"
    return "", "missing"


def _public_url_check(base_url: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "blocked",
        "value_echoed": False,
        "source_value_echoed": False,
        "finding": "Missing public base URL.",
    }
    if not base_url:
        return report

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        report["finding"] = "Public base URL must be a full http(s) URL."
    elif parsed.scheme != "https":
        report["finding"] = "Post-deployment smoke requires an HTTPS public base URL."
    elif host in LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local"):
        report["finding"] = "Public base URL must not point to localhost."
    elif (
        host == "example.com"
        or host.endswith(".example.com")
        or host.endswith(".example.net")
        or host.endswith(".example.org")
    ):
        report["finding"] = "Public base URL must not use an example domain."
    else:
        report.update({"status": "passed", "finding": "Public base URL shape is acceptable."})
    return report


def _sanitize_public_target(value: Any, *, base_url: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_public_target(item, base_url=base_url)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_public_target(item, base_url=base_url) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_public_target(item, base_url=base_url) for item in value]
    if isinstance(value, str):
        text = value
        if base_url:
            text = text.replace(base_url, PUBLIC_URL_PLACEHOLDER)
        return redact_text(text)
    return value


def _safe_payload(value: Any, *, base_url: str) -> Any:
    sanitized = _sanitize_public_target(value, base_url=base_url)
    return redact_data(sanitized)


def _probe_url(url: str, *, timeout_seconds: float) -> int:
    request = Request(url, headers={"User-Agent": "zhixing-m1-smoke-evidence/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - explicit smoke probe.
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except (OSError, TimeoutError, URLError) as exc:
        raise RuntimeError(exc.__class__.__name__) from exc


def build_health_probe_report(
    *,
    base_url: str,
    timeout_seconds: float = 5,
    probe_url: Any = _probe_url,
) -> dict[str, Any]:
    url_check = _public_url_check(base_url)
    report: dict[str, Any] = {
        "status": "blocked",
        "checked": True,
        "network_probe_requested": True,
        "value_echoed": False,
        "url_check": url_check,
        "endpoints": [],
    }
    if url_check["status"] == "blocked":
        report["finding"] = url_check["finding"]
        return report

    endpoints = []
    blocked = False
    for key, path in HEALTH_ENDPOINTS:
        item: dict[str, Any] = {
            "endpoint": key,
            "path": path,
            "value_echoed": False,
        }
        try:
            status_code = probe_url(
                base_url.rstrip("/") + path,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            blocked = True
            item.update(
                {
                    "status": "blocked",
                    "finding": f"Health endpoint probe failed: {exc}",
                }
            )
        else:
            item["http_status"] = int(status_code)
            if 200 <= int(status_code) < 400:
                item.update({"status": "passed", "finding": "Endpoint responded successfully."})
            else:
                blocked = True
                item.update({"status": "blocked", "finding": f"Endpoint returned HTTP {status_code}."})
        endpoints.append(item)

    report.update(
        {
            "status": "blocked" if blocked else "passed",
            "endpoints": endpoints,
            "finding": "Public health smoke failed." if blocked else "Public health smoke passed.",
        }
    )
    return report


def _run_command(
    args: Sequence[str],
    *,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def _safe_command_plan() -> list[dict[str, Any]]:
    return [
        {
            "key": "public_health",
            "command": f"GET {PUBLIC_URL_PLACEHOLDER}/health/live and {PUBLIC_URL_PLACEHOLDER}/health/ready",
            "runs_when": "--check-health-url",
        },
        {
            "key": "m1_deployment_gate",
            "command": (
                "python scripts/check_m1_deployment_gate.py --include-acceptance --check-backend "
                "--check-server-docker --check-server-deploy-dir --check-server-disk --check-server-health-url "
                f"--check-monitoring-health-url --base-url {PUBLIC_URL_PLACEHOLDER} --json"
            ),
            "runs_when": "--run-gate",
        },
        {
            "key": "acceptance_smoke",
            "command": (
                "python scripts/run_evaluation_scenarios.py --acceptance-smoke "
                f"--base-url {PUBLIC_URL_PLACEHOLDER} --json"
            ),
            "runs_when": "--run-acceptance-smoke",
            "may_call_external_apis": True,
        },
    ]


def build_gate_section(
    *,
    environ: Mapping[str, str],
    base_url: str,
    check_health_url: bool,
) -> dict[str, Any]:
    gate_report = build_m1_deployment_gate_report(
        environ=environ,
        base_url=base_url,
        include_acceptance=True,
        check_backend=True,
        check_server_docker=True,
        check_server_deploy_dir=True,
        check_server_disk=True,
        check_server_health_url=check_health_url,
        check_monitoring_health_url=check_health_url,
    )
    safe_report = _safe_payload(gate_report, base_url=base_url)
    status = str((safe_report or {}).get("status") or "unknown") if isinstance(safe_report, dict) else "unknown"
    return {
        "status": status,
        "checked": True,
        "command": "python scripts/check_m1_deployment_gate.py ... --base-url <public-url> --json",
        "report": safe_report,
    }


def _acceptance_command(base_url: str) -> list[str]:
    return [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_evaluation_scenarios.py"),
        "--acceptance-smoke",
        "--base-url",
        base_url,
        "--json",
    ]


def _first_safe_line(text: str, *, base_url: str) -> str:
    safe = str(_safe_payload(text, base_url=base_url) or "")
    for line in safe.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:400]
    return ""


def _acceptance_summary_from_json(payload: Mapping[str, Any]) -> dict[str, Any]:
    acceptance_summary = payload.get("acceptance_summary")
    preflight = payload.get("preflight")
    return {
        "status": payload.get("status"),
        "passed": payload.get("passed"),
        "preflight_status": preflight.get("status") if isinstance(preflight, Mapping) else None,
        "selected_count": (
            acceptance_summary.get("selected_count")
            if isinstance(acceptance_summary, Mapping)
            else None
        ),
        "result_count": (
            acceptance_summary.get("result_count")
            if isinstance(acceptance_summary, Mapping)
            else None
        ),
        "missing_required_count": len(payload.get("missing_required") or []),
        "blocking_reason_count": len(payload.get("blocking_reasons") or []),
        "failure_classification_counts": payload.get("failure_classification_counts") or {},
        "raw_payload_included": False,
    }


def build_acceptance_smoke_section(
    *,
    base_url: str,
    timeout_seconds: float,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    url_check = _public_url_check(base_url)
    section: dict[str, Any] = {
        "status": "blocked",
        "checked": True,
        "may_call_external_apis": True,
        "may_write_runtime_artifacts": True,
        "command": "python scripts/run_evaluation_scenarios.py --acceptance-smoke --base-url <public-url> --json",
        "url_check": url_check,
        "value_echoed": False,
    }
    if url_check["status"] == "blocked":
        section["finding"] = url_check["finding"]
        return section

    try:
        result = command_runner(
            _acceptance_command(base_url),
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError:
        section["finding"] = "Python command is not available for acceptance smoke."
        section["failure_category"] = "command_not_available"
        return section
    except subprocess.TimeoutExpired:
        section["finding"] = "Acceptance smoke command timed out."
        section["failure_category"] = "timeout"
        return section

    section["exit_code"] = int(result.returncode)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        section.update(
            {
                "status": "blocked",
                "finding": "Acceptance smoke did not return JSON.",
                "stdout_first_line": _first_safe_line(stdout, base_url=base_url),
                "stderr_first_line": _first_safe_line(stderr, base_url=base_url),
            }
        )
        return section

    safe_parsed = _safe_payload(parsed, base_url=base_url)
    if not isinstance(safe_parsed, Mapping):
        section.update({"status": "blocked", "finding": "Acceptance smoke JSON was not an object."})
        return section

    raw_status = str(safe_parsed.get("status") or "unknown")
    section.update(
        {
            "status": raw_status if result.returncode == 0 else "blocked",
            "smoke_status": raw_status,
            "summary": _acceptance_summary_from_json(safe_parsed),
            "finding": "Acceptance smoke completed." if result.returncode == 0 else "Acceptance smoke returned non-zero.",
        }
    )
    return section


def _overall_status(sections: Mapping[str, Mapping[str, Any]], *, any_requested: bool) -> str:
    if not any_requested:
        return "not_checked"
    statuses = [str(section.get("status") or "unknown") for section in sections.values()]
    if any(status in {"blocked", "failed", "skipped", "unknown"} for status in statuses):
        return "blocked"
    if any(status in {"degraded", "not_checked"} for status in statuses):
        return "degraded"
    return "passed"


def build_m1_smoke_evidence_report(
    *,
    environ: Mapping[str, str] | None = None,
    base_url: str | None = None,
    check_health_url: bool = False,
    run_gate: bool = False,
    run_acceptance_smoke: bool = False,
    timeout_seconds: float = 5,
    command_runner: Any = _run_command,
    probe_url: Any = _probe_url,
) -> dict[str, Any]:
    """Build a redacted post-deployment M1 smoke evidence report."""

    env = environ if environ is not None else os.environ
    resolved_url, url_source = _resolved_base_url(environ=env, base_url=base_url)
    sections: dict[str, dict[str, Any]] = {}

    if check_health_url:
        sections["public_health"] = build_health_probe_report(
            base_url=resolved_url,
            timeout_seconds=timeout_seconds,
            probe_url=probe_url,
        )
    if run_gate:
        sections["m1_deployment_gate"] = build_gate_section(
            environ=env,
            base_url=resolved_url,
            check_health_url=check_health_url,
        )
    if run_acceptance_smoke:
        sections["acceptance_smoke"] = build_acceptance_smoke_section(
            base_url=resolved_url,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )

    any_requested = bool(check_health_url or run_gate or run_acceptance_smoke)
    report = {
        "version": M1_SMOKE_EVIDENCE_VERSION,
        "status": _overall_status(sections, any_requested=any_requested),
        "policy": {
            "reads_dotenv": False,
            "does_not_echo_values": True,
            "network_probe_requested": check_health_url,
            "runs_m1_deployment_gate": run_gate,
            "runs_acceptance_smoke": run_acceptance_smoke,
            "may_call_external_apis": run_acceptance_smoke,
            "may_write_runtime_artifacts": run_acceptance_smoke,
            "starts_services": False,
        },
        "target": {
            "public_base_url_present": bool(resolved_url),
            "public_base_url_source": url_source,
            "public_base_url_echoed": False,
        },
        "command_plan": _safe_command_plan(),
        "section_statuses": {
            name: str(section.get("status") or "unknown")
            for name, section in sections.items()
        },
        "sections": sections,
        "not_proven_by_this_report": [
            "Plan-only mode proves no deployment result; run explicit smoke flags on the target environment.",
            "A passed health check proves reachability only, not business flow correctness.",
            "A passed deployment gate proves configured readiness inputs, not real booking, payment, ticketing, or fulfillment.",
            "Acceptance smoke can consume real LLM and external API quota and must be run intentionally.",
            "This report must stay redacted; raw logs, .env files, database backups, vector stores, and customer data are not public evidence.",
        ],
    }
    return _safe_payload(report, base_url=resolved_url)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_m1_smoke_evidence_markdown(report: Mapping[str, Any]) -> str:
    safe_report = redact_data(dict(report))
    if not isinstance(safe_report, Mapping):
        safe_report = {}
    lines = [
        "# M1 Smoke Evidence（部署后冒烟证据）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Reads `.env` | `{_markdown_cell((safe_report.get('policy') or {}).get('reads_dotenv'))}` |",
        f"| Calls external APIs | `{_markdown_cell((safe_report.get('policy') or {}).get('may_call_external_apis'))}` |",
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

    sections = safe_report.get("sections") or {}
    acceptance = sections.get("acceptance_smoke") if isinstance(sections, Mapping) else None
    if isinstance(acceptance, Mapping):
        summary = acceptance.get("summary") if isinstance(acceptance.get("summary"), Mapping) else {}
        lines.extend(
            [
                "",
                "## Acceptance Smoke 摘要",
                "",
                f"- Status: `{_markdown_cell(acceptance.get('status'))}`",
                f"- Smoke status: `{_markdown_cell(acceptance.get('smoke_status'))}`",
                f"- Selected count: {_markdown_cell(summary.get('selected_count'))}",
                f"- Result count: {_markdown_cell(summary.get('result_count'))}",
                f"- Blocking reason count: {_markdown_cell(summary.get('blocking_reason_count'))}",
                f"- Raw payload included: `{_markdown_cell(summary.get('raw_payload_included'))}`",
            ]
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
    parser.add_argument("--base-url", default=None, help="Public deployment base URL. Falls back to ZHIXING_PUBLIC_BASE_URL.")
    parser.add_argument("--check-health-url", action="store_true", help="Probe public /health/live and /health/ready.")
    parser.add_argument("--run-gate", action="store_true", help="Run the M1 deployment gate and embed the redacted summary.")
    parser.add_argument("--run-acceptance-smoke", action="store_true", help="Run live acceptance smoke. This may call LLM/external APIs.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout for health probes and the smoke command.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_smoke_evidence_report(
        base_url=args.base_url,
        check_health_url=args.check_health_url,
        run_gate=args.run_gate,
        run_acceptance_smoke=args.run_acceptance_smoke,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_m1_smoke_evidence_markdown(report)
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
