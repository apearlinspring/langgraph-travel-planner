"""Run the M1 deployment gate without reading .env files or starting services."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

if "--json" in sys.argv:
    os.environ.setdefault("ZHIXING_SUPPRESS_CONSOLE_LOGS", "1")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_launch_inputs import (  # noqa: E402
    build_m1_launch_inputs_report,
    load_m1_launch_input_values,
)
from scripts.check_public_release_boundary import build_public_release_boundary_report  # noqa: E402
from scripts.check_release_candidate_freeze import build_release_candidate_freeze_report  # noqa: E402
from scripts.check_backup_restore_readiness import build_backup_restore_readiness_report  # noqa: E402
from scripts.check_external_api_readiness import build_external_api_readiness_report  # noqa: E402
from scripts.check_monitoring_alerting_readiness import build_monitoring_alerting_readiness_report  # noqa: E402
from scripts.check_security_release_readiness import build_security_release_readiness_report  # noqa: E402
from scripts.check_server_preflight_readiness import build_server_preflight_readiness_report  # noqa: E402


M1_DEPLOYMENT_GATE_VERSION = "m1_deployment_gate.v1"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
NO_DOTENV_PATH = PROJECT_ROOT / "__m1_gate_does_not_read_dotenv__.env"
COMPOSE_CONFIG_COMMAND = (
    "docker compose --env-file .env.example config --quiet"
)


def _run_command(
    args: Sequence[str],
    *,
    timeout_seconds: float = 30,
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


def _summarize_process(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return (output.splitlines()[0] if output else f"exit code {result.returncode}")[:400]


def build_compose_config_gate_report(*, check: bool = True) -> dict[str, Any]:
    """Validate docker-compose.yml shape using .env.example only."""

    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "command": COMPOSE_CONFIG_COMMAND,
        "uses_env_file": ".env.example",
        "starts_services": False,
        "findings": [],
        "blocked_reasons": [],
        "repair_suggestions": [],
    }
    if not check:
        return report

    try:
        result = _run_command(
            ["docker", "compose", "--env-file", ".env.example", "config", "--quiet"],
            timeout_seconds=30,
        )
    except FileNotFoundError:
        finding = "Docker CLI is not available; cannot validate docker-compose.yml."
        report["status"] = "blocked"
        report["findings"].append(finding)
        report["blocked_reasons"].append(
            {
                "target": "compose_config",
                "key": "docker_cli",
                "reason": finding,
            }
        )
        report["repair_suggestions"].append(
            {
                "target": "compose_config",
                "key": "docker_cli",
                "action": "Install Docker CLI or run this gate inside an environment with Docker Compose available.",
            }
        )
        return report
    except subprocess.TimeoutExpired:
        finding = "docker compose config timed out."
        report["status"] = "blocked"
        report["findings"].append(finding)
        report["blocked_reasons"].append(
            {
                "target": "compose_config",
                "key": "docker_compose_timeout",
                "reason": finding,
            }
        )
        report["repair_suggestions"].append(
            {
                "target": "compose_config",
                "key": "docker_compose_timeout",
                "action": "Check Docker Compose installation and retry the config validation.",
            }
        )
        return report

    if result.returncode != 0:
        finding = "docker compose config failed: " + _summarize_process(result)
        report["status"] = "blocked"
        report["findings"].append(finding)
        report["blocked_reasons"].append(
            {
                "target": "compose_config",
                "key": "docker_compose_config",
                "reason": finding,
            }
        )
        report["repair_suggestions"].append(
            {
                "target": "compose_config",
                "key": "docker_compose_config",
                "action": "Fix docker-compose.yml or .env.example so Docker Compose can render the deployment config.",
            }
        )
        return report

    report["status"] = "passed"
    return report


def _status_from_section(section: Mapping[str, Any]) -> str:
    return str(section.get("status") or "unknown")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        payload: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key == "environ" and isinstance(item, Mapping):
                payload[text_key] = {
                    "redacted": True,
                    "key_count": len(item),
                }
                continue
            payload[text_key] = _json_safe(item)
        return payload
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _blocked_m1_input_json_report(path: Path, reason: str) -> dict[str, Any]:
    return {
        "version": "m1_launch_inputs.v1",
        "status": "blocked",
        "source": f"input_json:{path.name}",
        "policy": {
            "reads_env_files": False,
            "reads_input_json": True,
            "does_not_echo_values": True,
            "checks_non_secret_inputs_only": True,
        },
        "blocked_reasons": [
            {
                "section": "m1_launch_inputs",
                "target": "m1_launch_inputs",
                "key": "input_json",
                "reason": reason,
            }
        ],
        "repair_suggestions": [
            {
                "section": "m1_launch_inputs",
                "key": "input_json",
                "action": "Regenerate a non-secret template with check_m1_launch_inputs.py --template, fill it outside Git, and retry --m1-input-json.",
            }
        ],
    }


def build_runtime_readiness_report_without_dotenv(**kwargs: Any) -> dict[str, Any]:
    previous = os.environ.get("ZHIXING_DISABLE_DOTENV")
    os.environ["ZHIXING_DISABLE_DOTENV"] = "1"
    try:
        from scripts.check_runtime_readiness import build_runtime_readiness_report

        return build_runtime_readiness_report(**kwargs)
    finally:
        if previous is None:
            os.environ.pop("ZHIXING_DISABLE_DOTENV", None)
        else:
            os.environ["ZHIXING_DISABLE_DOTENV"] = previous


def _collect_section_blockers(
    *,
    section_name: str,
    section: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in section.get("blocked_reasons") or []:
        if isinstance(item, Mapping):
            payload = dict(item)
            payload.setdefault("section", section_name)
            payload.setdefault("target", section_name)
            blockers.append(payload)
    if not blockers and section.get("status") == "blocked":
        blockers.append(
            {
                "section": section_name,
                "target": section_name,
                "key": section_name,
                "reason": "Section status is blocked.",
            }
        )
    return blockers


def build_m1_deployment_gate_report(
    *,
    environ: Mapping[str, str] | None = None,
    m1_input_values: Mapping[str, str] | None = None,
    m1_input_source: str | None = None,
    m1_launch_inputs_report: Mapping[str, Any] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    check_backend: bool = False,
    include_acceptance: bool = False,
    check_public_boundary: bool = True,
    check_release_freeze: bool = True,
    check_m1_inputs: bool = True,
    check_compose_config: bool = True,
    check_runtime: bool = True,
    check_rag_mixed_corpus_safety: bool = True,
    check_backup_readiness: bool = True,
    check_backup_filesystem: bool = False,
    check_backup_tools: bool = False,
    check_monitoring_readiness: bool = True,
    check_monitoring_health_url: bool = False,
    check_security_readiness: bool = True,
    check_external_api_readiness: bool = True,
    check_server_preflight: bool = True,
    check_server_docker: bool = False,
    check_server_deploy_dir: bool = False,
    check_server_disk: bool = False,
    check_server_health_url: bool = False,
) -> dict[str, Any]:
    """Build a redacted aggregate M1 deployment gate report."""

    env = environ if environ is not None else os.environ
    sections: dict[str, dict[str, Any]] = {}

    if check_public_boundary:
        sections["public_release_boundary"] = build_public_release_boundary_report()
    else:
        sections["public_release_boundary"] = {"status": "not_checked", "checked": False}

    if check_release_freeze:
        sections["release_candidate_freeze"] = build_release_candidate_freeze_report()
    else:
        sections["release_candidate_freeze"] = {"status": "not_checked", "checked": False}

    if check_m1_inputs:
        if m1_launch_inputs_report is not None:
            sections["m1_launch_inputs"] = dict(m1_launch_inputs_report)
        elif m1_input_values is not None:
            sections["m1_launch_inputs"] = build_m1_launch_inputs_report(
                input_values=m1_input_values,
                source=m1_input_source or "input_values",
            )
        else:
            sections["m1_launch_inputs"] = build_m1_launch_inputs_report(environ=env)
    else:
        sections["m1_launch_inputs"] = {"status": "not_checked", "checked": False}

    if check_server_preflight:
        sections["server_preflight_readiness"] = build_server_preflight_readiness_report(
            environ=env,
            check_docker=check_server_docker,
            check_deploy_dir=check_server_deploy_dir,
            check_disk=check_server_disk,
            check_health_url=check_server_health_url,
        )
    else:
        sections["server_preflight_readiness"] = {"status": "not_checked", "checked": False}

    sections["compose_config"] = build_compose_config_gate_report(check=check_compose_config)

    if check_backup_readiness:
        sections["backup_restore_readiness"] = build_backup_restore_readiness_report(
            environ=env,
            check_filesystem=check_backup_filesystem,
            check_tools=check_backup_tools,
        )
    else:
        sections["backup_restore_readiness"] = {"status": "not_checked", "checked": False}

    if check_monitoring_readiness:
        sections["monitoring_alerting_readiness"] = build_monitoring_alerting_readiness_report(
            environ=env,
            check_health_url=check_monitoring_health_url,
        )
    else:
        sections["monitoring_alerting_readiness"] = {"status": "not_checked", "checked": False}

    if check_security_readiness:
        sections["security_release_readiness"] = build_security_release_readiness_report(
            environ=env,
            check_public_boundary=False,
        )
    else:
        sections["security_release_readiness"] = {"status": "not_checked", "checked": False}

    if check_external_api_readiness:
        sections["external_api_readiness"] = build_external_api_readiness_report(environ=env)
    else:
        sections["external_api_readiness"] = {"status": "not_checked", "checked": False}

    if check_runtime:
        targets = ["production", "acceptance"] if include_acceptance else ["production"]
        sections["runtime_readiness"] = build_runtime_readiness_report_without_dotenv(
            targets=targets,
            base_url=base_url,
            environ=env,
            dotenv_path=NO_DOTENV_PATH,
            check_backend=check_backend,
            check_docker=False,
            check_rag_mixed_corpus_safety=check_rag_mixed_corpus_safety,
            check_rag_multimodal_e2e=False,
        )
    else:
        sections["runtime_readiness"] = {"status": "not_checked", "checked": False}

    section_statuses = {
        name: _status_from_section(section)
        for name, section in sections.items()
    }
    if any(status in {"blocked", "skipped", "failed"} for status in section_statuses.values()):
        status = "blocked"
    elif any(status in {"degraded", "not_checked", "warning"} for status in section_statuses.values()):
        status = "degraded"
    else:
        status = "passed"

    blocked_reasons: list[dict[str, Any]] = []
    for section_name, section in sections.items():
        blocked_reasons.extend(
            _collect_section_blockers(section_name=section_name, section=section)
        )

    report = {
        "version": M1_DEPLOYMENT_GATE_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "does_not_echo_secret_values": True,
            "starts_services": False,
            "uses_current_process_environment": True,
            "uses_m1_input_json": m1_input_values is not None
            or m1_launch_inputs_report is not None,
        },
        "base_url": base_url,
        "check_backend": check_backend,
        "include_acceptance": include_acceptance,
        "section_statuses": section_statuses,
        "blocked_reasons": blocked_reasons,
        "sections": sections,
        "not_proven_by_this_gate": [
            "The target server has actually deployed the current release.",
            "Target server Docker services have actually started successfully.",
            "Real secrets are valid with their upstream providers.",
            "External APIs have actually responded from the target server.",
            "Key rotation has actually completed and old keys have been revoked.",
            "PostgreSQL backups and restore drills have actually run.",
            "Monitoring alerts have actually delivered to the intended channel.",
            "Acceptance smoke has passed unless include_acceptance and backend checks are executed against a live URL.",
            "The system is production-ready for real payment, booking, price lock, ticketing, or fulfillment.",
        ],
    }
    return _json_safe(report)


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 Deployment Gate",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, starts_services=false, does_not_echo_secret_values=true",
        "",
        "## Sections",
    ]
    for name, status in (report.get("section_statuses") or {}).items():
        lines.append(f"- {name}: {status}")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            label = item.get("env_var") or item.get("key") or item.get("target")
            reason = item.get("reason") or item.get("finding") or "blocked"
            lines.append(f"- {label}: {reason}")
    lines.extend(["", "## Boundary"])
    for item in report.get("not_proven_by_this_gate") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--m1-input-json",
        type=Path,
        default=None,
        help="Optional filled non-secret M1 launch input JSON file.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL for optional acceptance checks.")
    parser.add_argument("--check-backend", action="store_true", help="Probe backend /health endpoints for acceptance readiness.")
    parser.add_argument("--include-acceptance", action="store_true", help="Include acceptance preflight in runtime readiness.")
    parser.add_argument("--skip-public-boundary", action="store_true", help="Skip public release boundary scan.")
    parser.add_argument("--skip-release-freeze", action="store_true", help="Skip release candidate freeze check.")
    parser.add_argument("--skip-m1-inputs", action="store_true", help="Skip M1 non-secret launch input checks.")
    parser.add_argument("--skip-compose-config", action="store_true", help="Skip Docker Compose config validation.")
    parser.add_argument("--skip-runtime", action="store_true", help="Skip runtime readiness.")
    parser.add_argument("--skip-server-preflight", action="store_true", help="Skip target server preflight readiness.")
    parser.add_argument("--check-server-docker", action="store_true", help="Check docker and docker compose commands inside server preflight.")
    parser.add_argument("--check-server-deploy-dir", action="store_true", help="Check ZHIXING_DEPLOY_DIR exists inside server preflight.")
    parser.add_argument("--check-server-disk", action="store_true", help="Check deployment disk capacity inside server preflight.")
    parser.add_argument("--check-server-health-url", action="store_true", help="Probe public health endpoints inside server preflight.")
    parser.add_argument("--skip-backup-readiness", action="store_true", help="Skip backup/restore readiness.")
    parser.add_argument("--check-backup-filesystem", action="store_true", help="Create and delete a probe file in ZHIXING_BACKUP_DIR.")
    parser.add_argument("--check-backup-tools", action="store_true", help="Check docker, pg_dump, and pg_restore availability on PATH.")
    parser.add_argument("--skip-monitoring-readiness", action="store_true", help="Skip monitoring/alerting readiness.")
    parser.add_argument("--check-monitoring-health-url", action="store_true", help="Probe public /health endpoints inside monitoring readiness.")
    parser.add_argument("--skip-security-readiness", action="store_true", help="Skip security release readiness.")
    parser.add_argument("--skip-external-api-readiness", action="store_true", help="Skip external API readiness.")
    parser.add_argument(
        "--skip-rag-mixed-corpus-safety",
        action="store_true",
        help="Skip deterministic RAG mixed-corpus safety inside runtime readiness.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    m1_input_values = None
    m1_input_source = None
    m1_launch_inputs_report = None
    if args.m1_input_json is not None:
        try:
            m1_input_values = load_m1_launch_input_values(args.m1_input_json)
            m1_input_source = f"input_json:{args.m1_input_json.name}"
        except ValueError as exc:
            m1_launch_inputs_report = _blocked_m1_input_json_report(args.m1_input_json, str(exc))
    report = build_m1_deployment_gate_report(
        m1_input_values=m1_input_values,
        m1_input_source=m1_input_source,
        m1_launch_inputs_report=m1_launch_inputs_report,
        base_url=args.base_url,
        check_backend=args.check_backend,
        include_acceptance=args.include_acceptance,
        check_public_boundary=not args.skip_public_boundary,
        check_release_freeze=not args.skip_release_freeze,
        check_m1_inputs=not args.skip_m1_inputs,
        check_compose_config=not args.skip_compose_config,
        check_runtime=not args.skip_runtime,
        check_server_preflight=not args.skip_server_preflight,
        check_server_docker=args.check_server_docker,
        check_server_deploy_dir=args.check_server_deploy_dir,
        check_server_disk=args.check_server_disk,
        check_server_health_url=args.check_server_health_url,
        check_rag_mixed_corpus_safety=not args.skip_rag_mixed_corpus_safety,
        check_backup_readiness=not args.skip_backup_readiness,
        check_backup_filesystem=args.check_backup_filesystem,
        check_backup_tools=args.check_backup_tools,
        check_monitoring_readiness=not args.skip_monitoring_readiness,
        check_monitoring_health_url=args.check_monitoring_health_url,
        check_security_readiness=not args.skip_security_readiness,
        check_external_api_readiness=not args.skip_external_api_readiness,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
