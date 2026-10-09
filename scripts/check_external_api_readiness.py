"""Check external API readiness without reading .env files or calling providers."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


EXTERNAL_API_READINESS_VERSION = "external_api_readiness.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
READY_VALUES = {"1", "true", "yes", "y", "on", "ready", "enabled", "configured", "confirmed"}
BLOCKED_VALUES = {"0", "false", "no", "n", "off", "blocked", "missing", "invalid", "expired"}
OPTIONAL_SERVICE_ENV = {
    "tavily": "ZHIXING_TAVILY_SERVICE_STATUS",
    "variflight": "ZHIXING_VARIFLIGHT_SERVICE_STATUS",
    "aigohotel": "ZHIXING_AIGOHOTEL_SERVICE_STATUS",
    "12306": "ZHIXING_12306_MCP_STATUS",
}
OPTIONAL_SERVICE_ALIASES = {
    "tavily": "tavily",
    "search": "tavily",
    "variflight": "variflight",
    "flight": "variflight",
    "flights": "variflight",
    "aigohotel": "aigohotel",
    "hotel": "aigohotel",
    "hotels": "aigohotel",
    "12306": "12306",
    "rail": "12306",
    "train": "12306",
}


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "n/a", "na"}:
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
            finding="Missing required external API declaration.",
        )
    if _looks_placeholder(value):
        return _check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="External API declaration still looks like a placeholder.",
        )
    return _check(
        category=category,
        key=key,
        env_var=env_var,
        label=label,
        status="passed",
        finding="Declared.",
    )


def _check_ready_flag(*, key: str, env_var: str, value: str, label: str) -> dict[str, Any]:
    if not value:
        return _check(
            category="required_services",
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Missing required provider readiness flag.",
        )
    lowered = value.lower()
    if lowered in READY_VALUES:
        return _check(
            category="required_services",
            key=key,
            env_var=env_var,
            label=label,
            status="passed",
            finding="Required provider is declared ready.",
        )
    if lowered in BLOCKED_VALUES or _looks_placeholder(value):
        return _check(
            category="required_services",
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Required provider is not ready for M1.",
        )
    return _check(
        category="required_services",
        key=key,
        env_var=env_var,
        label=label,
        status="blocked",
        finding="Expected ready/true/yes/enabled for this provider.",
    )


def _check_budget(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="quota",
        key="external_api_quota_budget",
        env_var="ZHIXING_EXTERNAL_API_QUOTA_BUDGET",
        value=value,
        label="External API quota budget",
    )
    if item["status"] == "blocked":
        return item
    if not any(char.isdigit() for char in value):
        item["status"] = "blocked"
        item["finding"] = "External API quota budget must include a numeric limit."
    return item


def _check_timeout_retry_policy(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="reliability",
        key="external_api_timeout_retry_policy",
        env_var="ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY",
        value=value,
        label="External API timeout/retry policy",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if "timeout" not in lowered and "超时" not in lowered:
        item["status"] = "blocked"
        item["finding"] = "Timeout policy must explicitly mention timeout."
    elif "retry" not in lowered and "重试" not in lowered:
        item["status"] = "blocked"
        item["finding"] = "Timeout policy must explicitly mention retry."
    elif not any(char.isdigit() for char in value):
        item["status"] = "blocked"
        item["finding"] = "Timeout/retry policy must include numeric limits."
    return item


def _check_degradation_policy(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="degradation",
        key="external_api_degradation_policy",
        env_var="ZHIXING_EXTERNAL_API_DEGRADATION_POLICY",
        value=value,
        label="External API degradation policy",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    keywords = ("degrad", "manual", "disabled", "blocked", "待核验", "降级", "人工", "关闭")
    if not any(keyword in lowered for keyword in keywords):
        item["status"] = "blocked"
        item["finding"] = "Degradation policy must describe degraded/manual/disabled handling."
    return item


def _parse_optional_services(value: str) -> list[str]:
    if not value or _looks_placeholder(value):
        return []
    tokens = [
        part.strip().lower()
        for part in value.replace("，", ",").replace(";", ",").replace("/", ",").split(",")
    ]
    services: list[str] = []
    for token in tokens:
        if not token or token in {"none", "disabled", "no optional api", "no optional apis"}:
            continue
        normalized = OPTIONAL_SERVICE_ALIASES.get(token, token)
        if normalized not in services:
            services.append(normalized)
    return services


def _check_optional_services(value: str, environ: Mapping[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    declaration = _check_declared(
        category="optional_services",
        key="optional_external_apis",
        env_var="ZHIXING_OPTIONAL_EXTERNAL_APIS",
        value=value,
        label="Optional external APIs",
    )
    if declaration["status"] == "blocked":
        return declaration, []

    services = _parse_optional_services(value)
    declaration["services_declared"] = services
    service_checks: list[dict[str, Any]] = []
    for service in services:
        env_var = OPTIONAL_SERVICE_ENV.get(service)
        if not env_var:
            service_checks.append(
                _check(
                    category="optional_services",
                    key=service,
                    env_var="ZHIXING_OPTIONAL_EXTERNAL_APIS",
                    label=service,
                    status="blocked",
                    finding="Unknown optional external API service.",
                )
            )
            continue
        status_value = _value(environ, env_var)
        if not status_value:
            service_checks.append(
                _check(
                    category="optional_services",
                    key=service,
                    env_var=env_var,
                    label=service,
                    status="blocked",
                    finding="Optional service is declared enabled but has no readiness status.",
                )
            )
            continue
        lowered = status_value.lower()
        if _looks_placeholder(status_value):
            status = "blocked"
            finding = "Optional service status still looks like a placeholder."
        elif any(word in lowered for word in ("blocked", "missing", "invalid", "expired")):
            status = "blocked"
            finding = "Optional service is declared enabled but blocked."
        elif any(word in lowered for word in ("degraded", "待核验", "manual", "人工")):
            status = "degraded"
            finding = "Optional service is declared degraded; dependent scenarios need manual handling."
        elif any(word in lowered for word in ("ready", "enabled", "configured", "confirmed")):
            status = "passed"
            finding = "Optional service readiness is declared."
        elif any(word in lowered for word in ("disabled", "off", "not used")):
            status = "blocked"
            finding = "Optional service is listed as enabled but status says disabled."
        else:
            status = "blocked"
            finding = "Expected ready/degraded/blocked status for optional service."
        service_checks.append(
            _check(
                category="optional_services",
                key=service,
                env_var=env_var,
                label=service,
                status=status,
                finding=finding,
            )
        )
    return declaration, service_checks


def build_external_api_readiness_report(
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a redacted external API readiness report from declarations only."""

    env = environ if environ is not None else os.environ
    optional_declaration, service_checks = _check_optional_services(
        _value(env, "ZHIXING_OPTIONAL_EXTERNAL_APIS"),
        env,
    )
    checks = [
        _check_ready_flag(
            key="llm_provider_ready",
            env_var="ZHIXING_LLM_PROVIDER_READY",
            value=_value(env, "ZHIXING_LLM_PROVIDER_READY"),
            label="LLM provider ready",
        ),
        _check_ready_flag(
            key="map_api_ready",
            env_var="ZHIXING_MAP_API_READY",
            value=_value(env, "ZHIXING_MAP_API_READY"),
            label="Map API ready",
        ),
        optional_declaration,
        _check_budget(_value(env, "ZHIXING_EXTERNAL_API_QUOTA_BUDGET")),
        _check_declared(
            category="ownership",
            key="provider_console_owner",
            env_var="ZHIXING_PROVIDER_CONSOLE_OWNER",
            value=_value(env, "ZHIXING_PROVIDER_CONSOLE_OWNER"),
            label="Provider console owner",
        ),
        _check_declared(
            category="support",
            key="provider_support_channel",
            env_var="ZHIXING_PROVIDER_SUPPORT_CHANNEL",
            value=_value(env, "ZHIXING_PROVIDER_SUPPORT_CHANNEL"),
            label="Provider support channel",
        ),
        _check_degradation_policy(_value(env, "ZHIXING_EXTERNAL_API_DEGRADATION_POLICY")),
        _check_timeout_retry_policy(_value(env, "ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY")),
    ]
    all_checks = [*checks, *service_checks]
    blocked = [item for item in all_checks if item["status"] == "blocked"]
    degraded = [item for item in all_checks if item["status"] == "degraded"]
    status = "blocked" if blocked else "degraded" if degraded else "passed"

    return {
        "version": EXTERNAL_API_READINESS_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "calls_external_providers": False,
            "reads_secret_values": False,
            "does_not_echo_values": True,
        },
        "optional_services": optional_declaration.get("services_declared", []),
        "checks": checks,
        "service_checks": service_checks,
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "not_proven_by_this_check": [
            "Real provider secrets are valid.",
            "Provider consoles have actually enforced quotas, IP allowlists, or billing alerts.",
            "External APIs have been called successfully from the target server.",
            "Acceptance scenarios depending on optional APIs have passed.",
            "Supplier data is fresh, complete, or legally usable for production.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# External API Readiness",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, calls_external_providers=false",
        "",
        "## Checks",
    ]
    for item in [*(report.get("checks") or []), *(report.get("service_checks") or [])]:
        lines.append(f"- {item.get('env_var')}: {item.get('status')} ({item.get('finding')})")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded"])
        for item in report["degraded_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_external_api_readiness_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
