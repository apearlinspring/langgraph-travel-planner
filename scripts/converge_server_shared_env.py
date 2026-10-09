"""Converge a release-symlink server layout to shared/.env without echoing values.

Default mode is dry-run. Real copying requires ``--execute`` and the explicit
approval token. The remote script never prints env contents and refuses to
overwrite an existing shared env file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._remote_probe_helpers import (  # noqa: E402
    first_value as _first,
    parse_tabbed_probe_lines as _parse_probe_lines,
    run_utf8_command as _run_command,
)


SERVER_SHARED_ENV_CONVERGENCE_VERSION = "server_shared_env_convergence.v1"
APPROVAL_TOKEN = "APPROVE_SHARED_ENV_CONVERGENCE"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"


REMOTE_CONVERGE_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"
EXECUTE="$2"

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

if [ ! -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present false
  exit 0
fi
emit deploy_dir_present true
cd "$DEPLOY_DIR"

if [ -L current ]; then
  emit layout_mode release_symlink
elif [ -e current ]; then
  emit layout_mode blocked_current_not_symlink
elif [ -f docker-compose.yml ] || [ -d app ]; then
  emit layout_mode legacy_flat
else
  emit layout_mode empty_or_unknown
fi

test -f .env && emit root_env_present true || emit root_env_present false
test -f shared/.env && emit shared_env_present true || emit shared_env_present false
if [ -f .env ]; then
  root_mode="$(stat -c '%a' .env 2>/dev/null || true)"
  root_size="$(wc -c < .env 2>/dev/null | tr -d ' ' || true)"
  emit root_env_mode "$root_mode"
  emit root_env_size_present "$( [ "${root_size:-0}" -gt 0 ] && echo true || echo false )"
fi
if [ -f shared/.env ]; then
  shared_mode="$(stat -c '%a' shared/.env 2>/dev/null || true)"
  shared_size="$(wc -c < shared/.env 2>/dev/null | tr -d ' ' || true)"
  emit shared_env_mode "$shared_mode"
  emit shared_env_size_present "$( [ "${shared_size:-0}" -gt 0 ] && echo true || echo false )"
fi

if [ "$EXECUTE" != "1" ]; then
  emit action dry_run
  exit 0
fi

if [ ! -f .env ]; then
  emit action blocked_missing_root_env
  exit 0
fi
if [ -f shared/.env ]; then
  emit action skipped_shared_exists
  exit 0
fi

mkdir -p shared
umask 077
cp -p .env shared/.env.tmp
chmod 600 shared/.env.tmp
mv shared/.env.tmp shared/.env
emit action copied_root_to_shared
shared_mode="$(stat -c '%a' shared/.env 2>/dev/null || true)"
shared_size="$(wc -c < shared/.env 2>/dev/null | tr -d ' ' || true)"
emit shared_env_present_after true
emit shared_env_mode_after "$shared_mode"
emit shared_env_size_present_after "$( [ "${shared_size:-0}" -gt 0 ] && echo true || echo false )"
"""


def _mode_status(mode: str) -> str:
    if not mode:
        return "not_checked"
    try:
        numeric = int(mode, 8)
    except ValueError:
        return "unknown"
    return "passed" if numeric & 0o077 == 0 else "blocked"


def build_server_shared_env_convergence_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    execute: bool = False,
    approval_token: str = "",
    timeout_seconds: float = 90,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a dry-run or execution report for server shared env convergence."""

    report: dict[str, Any] = {
        "version": SERVER_SHARED_ENV_CONVERGENCE_VERSION,
        "status": "blocked",
        "mode": "execute" if execute else "dry_run",
        "policy": {
            "reads_env_values": False,
            "prints_env_values": False,
            "prints_secret_values": False,
            "prints_paths": False,
            "copies_env_file": bool(execute),
            "overwrites_existing_shared_env": False,
            "starts_services": False,
            "restarts_services": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "requires_execute_flag": True,
            "requires_approval_token": True,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "approval": {
            "execute_requested": bool(execute),
            "approval_token_accepted": bool(execute and approval_token == APPROVAL_TOKEN),
            "approval_token_echoed": False,
        },
        "not_proven_by_this_report": [
            "Secret values are valid with upstream providers.",
            "The shared env file has been used by a restarted compose stack.",
            "PostgreSQL, Redis, RAG, LLM, map, search, flight, or hotel providers are reachable.",
            "Future deployments will keep using shared/.env unless runbooks and commands are followed.",
        ],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [
            {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
        ]
        return report
    if execute and approval_token != APPROVAL_TOKEN:
        report["blocked_reasons"] = [
            {"key": "missing_approval", "finding": "Execution requires the explicit shared env convergence approval token."}
        ]
        return report

    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        ssh_target,
        "bash",
        "-s",
        "--",
        deploy_dir,
        "1" if execute else "0",
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_CONVERGE_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_probe_timeout", "finding": "SSH shared env convergence timed out."}]
        return report
    if completed.returncode != 0:
        report["blocked_reasons"] = [{"key": "ssh_probe_failed", "finding": "SSH shared env convergence failed."}]
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        return report

    parsed = _parse_probe_lines(completed.stdout)
    deploy_dir_present = _first(parsed, "deploy_dir_present") == "true"
    root_env_present = _first(parsed, "root_env_present") == "true"
    shared_env_present_before = _first(parsed, "shared_env_present") == "true"
    shared_env_present_after = _first(parsed, "shared_env_present_after") == "true"
    shared_env_present = shared_env_present_before or shared_env_present_after
    root_mode_status = _mode_status(_first(parsed, "root_env_mode"))
    shared_mode_status = _mode_status(_first(parsed, "shared_env_mode_after") or _first(parsed, "shared_env_mode"))
    action = _first(parsed, "action", "unknown")

    blocked_reasons: list[dict[str, Any]] = []
    degraded_reasons: list[dict[str, Any]] = []
    if not deploy_dir_present:
        blocked_reasons.append({"key": "deploy_dir_missing", "finding": "Deployment directory is missing."})
    if not root_env_present and not shared_env_present:
        blocked_reasons.append({"key": "env_missing", "finding": "Neither root .env nor shared .env exists on the target."})
    if root_mode_status == "blocked":
        degraded_reasons.append({"key": "root_env_permissions", "finding": "Root env file permissions are broader than owner-only."})
    if shared_mode_status == "blocked":
        blocked_reasons.append({"key": "shared_env_permissions", "finding": "Shared env file permissions are broader than owner-only."})
    if action == "blocked_missing_root_env":
        blocked_reasons.append({"key": "root_env_missing", "finding": "Root env file is required when shared env is missing and execution is requested."})

    if blocked_reasons:
        status = "blocked"
    elif shared_env_present:
        status = "passed" if not degraded_reasons else "degraded"
    elif root_env_present:
        status = "degraded"
        degraded_reasons.append({"key": "shared_env_missing", "finding": "Shared env is missing; run execute mode after approval to converge layout."})
    else:
        status = "blocked"

    report.update(
        {
            "status": status,
            "layout": {
                "deploy_dir_present": deploy_dir_present,
                "layout_mode": _first(parsed, "layout_mode"),
                "root_env_present": root_env_present,
                "shared_env_present": shared_env_present,
                "root_env_size_present": _first(parsed, "root_env_size_present") == "true",
                "shared_env_size_present": (
                    _first(parsed, "shared_env_size_present_after")
                    or _first(parsed, "shared_env_size_present")
                )
                == "true",
                "root_env_mode_status": root_mode_status,
                "shared_env_mode_status": shared_mode_status,
                "values_echoed": False,
                "paths_echoed": False,
            },
            "action": {
                "result": action,
                "dry_run": not execute,
                "copied": action == "copied_root_to_shared",
                "overwrote_existing_shared_env": False,
            },
            "blocked_reasons": blocked_reasons,
            "degraded_reasons": degraded_reasons,
        }
    )
    return report


def build_server_shared_env_convergence_markdown(report: Mapping[str, Any]) -> str:
    layout = report.get("layout") if isinstance(report.get("layout"), Mapping) else {}
    action = report.get("action") if isinstance(report.get("action"), Mapping) else {}
    lines = [
        "# Server Shared Env Convergence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Copies env file: `{(report.get('policy') or {}).get('copies_env_file')}`",
        f"- Starts services: `{(report.get('policy') or {}).get('starts_services')}`",
        f"- Action: `{action.get('result') or '-'}`",
        "",
        "## Layout",
        "",
        "| Check | Value |",
        "|---|---|",
        f"| Deploy dir present | `{layout.get('deploy_dir_present')}` |",
        f"| Layout mode | `{layout.get('layout_mode') or '-'}` |",
        f"| Root env present | `{layout.get('root_env_present')}` |",
        f"| Shared env present | `{layout.get('shared_env_present')}` |",
        f"| Root env permission | `{layout.get('root_env_mode_status') or '-'}` |",
        f"| Shared env permission | `{layout.get('shared_env_mode_status') or '-'}` |",
        "",
        "## Boundaries",
        "",
    ]
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _path_arg(value: str) -> Path:
    return Path(value)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--execute", action="store_true", help="Copy root .env to shared/.env if approved and missing.")
    parser.add_argument("--approval-token", default="", help="Required with --execute. Value is never echoed.")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_server_shared_env_convergence_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        execute=args.execute,
        approval_token=args.approval_token,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_server_shared_env_convergence_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
