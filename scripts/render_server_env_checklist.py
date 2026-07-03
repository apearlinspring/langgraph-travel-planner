"""Render a redacted server environment checklist for M1 deployment.

This script uses only public variable names from .env.example and existing
deployment specs. It never reads .env, never asks operators to paste secret
values into Git, and never echoes values from the current process environment.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_launch_inputs import M1_INPUT_SPECS  # noqa: E402
from scripts.export_acceptance_evidence import redact_text  # noqa: E402
from scripts.render_m1_resource_request import (  # noqa: E402
    RUNTIME_CONFIG_VARS,
    SECRET_INPUTS,
)


SERVER_ENV_CHECKLIST_VERSION = "server_env_checklist.v1"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
ENV_ASSIGNMENT_PATTERN = re.compile(r"^(?P<key>[A-Z0-9_]+)\s*=")

M1_REQUIRED_SECRET_VARS = {
    "DASHSCOPE_API_KEY",
    "JWT_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "AMAP_API_KEY",
}
OPTIONAL_SECRET_VARS = {
    "AMAP_WEB_JS_KEY",
    "TAVILY_API_KEY",
    "VARIFLIGHT_API_KEY",
    "AIGOHOTEL_API_KEY",
    "AIGOHOTEL_SECRET_KEY",
    "LANGSMITH_API_KEY",
    "REDIS_PASSWORD",
}
ACCEPTANCE_SECRET_VARS = {
    "EVAL_USERNAME",
    "EVAL_PASSWORD",
    "ZHIXING_EVAL_USERNAME",
    "ZHIXING_EVAL_PASSWORD",
}
SERVER_RUNTIME_VARS = {
    "APP_ENV",
    "DEBUG",
    "SQL_ECHO",
    "ZHIXING_SITE_ADDRESS",
    "ZHIXING_PUBLIC_BASE_URL",
    "ZHIXING_EVAL_BASE_URL",
    "ZHIXING_DEPLOY_DIR",
    "ZHIXING_SHARED_DATA_DIR",
    "ZHIXING_SHARED_LOG_DIR",
    "ZHIXING_SHARED_BACKUP_DIR",
    "RAG_VECTORSTORE_PATH",
    "RAG_INTERNAL_VECTORSTORE_PATH",
    "CORS_ALLOWED_ORIGINS",
    "AUTH_COOKIE_SECURE",
    "AUTH_COOKIE_SAMESITE",
}


def _parse_env_example_keys(path: Path = ENV_EXAMPLE_PATH) -> list[str]:
    """Return variable names from .env.example without returning values."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    keys: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_ASSIGNMENT_PATTERN.match(line)
        if match:
            keys.append(match.group("key"))
    return list(dict.fromkeys(keys))


def _secret_required_label(env_var: str) -> str:
    for item in SECRET_INPUTS:
        if item["env_var"] == env_var:
            return item["required"]
    if env_var in M1_REQUIRED_SECRET_VARS:
        return "M1 required"
    if env_var in ACCEPTANCE_SECRET_VARS:
        return "acceptance only"
    return "optional"


def _secret_purpose(env_var: str) -> str:
    for item in SECRET_INPUTS:
        if item["env_var"] == env_var:
            return item["purpose"]
    return "Runtime secret or credential."


def _non_secret_input_vars() -> set[str]:
    return {spec.env_var for spec in M1_INPUT_SPECS}


def _runtime_config_purpose(env_var: str) -> str:
    for item in RUNTIME_CONFIG_VARS:
        if item["env_var"] == env_var:
            return item["purpose"]
    if env_var.startswith("ZHIXING_"):
        return "M1 deployment declaration or operations status."
    if env_var.startswith("POSTGRES_"):
        return "PostgreSQL connection or runtime setting."
    if env_var.startswith("REDIS_"):
        return "Redis connection or runtime setting."
    if env_var.startswith("RAG_"):
        return "RAG runtime path, collection, or extraction setting."
    return "Application runtime configuration."


def _category_for(env_var: str) -> str:
    if env_var in M1_REQUIRED_SECRET_VARS:
        return "required_secret"
    if env_var in OPTIONAL_SECRET_VARS:
        return "optional_secret"
    if env_var in ACCEPTANCE_SECRET_VARS:
        return "acceptance_secret"
    if env_var in _non_secret_input_vars():
        return "m1_non_secret"
    if env_var in SERVER_RUNTIME_VARS:
        return "server_runtime"
    if env_var.startswith("ZHIXING_"):
        return "operations_declaration"
    if env_var.startswith(("POSTGRES_", "REDIS_")):
        return "runtime_service"
    if env_var.startswith(("QWEN_", "LANGSMITH_", "SESSION_", "AUTH_", "CORS_", "RAG_")):
        return "runtime_config"
    return "other_runtime"


def _is_secret(env_var: str) -> bool:
    return (
        env_var in M1_REQUIRED_SECRET_VARS
        or env_var in OPTIONAL_SECRET_VARS
        or env_var in ACCEPTANCE_SECRET_VARS
        or env_var.endswith("_PASSWORD")
        or env_var.endswith("_API_KEY")
        or env_var.endswith("_SECRET_KEY")
    )


def _required_for_m1(env_var: str) -> bool:
    if env_var in M1_REQUIRED_SECRET_VARS or env_var in _non_secret_input_vars():
        return True
    if env_var in {
        "APP_ENV",
        "ZHIXING_PUBLIC_BASE_URL",
        "ZHIXING_EVAL_BASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "REDIS_HOST",
        "REDIS_PORT",
        "RAG_VECTORSTORE_PATH",
        "RAG_INTERNAL_VECTORSTORE_PATH",
    }:
        return True
    return False


def _delivery_for(env_var: str) -> str:
    if _is_secret(env_var):
        return "secret manager, CI secrets, or server shared .env only"
    return "server shared .env or deployment environment"


def _placeholder_for(env_var: str) -> str:
    if _is_secret(env_var):
        return "<set-in-secret-store>"
    if env_var == "APP_ENV":
        return "staging"
    if env_var == "DEBUG":
        return "false"
    if env_var == "AUTH_COOKIE_SECURE":
        return "true"
    if env_var == "ZHIXING_REAL_PAYMENT_ORDER_DISABLED":
        return "true"
    if env_var.endswith("_READY") or env_var.endswith("_STATUS"):
        return "<ready|blocked|not_measured>"
    if env_var.endswith("_URL") or env_var.endswith("_BASE_URL"):
        return "https://<your-domain>"
    if env_var.endswith("_DIR") or env_var.endswith("_PATH"):
        return "/opt/zhixing/shared/<path>"
    return "<set-on-server>"


def _env_var_record(env_var: str) -> dict[str, Any]:
    secret = _is_secret(env_var)
    return {
        "env_var": env_var,
        "category": _category_for(env_var),
        "required_for_m1": _required_for_m1(env_var),
        "secret": secret,
        "required_label": _secret_required_label(env_var) if secret else ("M1 required" if _required_for_m1(env_var) else "optional"),
        "purpose": _secret_purpose(env_var) if secret else _runtime_config_purpose(env_var),
        "delivery": _delivery_for(env_var),
        "placeholder": _placeholder_for(env_var),
        "value_echoed": False,
    }


def build_server_env_checklist_report(
    *,
    env_example_path: Path = ENV_EXAMPLE_PATH,
) -> dict[str, Any]:
    """Build a redacted server environment checklist."""

    env_keys = _parse_env_example_keys(env_example_path)
    required_named_keys = sorted(
        _non_secret_input_vars()
        | M1_REQUIRED_SECRET_VARS
        | {item["env_var"] for item in RUNTIME_CONFIG_VARS}
        | SERVER_RUNTIME_VARS
    )
    ordered_keys = list(dict.fromkeys([*env_keys, *required_named_keys]))
    records = [_env_var_record(key) for key in ordered_keys]
    category_counts: dict[str, int] = {}
    for item in records:
        category = item["category"]
        category_counts[category] = category_counts.get(category, 0) + 1
    required_missing_from_example = [
        key for key in required_named_keys if key not in set(env_keys)
    ]
    return {
        "version": SERVER_ENV_CHECKLIST_VERSION,
        "status": "ready_to_prepare_server_env",
        "target_file": "<deploy-dir>/shared/.env",
        "file_permission": "chmod 600 <deploy-dir>/shared/.env",
        "source": ".env.example variable names only",
        "policy": {
            "reads_dotenv": False,
            "reads_env_example": True,
            "reads_current_process_environment": False,
            "does_not_echo_values": True,
            "safe_to_commit": True,
            "requests_secret_values_in_chat_or_git": False,
        },
        "env_var_count": len(records),
        "required_for_m1_count": sum(1 for item in records if item["required_for_m1"]),
        "secret_count": sum(1 for item in records if item["secret"]),
        "category_counts": category_counts,
        "required_missing_from_env_example": required_missing_from_example,
        "env_vars": records,
        "server_steps": [
            "Create <deploy-dir>/shared/.env on the server or inject the same variables through the secret manager.",
            "Set APP_ENV=staging for M1 and keep real payment, booking, price lock, and ticketing disabled.",
            "Put real secret values only in the server environment, CI secrets, or a cloud secret manager.",
            "Run chmod 600 <deploy-dir>/shared/.env and keep it outside Git and release archives.",
            "Run check_server_env_file.py --env-file <deploy-dir>/shared/.env --json on the server or secret-safe shell.",
            "After deploy, run check_m1_launch_inputs.py, check_runtime_readiness.py, and check_m1_deployment_gate.py in the target environment.",
        ],
        "not_proven_by_this_checklist": [
            "The server exists or is reachable.",
            "The server shared .env file has been created.",
            "Real secrets are present or valid.",
            "PostgreSQL, Redis, RAG vector stores, LLM, map, search, flight, or hotel providers are healthy.",
            "Backups, restore drills, monitoring alerts, acceptance smoke, or go/no-go have passed.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_server_env_checklist_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Server Env Checklist（服务器环境变量清单）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Target file | `{_markdown_cell(report.get('target_file'))}` |",
        f"| File permission | `{_markdown_cell(report.get('file_permission'))}` |",
        f"| Env vars | `{_markdown_cell(report.get('env_var_count'))}` |",
        f"| Required for M1 | `{_markdown_cell(report.get('required_for_m1_count'))}` |",
        f"| Secret vars | `{_markdown_cell(report.get('secret_count'))}` |",
        "",
        "## Policy",
        "",
    ]
    policy = report.get("policy") if isinstance(report.get("policy"), Mapping) else {}
    for key, value in policy.items():
        lines.append(f"- `{_markdown_cell(key)}`: `{_markdown_cell(value)}`")

    lines.extend(["", "## Variables", "", "| Env Var | Category | M1 | Secret | Placeholder | Delivery |", "|---|---|---|---|---|---|"])
    for item in report.get("env_vars") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"{_markdown_cell(item.get('category'))} | "
            f"{_markdown_cell(item.get('required_for_m1'))} | "
            f"{_markdown_cell(item.get('secret'))} | "
            f"`{_markdown_cell(item.get('placeholder'))}` | "
            f"{_markdown_cell(item.get('delivery'))} |"
        )

    lines.extend(["", "## Server Steps", ""])
    for item in report.get("server_steps") or []:
        lines.append(f"- {_markdown_cell(item)}")
    lines.extend(["", "## Boundary", ""])
    for item in report.get("not_proven_by_this_checklist") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def build_server_env_template_text(report: Mapping[str, Any]) -> str:
    """Build a placeholder-only template for operators to fill on the server."""

    lines = [
        "# ZhiXing server .env template",
        "# Fill this on the server or in a secret manager. Do not commit real values.",
    ]
    for item in report.get("env_vars") or []:
        if not isinstance(item, Mapping):
            continue
        env_var = _markdown_cell(item.get("env_var"))
        placeholder = _markdown_cell(item.get("placeholder"))
        lines.append(f"{env_var}={placeholder}")
    return "\n".join(lines)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--template", action="store_true", help="Print placeholder-only .env template.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_server_env_checklist_report()
    if args.template:
        output_text = build_server_env_template_text(report)
    elif args.json and not args.markdown:
        output_text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        output_text = build_server_env_checklist_markdown(report)
    if args.output is None:
        print(output_text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
