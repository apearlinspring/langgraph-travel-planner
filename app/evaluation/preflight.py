"""Preflight environment checks for live acceptance evaluation."""
from __future__ import annotations

import os
import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.config import (
    DEFAULT_DOTENV_PATH,
    PROJECT_ROOT,
    dependency_specs_by_key,
    has_real_env_value,
    load_effective_environment,
    runtime_configuration_snapshot,
)
from app.evaluation.scenarios import EvaluationScenario
from app.evaluation.llm_judge import LLM_JUDGE_ENV_VARS
from app.mcp_core.client import MCPClientManager


PREFLIGHT_VERSION = "acceptance_preflight.v1"
ACCEPTANCE_STATUSES = {"passed", "failed", "degraded", "blocked", "skipped"}

LLM_ENV_VARS = ("DASHSCOPE_API_KEY",)
ACCEPTANCE_RUNTIME_ENV = "staging"
EXTERNAL_API_ENV_VARS: dict[str, tuple[str, ...]] = {
    "amap": ("AMAP_API_KEY",),
    "tavily": ("TAVILY_API_KEY",),
    "variflight": ("VARIFLIGHT_API_KEY",),
    "aigohotel": ("AIGOHOTEL_API_KEY", "AIGOHOTEL_MCP_API", "AIGOHOTEL_SECRET_KEY"),
}
@dataclass(frozen=True)
class PreflightCheck:
    """One preflight check with redacted environment details."""

    key: str
    label: str
    status: str
    required: bool
    findings: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    suggestion: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightResult:
    """Full preflight result for a selected scenario set."""

    version: str
    status: str
    checks: list[PreflightCheck]
    required_capabilities: dict[str, Any]
    mcp_services: dict[str, Any]
    missing_required: list[str]
    degraded_optional: list[str]
    skipped_metrics: list[str]
    dotenv_present: bool

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "passed": self.passed,
            "blocked": self.blocked,
            "checks": [check.to_dict() for check in self.checks],
            "required_capabilities": self.required_capabilities,
            "mcp_services": self.mcp_services,
            "missing_required": self.missing_required,
            "degraded_optional": self.degraded_optional,
            "skipped_metrics": self.skipped_metrics,
            "dotenv_present": self.dotenv_present,
        }


def _has_real_value(value: str | None) -> bool:
    return has_real_env_value(value)


def _load_effective_env(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> tuple[dict[str, str], bool]:
    return load_effective_environment(environ=environ, dotenv_path=dotenv_path)


def _any_real_env(env: Mapping[str, str], names: tuple[str, ...]) -> bool:
    return any(_has_real_value(env.get(name)) for name in names)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _selected_mcp_entries(
    service_table: Mapping[str, Any],
    selected_servers: list[str],
) -> dict[str, dict[str, Any]]:
    return {
        server: _as_dict(service_table.get(server))
        for server in selected_servers
    }


def _selected_mcp_blockers(
    service_table: Mapping[str, Any],
    selected_servers: list[str],
) -> list[str]:
    blockers: list[str] = []
    for server in selected_servers:
        entry = _as_dict(service_table.get(server))
        status = str(entry.get("status") or "missing")
        if status == "healthy":
            continue
        reason = str(entry.get("reason") or entry.get("error") or "").strip()
        detail = f"{server}={status}"
        if reason:
            detail += f" ({reason})"
        blockers.append(detail)
    return blockers


def _build_mcp_preflight_service_table(
    *,
    env: Mapping[str, str],
    required_servers: list[str],
) -> dict[str, dict[str, Any]]:
    return MCPClientManager.build_service_health_table(
        required_servers=required_servers,
        configured_servers=MCPClientManager.configured_server_names_for_env(env),
        env=env,
        require_probe=False,
    )


def _mcp_service_table_from_ready_payload(
    payload: Mapping[str, Any],
    *,
    required_mcp_servers: list[str],
) -> dict[str, dict[str, Any]]:
    services = _as_dict(payload.get("services"))
    mcp = _as_dict(services.get("mcp"))
    service_health = mcp.get("service_health")
    if isinstance(service_health, dict):
        return {
            str(server): _as_dict(entry)
            for server, entry in service_health.items()
        }

    legacy_servers = _as_dict(mcp.get("servers"))
    table: dict[str, dict[str, Any]] = {}
    for server in sorted(set(required_mcp_servers) | set(str(item) for item in legacy_servers)):
        raw = _as_dict(legacy_servers.get(server))
        connection_status = str(raw.get("status") or "missing")
        status = "healthy" if connection_status == "healthy" else "degraded"
        table[server] = {
            "status": status,
            "required": server in required_mcp_servers,
            "connection_status": connection_status,
            "tool_count": int(raw.get("tool_count") or 0),
            "error": raw.get("error"),
            "reason": raw.get("error") or f"MCP service connection is {connection_status}.",
        }
    return table


def _scenario_requirements(scenario: EvaluationScenario) -> dict[str, Any]:
    requirements = dict(scenario.requirements or {})
    return {
        "real_llm": bool(requirements.get("real_llm", True)),
        "real_mcp": bool(requirements.get("real_mcp", False)),
        "mcp_servers": sorted(set(str(item) for item in requirements.get("mcp_servers", []) if item)),
        "external_apis": sorted(set(str(item) for item in requirements.get("external_apis", []) if item)),
        "notes": str(requirements.get("notes") or ""),
    }


def required_capabilities_for_scenarios(scenarios: list[EvaluationScenario]) -> dict[str, Any]:
    """Return merged live-environment requirements for selected scenarios."""

    per_scenario = {scenario.id: _scenario_requirements(scenario) for scenario in scenarios}
    return {
        "real_llm": any(item["real_llm"] for item in per_scenario.values()),
        "real_mcp": any(item["real_mcp"] for item in per_scenario.values()),
        "mcp_servers": sorted({server for item in per_scenario.values() for server in item["mcp_servers"]}),
        "external_apis": sorted({api for item in per_scenario.values() for api in item["external_apis"]}),
        "per_scenario": per_scenario,
    }


def _check_env_group(
    *,
    key: str,
    label: str,
    env: Mapping[str, str],
    env_vars: tuple[str, ...],
    required: bool,
    suggestion: str,
) -> PreflightCheck:
    if _any_real_env(env, env_vars):
        return PreflightCheck(
            key=key,
            label=label,
            status="passed",
            required=required,
            env_vars=list(env_vars),
        )
    status = "blocked" if required else "degraded"
    return PreflightCheck(
        key=key,
        label=label,
        status=status,
        required=required,
        findings=[f"Missing real value for one of: {', '.join(env_vars)}"],
        env_vars=list(env_vars),
        suggestion=suggestion,
    )


def _check_backend(base_url: str, *, required: bool = True, timeout_seconds: float = 3.0) -> PreflightCheck:
    url = f"{base_url.rstrip('/')}/health/live"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            if 200 <= response.status < 300:
                return PreflightCheck(
                    key="backend_live",
                    label="Backend live health endpoint",
                    status="passed",
                    required=required,
                    findings=[],
                    suggestion="",
                )
            finding = f"Backend health endpoint returned HTTP {response.status}"
    except (urllib.error.URLError, OSError) as exc:
        finding = str(exc)

    return PreflightCheck(
        key="backend_live",
        label="Backend live health endpoint",
        status="blocked" if required else "degraded",
        required=required,
        findings=[finding],
        suggestion="Start the backend and confirm GET /health/live before running live acceptance.",
    )


def _parse_json_response(response: Any) -> dict[str, Any]:
    raw = response.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _check_backend_ready(
    base_url: str,
    *,
    required: bool = True,
    timeout_seconds: float = 5.0,
    required_mcp_servers: list[str] | None = None,
) -> PreflightCheck:
    url = f"{base_url.rstrip('/')}/health/ready"
    payload: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            payload = _parse_json_response(response)
            http_status = response.status
    except urllib.error.HTTPError as exc:
        http_status = exc.code
        payload = _parse_json_response(exc)
    except (urllib.error.URLError, OSError) as exc:
        return PreflightCheck(
            key="backend_ready",
            label="Backend ready health endpoint",
            status="blocked" if required else "degraded",
            required=required,
            findings=[str(exc)],
            suggestion="Start the backend and confirm GET /health/ready before running live acceptance.",
        )

    selected_mcp_servers = sorted(set(required_mcp_servers or []))
    mcp_service_table = _mcp_service_table_from_ready_payload(
        payload,
        required_mcp_servers=selected_mcp_servers,
    )
    selected_mcp_blockers = _selected_mcp_blockers(
        mcp_service_table,
        selected_mcp_servers,
    )
    if (
        selected_mcp_blockers
        and 200 <= http_status < 300
        and str(payload.get("status") or "") in {"ready", "degraded"}
    ):
        return PreflightCheck(
            key="backend_ready",
            label="Backend ready health endpoint",
            status="blocked" if required else "degraded",
            required=required,
            findings=[
                "Selected MCP services are not healthy: "
                + ", ".join(selected_mcp_blockers)
            ],
            suggestion="Restore selected MCP services before claiming live acceptance passed.",
            details={
                "required_mcp_servers": selected_mcp_servers,
                "mcp_services": _selected_mcp_entries(
                    mcp_service_table,
                    selected_mcp_servers,
                ),
            },
        )

    ready_status = str(payload.get("status") or "")
    if 200 <= http_status < 300 and ready_status == "ready":
        return PreflightCheck(
            key="backend_ready",
            label="Backend ready health endpoint",
            status="passed",
            required=required,
            details={
                "required_mcp_servers": selected_mcp_servers,
                "mcp_services": _selected_mcp_entries(
                    mcp_service_table,
                    selected_mcp_servers,
                ),
            },
        )
    if 200 <= http_status < 300 and ready_status == "degraded":
        degraded_optional = [
            str(item)
            for item in payload.get("degraded_optional", [])
            if str(item)
        ]
        if degraded_optional == ["mcp"] and selected_mcp_servers:
            return PreflightCheck(
                key="backend_ready",
                label="Backend ready health endpoint",
                status="passed",
                required=required,
                findings=[
                    "Backend readiness is degraded only by MCP services outside the selected scenario set."
                ],
                suggestion="Review full /health/ready before broadening this run beyond the selected scenarios.",
                details={
                    "required_mcp_servers": selected_mcp_servers,
                    "mcp_services": _selected_mcp_entries(
                        mcp_service_table,
                        selected_mcp_servers,
                    ),
                },
            )
        return PreflightCheck(
            key="backend_ready",
            label="Backend ready health endpoint",
            status="degraded",
            required=False,
            findings=[
                "Backend readiness is degraded: "
                + ", ".join(str(item) for item in degraded_optional[:8])
            ],
            suggestion="Review optional dependency degradation before treating this run as production-like.",
            details={
                "required_mcp_servers": selected_mcp_servers,
                "mcp_services": _selected_mcp_entries(
                    mcp_service_table,
                    selected_mcp_servers,
                ),
            },
        )

    findings = [f"Backend readiness returned HTTP {http_status} with status {ready_status or 'unknown'}"]
    missing = payload.get("missing_required") if isinstance(payload, dict) else None
    if isinstance(missing, list) and missing:
        findings.append("Missing required dependencies: " + ", ".join(str(item) for item in missing[:8]))
    return PreflightCheck(
        key="backend_ready",
        label="Backend ready health endpoint",
        status="blocked" if required else "degraded",
        required=required,
        findings=findings,
        suggestion="Inspect /health/ready dependencies and resolve required blockers before live acceptance.",
    )


def _check_runtime_config_matrix(
    *,
    env: Mapping[str, str],
    dotenv_path: Path | None,
) -> PreflightCheck:
    snapshot = runtime_configuration_snapshot(
        app_env=ACCEPTANCE_RUNTIME_ENV,
        environ=env,
        dotenv_path=dotenv_path,
        require_real_values=True,
    )
    if not snapshot["missing_required"]:
        return PreflightCheck(
            key="runtime_config",
            label="Runtime config readiness matrix",
            status="passed",
            required=True,
            findings=[],
            suggestion="",
        )

    specs = dependency_specs_by_key()
    env_vars: list[str] = []
    findings: list[str] = []
    for key in snapshot["missing_required"]:
        dependency = snapshot["dependencies"].get(key) or {}
        spec = specs.get(str(key))
        env_vars.extend(str(item) for item in dependency.get("env_vars") or [])
        label = spec.label if spec else str(key)
        detail = "; ".join(str(item) for item in dependency.get("findings") or [])
        findings.append(f"{label}: {detail or 'required dependency is not configured'}")

    return PreflightCheck(
        key="runtime_config",
        label="Runtime config readiness matrix",
        status="blocked",
        required=True,
        findings=findings,
        env_vars=sorted(set(env_vars)),
        suggestion="Fill required runtime configuration for staging-like acceptance; tests may mock, acceptance may not.",
    )


def run_acceptance_preflight(
    scenarios: list[EvaluationScenario],
    *,
    base_url: str,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    check_backend: bool = True,
    require_llm_judge: bool = False,
) -> PreflightResult:
    """Check whether selected scenarios can produce a valid live acceptance result."""

    env, dotenv_present = _load_effective_env(environ=environ, dotenv_path=dotenv_path)
    capabilities = required_capabilities_for_scenarios(scenarios)
    required_mcp_servers = sorted(set(capabilities["mcp_servers"]))
    mcp_services = _build_mcp_preflight_service_table(
        env=env,
        required_servers=required_mcp_servers if capabilities["real_mcp"] else [],
    )
    checks: list[PreflightCheck] = []

    if not scenarios:
        checks.append(
            PreflightCheck(
                key="scenario_selection",
                label="Scenario selection",
                status="skipped",
                required=True,
                findings=["No scenarios were selected."],
                suggestion="Select at least one scenario before running acceptance.",
            )
        )

    checks.append(_check_runtime_config_matrix(env=env, dotenv_path=dotenv_path))

    if capabilities["real_llm"]:
        checks.append(
            _check_env_group(
                key="real_llm",
                label="Real LLM provider",
                env=env,
                env_vars=LLM_ENV_VARS,
                required=True,
                suggestion="Set a real DASHSCOPE_API_KEY before claiming live acceptance passed.",
            )
        )

    if require_llm_judge:
        checks.append(
            _check_env_group(
                key="llm_judge",
                label="LLM judge provider",
                env=env,
                env_vars=LLM_JUDGE_ENV_VARS,
                required=True,
                suggestion="Set a real DASHSCOPE_API_KEY before enabling --llm-judge.",
            )
        )

    for api_name in capabilities["external_apis"]:
        env_vars = EXTERNAL_API_ENV_VARS.get(api_name)
        if env_vars is None:
            checks.append(
                PreflightCheck(
                    key=f"external_api:{api_name}",
                    label=f"External API: {api_name}",
                    status="degraded",
                    required=False,
                    findings=[f"No preflight env mapping is defined for external API {api_name!r}."],
                    suggestion="Add an explicit preflight mapping before using this API as a hard gate.",
                )
            )
            continue
        checks.append(
            _check_env_group(
                key=f"external_api:{api_name}",
                label=f"External API: {api_name}",
                env=env,
                env_vars=env_vars,
                required=True,
                suggestion=f"Set a real credential for {api_name} before running scenarios that require it.",
            )
        )

    if capabilities["real_mcp"]:
        unknown_servers = [
            server
            for server in required_mcp_servers
            if server not in mcp_services
        ]
        known_required_servers = [
            server
            for server in required_mcp_servers
            if server in mcp_services
        ]
        mcp_findings = [
            f"Unknown MCP service required by scenario: {server}"
            for server in unknown_servers
        ]
        mcp_findings.extend(
            _selected_mcp_blockers(mcp_services, known_required_servers)
        )
        checks.append(
            PreflightCheck(
                key="real_mcp",
                label="Real MCP services",
                status="blocked" if mcp_findings else "passed",
                required=True,
                findings=mcp_findings,
                suggestion="Provide real backing API credentials or remove the scenario from live acceptance.",
                details={
                    "required_mcp_servers": required_mcp_servers,
                    "services": _selected_mcp_entries(
                        mcp_services,
                        required_mcp_servers,
                    ),
                },
            )
        )

    if check_backend:
        checks.append(_check_backend(base_url))
        checks.append(
            _check_backend_ready(
                base_url,
                required_mcp_servers=capabilities["mcp_servers"],
            )
        )

    blocked = [check.key for check in checks if check.status == "blocked"]
    degraded = [check.key for check in checks if check.status == "degraded"]
    skipped = [check.key for check in checks if check.status == "skipped"]
    if blocked:
        status = "blocked"
    elif skipped:
        status = "skipped"
    elif degraded:
        status = "degraded"
    else:
        status = "passed"

    skipped_metrics = (
        [
            "report_quality",
            "rag_quality",
            "tool_quality",
            "runtime_quality",
            "budget_confidence",
            "internal_evidence",
            "tool_audit",
            "llm_judge" if require_llm_judge else "",
        ]
        if status in {"blocked", "skipped"}
        else []
    )
    skipped_metrics = [item for item in skipped_metrics if item]
    return PreflightResult(
        version=PREFLIGHT_VERSION,
        status=status,
        checks=checks,
        required_capabilities=capabilities,
        mcp_services=mcp_services,
        missing_required=blocked,
        degraded_optional=degraded,
        skipped_metrics=skipped_metrics,
        dotenv_present=dotenv_present,
    )
