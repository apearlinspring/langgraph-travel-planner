"""Check a server .env file without echoing any values.

This script is meant for the target server or a secret-safe operator shell. It
validates that required M1 variables are present and not obvious placeholders,
but it never prints values. By default it refuses to read the repository's local
.env files to avoid accidental local secret exposure.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_acceptance_evidence import redact_text  # noqa: E402
from scripts.render_server_env_checklist import build_server_env_checklist_report  # noqa: E402


SERVER_ENV_FILE_CHECK_VERSION = "server_env_file_check.v1"
ENV_ASSIGNMENT_PATTERN = re.compile(r"^(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")
LOCAL_FORBIDDEN_ENV_FILES = {
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / ".env.local",
    PROJECT_ROOT / ".env.production",
}
PLACEHOLDER_MARKERS = (
    "<",
    "change-me",
    "changeme",
    "dummy",
    "example",
    "placeholder",
    "test-key",
    "todo",
    "your-",
)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_forbidden_local_env(path: Path) -> bool:
    resolved = _resolved(path)
    return any(resolved == _resolved(item) for item in LOCAL_FORBIDDEN_ENV_FILES)


def _strip_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1].strip()
    return stripped


def _looks_like_placeholder(value: str) -> bool:
    normalized = _strip_value(value).lower()
    if not normalized:
        return True
    return any(normalized.startswith(marker) or marker in normalized for marker in PLACEHOLDER_MARKERS)


def _parse_env_file_flags(path: Path) -> dict[str, dict[str, Any]]:
    """Parse an env file into flags only; never return values."""

    flags: dict[str, dict[str, Any]] = {}
    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_ASSIGNMENT_PATTERN.match(line)
        if not match:
            continue
        key = match.group("key")
        value = match.group("value")
        item = flags.setdefault(
            key,
            {
                "present": True,
                "line_count": 0,
                "first_line": line_number,
                "empty": False,
                "placeholder": False,
            },
        )
        item["line_count"] += 1
        item["empty"] = bool(item["empty"]) or not _strip_value(value)
        item["placeholder"] = bool(item["placeholder"]) or _looks_like_placeholder(value)
    return flags


def _permission_status(path: Path) -> str:
    if os.name == "nt":
        return "not_checked_windows"
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return "unknown"
    return "passed" if mode & 0o077 == 0 else "blocked"


def _required_records() -> list[dict[str, Any]]:
    checklist = build_server_env_checklist_report()
    return [
        dict(item)
        for item in checklist.get("env_vars", [])
        if isinstance(item, Mapping) and item.get("required_for_m1")
    ]


def build_server_env_file_check_report(
    *,
    env_file: str | Path | None = None,
    allow_project_env: bool = False,
) -> dict[str, Any]:
    """Build a redacted server env file check report."""

    required_records = _required_records()
    base_report: dict[str, Any] = {
        "version": SERVER_ENV_FILE_CHECK_VERSION,
        "status": "blocked",
        "checked": False,
        "env_file_provided": env_file is not None,
        "env_file_path_echoed": False,
        "required_var_count": len(required_records),
        "checked_var_count": 0,
        "present_required_count": 0,
        "missing_required_vars": [],
        "empty_required_vars": [],
        "placeholder_required_vars": [],
        "duplicate_vars": [],
        "permission_status": "not_checked",
        "blocked_reasons": [],
        "policy": {
            "reads_dotenv_by_default": False,
            "refuses_project_root_env": not allow_project_env,
            "does_not_echo_values": True,
            "does_not_echo_env_file_path": True,
            "safe_to_commit": True,
        },
        "not_proven_by_this_check": [
            "Secret values are valid with upstream providers.",
            "PostgreSQL, Redis, RAG vector stores, LLM, map, search, flight, or hotel providers are reachable.",
            "The server has deployed the current release.",
            "Backups, monitoring alerts, smoke tests, or go/no-go have passed.",
        ],
    }
    if env_file is None:
        base_report["blocked_reasons"].append(
            {
                "key": "env_file_required",
                "reason": "Pass --env-file <deploy-dir>/shared/.env on the target server or secret-safe shell.",
            }
        )
        return base_report

    path = Path(env_file)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not allow_project_env and _is_forbidden_local_env(path):
        base_report["blocked_reasons"].append(
            {
                "key": "refused_project_env",
                "reason": "Refusing to read repository-local .env files; run this against the server shared env file.",
            }
        )
        return base_report
    if not path.exists():
        base_report["blocked_reasons"].append(
            {
                "key": "env_file_missing",
                "reason": "Env file does not exist at the provided path.",
            }
        )
        return base_report

    flags = _parse_env_file_flags(path)
    required_names = [str(item["env_var"]) for item in required_records]
    missing = [name for name in required_names if name not in flags]
    empty = [name for name in required_names if name in flags and flags[name]["empty"]]
    placeholder = [name for name in required_names if name in flags and flags[name]["placeholder"]]
    duplicates = sorted(name for name, item in flags.items() if int(item.get("line_count") or 0) > 1)
    permission_status = _permission_status(path)

    blocked_reasons: list[dict[str, Any]] = []
    for key, values, reason in (
        ("missing_required_vars", missing, "Required M1 variables are missing."),
        ("empty_required_vars", empty, "Required M1 variables are present but empty."),
        ("placeholder_required_vars", placeholder, "Required M1 variables still look like placeholders."),
        ("duplicate_vars", duplicates, "Variables are declared more than once."),
    ):
        if values:
            blocked_reasons.append({"key": key, "reason": reason, "env_vars": values})
    if permission_status == "blocked":
        blocked_reasons.append(
            {
                "key": "env_file_permissions",
                "reason": "Env file permissions are broader than owner-only; use chmod 600.",
            }
        )

    return {
        **base_report,
        "status": "blocked" if blocked_reasons else "passed",
        "checked": True,
        "checked_var_count": len(flags),
        "present_required_count": len(required_names) - len(missing),
        "missing_required_vars": missing,
        "empty_required_vars": empty,
        "placeholder_required_vars": placeholder,
        "duplicate_vars": duplicates,
        "permission_status": permission_status,
        "blocked_reasons": blocked_reasons,
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_server_env_file_check_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Server Env File Check（服务器环境文件校验）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Checked | `{_markdown_cell(report.get('checked'))}` |",
        f"| Required vars | `{_markdown_cell(report.get('required_var_count'))}` |",
        f"| Present required | `{_markdown_cell(report.get('present_required_count'))}` |",
        f"| Checked vars | `{_markdown_cell(report.get('checked_var_count'))}` |",
        f"| Permission status | `{_markdown_cell(report.get('permission_status'))}` |",
        "",
        "## Blockers",
        "",
        "| Key | Reason | Env Vars |",
        "|---|---|---|",
    ]
    blockers = report.get("blocked_reasons") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('key'))} | "
                f"{_markdown_cell(item.get('reason'))} | "
                f"{_markdown_cell(', '.join(item.get('env_vars') or []))} |"
            )
    else:
        lines.append("| - | - | - |")
    lines.extend(["", "## Boundary", ""])
    for item in report.get("not_proven_by_this_check") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=_path_arg, default=None, help="Server shared .env path to validate.")
    parser.add_argument("--allow-project-env", action="store_true", help="Allow checking repository-local .env files.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_server_env_file_check_report(
        env_file=args.env_file,
        allow_project_env=args.allow_project_env,
    )
    if args.json and not args.markdown:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(build_server_env_file_check_markdown(report))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
