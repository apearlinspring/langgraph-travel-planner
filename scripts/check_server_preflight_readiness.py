"""Check target server preflight readiness without reading .env files."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PREFLIGHT_READINESS_VERSION = "server_preflight_readiness.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
READY_VALUES = {"1", "true", "yes", "y", "on", "ready", "fixed", "configured", "confirmed"}
BLOCKED_VALUES = {"0", "false", "no", "n", "off", "blocked", "missing", "unknown"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
HEALTH_ENDPOINTS = (
    ("health/live", "/health/live"),
    ("health/ready", "/health/ready"),
)
WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _check(
    *,
    category: str,
    key: str,
    env_var: str,
    label: str,
    status: str,
    finding: str,
) -> dict[str, Any]:
    return {
        "category": category,
        "key": key,
        "env_var": env_var,
        "label": label,
        "status": status,
        "finding": finding,
        "value_echoed": False,
    }


def _check_declared(
    *,
    category: str,
    key: str,
    env_var: str,
    value: str,
    label: str,
) -> dict[str, Any]:
    if not value:
        return _check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Missing required server preflight declaration.",
        )
    if _looks_placeholder(value):
        return _check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Server preflight declaration still looks like a placeholder.",
        )
    return _check(
        category=category,
        key=key,
        env_var=env_var,
        label=label,
        status="passed",
        finding="Declared.",
    )


def _check_ready(
    *,
    category: str,
    key: str,
    env_var: str,
    value: str,
    label: str,
) -> dict[str, Any]:
    if not value:
        return _check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Missing required ready/confirmed status.",
        )
    lowered = value.lower()
    if lowered in READY_VALUES or any(word in lowered for word in ("ready", "configured", "confirmed", "enabled")):
        return _check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="passed",
            finding="Ready status is declared.",
        )
    if lowered in BLOCKED_VALUES or _looks_placeholder(value):
        return _check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Required server preflight status is not ready.",
        )
    return _check(
        category=category,
        key=key,
        env_var=env_var,
        label=label,
        status="blocked",
        finding="Expected ready/fixed/configured/confirmed status.",
    )


def _check_resource_shape(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="server",
        key="cpu_ram_disk",
        env_var="ZHIXING_SERVER_CPU_RAM_DISK",
        value=value,
        label="CPU/RAM/disk baseline",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if not any(char.isdigit() for char in value):
        item["status"] = "blocked"
        item["finding"] = "CPU/RAM/disk baseline must include numeric capacity."
    elif "ram" not in lowered and "gb" not in lowered:
        item["status"] = "blocked"
        item["finding"] = "CPU/RAM/disk baseline must mention RAM or GB capacity."
    return item


def _check_deploy_mode(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="deployment",
        key="deploy_mode",
        env_var="ZHIXING_DEPLOY_MODE",
        value=value,
        label="Deployment mode",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if not any(word in lowered for word in ("docker", "compose", "container", "managed")):
        item["status"] = "blocked"
        item["finding"] = "M1 deployment mode should mention Docker Compose, containers, or managed runtime."
    return item


def _check_deploy_dir(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="deployment",
        key="deploy_dir",
        env_var="ZHIXING_DEPLOY_DIR",
        value=value,
        label="Deployment directory",
    )
    if item["status"] == "blocked":
        return item
    normalized = value.replace("\\", "/")
    if not (normalized.startswith("/") or WINDOWS_ABSOLUTE_PATH.match(value)):
        item["status"] = "blocked"
        item["finding"] = "Deployment directory must be an absolute path."
        return item
    path = Path(value)
    if normalized.startswith("/") and not WINDOWS_ABSOLUTE_PATH.match(value):
        return item
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return item
    item["status"] = "blocked"
    item["finding"] = "Deployment directory must not point inside the Git workspace."
    return item


def _check_public_base_url(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="network",
        key="public_base_url",
        env_var="ZHIXING_PUBLIC_BASE_URL",
        value=value,
        label="Public base URL",
    )
    if item["status"] == "blocked":
        return item
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        item["status"] = "blocked"
        item["finding"] = "Public base URL must be a full http(s) URL."
    elif parsed.scheme != "https":
        item["status"] = "blocked"
        item["finding"] = "Server preflight requires an HTTPS public base URL."
    elif host in LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local"):
        item["status"] = "blocked"
        item["finding"] = "Public base URL must not point to localhost."
    elif host.endswith(".example.com") or host == "example.com":
        item["status"] = "blocked"
        item["finding"] = "Public base URL must not use an example domain."
    return item


def _check_site_address(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="network",
        key="site_address",
        env_var="ZHIXING_SITE_ADDRESS",
        value=value,
        label="Reverse proxy site address",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if lowered in {":80", "http://localhost", "localhost", "127.0.0.1"}:
        item["status"] = "blocked"
        item["finding"] = "Server preflight requires a public domain-style site address."
    elif "." not in lowered and not lowered.startswith("http"):
        item["status"] = "blocked"
        item["finding"] = "Site address should be a public domain or full URL."
    return item


def _check_ports_status(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="network",
        key="server_ports_status",
        env_var="ZHIXING_SERVER_PORTS_STATUS",
        value=value,
        label="Server ports status",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if "80" not in lowered or "443" not in lowered:
        item["status"] = "blocked"
        item["finding"] = "Server ports status must mention 80 and 443."
    elif not any(word in lowered for word in ("open", "ready", "allowed", "开放", "放行")):
        item["status"] = "blocked"
        item["finding"] = "Server ports status must say the ports are open/allowed."
    return item


def _run_command(args: Sequence[str], *, timeout_seconds: float = 10) -> subprocess.CompletedProcess[str]:
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


def _docker_probe(*, check: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "starts_services": False,
        "finding": "Docker CLI probe not requested.",
    }
    if not check:
        return report
    commands = {
        "docker": ["docker", "--version"],
        "docker_compose": ["docker", "compose", "version"],
    }
    results: dict[str, Any] = {}
    blocked = False
    for name, command in commands.items():
        try:
            result = _run_command(command)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            results[name] = {"status": "blocked", "finding": exc.__class__.__name__}
            blocked = True
            continue
        if result.returncode == 0:
            results[name] = {"status": "passed", "finding": "Command is available."}
        else:
            results[name] = {"status": "blocked", "finding": f"Command exited {result.returncode}."}
            blocked = True
    report.update(
        {
            "status": "blocked" if blocked else "passed",
            "commands": results,
            "finding": "Docker CLI probe failed." if blocked else "Docker CLI and Compose are available.",
        }
    )
    return report


def _deploy_dir_probe(path_text: str, *, check: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "writes_files": False,
        "value_echoed": False,
        "finding": "Deployment directory filesystem probe not requested.",
    }
    if not check:
        return report
    path = Path(path_text)
    if not path.exists():
        report.update({"status": "blocked", "finding": "Deployment directory does not exist."})
    elif not path.is_dir():
        report.update({"status": "blocked", "finding": "Deployment path is not a directory."})
    else:
        report.update({"status": "passed", "finding": "Deployment directory exists."})
    return report


def _disk_probe(
    path_text: str,
    *,
    check: bool,
    min_free_mb: int,
    warn_used_percent: int,
    fail_used_percent: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "writes_files": False,
        "value_echoed": False,
        "min_free_mb": min_free_mb,
        "warn_used_percent": warn_used_percent,
        "fail_used_percent": fail_used_percent,
        "finding": "Disk capacity probe not requested.",
    }
    if not check:
        return report
    if min_free_mb < 0 or warn_used_percent < 0 or fail_used_percent < 0:
        report.update({"status": "blocked", "finding": "Disk thresholds must be non-negative integers."})
        return report
    if warn_used_percent >= fail_used_percent:
        report.update({"status": "blocked", "finding": "Disk warning threshold must be lower than fail threshold."})
        return report
    if not path_text.strip():
        report.update({"status": "blocked", "finding": "Disk probe target is missing."})
        return report
    path = Path(path_text)
    if not path.exists():
        report.update({"status": "blocked", "finding": "Disk probe target does not exist."})
        return report
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        report.update({"status": "blocked", "finding": f"Disk probe failed: {exc.__class__.__name__}."})
        return report

    total_mb = usage.total // (1024 * 1024)
    free_mb = usage.free // (1024 * 1024)
    used_percent = 0 if usage.total <= 0 else round((usage.used / usage.total) * 100)
    report.update(
        {
            "total_mb": total_mb,
            "free_mb": free_mb,
            "used_percent": used_percent,
        }
    )
    if free_mb < min_free_mb:
        report.update({"status": "blocked", "finding": "Free disk space is below the minimum runtime-build threshold."})
    elif used_percent >= fail_used_percent:
        report.update({"status": "blocked", "finding": "Disk usage is at or above the fail threshold."})
    elif used_percent >= warn_used_percent:
        report.update(
            {
                "status": "warning",
                "finding": "Disk usage is above the warning threshold; release may proceed only with cleanup or capacity plan evidence.",
            }
        )
    else:
        report.update({"status": "passed", "finding": "Disk capacity is within the runtime-build threshold."})
    return report


def _probe_url(url: str, *, timeout_seconds: float) -> int:
    request = Request(url, headers={"User-Agent": "zhixing-server-preflight/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - explicit readiness probe.
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except (OSError, TimeoutError, URLError) as exc:
        raise RuntimeError(exc.__class__.__name__) from exc


def _health_probe(
    *,
    base_url: str,
    check: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "network_probe_requested": check,
        "value_echoed": False,
        "endpoints": [],
        "finding": "Public health URL probe not requested.",
    }
    if not check:
        return report

    base_check = _check_public_base_url(base_url)
    report["base_url_check"] = base_check
    if base_check["status"] == "blocked":
        report.update({"status": "blocked", "finding": base_check["finding"]})
        return report

    endpoint_reports: list[dict[str, Any]] = []
    for label, endpoint_path in HEALTH_ENDPOINTS:
        item: dict[str, Any] = {"endpoint": label, "value_echoed": False}
        try:
            status_code = _probe_url(base_url.rstrip("/") + endpoint_path, timeout_seconds=timeout_seconds)
        except RuntimeError as exc:
            item.update({"status": "blocked", "finding": f"Health endpoint probe failed: {exc}"})
        else:
            item["http_status"] = status_code
            if 200 <= status_code < 400:
                item.update({"status": "passed", "finding": "Endpoint responded successfully."})
            else:
                item.update({"status": "blocked", "finding": f"Endpoint returned HTTP {status_code}."})
        endpoint_reports.append(item)
    blocked = [item for item in endpoint_reports if item["status"] == "blocked"]
    report.update(
        {
            "status": "blocked" if blocked else "passed",
            "endpoints": endpoint_reports,
            "finding": "Public health endpoint probe failed." if blocked else "Public health endpoints responded successfully.",
        }
    )
    return report


def build_server_preflight_readiness_report(
    *,
    environ: Mapping[str, str] | None = None,
    check_docker: bool = False,
    check_deploy_dir: bool = False,
    check_disk: bool = False,
    check_health_url: bool = False,
    min_free_disk_mb: int = 2048,
    disk_warn_used_percent: int = 90,
    disk_fail_used_percent: int = 98,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Build a redacted target-server preflight readiness report."""

    env = environ if environ is not None else os.environ
    checks = [
        _check_declared(
            category="server",
            key="server_provider",
            env_var="ZHIXING_SERVER_PROVIDER",
            value=_value(env, "ZHIXING_SERVER_PROVIDER"),
            label="Server provider",
        ),
        _check_declared(
            category="server",
            key="os_version",
            env_var="ZHIXING_SERVER_OS_VERSION",
            value=_value(env, "ZHIXING_SERVER_OS_VERSION"),
            label="Server OS version",
        ),
        _check_resource_shape(_value(env, "ZHIXING_SERVER_CPU_RAM_DISK")),
        _check_deploy_mode(_value(env, "ZHIXING_DEPLOY_MODE")),
        _check_deploy_dir(_value(env, "ZHIXING_DEPLOY_DIR")),
        _check_public_base_url(_value(env, "ZHIXING_PUBLIC_BASE_URL")),
        _check_site_address(_value(env, "ZHIXING_SITE_ADDRESS")),
        _check_ready(
            category="network",
            key="domain_ready",
            env_var="ZHIXING_DOMAIN_READY",
            value=_value(env, "ZHIXING_DOMAIN_READY"),
            label="Domain ready",
        ),
        _check_ready(
            category="network",
            key="server_egress_ip_status",
            env_var="ZHIXING_SERVER_EGRESS_IP_STATUS",
            value=_value(env, "ZHIXING_SERVER_EGRESS_IP_STATUS"),
            label="Server egress IP status",
        ),
        _check_ports_status(_value(env, "ZHIXING_SERVER_PORTS_STATUS")),
        _check_ready(
            category="network",
            key="tls_status",
            env_var="ZHIXING_TLS_STATUS",
            value=_value(env, "ZHIXING_TLS_STATUS"),
            label="TLS status",
        ),
        _check_ready(
            category="reverse_proxy",
            key="reverse_proxy_status",
            env_var="ZHIXING_REVERSE_PROXY_STATUS",
            value=_value(env, "ZHIXING_REVERSE_PROXY_STATUS"),
            label="Reverse proxy status",
        ),
        _check_ready(
            category="runtime",
            key="docker_status",
            env_var="ZHIXING_DOCKER_STATUS",
            value=_value(env, "ZHIXING_DOCKER_STATUS"),
            label="Docker status",
        ),
    ]
    docker_probe = _docker_probe(check=check_docker)
    deploy_dir_probe = _deploy_dir_probe(_value(env, "ZHIXING_DEPLOY_DIR"), check=check_deploy_dir)
    disk_probe = _disk_probe(
        _value(env, "ZHIXING_DEPLOY_DIR"),
        check=check_disk,
        min_free_mb=min_free_disk_mb,
        warn_used_percent=disk_warn_used_percent,
        fail_used_percent=disk_fail_used_percent,
    )
    health_probe = _health_probe(
        base_url=_value(env, "ZHIXING_PUBLIC_BASE_URL"),
        check=check_health_url,
        timeout_seconds=timeout_seconds,
    )

    blocked = [item for item in checks if item["status"] == "blocked"]
    for probe_key, env_var, probe in [
        ("docker_probe", "PATH", docker_probe),
        ("deploy_dir_probe", "ZHIXING_DEPLOY_DIR", deploy_dir_probe),
        ("disk_probe", "ZHIXING_DEPLOY_DIR", disk_probe),
        ("health_probe", "ZHIXING_PUBLIC_BASE_URL", health_probe),
    ]:
        if probe["status"] == "blocked":
            blocked.append(
                {
                    "category": "probe",
                    "key": probe_key,
                    "env_var": env_var,
                    "label": probe_key,
                    "status": "blocked",
                    "finding": probe["finding"],
                    "value_echoed": False,
                }
            )

    return {
        "version": SERVER_PREFLIGHT_READINESS_VERSION,
        "status": "blocked" if blocked else "passed",
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "writes_files": False,
            "does_not_echo_values": True,
            "docker_probe_requested": check_docker,
            "deploy_dir_probe_requested": check_deploy_dir,
            "disk_probe_requested": check_disk,
            "network_probe_requested": check_health_url,
        },
        "checks": checks,
        "docker_probe": docker_probe,
        "deploy_dir_probe": deploy_dir_probe,
        "disk_probe": disk_probe,
        "health_probe": health_probe,
        "blocked_reasons": blocked,
        "warnings": [
            {
                "category": "probe",
                "key": "disk_probe",
                "env_var": "ZHIXING_DEPLOY_DIR",
                "label": "disk_probe",
                "status": "warning",
                "finding": disk_probe["finding"],
                "value_echoed": False,
            }
        ]
        if disk_probe["status"] == "warning"
        else [],
        "not_proven_by_this_check": [
            "The current release has actually been deployed.",
            "Docker services have started successfully.",
            "DNS, TLS, firewall, and reverse proxy are correctly configured unless optional probes are run against the target server.",
            "Database, Redis, RAG, and external provider credentials are valid.",
            "Acceptance smoke has passed through the public URL.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# Server Preflight Readiness",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, starts_services=false, writes_files=false",
        "",
        "## Checks",
    ]
    for item in report.get("checks") or []:
        lines.append(f"- {item.get('env_var')}: {item.get('status')} ({item.get('finding')})")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--check-docker", action="store_true", help="Check docker and docker compose commands without starting services.")
    parser.add_argument("--check-deploy-dir", action="store_true", help="Check ZHIXING_DEPLOY_DIR exists without writing files.")
    parser.add_argument("--check-disk", action="store_true", help="Check deployment filesystem capacity without writing files.")
    parser.add_argument("--check-health-url", action="store_true", help="Probe public /health/live and /health/ready.")
    parser.add_argument("--min-free-disk-mb", type=int, default=2048, help="Minimum free disk space required for runtime image refresh.")
    parser.add_argument("--disk-warn-used-percent", type=int, default=90, help="Disk usage percentage that reports a warning.")
    parser.add_argument("--disk-fail-used-percent", type=int, default=98, help="Disk usage percentage that blocks deployment preflight.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout for each optional health URL probe.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_server_preflight_readiness_report(
        check_docker=args.check_docker,
        check_deploy_dir=args.check_deploy_dir,
        check_disk=args.check_disk,
        check_health_url=args.check_health_url,
        min_free_disk_mb=args.min_free_disk_mb,
        disk_warn_used_percent=args.disk_warn_used_percent,
        disk_fail_used_percent=args.disk_fail_used_percent,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
