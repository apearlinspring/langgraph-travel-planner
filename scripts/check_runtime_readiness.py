"""Check Runtime Config Readiness（运行配置就绪） targets."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import (  # noqa: E402
    DEFAULT_DOTENV_PATH,
    RuntimeEnvironment,
    dependency_specs_by_key,
    runtime_configuration_snapshot,
    settings,
)
from app.evaluation.live_runner import DEFAULT_BASE_URL  # noqa: E402
from app.evaluation.preflight import run_acceptance_preflight  # noqa: E402
from app.evaluation.scenarios import acceptance_core_scenarios, load_scenarios  # noqa: E402
from app.models.migration_contract import (  # noqa: E402
    BUSINESS_MANAGED_TABLES,
    EXTERNALLY_MANAGED_DATABASE_OBJECTS,
    LANGGRAPH_CHECKPOINT_TABLES,
    LANGGRAPH_STORE_TABLES,
)


READINESS_REPORT_VERSION = "runtime_readiness_report.v1"
DATABASE_MIGRATION_READINESS_VERSION = "database_migration_readiness.v1"
DOCKER_COMPOSE_READINESS_VERSION = "docker_compose_readiness.v1"
READINESS_TARGETS = ("development", "staging", "acceptance", "production")
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = PROJECT_ROOT / "alembic"
ALEMBIC_VERSION_PATH = ALEMBIC_SCRIPT_PATH / "versions"
DOCKER_TIMEOUT_SECONDS = 8


def _run_command(
    args: Sequence[str],
    *,
    timeout_seconds: float = DOCKER_TIMEOUT_SECONDS,
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


def _summarize_process_failure(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    summary = output.splitlines()[0] if output else f"exit code {result.returncode}"
    return summary[:400]


def build_docker_compose_readiness_report(*, check: bool = False) -> dict[str, Any]:
    """Check whether local Docker Compose dependencies can be started."""

    commands = {
        "check": "python scripts/check_runtime_readiness.py --target staging --check-docker --json",
        "start_dependencies": "docker compose up -d postgres redis",
        "inspect": "docker compose ps postgres redis",
    }
    report: dict[str, Any] = {
        "version": DOCKER_COMPOSE_READINESS_VERSION,
        "status": "not_checked",
        "checked": check,
        "requires_docker_desktop": True,
        "commands": commands,
        "findings": [],
        "services": ["postgres", "redis"],
    }
    if not check:
        return report

    try:
        compose_version = _run_command(["docker", "compose", "version", "--short"])
    except FileNotFoundError:
        report["status"] = "blocked"
        report["findings"].append(
            "Docker CLI（命令行工具）不可用。请先安装并启动 Docker Desktop，再重试。"
        )
        return report
    except subprocess.TimeoutExpired:
        report["status"] = "blocked"
        report["findings"].append(
            "docker compose version 超时。请确认 Docker Desktop 已启动且命令行可访问。"
        )
        return report

    if compose_version.returncode != 0:
        report["status"] = "blocked"
        report["findings"].append(
            "Docker Compose（容器编排）插件不可用："
            + _summarize_process_failure(compose_version)
        )
        return report
    report["compose_version"] = compose_version.stdout.strip()

    try:
        docker_info = _run_command(["docker", "info", "--format", "{{.ServerVersion}}"])
    except subprocess.TimeoutExpired:
        report["status"] = "blocked"
        report["findings"].append(
            "docker info 超时。请确认 Docker Desktop 正在运行，再执行 docker compose up -d postgres redis。"
        )
        return report

    if docker_info.returncode != 0:
        report["status"] = "blocked"
        report["findings"].append(
            "Docker daemon（后台服务）不可达；Docker Desktop 可能未运行："
            + _summarize_process_failure(docker_info)
        )
        return report

    report["status"] = "passed"
    report["server_version"] = docker_info.stdout.strip()
    return report


def _dependency_status_counts(dependencies: Mapping[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dependency in dependencies.values():
        status = str(dependency.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _resolve_target_status(snapshot: dict[str, Any]) -> str:
    if snapshot.get("missing_required"):
        return "blocked"
    if snapshot.get("degraded_optional"):
        return "degraded"
    return "passed"


def _configuration_target(
    *,
    target: RuntimeEnvironment,
    environ: Mapping[str, str] | None,
    dotenv_path: Path | None,
    require_real_values: bool,
) -> dict[str, Any]:
    snapshot = runtime_configuration_snapshot(
        app_env=target,
        environ=environ,
        dotenv_path=dotenv_path,
        require_real_values=require_real_values,
    )
    snapshot["target"] = target
    snapshot["status"] = _resolve_target_status(snapshot)
    snapshot["status_counts"] = _dependency_status_counts(snapshot["dependencies"])
    return snapshot


def _acceptance_target(
    *,
    base_url: str,
    environ: Mapping[str, str] | None,
    dotenv_path: Path | None,
    check_backend: bool,
) -> dict[str, Any]:
    scenarios = acceptance_core_scenarios(load_scenarios())
    preflight = run_acceptance_preflight(
        scenarios,
        base_url=base_url,
        environ=environ,
        dotenv_path=dotenv_path,
        check_backend=check_backend,
    ).to_dict()
    return {
        "target": "acceptance",
        "status": preflight["status"],
        "base_url": base_url,
        "check_backend": check_backend,
        "scenario_count": len(scenarios),
        "preflight": preflight,
    }


def build_database_migration_readiness_report() -> dict[str, Any]:
    """Build a static migration readiness report without connecting to PostgreSQL."""

    revision_files = sorted(ALEMBIC_VERSION_PATH.glob("*.py")) if ALEMBIC_VERSION_PATH.exists() else []
    missing: list[str] = []
    if not ALEMBIC_CONFIG_PATH.exists():
        missing.append("alembic.ini")
    if not (ALEMBIC_SCRIPT_PATH / "env.py").exists():
        missing.append("alembic/env.py")
    if not revision_files:
        missing.append("alembic/versions/*.py")

    status = "blocked" if missing else "passed"
    return {
        "version": DATABASE_MIGRATION_READINESS_VERSION,
        "status": status,
        "requires_database_connection": False,
        "missing_required": missing,
        "alembic": {
            "config_path": str(ALEMBIC_CONFIG_PATH),
            "script_path": str(ALEMBIC_SCRIPT_PATH),
            "revision_files": [str(path) for path in revision_files],
        },
        "managed_tables": {
            "business": list(BUSINESS_MANAGED_TABLES),
            "langgraph_checkpointer": list(LANGGRAPH_CHECKPOINT_TABLES),
            "langgraph_store": list(LANGGRAPH_STORE_TABLES),
        },
        "boundaries": {
            "business_migrations": (
                "Alembic manages only app.models business, user/session/message, "
                "approval, and tool audit tables."
            ),
            "externally_managed": list(EXTERNALLY_MANAGED_DATABASE_OBJECTS),
            "langgraph": (
                "LangGraph Checkpointer and Store tables are created and upgraded by "
                "AsyncPostgresSaver.setup() and AsyncPostgresStore.setup()."
            ),
        },
        "commands": {
            "first_bootstrap": "python -m scripts.init_db --mode bootstrap",
            "incremental_migration": "alembic upgrade head",
            "acceptance_check": "python scripts/check_runtime_readiness.py --target production --json",
        },
    }


def build_runtime_readiness_report(
    *,
    targets: list[str] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    check_backend: bool = False,
    check_docker: bool = False,
) -> dict[str, Any]:
    """Build a redacted readiness report for development, acceptance, and production."""

    selected_targets = targets or list(READINESS_TARGETS)
    unknown_targets = sorted(set(selected_targets) - set(READINESS_TARGETS))
    if unknown_targets:
        raise ValueError("Unknown readiness targets: " + ", ".join(unknown_targets))

    resolved_dotenv = dotenv_path or DEFAULT_DOTENV_PATH
    target_results: dict[str, dict[str, Any]] = {}
    if "development" in selected_targets:
        target_results["development"] = _configuration_target(
            target="development",
            environ=environ,
            dotenv_path=resolved_dotenv,
            require_real_values=False,
        )
    if "staging" in selected_targets:
        target_results["staging"] = _configuration_target(
            target="staging",
            environ=environ,
            dotenv_path=resolved_dotenv,
            require_real_values=True,
        )
    if "acceptance" in selected_targets:
        target_results["acceptance"] = _acceptance_target(
            base_url=base_url,
            environ=environ,
            dotenv_path=resolved_dotenv,
            check_backend=check_backend,
        )
    if "production" in selected_targets:
        target_results["production"] = _configuration_target(
            target="production",
            environ=environ,
            dotenv_path=resolved_dotenv,
            require_real_values=True,
        )

    statuses = {key: value["status"] for key, value in target_results.items()}
    database_migrations = build_database_migration_readiness_report()
    docker_compose = build_docker_compose_readiness_report(check=check_docker)
    if any(status == "blocked" for status in statuses.values()):
        overall_status = "blocked"
    elif database_migrations["status"] == "blocked":
        overall_status = "blocked"
    elif docker_compose["status"] == "blocked":
        overall_status = "blocked"
    elif any(status == "skipped" for status in statuses.values()):
        overall_status = "skipped"
    elif any(status == "degraded" for status in statuses.values()):
        overall_status = "degraded"
    else:
        overall_status = "passed"

    return {
        "version": READINESS_REPORT_VERSION,
        "status": overall_status,
        "current_environment": settings.runtime_environment,
        "dotenv_path": str(resolved_dotenv),
        "targets": target_results,
        "target_statuses": statuses,
        "database_migrations": database_migrations,
        "docker_compose": docker_compose,
        "dependency_matrix": {
            key: spec.to_dict(settings.runtime_environment)
            for key, spec in dependency_specs_by_key().items()
        },
    }


def _render_human(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Config Readiness",
        f"- Overall: {report['status']}",
        f"- Current environment: {report['current_environment']}",
        f"- .env path: {report['dotenv_path']}",
        "",
    ]
    database_migrations = report.get("database_migrations") or {}
    lines.append(f"## database migrations: {database_migrations.get('status')}")
    lines.append(
        "- Business tables: "
        + ", ".join((database_migrations.get("managed_tables") or {}).get("business") or [])
    )
    lines.append(
        "- LangGraph-owned: "
        + ", ".join((database_migrations.get("boundaries") or {}).get("externally_managed") or [])
    )
    lines.append("")
    docker_compose = report.get("docker_compose") or {}
    lines.append(f"## docker compose: {docker_compose.get('status')}")
    if docker_compose.get("checked"):
        findings = docker_compose.get("findings") or []
        lines.append("- Findings: " + ("; ".join(findings) if findings else "-"))
    else:
        lines.append("- Findings: not checked; add --check-docker for local/staging bootstrap.")
    lines.append("")
    for target, result in report["targets"].items():
        lines.append(f"## {target}: {result['status']}")
        if target == "acceptance":
            preflight = result.get("preflight") or {}
            lines.append(f"- Scenarios: {result.get('scenario_count')}")
            lines.append(f"- Backend checked: {result.get('check_backend')}")
            missing = ", ".join(preflight.get("missing_required") or []) or "-"
            lines.append("- Missing required: " + missing)
            continue

        missing = result.get("missing_required") or []
        degraded = result.get("degraded_optional") or []
        lines.append("- Missing required: " + (", ".join(missing) if missing else "-"))
        lines.append("- Optional degraded/not configured: " + (", ".join(degraded) if degraded else "-"))
        lines.append(f"- Status counts: {result.get('status_counts')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        choices=READINESS_TARGETS,
        help="Target to check. Can be repeated. Defaults to all targets.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Backend base URL used when --check-backend is enabled.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_DOTENV_PATH,
        help="Path to .env file to evaluate.",
    )
    parser.add_argument(
        "--check-backend",
        action="store_true",
        help="Also require backend /health/live and /health/ready for acceptance.",
    )
    parser.add_argument(
        "--check-docker",
        action="store_true",
        help="Also require Docker Desktop and Docker Compose for local/staging dependency bootstrap.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    args = parser.parse_args()

    report = build_runtime_readiness_report(
        targets=args.target,
        base_url=args.base_url,
        dotenv_path=args.env_file,
        check_backend=args.check_backend,
        check_docker=args.check_docker,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] in {"blocked", "skipped"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
