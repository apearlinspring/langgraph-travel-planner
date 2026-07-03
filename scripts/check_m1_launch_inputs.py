"""Check M1 launch input readiness without reading .env files or printing values."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


M1_LAUNCH_INPUTS_VERSION = "m1_launch_inputs.v1"
M1_LAUNCH_INPUTS_TEMPLATE_VERSION = "m1_launch_inputs_template.v1"

PLACEHOLDER_EXACT = {
    "",
    "change-me",
    "changeme",
    "example",
    "n/a",
    "na",
    "null",
    "placeholder",
    "tbd",
    "todo",
    "unknown",
}
PLACEHOLDER_PREFIXES = (
    "<",
    "${",
    "change-me",
    "example-",
    "placeholder",
    "test-",
    "your-",
)
TRUTHY = {"1", "true", "yes", "y", "on", "disabled", "confirmed"}
FALSEY = {"0", "false", "no", "n", "off", "enabled"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
DEFAULT_BACKUP_DIRS = {"./backups", ".\\backups", "backups"}
FORBIDDEN_INPUT_FILE_PARTS = {".runtime", ".venv", "vectorstore", "vectorstore_internal"}


@dataclass(frozen=True)
class InputSpec:
    category: str
    key: str
    env_var: str
    label: str
    validator: str = "present"
    required: bool = True


M1_INPUT_SPECS: tuple[InputSpec, ...] = (
    InputSpec("scope", "m1_audience", "ZHIXING_M1_AUDIENCE", "M1 audience"),
    InputSpec(
        "scope",
        "real_payment_order_disabled",
        "ZHIXING_REAL_PAYMENT_ORDER_DISABLED",
        "Real payment/order disabled",
        "true",
    ),
    InputSpec(
        "network",
        "public_base_url",
        "ZHIXING_PUBLIC_BASE_URL",
        "Public base URL",
        "public_url",
    ),
    InputSpec(
        "network",
        "eval_base_url",
        "ZHIXING_EVAL_BASE_URL",
        "Evaluation base URL",
        "public_url",
    ),
    InputSpec("server", "server_provider", "ZHIXING_SERVER_PROVIDER", "Server provider"),
    InputSpec("server", "os_version", "ZHIXING_SERVER_OS_VERSION", "Server OS version"),
    InputSpec("server", "cpu_ram_disk", "ZHIXING_SERVER_CPU_RAM_DISK", "CPU/RAM/disk baseline"),
    InputSpec("network", "domain_ready", "ZHIXING_DOMAIN_READY", "Domain or access URL ready", "ready_flag"),
    InputSpec(
        "network",
        "server_egress_ip_status",
        "ZHIXING_SERVER_EGRESS_IP_STATUS",
        "Server egress IP status",
        "declared",
    ),
    InputSpec("deployment", "deploy_mode", "ZHIXING_DEPLOY_MODE", "Deployment mode"),
    InputSpec("deployment", "postgres_mode", "ZHIXING_POSTGRES_MODE", "PostgreSQL mode"),
    InputSpec("deployment", "redis_mode", "ZHIXING_REDIS_MODE", "Redis mode"),
    InputSpec("secrets", "secret_store", "ZHIXING_SECRET_STORE", "Secret store"),
    InputSpec("secrets", "secret_owner", "ZHIXING_SECRET_OWNER", "Secret owner"),
    InputSpec(
        "secrets",
        "rotation_cadence",
        "ZHIXING_SECRET_ROTATION_CADENCE",
        "Secret rotation cadence",
    ),
    InputSpec("external_api", "llm_provider_ready", "ZHIXING_LLM_PROVIDER_READY", "LLM provider ready", "ready_flag"),
    InputSpec("external_api", "map_api_ready", "ZHIXING_MAP_API_READY", "Map API ready", "ready_flag"),
    InputSpec(
        "external_api",
        "optional_external_apis",
        "ZHIXING_OPTIONAL_EXTERNAL_APIS",
        "Optional external APIs",
        "declared_allow_none",
    ),
    InputSpec("data", "data_scope", "ZHIXING_DATA_SCOPE", "Data scope"),
    InputSpec("acceptance", "acceptance_window", "ZHIXING_ACCEPTANCE_WINDOW", "Acceptance window"),
    InputSpec("acceptance", "eval_account_ready", "ZHIXING_EVAL_ACCOUNT_READY", "Evaluation account ready", "ready_flag"),
    InputSpec("backup", "backup_target", "ZHIXING_BACKUP_TARGET", "Backup target"),
    InputSpec("backup", "backup_dir", "ZHIXING_BACKUP_DIR", "Backup command directory", "backup_dir"),
    InputSpec("backup", "backup_retention", "ZHIXING_BACKUP_RETENTION", "Backup retention"),
    InputSpec("backup", "rag_restore_strategy", "ZHIXING_RAG_RESTORE_STRATEGY", "RAG restore strategy"),
    InputSpec("ops", "monitoring_provider", "ZHIXING_MONITORING_PROVIDER", "Monitoring provider"),
    InputSpec("ops", "alert_channel", "ZHIXING_ALERT_CHANNEL", "Alert channel"),
    InputSpec("ops", "daily_cost_budget", "ZHIXING_DAILY_COST_BUDGET", "Daily cost budget", "cost_budget"),
    InputSpec("ownership", "rollback_owner", "ZHIXING_ROLLBACK_OWNER", "Rollback owner"),
    InputSpec("ownership", "incident_owner", "ZHIXING_INCIDENT_OWNER", "Incident owner"),
)


def _normalized(value: str | None) -> str:
    return str(value or "").strip()


def _input_file_source(path: Path) -> str:
    return f"input_json:{path.name}"


def _is_forbidden_input_file(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_INPUT_FILE_PARTS)


def _example_for(spec: InputSpec) -> str:
    examples = {
        "ZHIXING_M1_AUDIENCE": "internal testers",
        "ZHIXING_REAL_PAYMENT_ORDER_DISABLED": "true",
        "ZHIXING_PUBLIC_BASE_URL": "https://m1.example.net",
        "ZHIXING_EVAL_BASE_URL": "https://m1.example.net",
        "ZHIXING_SERVER_PROVIDER": "cloud provider",
        "ZHIXING_SERVER_OS_VERSION": "Ubuntu 24.04",
        "ZHIXING_SERVER_CPU_RAM_DISK": "4 vCPU / 16 GB RAM / 160 GB SSD",
        "ZHIXING_DOMAIN_READY": "ready",
        "ZHIXING_SERVER_EGRESS_IP_STATUS": "fixed",
        "ZHIXING_DEPLOY_MODE": "Docker Compose",
        "ZHIXING_POSTGRES_MODE": "managed PostgreSQL",
        "ZHIXING_REDIS_MODE": "managed Redis",
        "ZHIXING_SECRET_STORE": "server .env / cloud secret manager",
        "ZHIXING_SECRET_OWNER": "deployment owner",
        "ZHIXING_SECRET_ROTATION_CADENCE": "90 days",
        "ZHIXING_LLM_PROVIDER_READY": "ready",
        "ZHIXING_MAP_API_READY": "ready",
        "ZHIXING_OPTIONAL_EXTERNAL_APIS": "none",
        "ZHIXING_DATA_SCOPE": "public docs and desensitized route templates",
        "ZHIXING_ACCEPTANCE_WINDOW": "2026-07-01 20:00-22:00",
        "ZHIXING_EVAL_ACCOUNT_READY": "ready",
        "ZHIXING_BACKUP_TARGET": "encrypted object storage",
        "ZHIXING_BACKUP_DIR": "/var/backups/zhixing",
        "ZHIXING_BACKUP_RETENTION": "7 daily backups and 3 release backups",
        "ZHIXING_RAG_RESTORE_STRATEGY": "rebuild from curated documents",
        "ZHIXING_MONITORING_PROVIDER": "cloud monitoring",
        "ZHIXING_ALERT_CHANNEL": "ops email",
        "ZHIXING_DAILY_COST_BUDGET": "200 CNY per day",
        "ZHIXING_ROLLBACK_OWNER": "release owner",
        "ZHIXING_INCIDENT_OWNER": "incident owner",
    }
    return examples.get(spec.env_var, "")


def build_m1_launch_inputs_template() -> dict[str, Any]:
    """Build a non-secret JSON template that can be filled outside Git."""

    return {
        "version": M1_LAUNCH_INPUTS_TEMPLATE_VERSION,
        "policy": {
            "non_secret_only": True,
            "do_not_put_real_secrets_here": True,
            "safe_blank_template_to_commit": True,
            "filled_file_may_contain_local_deployment_details": True,
        },
        "instructions": [
            "Fill value fields with non-secret M1 deployment declarations only.",
            "Do not write API keys, passwords, tokens, cookies, private keys, customer data, or supplier private data.",
            "Keep a filled file outside Git if it contains server coordinates, personal owners, or internal operations details.",
            "Validate it with: uv run python scripts/check_m1_launch_inputs.py --input-json <filled-file> --json",
        ],
        "inputs": [
            {
                "category": spec.category,
                "key": spec.key,
                "env_var": spec.env_var,
                "label": spec.label,
                "required": spec.required,
                "validator": spec.validator,
                "value": "",
                "example": _example_for(spec),
                "notes": "",
            }
            for spec in M1_INPUT_SPECS
        ],
    }


def _extract_values_from_inputs(payload: Mapping[str, Any]) -> dict[str, str]:
    raw_inputs = payload.get("inputs", payload.get("values", {}))
    values: dict[str, str] = {}
    if isinstance(raw_inputs, Mapping):
        for key, value in raw_inputs.items():
            values[str(key)] = _normalized(value)
        return values
    if isinstance(raw_inputs, list):
        for index, item in enumerate(raw_inputs):
            if not isinstance(item, Mapping):
                raise ValueError(f"Input item {index} must be an object.")
            env_var = _normalized(item.get("env_var"))
            key = _normalized(item.get("key"))
            lookup = env_var or key
            if not lookup:
                raise ValueError(f"Input item {index} must include env_var or key.")
            values[lookup] = _normalized(item.get("value"))
        return values
    raise ValueError("M1 launch input JSON must contain an inputs object/list or values object.")


def load_m1_launch_input_values(path: Path) -> dict[str, str]:
    """Load a non-secret M1 launch input JSON file without echoing values."""

    if _is_forbidden_input_file(path):
        raise ValueError("Refusing to read a forbidden M1 launch input file path.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read M1 launch input JSON.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("M1 launch input JSON must be an object.")
    return _extract_values_from_inputs(payload)


def _value_for_spec(source: Mapping[str, str], spec: InputSpec) -> str:
    return _normalized(source.get(spec.env_var) or source.get(spec.key))


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in PLACEHOLDER_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _result(
    spec: InputSpec,
    *,
    status: str,
    finding: str,
    present: bool,
    action: str | None = None,
) -> dict[str, Any]:
    return {
        "category": spec.category,
        "key": spec.key,
        "env_var": spec.env_var,
        "label": spec.label,
        "required": spec.required,
        "status": status,
        "present": present,
        "value_echoed": False,
        "finding": finding,
        "action": action
        or f"Set {spec.env_var} in the deployment environment and keep the real value outside Git.",
    }


def _present_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    if not value:
        return _result(spec, status="blocked", finding="Missing required launch input.", present=False)
    if _looks_like_placeholder(value):
        return _result(spec, status="blocked", finding="Launch input still looks like a placeholder.", present=True)
    return _result(spec, status="passed", finding="Configured.", present=True)


def _true_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    if not value:
        return _result(spec, status="blocked", finding="Missing required true/confirmed flag.", present=False)
    lowered = value.lower()
    if lowered in TRUTHY:
        return _result(spec, status="passed", finding="Confirmed.", present=True)
    if lowered in FALSEY:
        return _result(
            spec,
            status="blocked",
            finding="M1 must keep real payment, booking, price lock, and ticketing disabled.",
            present=True,
        )
    if _looks_like_placeholder(value):
        return _result(spec, status="blocked", finding="Launch flag still looks like a placeholder.", present=True)
    return _result(spec, status="blocked", finding="Expected an explicit true/yes/disabled confirmation.", present=True)


def _ready_flag_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    if not value:
        return _result(spec, status="blocked", finding="Missing required readiness flag.", present=False)
    lowered = value.lower()
    if lowered in TRUTHY or lowered == "ready":
        return _result(spec, status="passed", finding="Ready flag confirmed.", present=True)
    if lowered in FALSEY or lowered in {"not_ready", "blocked"}:
        return _result(spec, status="blocked", finding="Required readiness flag is not confirmed.", present=True)
    if _looks_like_placeholder(value):
        return _result(spec, status="blocked", finding="Readiness flag still looks like a placeholder.", present=True)
    return _result(spec, status="blocked", finding="Expected ready/true/yes for this M1 gate.", present=True)


def _declared_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    if not value:
        return _result(spec, status="blocked", finding="Missing required declaration.", present=False)
    if _looks_like_placeholder(value):
        return _result(spec, status="blocked", finding="Declaration still looks like a placeholder.", present=True)
    return _result(spec, status="passed", finding="Declared.", present=True)


def _declared_allow_none_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    if not value:
        return _result(spec, status="blocked", finding="Missing required declaration; use none if intentionally disabled.", present=False)
    lowered = value.lower()
    if lowered == "none":
        return _result(spec, status="passed", finding="Explicitly declared as none.", present=True)
    if _looks_like_placeholder(value):
        return _result(spec, status="blocked", finding="Declaration still looks like a placeholder.", present=True)
    return _result(spec, status="passed", finding="Declared.", present=True)


def _public_url_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    base = _present_validator(spec, value)
    if base["status"] != "passed":
        return base
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _result(spec, status="blocked", finding="Expected a full http(s) URL.", present=True)
    host = (parsed.hostname or "").lower()
    if host in LOCAL_HOSTS:
        return _result(spec, status="blocked", finding="M1 requires a non-localhost target URL.", present=True)
    if host.endswith(".example.com") or host == "example.com":
        return _result(spec, status="blocked", finding="Target URL still looks like an example domain.", present=True)
    return _result(spec, status="passed", finding="Non-local target URL is declared.", present=True)


def _backup_dir_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    base = _present_validator(spec, value)
    if base["status"] != "passed":
        return base
    normalized = value.replace("\\", "/").strip()
    lowered = normalized.lower()
    if lowered in DEFAULT_BACKUP_DIRS or lowered.startswith("./") or lowered.startswith("../"):
        return _result(spec, status="blocked", finding="M1 backup directory must not use the committed local default.", present=True)
    if not (normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized)):
        return _result(spec, status="blocked", finding="Expected an absolute backup directory path.", present=True)
    return _result(spec, status="passed", finding="Absolute backup directory is declared.", present=True)


def _cost_budget_validator(spec: InputSpec, value: str) -> dict[str, Any]:
    base = _present_validator(spec, value)
    if base["status"] != "passed":
        return base
    if not any(char.isdigit() for char in value):
        return _result(spec, status="blocked", finding="Daily cost budget must include an explicit numeric limit.", present=True)
    return _result(spec, status="passed", finding="Daily cost budget is declared.", present=True)


VALIDATORS: dict[str, Callable[[InputSpec, str], dict[str, Any]]] = {
    "present": _present_validator,
    "true": _true_validator,
    "ready_flag": _ready_flag_validator,
    "declared": _declared_validator,
    "declared_allow_none": _declared_allow_none_validator,
    "public_url": _public_url_validator,
    "backup_dir": _backup_dir_validator,
    "cost_budget": _cost_budget_validator,
}


def build_m1_launch_inputs_report(
    *,
    environ: Mapping[str, str] | None = None,
    input_values: Mapping[str, str] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Build a redacted M1 launch input report from env or a non-secret input map."""

    values = input_values if input_values is not None else environ if environ is not None else os.environ
    source_label = source or ("input_values" if input_values is not None else "process_environment")
    checks: list[dict[str, Any]] = []
    for spec in M1_INPUT_SPECS:
        validator = VALIDATORS[spec.validator]
        checks.append(validator(spec, _value_for_spec(values, spec)))

    blocked = [item for item in checks if item["status"] == "blocked"]
    degraded = [item for item in checks if item["status"] == "degraded"]
    status = "blocked" if blocked else "degraded" if degraded else "passed"
    category_statuses: dict[str, str] = {}
    for category in sorted({spec.category for spec in M1_INPUT_SPECS}):
        category_checks = [item for item in checks if item["category"] == category]
        if any(item["status"] == "blocked" for item in category_checks):
            category_statuses[category] = "blocked"
        elif any(item["status"] == "degraded" for item in category_checks):
            category_statuses[category] = "degraded"
        else:
            category_statuses[category] = "passed"

    return {
        "version": M1_LAUNCH_INPUTS_VERSION,
        "status": status,
        "source": source_label,
        "policy": {
            "reads_env_files": False,
            "reads_input_json": input_values is not None,
            "does_not_echo_values": True,
            "checks_non_secret_inputs_only": True,
        },
        "input_count": len(checks),
        "passed_count": sum(1 for item in checks if item["status"] == "passed"),
        "blocked_count": len(blocked),
        "degraded_count": len(degraded),
        "category_statuses": category_statuses,
        "missing_or_blocked_env_vars": [item["env_var"] for item in blocked],
        "checks": checks,
        "blocked_reasons": blocked,
        "repair_suggestions": [
            {
                "category": item["category"],
                "key": item["key"],
                "env_var": item["env_var"],
                "action": item["action"],
            }
            for item in blocked
        ],
        "not_proven_by_this_check": [
            "Real secrets are present and valid.",
            "The target server is reachable.",
            "PostgreSQL, Redis, RAG, and external APIs are healthy.",
            "Backups and restore drills have actually run.",
            "Acceptance smoke has passed against the target URL.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 Launch Inputs",
        f"- Overall: {report['status']}",
        f"- Source: {report.get('source', 'process_environment')}",
        "- Policy: reads_env_files=false, does_not_echo_values=true",
        f"- Passed: {report['passed_count']} / {report['input_count']}",
        "",
    ]
    category_statuses = report.get("category_statuses") or {}
    lines.append("## Categories")
    for category, status in category_statuses.items():
        lines.append(f"- {category}: {status}")
    lines.append("")
    if report.get("blocked_reasons"):
        lines.append("## Blocked")
        for item in report["blocked_reasons"]:
            lines.append(f"- {item['env_var']}: {item['finding']}")
        lines.append("")
    lines.append("## Boundary")
    for item in report.get("not_proven_by_this_check") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", action="store_true", help="Print a non-secret fillable JSON template.")
    parser.add_argument("--input-json", type=Path, default=None, help="Validate a filled non-secret input JSON file.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        payload = build_m1_launch_inputs_template()
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        exit_code = 0
    else:
        try:
            input_values = load_m1_launch_input_values(args.input_json) if args.input_json is not None else None
        except ValueError as exc:
            payload = {
                "version": M1_LAUNCH_INPUTS_VERSION,
                "status": "blocked",
                "source": _input_file_source(args.input_json) if args.input_json is not None else "input_json",
                "blocked_reasons": [
                    {
                        "key": "input_json",
                        "reason": str(exc),
                    }
                ],
                "policy": {
                    "reads_env_files": False,
                    "reads_input_json": True,
                    "does_not_echo_values": True,
                    "checks_non_secret_inputs_only": True,
                },
            }
            output = json.dumps(payload, ensure_ascii=False, indent=2) if args.json else _render_human(
                {
                    "status": "blocked",
                    "source": payload["source"],
                    "passed_count": 0,
                    "input_count": len(M1_INPUT_SPECS),
                    "category_statuses": {},
                    "blocked_reasons": payload["blocked_reasons"],
                    "not_proven_by_this_check": [
                        "The input JSON was accepted.",
                        "Real secrets are present and valid.",
                    ],
                }
            )
            exit_code = 2
        else:
            report = build_m1_launch_inputs_report(
                input_values=input_values,
                source=_input_file_source(args.input_json) if args.input_json is not None else "process_environment",
            )
            output = json.dumps(report, ensure_ascii=False, indent=2) if args.json else _render_human(report)
            exit_code = 2 if report["status"] == "blocked" else 0
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
