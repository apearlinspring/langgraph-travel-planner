"""Check whether API rate limiting is inside the releasable Git scope.

The production deployment runbook builds release archives from Git HEAD. This
checker prevents a common false positive: the local worktree has rate-limit
code, but the official release archive would not contain it because files are
untracked or modified after the last commit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RATE_LIMIT_RELEASE_SCOPE_VERSION = "rate_limit_release_scope.v1"

REQUIRED_RELEASE_FILES: tuple[str, ...] = (
    ".env.example",
    "app/api/v1/mock_checkout.py",
    "app/config.py",
    "app/core/rate_limit.py",
    "app/main.py",
    "docker-compose.yml",
    "docs/部署与运行/deployment-readiness.md",
    "docs/部署与运行/postgres-redis-ops-runbook.md",
    "scripts/check_rate_limit_release_scope.py",
    "scripts/collect_m1_go_no_go_evidence.py",
    "scripts/collect_rate_limit_live_probe.py",
    "tests/test_api_rate_limit_middleware.py",
    "tests/test_m1_go_no_go_evidence.py",
    "tests/test_mock_checkout.py",
    "tests/test_rate_limit_live_probe.py",
    "tests/test_rate_limit_release_scope.py",
    "tests/test_script_entrypoints.py",
)

CONTRACT_MARKERS: tuple[dict[str, Any], ...] = (
    {
        "path": "app/core/rate_limit.py",
        "markers": [
            "ApiRateLimitMiddleware",
            "RedisFixedWindowRateLimitStore",
            "redis_unavailable",
            "Retry-After",
            "X-RateLimit-Limit",
        ],
    },
    {
        "path": "app/main.py",
        "markers": [
            "ApiRateLimitMiddleware",
            "settings.api_rate_limit_enabled",
            "settings.api_rate_limit_local_fallback",
        ],
    },
    {
        "path": "app/config.py",
        "markers": [
            "API_RATE_LIMIT_ENABLED",
            "API_RATE_LIMIT_BACKEND",
            "API_RATE_LIMIT_LOCAL_FALLBACK",
            "api_rate_limit_protected_prefixes",
        ],
    },
    {
        "path": "docker-compose.yml",
        "markers": [
            "API_RATE_LIMIT_ENABLED: ${API_RATE_LIMIT_ENABLED:-true}",
            "API_RATE_LIMIT_BACKEND: ${API_RATE_LIMIT_BACKEND:-redis}",
            "API_RATE_LIMIT_LOCAL_FALLBACK: ${API_RATE_LIMIT_LOCAL_FALLBACK:-false}",
        ],
    },
    {
        "path": "scripts/collect_rate_limit_live_probe.py",
        "markers": [
            "RATE_LIMIT_LIVE_PROBE_VERSION",
            "reads_response_body",
            "missing_429",
            "missing_limit_header",
        ],
    },
    {
        "path": "scripts/collect_m1_go_no_go_evidence.py",
        "markers": [
            "include_rate_limit_live_probe",
            "build_rate_limit_live_probe_report",
            "runs_rate_limit_live_probe",
        ],
    },
    {
        "path": "docs/部署与运行/deployment-readiness.md",
        "markers": ["collect_rate_limit_live_probe.py", "Retry-After"],
    },
    {
        "path": "docs/部署与运行/postgres-redis-ops-runbook.md",
        "markers": ["API_RATE_LIMIT_BACKEND=redis", "API_RATE_LIMIT_LOCAL_FALLBACK=false"],
    },
)


def _run_command(
    args: Sequence[str],
    *,
    repo_root: Path,
    timeout_seconds: float = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def _normalize_repo_path(path: str | Path) -> str:
    text = Path(str(path).replace("\\", "/")).as_posix()
    return text[2:] if text.startswith("./") else text


def _parse_git_status_short(output: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip() or line.startswith("##"):
            continue
        raw_status = line[:2] if len(line) >= 2 else line.strip()
        path_text = line[3:].strip() if len(line) > 3 else line[2:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        statuses[_normalize_repo_path(path_text)] = raw_status.strip() or raw_status
    return statuses


def _git_statuses(
    *,
    repo_root: Path,
    command_runner: Any,
) -> tuple[dict[str, str], str | None]:
    try:
        result = command_runner(
            ["git", "-c", "core.quotepath=false", "status", "--short", "--branch"],
            repo_root=repo_root,
            timeout_seconds=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {}, exc.__class__.__name__
    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        return {}, (output.splitlines()[0] if output else "git status failed")[:300]
    return _parse_git_status_short(result.stdout or ""), None


def _git_head_paths(
    *,
    repo_root: Path,
    command_runner: Any,
) -> tuple[set[str], str | None]:
    try:
        result = command_runner(
            ["git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD", "--"],
            repo_root=repo_root,
            timeout_seconds=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return set(), exc.__class__.__name__
    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        return set(), (output.splitlines()[0] if output else "git ls-tree failed")[:300]
    return {
        _normalize_repo_path(line)
        for line in (result.stdout or "").splitlines()
        if line.strip()
    }, None


def _default_command_runner(args: Sequence[str], *, repo_root: Path, timeout_seconds: float = 30):
    return _run_command(args, repo_root=repo_root, timeout_seconds=timeout_seconds)


def _read_text(repo_root: Path, relative_path: str) -> str | None:
    try:
        return (repo_root / relative_path).read_text(encoding="utf-8")
    except OSError:
        return None


def _contract_marker_findings(repo_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for item in CONTRACT_MARKERS:
        path = str(item["path"])
        text = _read_text(repo_root, path)
        if text is None:
            findings.append(
                {
                    "path": path,
                    "key": "missing_contract_file",
                    "finding": "Required contract file is missing on disk.",
                }
            )
            continue
        for marker in item["markers"]:
            if str(marker) not in text:
                findings.append(
                    {
                        "path": path,
                        "key": "missing_contract_marker",
                        "finding": str(marker),
                    }
                )
    return findings


def build_rate_limit_release_scope_report(
    *,
    repo_root: str | Path = PROJECT_ROOT,
    command_runner: Any = _default_command_runner,
) -> dict[str, Any]:
    """Build release-scope evidence for API rate limiting."""

    root = Path(repo_root).resolve()
    statuses, status_error = _git_statuses(repo_root=root, command_runner=command_runner)
    head_paths, head_error = _git_head_paths(repo_root=root, command_runner=command_runner)
    blocked_reasons: list[dict[str, Any]] = []
    if status_error:
        blocked_reasons.append({"key": "git_status", "finding": status_error})
    if head_error:
        blocked_reasons.append({"key": "git_head", "finding": head_error})

    file_reports: list[dict[str, Any]] = []
    for path in REQUIRED_RELEASE_FILES:
        normalized = _normalize_repo_path(path)
        exists_on_disk = (root / normalized).exists()
        in_git_head = normalized in head_paths
        worktree_status = statuses.get(normalized, "")
        file_status = "passed"
        reasons: list[dict[str, str]] = []
        if not exists_on_disk:
            file_status = "blocked"
            reasons.append({"key": "missing_on_disk", "finding": "Required file is missing locally."})
        if not in_git_head:
            file_status = "blocked"
            reasons.append(
                {
                    "key": "not_in_git_head",
                    "finding": "File would be absent from a git archive built from HEAD.",
                }
            )
        if worktree_status:
            file_status = "blocked"
            reasons.append(
                {
                    "key": "dirty_required_file",
                    "finding": f"Worktree status is {worktree_status}; HEAD does not match the local release scope.",
                }
            )
        file_reports.append(
            {
                "path": normalized,
                "status": file_status,
                "exists_on_disk": exists_on_disk,
                "in_git_head": in_git_head,
                "worktree_status": worktree_status or "clean",
                "reasons": reasons,
            }
        )
        for reason in reasons:
            blocked_reasons.append({"path": normalized, **reason})

    marker_findings = _contract_marker_findings(root)
    for finding in marker_findings:
        blocked_reasons.append(finding)

    status = "blocked" if blocked_reasons else "passed"
    return {
        "version": RATE_LIMIT_RELEASE_SCOPE_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "reads_runtime_data": False,
            "starts_services": False,
            "uses_git_head_as_release_source": True,
        },
        "required_files": file_reports,
        "contract_marker_findings": marker_findings,
        "blocked_reasons": blocked_reasons,
        "required_actions": [
            "Stage and commit the selected rate-limit files before building the production release archive.",
            "Rerun this checker and require status=passed before upload.",
            "Build the release archive from clean Git HEAD, then deploy using the production runbook.",
            "After deployment, rerun collect_rate_limit_live_probe.py and require at least one 429 plus X-RateLimit/Retry-After headers.",
        ],
        "next_commands": [
            "uv run python scripts/check_rate_limit_release_scope.py --json",
            "uv run python scripts/check_release_candidate_freeze.py --json",
            "uv run python scripts/build_release_artifact.py --json",
            "uv run python scripts/collect_rate_limit_live_probe.py --base-url <public-url> --request-count 130 --timeout-seconds 5 --json",
        ],
        "not_proven_by_this_report": [
            "The release archive has been built.",
            "The rate-limit code has been deployed to the server.",
            "The live service is returning HTTP 429.",
            "WAF, autoscaling, upstream provider quota protection, or long-duration load capacity.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ") or "-"


def build_rate_limit_release_scope_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# API Rate Limit Release Scope",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "",
        "| Path | Status | In HEAD | Worktree |",
        "|---|---|---:|---|",
    ]
    for item in report.get("required_files") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('path'))}` | "
            f"`{_markdown_cell(item.get('status'))}` | "
            f"`{_markdown_cell(item.get('in_git_head'))}` | "
            f"`{_markdown_cell(item.get('worktree_status'))}` |"
        )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                target = item.get("path") or item.get("key")
                key = item.get("key")
                finding = item.get("finding") or item.get("reason")
                lines.append(
                    f"- `{_markdown_cell(key)}` `{_markdown_cell(target)}`: "
                    f"{_markdown_cell(finding)}"
                )
    lines.extend(["", "## Required Actions", ""])
    for item in report.get("required_actions") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_rate_limit_release_scope_report()
    if args.json and not args.markdown:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(build_rate_limit_release_scope_markdown(report), end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
