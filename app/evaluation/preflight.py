"""Preflight environment checks for live acceptance evaluation."""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values

from app.evaluation.scenarios import EvaluationScenario


PREFLIGHT_VERSION = "acceptance_preflight.v1"
ACCEPTANCE_STATUSES = {"passed", "failed", "degraded", "blocked", "skipped"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"

PLACEHOLDER_MARKERS = (
    "your-",
    "change-me",
    "placeholder",
    "not-a-real",
    "test-key",
    "dummy",
    "example",
)

LLM_ENV_VARS = ("DASHSCOPE_API_KEY",)
STARTUP_REQUIRED_ENV_VARS = (
    "DASHSCOPE_API_KEY",
    "LANGSMITH_API_KEY",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)
EXTERNAL_API_ENV_VARS: dict[str, tuple[str, ...]] = {
    "amap": ("AMAP_API_KEY",),
    "tavily": ("TAVILY_API_KEY",),
    "variflight": ("VARIFLIGHT_API_KEY",),
    "aigohotel": ("AIGOHOTEL_API_KEY", "AIGOHOTEL_MCP_API", "AIGOHOTEL_SECRET_KEY"),
}
MCP_SERVER_BACKING_APIS: dict[str, str | None] = {
    "weather": "amap",
    "search": "tavily",
    "amap": "amap",
    "12306-mcp": None,
    "VariFlight-Aviation": "variflight",
    "aigohotel-mcp": "aigohotel",
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightResult:
    """Full preflight result for a selected scenario set."""

    version: str
    status: str
    checks: list[PreflightCheck]
    required_capabilities: dict[str, Any]
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
            "missing_required": self.missing_required,
            "degraded_optional": self.degraded_optional,
            "skipped_metrics": self.skipped_metrics,
            "dotenv_present": self.dotenv_present,
        }


def _has_real_value(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    normalized = value.strip().lower()
    return not any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def _load_effective_env(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> tuple[dict[str, str], bool]:
    path = dotenv_path or DEFAULT_DOTENV_PATH
    dotenv_values_map = {
        key: value
        for key, value in dotenv_values(path).items()
        if isinstance(key, str) and isinstance(value, str)
    } if path.exists() else {}
    effective = dict(dotenv_values_map)
    effective.update(dict(environ or os.environ))
    return effective, path.exists()


def _any_real_env(env: Mapping[str, str], names: tuple[str, ...]) -> bool:
    return any(_has_real_value(env.get(name)) for name in names)


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


def run_acceptance_preflight(
    scenarios: list[EvaluationScenario],
    *,
    base_url: str,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    check_backend: bool = True,
) -> PreflightResult:
    """Check whether selected scenarios can produce a valid live acceptance result."""

    env, dotenv_present = _load_effective_env(environ=environ, dotenv_path=dotenv_path)
    capabilities = required_capabilities_for_scenarios(scenarios)
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

    startup_missing = [name for name in STARTUP_REQUIRED_ENV_VARS if not env.get(name)]
    if startup_missing:
        checks.append(
            PreflightCheck(
                key="startup_required_env",
                label="Backend startup required environment",
                status="blocked",
                required=True,
                findings=["Missing required startup environment variables: " + ", ".join(startup_missing)],
                env_vars=startup_missing,
                suggestion="Provide startup configuration through process environment or .env; do not commit secrets.",
            )
        )

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
        mcp_findings = []
        for server in capabilities["mcp_servers"]:
            backing_api = MCP_SERVER_BACKING_APIS.get(server)
            if backing_api is None:
                continue
            env_vars = EXTERNAL_API_ENV_VARS.get(backing_api, ())
            if env_vars and not _any_real_env(env, env_vars):
                mcp_findings.append(f"{server} requires {backing_api} credential")
        checks.append(
            PreflightCheck(
                key="real_mcp",
                label="Real MCP services",
                status="blocked" if mcp_findings else "passed",
                required=True,
                findings=mcp_findings,
                suggestion="Provide real backing API credentials or remove the scenario from live acceptance.",
            )
        )

    if check_backend:
        checks.append(_check_backend(base_url))

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
        ]
        if status in {"blocked", "skipped"}
        else []
    )
    return PreflightResult(
        version=PREFLIGHT_VERSION,
        status=status,
        checks=checks,
        required_capabilities=capabilities,
        missing_required=blocked,
        degraded_optional=degraded,
        skipped_metrics=skipped_metrics,
        dotenv_present=dotenv_present,
    )
