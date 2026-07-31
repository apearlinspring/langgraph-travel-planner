"""Check whether the current Git worktree is frozen for a release candidate.

The report is intentionally conservative: a production release artifact must be
built from a clean Git HEAD. When the worktree is dirty, this script groups the
changed paths by review stream so the release owner can decide what belongs in
the current candidate and what should be deferred.
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RELEASE_CANDIDATE_FREEZE_VERSION = "release_candidate_freeze.v1"

FORBIDDEN_EXACT_PATHS = {
    ".env",
    ".env.local",
    ".env.production",
}
ALLOWED_ENV_EXAMPLE_PATHS = {
    ".env.example",
}
FORBIDDEN_PREFIXES = (
    ".env.",
    ".runtime/",
    ".venv/",
    "backups/",
    "data/vectorstore/",
    "data/vectorstore_internal/",
    "logs/",
)

WORKSTREAMS: tuple[dict[str, Any], ...] = (
    {
        "key": "deployment_runtime",
        "label": "Deployment and runtime",
        "owner": "Coordinator / Deployment",
        "exact": {
            ".env.example",
            ".gitignore",
            "Dockerfile",
            "docker-compose.yml",
            "deploy/Caddyfile",
            "deploy/Dockerfile.runtime",
            "deploy/first-deploy.sh",
            "deploy/update-runtime-image.sh",
        },
        "prefixes": (
            "deploy/",
            "docs/部署与运行/",
            "scripts/check_backup_restore_readiness.py",
            "scripts/check_external_api_readiness.py",
            "scripts/check_m1_",
            "scripts/check_monitoring_alerting_readiness.py",
            "scripts/check_production_image_build_",
            "scripts/check_public_release_boundary.py",
            "scripts/check_release_candidate_freeze.py",
            "scripts/check_runtime_readiness.py",
            "scripts/check_security_release_readiness.py",
            "scripts/check_server_preflight_readiness.py",
            "scripts/build_release_artifact.py",
            "scripts/collect_",
            "scripts/prepare_production_image_build_execution.py",
            "scripts/render_m1_",
            "tests/test_backup_restore",
            "tests/test_external_api_readiness.py",
            "tests/test_first_deploy_script_contract.py",
            "tests/test_incident_rollback",
            "tests/test_m1_",
            "tests/test_monitoring_alerting",
            "tests/test_production_image_build_",
            "tests/test_production_image_build_execution_preparer.py",
            "tests/test_public_release_boundary.py",
            "tests/test_release_artifact_builder.py",
            "tests/test_runtime_readiness.py",
            "tests/test_security_release_readiness.py",
            "tests/test_server_preflight_readiness.py",
        ),
        "validation_commands": [
            "uv run python scripts/check_release_candidate_freeze.py --json",
            "uv run python scripts/check_m1_deployment_gate.py --json",
            "uv run python scripts/build_release_artifact.py --json",
            "docker compose --env-file .env.example config --quiet",
        ],
    },
    {
        "key": "rag_evaluation",
        "label": "RAG and evaluation",
        "owner": "RAG / Evaluation",
        "exact": set(),
        "prefixes": (
            "app/rag/",
            "app/evaluation/",
            "data/documents/",
            "data/evaluation/",
            "docs/RAG与知识库/",
            "scripts/accept_rag_",
            "scripts/evaluate_rag_retrieval.py",
            "scripts/rag_transcribe_",
            "tests/test_rag",
            "tests/test_evaluation_",
            "tests/test_agent_metrics_evaluation.py",
            "tests/test_internal_rag_businessization.py",
        ),
        "validation_commands": [
            "uv run python scripts/evaluate_rag_retrieval.py --json",
            "uv run python -m pytest tests/test_rag_retrieval_evaluation.py tests/test_rag_retriever.py -q",
        ],
    },
    {
        "key": "agent_state_architecture",
        "label": "Agent state and architecture",
        "owner": "Agent State / Architecture",
        "exact": set(),
        "prefixes": (
            "app/core/",
            "app/agents/handoffs/",
            "docs/架构与流程/",
            "tests/test_step_prompt_rendering.py",
            "tests/test_workflow_maintainability.py",
        ),
        "validation_commands": [
            "uv run python -m pytest tests/test_step_prompt_rendering.py tests/test_workflow_maintainability.py -q",
        ],
    },
    {
        "key": "tool_security_governance",
        "label": "Tool security and governance",
        "owner": "Tool / Security",
        "exact": {
            "app/utils/security.py",
            "tests/test_tool_audit_governance.py",
        },
        "prefixes": (
            "app/mcp_core/",
            "app/tools/",
            "docs/治理与可观测/",
            "tests/test_mcp",
        ),
        "validation_commands": [
            "uv run python -m pytest tests/test_mcp_client_config_unit.py tests/test_tool_audit_governance.py -q",
            "uv run python scripts/check_security_release_readiness.py --json",
        ],
    },
    {
        "key": "report_frontend",
        "label": "Report delivery and frontend",
        "owner": "Report / Frontend",
        "exact": {
            "frontend/app.js",
            "frontend/report-renderer.js",
            "scripts/verify_frontend_browser_regression.js",
            "scripts/verify_frontend_report_renderer.js",
        },
        "prefixes": (
            "app/reports/",
            "docs/前端与演示/",
            "frontend/",
            "tests/test_report",
        ),
        "validation_commands": [
            "node --check frontend/app.js",
            "node scripts/verify_frontend_report_renderer.js",
            "node scripts/verify_frontend_browser_regression.js",
        ],
    },
    {
        "key": "business_api_runtime",
        "label": "Business API and runtime config",
        "owner": "Coordinator / Backend",
        "exact": {
            "app/config.py",
            "app/main.py",
            "main.py",
        },
        "prefixes": (
            "app/agency/",
            "app/api/",
            "app/journey/",
            "app/models/",
            "app/schemas/",
            "tests/test_api/",
            "tests/test_agency",
        ),
        "validation_commands": [
            "uv run python -m pytest tests/test_api tests/test_report_contract_module.py -q",
            "uv run python scripts/check_runtime_readiness.py --target production --json",
        ],
    },
    {
        "key": "configuration_dependencies",
        "label": "Configuration and dependencies",
        "owner": "Coordinator / Runtime",
        "exact": {
            "pyproject.toml",
            "requirements.txt",
            "requirements.runtime.txt",
            "uv.lock",
        },
        "prefixes": (
            ".github/",
            "alembic/",
        ),
        "validation_commands": [
            "uv sync --locked",
            "uv run python scripts/check_runtime_dependency_scope.py --json",
            "uv run python -m compileall app tests scripts",
        ],
    },
    {
        "key": "project_docs",
        "label": "Project documentation",
        "owner": "Coordinator / Docs",
        "exact": {
            "AGENTS.md",
            "README.md",
            "docs/README.md",
        },
        "prefixes": (
            "docs/项目总览/",
            "docs/评估与验收/",
        ),
        "validation_commands": [
            "uv run python scripts/check_public_release_boundary.py --json",
        ],
    },
    {
        "key": "test_validation",
        "label": "Tests and validation",
        "owner": "Coordinator / QA",
        "exact": set(),
        "prefixes": (
            "tests/",
            "scripts/",
        ),
        "validation_commands": [
            "uv run python -m pytest -q",
        ],
    },
)

DEFAULT_VALIDATION_COMMANDS = [
    "git diff --check",
    "uv run python -m compileall app tests scripts",
    "uv run python -m pytest -q",
]


def _run_command(
    args: Sequence[str],
    *,
    timeout_seconds: float = 30,
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


def _normalize_repo_path(path: str | Path) -> str:
    text = Path(str(path).replace("\\", "/")).as_posix()
    if text.startswith("./"):
        text = text[2:]
    return text


def _is_forbidden_release_path(path: str | Path) -> bool:
    relative = _normalize_repo_path(path)
    if relative in ALLOWED_ENV_EXAMPLE_PATHS:
        return False
    if relative in FORBIDDEN_EXACT_PATHS:
        return True
    return any(relative.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)


def parse_git_status_short(output: str) -> list[dict[str, str]]:
    """Parse `git status --short --branch` without touching file contents."""

    entries: list[dict[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip() or line.startswith("##"):
            continue
        raw_status = line[:2] if len(line) >= 2 else line.strip()
        path_text = line[3:].strip() if len(line) > 3 else line[2:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        entries.append(
            {
                "status": raw_status.strip() or raw_status,
                "raw_status": raw_status,
                "path": _normalize_repo_path(path_text),
            }
        )
    return entries


def _git_status_entries(*, command_runner: Any = _run_command) -> tuple[list[dict[str, str]], str, str | None]:
    try:
        result = command_runner(
            ["git", "-c", "core.quotepath=false", "status", "--short", "--branch"],
            timeout_seconds=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [], "unknown", exc.__class__.__name__
    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        return [], "unknown", (output.splitlines()[0] if output else "git status failed")[:300]
    branch_line = next(
        (line.strip() for line in (result.stdout or "").splitlines() if line.startswith("##")),
        "unknown",
    )
    return parse_git_status_short(result.stdout or ""), branch_line, None


def _matches_stream(path: str, stream: Mapping[str, Any]) -> bool:
    if path in stream.get("exact", set()):
        return True
    return any(path.startswith(prefix) for prefix in stream.get("prefixes", ()))


def _classify_path(path: str) -> str:
    for stream in WORKSTREAMS:
        if _matches_stream(path, stream):
            return str(stream["key"])
    return "unknown"


def _build_workstream_sections(entries: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    grouped: dict[str, list[dict[str, str]]] = {str(stream["key"]): [] for stream in WORKSTREAMS}
    unknown_paths: list[str] = []
    for entry in entries:
        path = str(entry.get("path") or "")
        key = _classify_path(path)
        if key == "unknown":
            unknown_paths.append(path)
            continue
        grouped[key].append({"path": path, "status": str(entry.get("status") or "")})

    sections: list[dict[str, Any]] = []
    for stream in WORKSTREAMS:
        key = str(stream["key"])
        paths = sorted(grouped[key], key=lambda item: item["path"])
        sections.append(
            {
                "key": key,
                "label": stream["label"],
                "owner": stream["owner"],
                "status": "review_required" if paths else "not_changed",
                "changed_count": len(paths),
                "paths": paths,
                "validation_commands": list(stream["validation_commands"]),
            }
        )
    return sections, sorted(unknown_paths)


def build_release_candidate_freeze_report(
    *,
    command_runner: Any = _run_command,
    check_public_closure: bool = False,
    public_closure_builder: Any | None = None,
) -> dict[str, Any]:
    """Build a conservative release freeze report."""

    entries, branch, error = _git_status_entries(command_runner=command_runner)
    if error:
        return {
            "version": RELEASE_CANDIDATE_FREEZE_VERSION,
            "status": "blocked",
            "freeze_state": "unknown",
            "branch": branch,
            "dirty_count": None,
            "policy": {
                "reads_dotenv": False,
                "reads_file_contents": False,
                "starts_services": False,
                "uses_git_status_only": True,
            },
            "blocked_reasons": [
                {
                    "key": "git_status",
                    "reason": error,
                }
            ],
            "workstreams": [],
            "unknown_paths": [],
            "forbidden_paths": [],
        }

    public_closure: dict[str, Any] = {"status": "not_checked", "checked": False}
    if check_public_closure:
        if public_closure_builder is None:
            from scripts.check_m1_public_release_closure import (  # noqa: PLC0415
                build_m1_public_release_closure_report,
            )

            public_closure_builder = build_m1_public_release_closure_report
        public_closure = dict(public_closure_builder())
        public_closure.setdefault("checked", True)

    workstreams, unknown_paths = _build_workstream_sections(entries)
    forbidden_paths = sorted(
        entry["path"] for entry in entries if _is_forbidden_release_path(entry["path"])
    )
    dirty_count = len(entries)
    blocked_reasons: list[dict[str, Any]] = []
    if dirty_count:
        blocked_reasons.append(
            {
                "key": "release_candidate_not_frozen",
                "reason": (
                    f"Working tree has {dirty_count} uncommitted changes; "
                    "production release artifacts must be built from a clean Git HEAD."
                ),
            }
        )
    for path in forbidden_paths:
        blocked_reasons.append(
            {
                "key": "forbidden_release_path",
                "path": path,
                "reason": "Forbidden local secret or runtime path appears in the release candidate worktree.",
            }
        )
    if unknown_paths:
        blocked_reasons.append(
            {
                "key": "unknown_path_review",
                "reason": "Some changed paths do not match an owned review stream and need manual routing.",
                "paths": unknown_paths,
            }
        )
    if check_public_closure and public_closure.get("status") != "passed":
        blocked_reasons.append(
            {
                "key": "public_release_closure",
                "reason": "M1 public release closure is not passed.",
                "status": public_closure.get("status"),
            }
        )

    status = "blocked" if blocked_reasons else "passed"
    return {
        "version": RELEASE_CANDIDATE_FREEZE_VERSION,
        "status": status,
        "freeze_state": "frozen" if status == "passed" else "not_frozen",
        "branch": branch,
        "dirty_count": dirty_count,
        "policy": {
            "reads_dotenv": False,
            "reads_file_contents": bool(check_public_closure),
            "starts_services": False,
            "uses_git_status_only": not check_public_closure,
            "requires_clean_head_for_release_artifact": True,
            "checks_public_release_closure": bool(check_public_closure),
        },
        "public_release_closure": public_closure,
        "workstreams": workstreams,
        "unknown_paths": unknown_paths,
        "forbidden_paths": forbidden_paths,
        "blocked_reasons": blocked_reasons,
        "required_actions": [
            "Review each changed workstream and decide include/defer for the release candidate.",
            "Move unrelated or private changes out of the public release candidate.",
            "Run the workstream validation commands and record results in the release notes or acceptance record.",
            "Commit the selected public release candidate so the worktree is clean.",
            "Rerun build_release_artifact.py from the clean HEAD before uploading to the server.",
        ],
        "recommended_freeze_order": [
            "deployment_runtime",
            "tool_security_governance",
            "rag_evaluation",
            "report_frontend",
            "business_api_runtime",
            "agent_state_architecture",
            "configuration_dependencies",
            "project_docs",
            "test_validation",
        ],
        "default_validation_commands": DEFAULT_VALIDATION_COMMANDS,
        "next_commands": [
            "uv run python scripts/check_release_candidate_freeze.py --check-public-closure --json",
            "uv run python scripts/render_release_candidate_freeze_record.py --draft-baseline-decisions --markdown",
            "uv run python scripts/check_release_candidate_freeze_signoff.py --record-json <filled-freeze-record.json> --check-current-worktree --json",
            "uv run python scripts/check_public_release_boundary.py --json",
            "uv run python scripts/check_m1_public_release_closure.py --json",
            "uv run python scripts/check_m1_deployment_gate.py --json",
            "uv run python scripts/build_release_artifact.py --json",
        ],
        "not_proven_by_this_report": [
            "Code review has actually happened.",
            "The selected release candidate has been committed.",
            "The release archive has been generated.",
            "The release archive has been uploaded or deployed to a server.",
            "Runtime secrets, backups, monitoring, and smoke tests are valid in the target environment.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_release_candidate_freeze_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Release Candidate Freeze（发布候选冻结）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Freeze state | `{_markdown_cell(report.get('freeze_state'))}` |",
        f"| Branch | `{_markdown_cell(report.get('branch'))}` |",
        f"| Dirty count | `{_markdown_cell(report.get('dirty_count'))}` |",
        f"| Public release closure | `{_markdown_cell((report.get('public_release_closure') or {}).get('status'))}` |",
        "",
        "## Workstreams",
        "",
        "| Workstream | Owner | Status | Changed |",
        "|---|---|---|---|",
    ]
    for stream in report.get("workstreams") or []:
        if not isinstance(stream, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(stream.get("key")),
                    _markdown_cell(stream.get("owner")),
                    _markdown_cell(stream.get("status")),
                    _markdown_cell(stream.get("changed_count")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Blockers", "", "| Key | Reason |", "|---|---|"])
    blockers = report.get("blocked_reasons") or []
    if blockers:
        for item in blockers:
            if isinstance(item, Mapping):
                lines.append(f"| {_markdown_cell(item.get('key'))} | {_markdown_cell(item.get('reason'))} |")
    else:
        lines.append("| - | - |")

    lines.extend(["", "## Required Actions", ""])
    for item in report.get("required_actions") or []:
        lines.append(f"- {_markdown_cell(item)}")

    lines.extend(["", "## Next Commands", ""])
    for item in report.get("next_commands") or []:
        lines.append(f"- `{_markdown_cell(item)}`")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument(
        "--check-public-closure",
        action="store_true",
        help="Also run the public M1 release closure check.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_release_candidate_freeze_report(check_public_closure=args.check_public_closure)
    if args.json and not args.markdown:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(build_release_candidate_freeze_markdown(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
