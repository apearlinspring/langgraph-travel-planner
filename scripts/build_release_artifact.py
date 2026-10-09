"""Build a release archive and redacted manifest from a clean Git HEAD.

Default mode is dry-run: it checks whether a production release artifact can be
created, but does not write archives or manifests. The script never reads .env
files and never includes runtime data outside Git HEAD.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_public_release_boundary import build_public_release_boundary_report  # noqa: E402


RELEASE_ARTIFACT_VERSION = "release_artifact.v1"
DEFAULT_PREFIX = "zhixing-release"
BLOCKING_STATUSES = {"blocked", "failed", "unknown"}


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


def _first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return next((line.strip() for line in output.splitlines() if line.strip()), "")[:300]


def _git_text(
    args: Sequence[str],
    *,
    command_runner: Any = _run_command,
    timeout_seconds: float = 20,
) -> tuple[str, str | None]:
    try:
        result = command_runner(["git", *args], timeout_seconds=timeout_seconds)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return "", exc.__class__.__name__
    if result.returncode != 0:
        return "", _first_output_line(result) or f"git {' '.join(args)} failed"
    return (result.stdout or "").strip(), None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_release_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in value.strip())
    return safe.strip(".-_") or DEFAULT_PREFIX


def build_git_worktree_section(*, command_runner: Any = _run_command) -> dict[str, Any]:
    output, error = _git_text(["status", "--short", "--branch"], command_runner=command_runner)
    section: dict[str, Any] = {
        "status": "blocked",
        "command": "git status --short --branch",
        "branch": "unknown",
        "dirty_count": None,
    }
    if error:
        section["finding"] = error
        return section
    lines = [line for line in output.splitlines() if line.strip()]
    dirty_count = len(lines[1:])
    section["branch"] = lines[0] if lines else "unknown"
    section["dirty_count"] = dirty_count
    if dirty_count:
        section["finding"] = "Working tree has uncommitted changes; release archive must be built from a clean HEAD."
    else:
        section.update({"status": "passed", "finding": "Working tree is clean."})
    return section


def build_git_identity_section(*, command_runner: Any = _run_command) -> dict[str, Any]:
    commit, commit_error = _git_text(["rev-parse", "HEAD"], command_runner=command_runner)
    short_commit, short_error = _git_text(["rev-parse", "--short", "HEAD"], command_runner=command_runner)
    tree, tree_error = _git_text(["rev-parse", "HEAD^{tree}"], command_runner=command_runner)
    branch, branch_error = _git_text(["branch", "--show-current"], command_runner=command_runner)
    files, files_error = _git_text(["ls-tree", "-r", "--name-only", "HEAD"], command_runner=command_runner)

    errors = [item for item in [commit_error, short_error, tree_error, branch_error, files_error] if item]
    paths = [line for line in files.splitlines() if line.strip()] if not files_error else []
    status = "blocked" if errors else "passed"
    return {
        "status": status,
        "commit": commit if not commit_error else "unknown",
        "short_commit": short_commit if not short_error else "unknown",
        "tree": tree if not tree_error else "unknown",
        "branch": branch if not branch_error else "unknown",
        "tracked_file_count": len(paths),
        "tracked_files": paths,
        "finding": "; ".join(errors) if errors else "Git HEAD identity resolved.",
    }


def _section_statuses(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {name: str(section.get("status") or "unknown") for name, section in sections.items()}


def _collect_blockers(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for name, section in sections.items():
        status = str(section.get("status") or "unknown")
        if status not in BLOCKING_STATUSES:
            continue
        blockers.append(
            {
                "section": name,
                "status": status,
                "reason": str(section.get("finding") or section.get("status") or "blocked"),
            }
        )
    return blockers


def build_release_artifact_report(
    *,
    execute: bool = False,
    output_dir: str | Path | None = None,
    release_id: str | None = None,
    generated_at: datetime | None = None,
    command_runner: Any = _run_command,
    boundary_builder: Any = build_public_release_boundary_report,
) -> dict[str, Any]:
    """Build a release artifact report, optionally writing archive + manifest."""

    git_worktree = build_git_worktree_section(command_runner=command_runner)
    git_identity = build_git_identity_section(command_runner=command_runner)
    public_boundary = boundary_builder()
    if not isinstance(public_boundary, Mapping):
        public_boundary = {"status": "blocked", "finding": "Public boundary report is invalid."}

    sections: dict[str, Mapping[str, Any]] = {
        "git_worktree": git_worktree,
        "git_identity": git_identity,
        "public_release_boundary": public_boundary,
    }
    statuses = _section_statuses(sections)
    blocked = any(status in BLOCKING_STATUSES for status in statuses.values())
    now = generated_at or datetime.now(UTC)
    short_commit = str(git_identity.get("short_commit") or "unknown")
    resolved_release_id = _safe_release_id(release_id or f"{DEFAULT_PREFIX}-{short_commit}")
    archive_name = f"{resolved_release_id}.tar"
    manifest_name = f"{resolved_release_id}.manifest.json"
    output_root = Path(output_dir).resolve() if output_dir is not None else None
    archive_path = output_root / archive_name if output_root is not None else None
    manifest_path = output_root / manifest_name if output_root is not None else None

    artifact: dict[str, Any] = {
        "release_id": resolved_release_id,
        "archive_name": archive_name,
        "manifest_name": manifest_name,
        "archive_written": False,
        "manifest_written": False,
        "archive_sha256": None,
        "archive_size_bytes": None,
        "manifest_path_echoed": False,
        "archive_path_echoed": False,
    }

    write_status = "not_requested"
    write_finding = "Dry-run only; no archive or manifest was written."
    if execute:
        if output_root is None:
            write_status = "blocked"
            write_finding = "--output-dir is required when --execute is used."
        elif blocked:
            write_status = "blocked"
            write_finding = "Release archive was not written because a prerequisite section is blocked."
        else:
            try:
                output_root.mkdir(parents=True, exist_ok=True)
                result = command_runner(
                    ["git", "archive", "--format=tar", "-o", str(archive_path), "HEAD"],
                    timeout_seconds=120,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                write_status = "blocked"
                write_finding = exc.__class__.__name__
            else:
                if result.returncode != 0:
                    write_status = "blocked"
                    write_finding = _first_output_line(result) or "git archive failed."
                elif archive_path is None or not archive_path.exists():
                    write_status = "blocked"
                    write_finding = "git archive completed but archive file is missing."
                else:
                    artifact["archive_written"] = True
                    artifact["archive_sha256"] = _sha256_file(archive_path)
                    artifact["archive_size_bytes"] = archive_path.stat().st_size
                    write_status = "passed"
                    write_finding = "Archive written from Git HEAD."

    write_section = {
        "status": write_status,
        "execute": execute,
        "writes_files": bool(execute and write_status == "passed"),
        "finding": write_finding,
    }
    sections["artifact_write"] = write_section
    statuses = _section_statuses(sections)
    final_status = "blocked" if any(status in BLOCKING_STATUSES for status in statuses.values()) else "passed"
    if not execute and final_status == "passed":
        final_status = "ready_to_build"

    report: dict[str, Any] = {
        "version": RELEASE_ARTIFACT_VERSION,
        "status": final_status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "uses_git_head_only": True,
            "requires_clean_worktree": True,
            "checks_public_release_boundary": True,
            "writes_files_by_default": False,
            "does_not_echo_local_paths": True,
        },
        "section_statuses": statuses,
        "blockers": _collect_blockers(sections),
        "artifact": artifact,
        "sections": sections,
        "next_commands": [
            "git status --short --branch",
            "python scripts/build_release_artifact.py --execute --output-dir <release-output-dir> --json",
            "scp <release-archive> <ssh-user>@<server-host>:/tmp/<release-archive>",
            "scp <release-manifest> <ssh-user>@<server-host>:/tmp/<release-manifest>",
            "scp deploy/first-deploy.sh <ssh-user>@<server-host>:/tmp/zhixing-first-deploy.sh",
            "ssh <ssh-user>@<server-host> \"sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>\"",
            "ssh <ssh-user>@<server-host> \"sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>\"",
        ],
        "not_proven_by_this_report": [
            "SSH authentication works.",
            "The archive was uploaded to a server.",
            "Server .env or secret manager contains valid values.",
            "Docker services started on the target server.",
            "Health/readiness, smoke, backup restore, monitoring alerting or go/no-go evidence passed.",
        ],
    }

    if execute and write_status == "passed" and manifest_path is not None:
        manifest_payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        manifest_path.write_text(manifest_payload + "\n", encoding="utf-8")
        report["artifact"]["manifest_written"] = True
        report["sections"]["artifact_write"] = {
            **write_section,
            "manifest_written": True,
        }
        manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_release_artifact_markdown(report: Mapping[str, Any]) -> str:
    artifact = report.get("artifact") if isinstance(report.get("artifact"), Mapping) else {}
    lines = [
        "# Release Artifact Manifest（发布包清单）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Release ID | `{_markdown_cell(artifact.get('release_id'))}` |",
        f"| Archive | `{_markdown_cell(artifact.get('archive_name'))}` |",
        f"| Archive written | `{_markdown_cell(artifact.get('archive_written'))}` |",
        f"| Archive sha256 | `{_markdown_cell(artifact.get('archive_sha256'))}` |",
        "",
        "## Section 状态",
        "",
        "| Section | Status |",
        "|---|---|",
    ]
    for section, status in (report.get("section_statuses") or {}).items():
        lines.append(f"| {_markdown_cell(section)} | {_markdown_cell(status)} |")

    lines.extend(["", "## Blockers", "", "| Section | Reason |", "|---|---|"])
    blockers = report.get("blockers") or []
    if blockers:
        for item in blockers:
            if isinstance(item, Mapping):
                lines.append(f"| {_markdown_cell(item.get('section'))} | {_markdown_cell(item.get('reason'))} |")
    else:
        lines.append("| - | - |")

    lines.extend(["", "## 下一步命令", ""])
    for item in report.get("next_commands") or []:
        lines.append(f"- `{_markdown_cell(item)}`")

    lines.extend(["", "## 边界", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Write archive and manifest after all gates pass.")
    parser.add_argument("--output-dir", type=_path_arg, default=None, help="Directory for release artifacts.")
    parser.add_argument("--release-id", default=None, help="Optional release id; defaults to zhixing-release-<commit>.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_release_artifact_report(
        execute=args.execute,
        output_dir=args.output_dir,
        release_id=args.release_id,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_release_artifact_markdown(report)
    )
    print(output_text)
    return 0 if report["status"] in {"passed", "ready_to_build"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
