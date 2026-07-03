"""Check a safe first-deployment dry run without SSH, SCP, .env reads or uploads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_public_release_boundary import build_public_release_boundary_report  # noqa: E402
from scripts.export_acceptance_evidence import redact_text  # noqa: E402


M1_FIRST_DEPLOY_DRY_RUN_VERSION = "m1_first_deploy_dry_run.v1"
PLACEHOLDER_PREFIXES = ("<", "${", "change-me", "example", "placeholder", "todo", "your-")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
TARGET_PLACEHOLDER = "<ssh-user>@<server-host>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
PUBLIC_URL_PLACEHOLDER = "<public-url>"


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _safe_payload(value: Any, *, env: Mapping[str, str]) -> Any:
    replacements = {
        _value(env, "ZHIXING_DEPLOY_USER"): "<ssh-user>",
        _value(env, "ZHIXING_DEPLOY_HOST"): "<server-host>",
        _value(env, "ZHIXING_DEPLOY_DIR"): DEPLOY_DIR_PLACEHOLDER,
        _value(env, "ZHIXING_PUBLIC_BASE_URL"): PUBLIC_URL_PLACEHOLDER,
    }

    def sanitize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): sanitize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        if isinstance(item, tuple):
            return [sanitize(child) for child in item]
        if isinstance(item, str):
            text = item
            for raw, placeholder in replacements.items():
                if raw:
                    text = text.replace(raw, placeholder)
            return redact_text(text)
        return item

    return sanitize(value)


def _target_input_check(
    *,
    key: str,
    env_var: str,
    value: str,
    label: str,
    validator: str = "present",
) -> dict[str, Any]:
    item = {
        "key": key,
        "env_var": env_var,
        "label": label,
        "status": "blocked",
        "value_echoed": False,
        "finding": "Missing deployment target input.",
    }
    if not value:
        return item
    if _looks_placeholder(value):
        item["finding"] = "Deployment target input still looks like a placeholder."
        return item
    if validator == "public_url":
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            item["finding"] = "Public URL must be a full HTTPS URL."
            return item
        if host in LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local"):
            item["finding"] = "Public URL must not point to localhost."
            return item
    elif validator == "absolute_path":
        normalized = value.replace("\\", "/")
        if not (normalized.startswith("/") or (len(normalized) > 2 and normalized[1:3] == ":/")):
            item["finding"] = "Deployment directory must be an absolute path."
            return item
    item.update({"status": "passed", "finding": "Declared."})
    return item


def _run_command(
    args: Sequence[str],
    *,
    timeout_seconds: float = 20,
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


def _first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return next((line.strip() for line in output.splitlines() if line.strip()), "")[:300]


def _tool_check(
    *,
    key: str,
    command: Sequence[str],
    command_runner: Any,
    presence_only: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "command": " ".join(command),
        "status": "blocked",
        "starts_services": False,
        "writes_files": False,
    }
    try:
        result = command_runner(command, timeout_seconds=20)
    except FileNotFoundError:
        item["finding"] = "Command is not available."
        return item
    except subprocess.TimeoutExpired:
        item["finding"] = "Command timed out."
        return item
    item["exit_code"] = int(result.returncode)
    if presence_only:
        item.update({"status": "passed", "finding": _first_output_line(result) or "Command is available."})
    elif result.returncode == 0:
        item.update({"status": "passed", "finding": _first_output_line(result) or "Command is available."})
    else:
        item["finding"] = _first_output_line(result) or f"Command exited {result.returncode}."
    return item


def build_local_tool_report(*, command_runner: Any = _run_command) -> dict[str, Any]:
    checks = [
        _tool_check(key="git", command=["git", "--version"], command_runner=command_runner),
        _tool_check(key="ssh", command=["ssh", "-V"], command_runner=command_runner),
        _tool_check(key="scp", command=["scp", "-V"], command_runner=command_runner, presence_only=True),
        _tool_check(key="docker", command=["docker", "--version"], command_runner=command_runner),
        _tool_check(key="docker_compose", command=["docker", "compose", "version"], command_runner=command_runner),
    ]
    status = "blocked" if any(item["status"] == "blocked" for item in checks) else "passed"
    return {"status": status, "checks": checks}


def build_git_worktree_report(*, command_runner: Any = _run_command) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "blocked",
        "command": "git status --short --branch",
        "branch": "unknown",
        "dirty_count": None,
        "path_echoed": False,
    }
    try:
        result = command_runner(["git", "status", "--short", "--branch"], timeout_seconds=20)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        report["finding"] = exc.__class__.__name__
        return report
    report["exit_code"] = int(result.returncode)
    if result.returncode != 0:
        report["finding"] = _first_output_line(result) or "git status failed."
        return report
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    report["branch"] = lines[0] if lines else "unknown"
    dirty_count = len([line for line in lines[1:] if line.strip()])
    report["dirty_count"] = dirty_count
    if dirty_count:
        report["finding"] = "Working tree has uncommitted changes; do not create a production release archive yet."
    else:
        report.update({"status": "passed", "finding": "Working tree is clean."})
    return report


def build_compose_dry_run_report(*, command_runner: Any = _run_command) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "blocked",
        "command": "docker compose --env-file .env.example config --quiet",
        "uses_env_file": ".env.example",
        "starts_services": False,
    }
    try:
        result = command_runner(
            ["docker", "compose", "--env-file", ".env.example", "config", "--quiet"],
            timeout_seconds=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        report["finding"] = exc.__class__.__name__
        return report
    report["exit_code"] = int(result.returncode)
    if result.returncode == 0:
        report.update({"status": "passed", "finding": "Docker Compose config renders with .env.example."})
    else:
        report["finding"] = _first_output_line(result) or "Docker Compose config failed."
    return report


def _command_plan() -> list[dict[str, Any]]:
    return [
        {
            "key": "local_gate",
            "command": "run compileall, tests, public boundary, resource request, deployment gate and go/no-go plan",
            "runs_where": "local",
        },
        {
            "key": "release_archive",
            "command": "python scripts/build_release_artifact.py --execute --output-dir <release-output-dir> --json",
            "runs_where": "local",
            "writes_release_archive": True,
        },
        {
            "key": "upload_archive",
            "command": f"scp <temp-release-archive> {TARGET_PLACEHOLDER}:/tmp/<release-archive>",
            "runs_where": "local to server",
            "requires_manual_approval": True,
        },
        {
            "key": "upload_first_deploy_script",
            "command": f"scp deploy/first-deploy.sh {TARGET_PLACEHOLDER}:/tmp/zhixing-first-deploy.sh",
            "runs_where": "local to server",
            "requires_manual_approval": True,
        },
        {
            "key": "remote_first_deploy_dry_run",
            "command": f"ssh {TARGET_PLACEHOLDER} \"sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir {DEPLOY_DIR_PLACEHOLDER}\"",
            "runs_where": "server",
            "requires_manual_approval": True,
        },
        {
            "key": "remote_first_deploy_execute",
            "command": f"ssh {TARGET_PLACEHOLDER} \"sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir {DEPLOY_DIR_PLACEHOLDER}\"",
            "runs_where": "server",
            "requires_manual_approval": True,
            "starts_services": True,
        },
        {
            "key": "remote_readiness",
            "command": "run server preflight, runtime readiness, backup, monitoring, incident and go/no-go evidence on target",
            "runs_where": "server",
        },
    ]


def _collect_blockers(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for section_name, section in sections.items():
        if section.get("status") != "blocked":
            continue
        for item in section.get("checks") or []:
            if isinstance(item, Mapping) and item.get("status") == "blocked":
                blockers.append({**dict(item), "section": section_name})
        if not any(item.get("section") == section_name for item in blockers):
            blockers.append(
                {
                    "section": section_name,
                    "key": section_name,
                    "status": "blocked",
                    "finding": section.get("finding") or "Section is blocked.",
                    "value_echoed": False,
                }
            )
    return blockers


def build_m1_first_deploy_dry_run_report(
    *,
    environ: Mapping[str, str] | None = None,
    check_local_tools: bool = True,
    check_git_worktree: bool = True,
    check_compose_config: bool = True,
    check_public_boundary: bool = True,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a safe first-deployment dry-run report."""

    env = environ if environ is not None else os.environ
    target_checks = [
        _target_input_check(
            key="deploy_user",
            env_var="ZHIXING_DEPLOY_USER",
            value=_value(env, "ZHIXING_DEPLOY_USER"),
            label="SSH deploy user",
        ),
        _target_input_check(
            key="deploy_host",
            env_var="ZHIXING_DEPLOY_HOST",
            value=_value(env, "ZHIXING_DEPLOY_HOST"),
            label="SSH deploy host",
        ),
        _target_input_check(
            key="deploy_dir",
            env_var="ZHIXING_DEPLOY_DIR",
            value=_value(env, "ZHIXING_DEPLOY_DIR"),
            label="Deployment directory",
            validator="absolute_path",
        ),
        _target_input_check(
            key="public_base_url",
            env_var="ZHIXING_PUBLIC_BASE_URL",
            value=_value(env, "ZHIXING_PUBLIC_BASE_URL"),
            label="Public base URL",
            validator="public_url",
        ),
    ]
    target_inputs = {
        "status": "blocked" if any(item["status"] == "blocked" for item in target_checks) else "passed",
        "checks": target_checks,
    }
    sections: dict[str, dict[str, Any]] = {"target_inputs": target_inputs}

    if check_local_tools:
        sections["local_tools"] = build_local_tool_report(command_runner=command_runner)
    else:
        sections["local_tools"] = {"status": "not_checked", "checked": False}

    if check_git_worktree:
        sections["git_worktree"] = build_git_worktree_report(command_runner=command_runner)
    else:
        sections["git_worktree"] = {"status": "not_checked", "checked": False}

    if check_compose_config:
        sections["compose_config"] = build_compose_dry_run_report(command_runner=command_runner)
    else:
        sections["compose_config"] = {"status": "not_checked", "checked": False}

    if check_public_boundary:
        sections["public_release_boundary"] = build_public_release_boundary_report()
    else:
        sections["public_release_boundary"] = {"status": "not_checked", "checked": False}

    statuses = [str(section.get("status") or "unknown") for section in sections.values()]
    if any(status == "blocked" for status in statuses):
        status = "blocked"
    elif any(status in {"not_checked", "unknown"} for status in statuses):
        status = "degraded"
    else:
        status = "passed"

    report = {
        "version": M1_FIRST_DEPLOY_DRY_RUN_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "uploads_files": False,
            "writes_release_archive": False,
            "starts_services": False,
            "does_not_echo_values": True,
            "safe_to_run_locally": True,
        },
        "section_statuses": {
            name: str(section.get("status") or "unknown")
            for name, section in sections.items()
        },
        "blockers": _collect_blockers(sections),
        "sections": sections,
        "command_plan": _command_plan(),
        "not_proven_by_this_dry_run": [
            "SSH authentication works.",
            "The archive has been uploaded or extracted on the server.",
            "Server .env or secret manager contains real valid values.",
            "Docker services have started on the target server.",
            "Database migrations, RAG initialization, backups, alerts or acceptance smoke have run.",
            "The system can process real payment, booking, price lock, ticketing or fulfillment.",
        ],
    }
    return _safe_payload(report, env=env)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_m1_first_deploy_dry_run_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 First Deploy Dry Run（首次部署预演）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Reads `.env` | `{_markdown_cell((report.get('policy') or {}).get('reads_dotenv'))}` |",
        f"| Connects SSH | `{_markdown_cell((report.get('policy') or {}).get('connects_ssh'))}` |",
        f"| Uploads files | `{_markdown_cell((report.get('policy') or {}).get('uploads_files'))}` |",
        "",
        "## Section 状态",
        "",
        "| Section | Status |",
        "|---|---|",
    ]
    for name, status in (report.get("section_statuses") or {}).items():
        lines.append(f"| {_markdown_cell(name)} | {_markdown_cell(status)} |")

    lines.extend(["", "## Blockers", "", "| Section | Key | Finding |", "|---|---|---|"])
    blockers = report.get("blockers") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('section'))} | "
                f"{_markdown_cell(item.get('env_var') or item.get('key'))} | "
                f"{_markdown_cell(item.get('finding'))} |"
            )
    else:
        lines.append("| - | - | - |")

    lines.extend(["", "## 命令计划", "", "| Key | Command | Runs where |", "|---|---|---|"])
    for item in report.get("command_plan") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"`{_markdown_cell(item.get('command'))}` | "
            f"{_markdown_cell(item.get('runs_where'))} |"
        )

    lines.extend(["", "## 边界", ""])
    for item in report.get("not_proven_by_this_dry_run") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    parser.add_argument("--skip-local-tools", action="store_true", help="Skip local git/ssh/scp/docker command checks.")
    parser.add_argument("--skip-git-worktree", action="store_true", help="Skip git dirty-worktree check.")
    parser.add_argument("--skip-compose-config", action="store_true", help="Skip Docker Compose .env.example config check.")
    parser.add_argument("--skip-public-boundary", action="store_true", help="Skip public release boundary scan.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_first_deploy_dry_run_report(
        check_local_tools=not args.skip_local_tools,
        check_git_worktree=not args.skip_git_worktree,
        check_compose_config=not args.skip_compose_config,
        check_public_boundary=not args.skip_public_boundary,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_m1_first_deploy_dry_run_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(output_text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
