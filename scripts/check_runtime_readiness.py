"""Check Runtime Config Readiness（运行配置就绪） targets."""
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

from app.config import (  # noqa: E402
    DEFAULT_DOTENV_PATH,
    RuntimeEnvironment,
    dependency_specs_by_key,
    runtime_configuration_snapshot,
    settings,
)
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
RAG_MULTIMODAL_E2E_READINESS_VERSION = "rag_multimodal_e2e_readiness.v1"
RAG_MIXED_CORPUS_SAFETY_READINESS_VERSION = "rag_mixed_corpus_safety_readiness.v1"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
READINESS_TARGETS = ("development", "staging", "acceptance", "production")
READINESS_TARGET_ALIASES = {"local": "development"}
READINESS_TARGET_CHOICES = ("local", *READINESS_TARGETS)
READINESS_COMPONENTS = {
    "postgresql": "PostgreSQL（关系型数据库）",
    "redis": "Redis（内存数据结构存储）",
    "rag_vector_store": "RAG（检索增强生成）",
    "mcp": "MCP（模型上下文协议）",
    "llm": "LLM（大语言模型）",
}
READINESS_STATUS_LEGEND = {
    "ready": "Required configuration or health evidence is present for this target.",
    "degraded": "Core path can continue, but an optional capability is missing, unprobed, or degraded.",
    "not_ready": "A required dependency is missing, placeholder-like, or unhealthy for this target.",
}
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = PROJECT_ROOT / "alembic"
ALEMBIC_VERSION_PATH = ALEMBIC_SCRIPT_PATH / "versions"
DOCKER_TIMEOUT_SECONDS = 8
RAG_MULTIMODAL_E2E_READINESS_COMMAND = (
    ".\\.venv\\Scripts\\python scripts\\check_rag_multimodal_readiness.py --json --check-e2e"
)
RAG_MIXED_CORPUS_SAFETY_READINESS_COMMAND = (
    ".\\.venv\\Scripts\\python scripts\\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json"
)

DEPENDENCY_REPAIR_SUGGESTIONS: dict[str, dict[str, str]] = {
    "postgresql": {
        "action": (
            "Set POSTGRES_HOST/POSTGRES_PORT/POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD, "
            "start PostgreSQL, then run database bootstrap."
        ),
        "command": (
            "docker compose up -d postgres; "
            ".\\.venv\\Scripts\\python -m scripts.init_db --mode bootstrap"
        ),
    },
    "redis": {
        "action": (
            "Set REDIS_HOST/REDIS_PORT/REDIS_DB and start Redis; staging/production should "
            "not rely on local in-process session locks."
        ),
        "command": "docker compose up -d redis",
    },
    "llm": {
        "action": (
            "Set a real DASHSCOPE_API_KEY and keep model creation through app/utils/llm_factory.py."
        ),
        "command": ".\\.venv\\Scripts\\python scripts\\check_runtime_readiness.py --target staging --json",
    },
    "rag_vector_store": {
        "action": (
            "Initialize both public and internal RAG vector stores so chroma.sqlite3 contains "
            "the configured collections."
        ),
        "command": ".\\.venv\\Scripts\\python -m scripts.init_rag",
    },
    "mcp": {
        "action": (
            "Probe backend /health/ready for MCP service health and restore required upstream "
            "credentials or network access before live acceptance."
        ),
        "command": (
            ".\\.venv\\Scripts\\python scripts\\check_runtime_readiness.py "
            "--target acceptance --check-backend --base-url http://127.0.0.1:8000 --json"
        ),
    },
    "map": {
        "action": "Set a real AMAP_API_KEY before running staging, production, or map-backed acceptance.",
        "command": ".\\.venv\\Scripts\\python scripts\\check_runtime_readiness.py --target staging --json",
    },
    "auth_jwt": {
        "action": (
            "Set a long non-default JWT_SECRET_KEY and keep JWT_ALGORITHM=HS256 unless deployment "
            "policy changes."
        ),
        "command": ".\\.venv\\Scripts\\python scripts\\check_runtime_readiness.py --target production --json",
    },
}

GENERIC_REPAIR_SUGGESTION = {
    "action": "Set the listed environment variables to real values or confirm the dependency can degrade.",
    "command": ".\\.venv\\Scripts\\python scripts\\check_runtime_readiness.py --json",
}


def _canonical_readiness_target(target: str) -> str:
    return READINESS_TARGET_ALIASES.get(target, target)


def _selected_target_pairs(targets: Sequence[str] | None) -> list[tuple[str, str]]:
    selected_targets = list(targets or READINESS_TARGETS)
    unknown_targets = sorted(
        {
            target
            for target in selected_targets
            if target not in READINESS_TARGETS and target not in READINESS_TARGET_ALIASES
        }
    )
    if unknown_targets:
        raise ValueError("Unknown readiness targets: " + ", ".join(unknown_targets))

    pairs: list[tuple[str, str]] = []
    for target in selected_targets:
        pairs.append((target, _canonical_readiness_target(target)))
    return pairs


def _runtime_readiness_status(status: str | None) -> str:
    if status == "passed":
        return "ready"
    if status == "degraded":
        return "degraded"
    return "not_ready"


def _dependency_runtime_status(key: str, dependency: Mapping[str, Any]) -> str:
    status = str(dependency.get("status") or "unknown")
    requirement = str(dependency.get("requirement") or "optional")
    if status in {"configured", "ready", "healthy", "passed"}:
        return "ready"
    if status in {"blocked", "not_ready", "unavailable", "failed"}:
        return "not_ready"
    if status == "service_checked":
        return "degraded" if key == "mcp" else "ready"
    if requirement == "required":
        return "not_ready"
    return "degraded"


def _component_reason(key: str, dependency: Mapping[str, Any], runtime_status: str) -> str:
    findings = list(dependency.get("findings") or [])
    if findings:
        return _finding_summary(findings)
    raw_status = str(dependency.get("status") or "unknown")
    if key == "mcp" and raw_status == "service_checked":
        return (
            "Configuration-only smoke cannot prove MCP service health; run acceptance "
            "readiness with --check-backend to verify selected MCP services."
        )
    if runtime_status == "ready":
        return "Required configuration evidence is present for this target."
    if runtime_status == "degraded":
        return str(dependency.get("optional_reason") or "Optional capability is unavailable or unprobed.")
    return "Required dependency is missing, placeholder-like, or not ready."


def _component_readiness_from_dependencies(
    dependencies: Mapping[str, Mapping[str, Any]],
    *,
    target: str,
) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for key, default_label in READINESS_COMPONENTS.items():
        dependency = dependencies.get(key) or {}
        runtime_status = _dependency_runtime_status(key, dependency)
        repair = _dependency_repair_suggestion(key, dependency, target=target)
        components[key] = {
            "key": key,
            "label": dependency.get("label") or default_label,
            "status": runtime_status,
            "raw_status": dependency.get("status") or "unknown",
            "requirement": dependency.get("requirement") or "optional",
            "reason": _component_reason(key, dependency, runtime_status),
            "env_vars": list(dependency.get("env_vars") or []),
            "repair_suggestion": repair,
        }
    return components


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


def _finding_summary(findings: Sequence[Any]) -> str:
    text = "; ".join(str(item) for item in findings if str(item).strip())
    return text or "required dependency is not configured"


def _dependency_repair_suggestion(
    key: str,
    dependency: Mapping[str, Any],
    *,
    target: str,
) -> dict[str, Any]:
    template = DEPENDENCY_REPAIR_SUGGESTIONS.get(key, GENERIC_REPAIR_SUGGESTION)
    return {
        "target": target,
        "key": key,
        "label": dependency.get("label") or key,
        "action": template["action"],
        "command": template["command"],
        "env_vars": list(dependency.get("env_vars") or []),
    }


def _dependency_issue(
    key: str,
    dependency: Mapping[str, Any],
    *,
    target: str,
) -> dict[str, Any]:
    findings = list(dependency.get("findings") or [])
    return {
        "target": target,
        "key": key,
        "label": dependency.get("label") or key,
        "reason": _finding_summary(findings),
        "findings": findings,
        "env_vars": list(dependency.get("env_vars") or []),
        "status": dependency.get("status"),
        "requirement": dependency.get("requirement"),
    }


def _configuration_issues(
    snapshot: Mapping[str, Any],
    keys: Sequence[str],
    *,
    target: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dependencies = snapshot.get("dependencies") or {}
    issues: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for key in keys:
        dependency = dependencies.get(key) or {}
        issues.append(_dependency_issue(str(key), dependency, target=target))
        suggestions.append(_dependency_repair_suggestion(str(key), dependency, target=target))
    return issues, suggestions


def _preflight_issues(preflight: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for check in preflight.get("checks") or []:
        if not isinstance(check, Mapping) or check.get("status") != "blocked":
            continue
        key = str(check.get("key") or "acceptance")
        label = str(check.get("label") or key)
        findings = list(check.get("findings") or [])
        suggestion = str(check.get("suggestion") or "").strip()
        issues.append(
            {
                "target": "acceptance",
                "key": key,
                "label": label,
                "reason": _finding_summary(findings),
                "findings": findings,
                "env_vars": list(check.get("env_vars") or []),
                "status": check.get("status"),
                "requirement": "required" if check.get("required") else "optional",
            }
        )
        if suggestion:
            suggestions.append(
                {
                    "target": "acceptance",
                    "key": key,
                    "label": label,
                    "action": suggestion,
                    "command": (
                        ".\\.venv\\Scripts\\python scripts\\run_evaluation_scenarios.py "
                        "--acceptance-core --preflight-only --json"
                    ),
                    "env_vars": list(check.get("env_vars") or []),
                }
            )
    return issues, suggestions


def _dedupe_dicts(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = (
            item.get("target"),
            item.get("key"),
            item.get("label"),
            item.get("reason"),
            item.get("action"),
            item.get("command"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(item))
    return unique


def _append_blocker(
    report: dict[str, Any],
    *,
    key: str,
    label: str,
    reason: str,
    action: str,
    command: str,
    target: str,
) -> None:
    report.setdefault("blocked_reasons", []).append(
        {
            "target": target,
            "key": key,
            "label": label,
            "reason": reason,
            "findings": [reason],
            "env_vars": [],
            "status": "blocked",
            "requirement": "required",
        }
    )
    report.setdefault("repair_suggestions", []).append(
        {
            "target": target,
            "key": key,
            "label": label,
            "action": action,
            "command": command,
            "env_vars": [],
        }
    )


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
        "blocked_reasons": [],
        "repair_suggestions": [],
        "services": ["postgres", "redis"],
    }
    if not check:
        return report

    try:
        compose_version = _run_command(["docker", "compose", "version", "--short"])
    except FileNotFoundError:
        report["status"] = "blocked"
        finding = "Docker CLI（命令行工具）不可用。请先安装并启动 Docker Desktop，再重试。"
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="docker_cli",
            label="Docker CLI（命令行工具）",
            reason=finding,
            action="Install Docker Desktop and make the docker command available on PATH.",
            command="docker compose version",
            target="docker_compose",
        )
        return report
    except subprocess.TimeoutExpired:
        report["status"] = "blocked"
        finding = "docker compose version 超时。请确认 Docker Desktop 已启动且命令行可访问。"
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="docker_compose_timeout",
            label="Docker Compose（容器编排）",
            reason=finding,
            action="Start Docker Desktop and retry the readiness command.",
            command="docker compose version --short",
            target="docker_compose",
        )
        return report

    if compose_version.returncode != 0:
        report["status"] = "blocked"
        finding = "Docker Compose（容器编排）插件不可用：" + _summarize_process_failure(compose_version)
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="docker_compose_plugin",
            label="Docker Compose（容器编排）",
            reason=finding,
            action="Install or repair the Docker Compose plugin, then retry local/staging dependency bootstrap.",
            command="docker compose version --short",
            target="docker_compose",
        )
        return report
    report["compose_version"] = compose_version.stdout.strip()

    try:
        docker_info = _run_command(["docker", "info", "--format", "{{.ServerVersion}}"])
    except subprocess.TimeoutExpired:
        report["status"] = "blocked"
        finding = "docker info 超时。请确认 Docker Desktop 正在运行，再执行 docker compose up -d postgres redis。"
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="docker_daemon_timeout",
            label="Docker daemon（后台服务）",
            reason=finding,
            action="Start Docker Desktop and wait until docker info responds.",
            command="docker info --format {{.ServerVersion}}",
            target="docker_compose",
        )
        return report

    if docker_info.returncode != 0:
        report["status"] = "blocked"
        finding = (
            "Docker daemon（后台服务）不可达；Docker Desktop 可能未运行："
            + _summarize_process_failure(docker_info)
        )
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="docker_daemon",
            label="Docker daemon（后台服务）",
            reason=finding,
            action="Start Docker Desktop, then run docker compose up -d postgres redis.",
            command="docker compose up -d postgres redis",
            target="docker_compose",
        )
        return report

    report["status"] = "passed"
    report["server_version"] = docker_info.stdout.strip()
    return report


def build_rag_multimodal_e2e_readiness_report(*, check: bool = False) -> dict[str, Any]:
    """Optionally run the live RAG multimodal vector-store acceptance check."""

    report: dict[str, Any] = {
        "version": RAG_MULTIMODAL_E2E_READINESS_VERSION,
        "status": "not_checked",
        "checked": check,
        "requires_real_llm": True,
        "requires_runtime_samples": True,
        "commands": {
            "check": RAG_MULTIMODAL_E2E_READINESS_COMMAND,
            "prepare_samples": (
                "Prepare image/audio/video samples under "
                ".runtime\\rag_web_acceptance\\documents\\destinations"
            ),
        },
        "findings": [],
        "blocked_reasons": [],
        "repair_suggestions": [],
    }
    if not check:
        return report

    try:
        from scripts.check_rag_multimodal_readiness import (
            build_rag_multimodal_readiness_report,
        )

        readiness = build_rag_multimodal_readiness_report(check_e2e=True)
    except Exception as exc:
        report["status"] = "blocked"
        finding = (
            "RAG multimodal e2e readiness failed before producing a report: "
            f"{exc.__class__.__name__}: {exc}"
        )
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="rag_multimodal_e2e_exception",
            label="RAG multimodal e2e acceptance",
            reason=finding,
            action=(
                "Check multimodal runtime dependencies, sample files, real DASHSCOPE_API_KEY, "
                "ffmpeg and faster-whisper, then rerun the deep readiness check."
            ),
            command=RAG_MULTIMODAL_E2E_READINESS_COMMAND,
            target="rag_multimodal_e2e",
        )
        return report

    e2e_acceptance = readiness.get("e2e_acceptance") or {}
    e2e_passed = bool(e2e_acceptance.get("passed")) if isinstance(e2e_acceptance, Mapping) else False
    report["readiness"] = readiness
    report["e2e_acceptance"] = e2e_acceptance
    report["findings"] = list(readiness.get("findings") or [])
    if e2e_passed and readiness.get("status") == "passed":
        report["status"] = "passed"
        return report

    report["status"] = "blocked"
    reason = (
        "RAG multimodal e2e acceptance did not pass; "
        f"readiness={readiness.get('status')}, e2e={e2e_acceptance.get('status') if isinstance(e2e_acceptance, Mapping) else 'missing'}."
    )
    report["findings"].append(reason)
    _append_blocker(
        report,
        key="rag_multimodal_e2e",
        label="RAG multimodal e2e acceptance",
        reason=reason,
        action=(
            "Prepare runtime samples, configure real multimodal extraction dependencies, "
            "then rerun the RAG multimodal e2e readiness check."
        ),
        command=RAG_MULTIMODAL_E2E_READINESS_COMMAND,
        target="rag_multimodal_e2e",
    )
    return report


def build_rag_mixed_corpus_safety_readiness_report(*, check: bool = True) -> dict[str, Any]:
    """Run the deterministic public-vs-internal RAG safety gate."""

    report: dict[str, Any] = {
        "version": RAG_MIXED_CORPUS_SAFETY_READINESS_VERSION,
        "status": "not_checked",
        "checked": check,
        "requires_real_llm": False,
        "requires_vectorstore": False,
        "commands": {
            "check": RAG_MIXED_CORPUS_SAFETY_READINESS_COMMAND,
        },
        "findings": [],
        "blocked_reasons": [],
        "repair_suggestions": [],
    }
    if not check:
        return report

    try:
        from app.evaluation.rag_retrieval import (
            evaluate_rag_mixed_corpus_safety,
            rag_mixed_corpus_safety_failures,
        )

        result = evaluate_rag_mixed_corpus_safety(top_k_values=(3,))
        failures = rag_mixed_corpus_safety_failures(result)
    except Exception as exc:
        report["status"] = "blocked"
        finding = (
            "RAG mixed-corpus safety gate failed before producing a report: "
            f"{exc.__class__.__name__}: {exc}"
        )
        report["findings"].append(finding)
        _append_blocker(
            report,
            key="rag_mixed_corpus_safety_exception",
            label="RAG mixed-corpus safety gate",
            reason=finding,
            action=(
                "Repair deterministic RAG retrieval fixtures or evaluation code, "
                "then rerun the mixed-corpus safety gate."
            ),
            command=RAG_MIXED_CORPUS_SAFETY_READINESS_COMMAND,
            target="rag_mixed_corpus_safety",
        )
        return report

    report["scenario_count"] = result.scenario_count
    report["document_count"] = result.document_count
    report["top_k_values"] = result.top_k_values
    report["summaries"] = [summary.to_dict() for summary in result.summaries]
    report["failed_scenarios"] = failures
    if failures:
        report["status"] = "blocked"
        reason = (
            "RAG mixed-corpus safety gate failed: public scenarios returned "
            f"{len(failures)} unsafe or incomplete retrieval result(s)."
        )
        report["findings"].append(reason)
        _append_blocker(
            report,
            key="rag_mixed_corpus_safety",
            label="RAG mixed-corpus safety gate",
            reason=reason,
            action=(
                "Review forbidden public/internal visibility metadata and retrieval filters, "
                "then rerun the mixed-corpus safety gate."
            ),
            command=RAG_MIXED_CORPUS_SAFETY_READINESS_COMMAND,
            target="rag_mixed_corpus_safety",
        )
        return report

    report["status"] = "passed"
    report["findings"].append(
        (
            f"{result.scenario_count} public safety scenario(s) passed across "
            f"{result.document_count} mixed-corpus document(s)."
        )
    )
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
    display_target: str | None = None,
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
    output_target = display_target or target
    snapshot["target"] = output_target
    snapshot["resolved_environment"] = target
    snapshot["status"] = _resolve_target_status(snapshot)
    snapshot["readiness_status"] = _runtime_readiness_status(snapshot["status"])
    snapshot["status_counts"] = _dependency_status_counts(snapshot["dependencies"])
    blocked_reasons, repair_suggestions = _configuration_issues(
        snapshot,
        snapshot.get("missing_required") or [],
        target=output_target,
    )
    degraded_reasons, _ = _configuration_issues(
        snapshot,
        snapshot.get("degraded_optional") or [],
        target=output_target,
    )
    snapshot["blocked_reasons"] = blocked_reasons
    snapshot["degraded_reasons"] = degraded_reasons
    snapshot["repair_suggestions"] = repair_suggestions
    snapshot["component_readiness"] = _component_readiness_from_dependencies(
        snapshot.get("dependencies") or {},
        target=output_target,
    )
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
    blocked_reasons, repair_suggestions = _preflight_issues(preflight)
    return {
        "target": "acceptance",
        "status": preflight["status"],
        "readiness_status": _runtime_readiness_status(preflight["status"]),
        "base_url": base_url,
        "check_backend": check_backend,
        "scenario_count": len(scenarios),
        "preflight": preflight,
        "blocked_reasons": blocked_reasons,
        "repair_suggestions": repair_suggestions,
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
    blocked_reasons: list[dict[str, Any]] = []
    repair_suggestions: list[dict[str, Any]] = []
    if missing:
        reason = "Missing migration contract files: " + ", ".join(missing)
        blocked_reasons.append(
            {
                "target": "database_migrations",
                "key": "alembic_static_contract",
                "label": "Alembic（数据库迁移工具）static contract",
                "reason": reason,
                "findings": [reason],
                "env_vars": [],
                "status": "blocked",
                "requirement": "required",
            }
        )
        repair_suggestions.append(
            {
                "target": "database_migrations",
                "key": "alembic_static_contract",
                "label": "Alembic（数据库迁移工具）static contract",
                "action": "Restore alembic.ini, alembic/env.py, and at least one migration revision before deployment.",
                "command": "git status --short; Get-ChildItem alembic\\versions",
                "env_vars": [],
            }
        )
    return {
        "version": DATABASE_MIGRATION_READINESS_VERSION,
        "status": status,
        "requires_database_connection": False,
        "missing_required": missing,
        "blocked_reasons": blocked_reasons,
        "repair_suggestions": repair_suggestions,
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


def _collect_report_blockers(
    *,
    target_results: Mapping[str, Mapping[str, Any]],
    database_migrations: Mapping[str, Any],
    docker_compose: Mapping[str, Any],
    rag_mixed_corpus_safety: Mapping[str, Any],
    rag_multimodal_e2e: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocked_reasons: list[dict[str, Any]] = []
    repair_suggestions: list[dict[str, Any]] = []

    for target, result in target_results.items():
        for issue in result.get("blocked_reasons") or []:
            payload = dict(issue)
            payload.setdefault("target", target)
            blocked_reasons.append(payload)
        for suggestion in result.get("repair_suggestions") or []:
            payload = dict(suggestion)
            payload.setdefault("target", target)
            repair_suggestions.append(payload)

    for section_name, section in (
        ("database_migrations", database_migrations),
        ("docker_compose", docker_compose),
        ("rag_mixed_corpus_safety", rag_mixed_corpus_safety),
        ("rag_multimodal_e2e", rag_multimodal_e2e),
    ):
        for issue in section.get("blocked_reasons") or []:
            payload = dict(issue)
            payload.setdefault("target", section_name)
            blocked_reasons.append(payload)
        for suggestion in section.get("repair_suggestions") or []:
            payload = dict(suggestion)
            payload.setdefault("target", section_name)
            repair_suggestions.append(payload)

    return _dedupe_dicts(blocked_reasons), _dedupe_dicts(repair_suggestions)


def _render_issue(issue: Mapping[str, Any]) -> str:
    label = issue.get("label") or issue.get("key") or "unknown"
    reason = issue.get("reason") or _finding_summary(issue.get("findings") or [])
    return f"{label}: {reason}"


def _render_suggestion(suggestion: Mapping[str, Any]) -> str:
    action = suggestion.get("action") or "Review and repair this blocker."
    command = suggestion.get("command")
    return f"{action} Command: {command}" if command else str(action)


def build_runtime_readiness_report(
    *,
    targets: list[str] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    check_backend: bool = False,
    check_docker: bool = False,
    check_rag_mixed_corpus_safety: bool = True,
    check_rag_multimodal_e2e: bool = False,
) -> dict[str, Any]:
    """Build a redacted readiness report for development, acceptance, and production."""

    selected_target_pairs = _selected_target_pairs(targets)
    resolved_dotenv = dotenv_path or DEFAULT_DOTENV_PATH
    target_results: dict[str, dict[str, Any]] = {}
    for output_target, canonical_target in selected_target_pairs:
        if canonical_target == "development":
            target_results[output_target] = _configuration_target(
                target="development",
                display_target=output_target,
                environ=environ,
                dotenv_path=resolved_dotenv,
                require_real_values=False,
            )
        elif canonical_target == "staging":
            target_results[output_target] = _configuration_target(
                target="staging",
                display_target=output_target,
                environ=environ,
                dotenv_path=resolved_dotenv,
                require_real_values=True,
            )
        elif canonical_target == "acceptance":
            target_results[output_target] = _acceptance_target(
                base_url=base_url,
                environ=environ,
                dotenv_path=resolved_dotenv,
                check_backend=check_backend,
            )
        elif canonical_target == "production":
            target_results[output_target] = _configuration_target(
                target="production",
                display_target=output_target,
                environ=environ,
                dotenv_path=resolved_dotenv,
                require_real_values=True,
            )

    statuses = {key: value["status"] for key, value in target_results.items()}
    readiness_statuses = {
        key: value.get("readiness_status") or _runtime_readiness_status(value.get("status"))
        for key, value in target_results.items()
    }
    database_migrations = build_database_migration_readiness_report()
    docker_compose = build_docker_compose_readiness_report(check=check_docker)
    rag_mixed_corpus_safety = build_rag_mixed_corpus_safety_readiness_report(
        check=check_rag_mixed_corpus_safety
    )
    rag_multimodal_e2e = build_rag_multimodal_e2e_readiness_report(
        check=check_rag_multimodal_e2e
    )
    if any(status == "blocked" for status in statuses.values()):
        overall_status = "blocked"
    elif database_migrations["status"] == "blocked":
        overall_status = "blocked"
    elif docker_compose["status"] == "blocked":
        overall_status = "blocked"
    elif rag_mixed_corpus_safety["status"] == "blocked":
        overall_status = "blocked"
    elif rag_multimodal_e2e["status"] == "blocked":
        overall_status = "blocked"
    elif any(status == "skipped" for status in statuses.values()):
        overall_status = "skipped"
    elif any(status == "degraded" for status in statuses.values()):
        overall_status = "degraded"
    else:
        overall_status = "passed"
    blocked_reasons, repair_suggestions = _collect_report_blockers(
        target_results=target_results,
        database_migrations=database_migrations,
        docker_compose=docker_compose,
        rag_mixed_corpus_safety=rag_mixed_corpus_safety,
        rag_multimodal_e2e=rag_multimodal_e2e,
    )

    return {
        "version": READINESS_REPORT_VERSION,
        "status": overall_status,
        "readiness_status": _runtime_readiness_status(overall_status),
        "readiness_status_legend": READINESS_STATUS_LEGEND,
        "current_environment": settings.runtime_environment,
        "dotenv_path": str(resolved_dotenv),
        "blocked_reasons": blocked_reasons,
        "repair_suggestions": repair_suggestions,
        "targets": target_results,
        "target_statuses": statuses,
        "target_readiness_statuses": readiness_statuses,
        "database_migrations": database_migrations,
        "docker_compose": docker_compose,
        "rag_mixed_corpus_safety": rag_mixed_corpus_safety,
        "rag_multimodal_e2e": rag_multimodal_e2e,
        "dependency_matrix": {
            key: spec.to_dict(settings.runtime_environment)
            for key, spec in dependency_specs_by_key().items()
        },
    }


def _render_human(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Config Readiness",
        f"- Overall: {report['status']} ({report.get('readiness_status')})",
        f"- Current environment: {report['current_environment']}",
        f"- .env path: {report['dotenv_path']}",
        "",
    ]
    database_migrations = report.get("database_migrations") or {}
    lines.append(f"## database migrations: {database_migrations.get('status')}")
    if database_migrations.get("blocked_reasons"):
        lines.append(
            "- Blocked reasons: "
            + " | ".join(_render_issue(item) for item in database_migrations["blocked_reasons"])
        )
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
        if docker_compose.get("repair_suggestions"):
            lines.append(
                "- Next steps: "
                + " | ".join(
                    _render_suggestion(item)
                    for item in docker_compose.get("repair_suggestions") or []
                )
            )
    else:
        lines.append("- Findings: not checked; add --check-docker for local/staging bootstrap.")
    lines.append("")
    rag_mixed_corpus_safety = report.get("rag_mixed_corpus_safety") or {}
    lines.append(f"## rag mixed-corpus safety: {rag_mixed_corpus_safety.get('status')}")
    if rag_mixed_corpus_safety.get("checked"):
        findings = rag_mixed_corpus_safety.get("findings") or []
        lines.append("- Findings: " + ("; ".join(findings) if findings else "-"))
        summaries = rag_mixed_corpus_safety.get("summaries") or []
        if summaries:
            summary_bits = [
                (
                    f"{item.get('strategy')}@{item.get('top_k')}: "
                    f"safety={item.get('safety_pass_rate')}, source={item.get('source_recall')}"
                )
                for item in summaries
            ]
            lines.append("- Summary: " + " | ".join(summary_bits))
        if rag_mixed_corpus_safety.get("repair_suggestions"):
            lines.append(
                "- Next steps: "
                + " | ".join(
                    _render_suggestion(item)
                    for item in rag_mixed_corpus_safety.get("repair_suggestions") or []
                )
            )
    else:
        lines.append(
            "- Findings: not checked; this deterministic gate is enabled by default."
        )
    lines.append("")
    rag_multimodal_e2e = report.get("rag_multimodal_e2e") or {}
    lines.append(f"## rag multimodal e2e: {rag_multimodal_e2e.get('status')}")
    if rag_multimodal_e2e.get("checked"):
        findings = rag_multimodal_e2e.get("findings") or []
        lines.append("- Findings: " + ("; ".join(findings) if findings else "-"))
        e2e_acceptance = rag_multimodal_e2e.get("e2e_acceptance") or {}
        if e2e_acceptance:
            lines.append(f"- E2E acceptance: {e2e_acceptance.get('status')}")
        if rag_multimodal_e2e.get("repair_suggestions"):
            lines.append(
                "- Next steps: "
                + " | ".join(
                    _render_suggestion(item)
                    for item in rag_multimodal_e2e.get("repair_suggestions") or []
                )
            )
    else:
        lines.append(
            "- Findings: not checked; add --check-rag-multimodal-e2e for release deep gate."
        )
    lines.append("")
    for target, result in report["targets"].items():
        lines.append(f"## {target}: {result['status']} ({result.get('readiness_status')})")
        components = result.get("component_readiness") or {}
        if components:
            lines.append(
                "- Component readiness: "
                + ", ".join(
                    f"{item.get('label') or key}={item.get('status')}"
                    for key, item in components.items()
                )
            )
        if target == "acceptance":
            preflight = result.get("preflight") or {}
            lines.append(f"- Scenarios: {result.get('scenario_count')}")
            lines.append(f"- Backend checked: {result.get('check_backend')}")
            missing = ", ".join(preflight.get("missing_required") or []) or "-"
            lines.append("- Missing required: " + missing)
            required_mcp = (
                (preflight.get("required_capabilities") or {}).get("mcp_servers")
                or []
            )
            mcp_services = preflight.get("mcp_services") or {}
            if required_mcp and mcp_services:
                service_bits = [
                    f"{server}={((mcp_services.get(server) or {}).get('status') or 'missing')}"
                    for server in required_mcp
                ]
                lines.append("- Required MCP services: " + ", ".join(service_bits))
            if result.get("blocked_reasons"):
                lines.append(
                    "- Blocked reasons: "
                    + " | ".join(_render_issue(item) for item in result["blocked_reasons"])
                )
            if result.get("repair_suggestions"):
                lines.append(
                    "- Next steps: "
                    + " | ".join(_render_suggestion(item) for item in result["repair_suggestions"])
                )
            continue

        missing = result.get("missing_required") or []
        degraded = result.get("degraded_optional") or []
        lines.append("- Missing required: " + (", ".join(missing) if missing else "-"))
        lines.append("- Optional degraded/not configured: " + (", ".join(degraded) if degraded else "-"))
        lines.append(f"- Status counts: {result.get('status_counts')}")
        if result.get("blocked_reasons"):
            lines.append(
                "- Blocked reasons: "
                + " | ".join(_render_issue(item) for item in result["blocked_reasons"])
            )
        if result.get("repair_suggestions"):
            lines.append(
                "- Next steps: "
                + " | ".join(_render_suggestion(item) for item in result["repair_suggestions"])
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        choices=READINESS_TARGET_CHOICES,
        help=(
            "Target to check. Can be repeated. Defaults to development/staging/"
            "acceptance/production. local is an alias for development."
        ),
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
        "--check-rag-multimodal-e2e",
        action="store_true",
        help=(
            "Also run the live RAG multimodal vector-store acceptance check under .runtime. "
            "This requires real LLM credentials and prepared local samples."
        ),
    )
    parser.add_argument(
        "--skip-rag-mixed-corpus-safety",
        action="store_true",
        help=(
            "Skip the deterministic RAG public-vs-internal mixed-corpus safety gate. "
            "The gate is checked by default."
        ),
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
        check_rag_mixed_corpus_safety=not args.skip_rag_mixed_corpus_safety,
        check_rag_multimodal_e2e=args.check_rag_multimodal_e2e,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] in {"blocked", "skipped"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
