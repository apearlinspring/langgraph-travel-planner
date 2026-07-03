"""Validate staged paths against a filled release candidate freeze record.

This is a pre-commit safety gate. It reads only Git staged path metadata and the
explicit freeze record JSON. It does not read changed source contents, `.env`,
runtime directories, logs, backups or private evidence.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
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

from scripts.check_release_candidate_freeze import (  # noqa: E402
    _classify_path,
    _is_forbidden_release_path,
)
from scripts.export_acceptance_evidence import redact_text  # noqa: E402
from scripts.render_release_candidate_freeze_record import (  # noqa: E402
    RELEASE_CANDIDATE_FREEZE_RECORD_VERSION,
)


RELEASE_CANDIDATE_STAGE_SCOPE_VERSION = "release_candidate_stage_scope.v1"


def _run_command(args: Sequence[str], *, timeout_seconds: float = 30) -> subprocess.CompletedProcess[str]:
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
    return text[2:] if text.startswith("./") else text


def _load_record_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read release freeze record JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Release freeze record JSON must be an object: {path}")
    return payload


def parse_git_diff_cached_name_status(output: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        if len(parts) >= 3 and status.startswith(("R", "C")):
            path = parts[-1]
        elif len(parts) >= 2:
            path = parts[1]
        else:
            continue
        entries.append({"status": status, "path": _normalize_repo_path(path)})
    return entries


def _staged_entries(*, command_runner: Any = _run_command) -> tuple[list[dict[str, str]], str | None]:
    try:
        result = command_runner(
            ["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-status"],
            timeout_seconds=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [], exc.__class__.__name__
    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        return [], (output.splitlines()[0] if output else "git diff --cached failed")[:300]
    return parse_git_diff_cached_name_status(result.stdout or ""), None


def _decision_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("decision_rows")
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, Mapping)]


def _paths_for_row(row: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()
    for item in row.get("paths") or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            paths.add(_normalize_repo_path(path))
    return paths


def _rows_by_decision(record: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped = {"include": [], "defer": [], "remove": [], "other": []}
    for row in _decision_rows(record):
        if int(row.get("changed_count") or 0) <= 0:
            continue
        decision = str(row.get("decision") or "").strip().lower()
        grouped[decision if decision in grouped else "other"].append(row)
    return grouped


def _workstream_name(row: Mapping[str, Any]) -> str:
    return str(row.get("workstream") or row.get("key") or "unknown")


def _blocker(*, key: str, reason: str, path: str | None = None, workstream: str | None = None) -> dict[str, str]:
    item = {"key": key, "reason": reason}
    if path:
        item["path"] = path
    if workstream:
        item["workstream"] = workstream
    return item


def build_release_candidate_stage_scope_report(
    record: Mapping[str, Any],
    *,
    command_runner: Any = _run_command,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    staged_entries, staged_error = _staged_entries(command_runner=command_runner)
    grouped = _rows_by_decision(record)
    included_paths = set().union(*[_paths_for_row(row) for row in grouped["include"]]) if grouped["include"] else set()
    deferred_paths = set().union(*[_paths_for_row(row) for row in grouped["defer"]]) if grouped["defer"] else set()
    removed_paths = set().union(*[_paths_for_row(row) for row in grouped["remove"]]) if grouped["remove"] else set()
    included_workstreams = {_workstream_name(row) for row in grouped["include"]}
    deferred_workstreams = {_workstream_name(row) for row in grouped["defer"]}
    removed_workstreams = {_workstream_name(row) for row in grouped["remove"]}
    staged_paths = {entry["path"] for entry in staged_entries}

    blocked_reasons: list[dict[str, str]] = []
    if staged_error:
        blocked_reasons.append(_blocker(key="git_staged_paths", reason=staged_error))
    if str(record.get("version")) != RELEASE_CANDIDATE_FREEZE_RECORD_VERSION:
        blocked_reasons.append(
            _blocker(key="record_version", reason="Freeze record version is missing or unsupported.")
        )
    public_closure_status = str(record.get("public_release_closure_status") or "").lower()
    if public_closure_status and public_closure_status != "passed":
        blocked_reasons.append(
            _blocker(key="public_release_closure", reason="Freeze record public release closure is not passed.")
        )
    if not staged_entries and not staged_error:
        blocked_reasons.append(_blocker(key="no_staged_paths", reason="No staged paths are ready for commit."))

    for entry in staged_entries:
        path = entry["path"]
        workstream = _classify_path(path)
        if _is_forbidden_release_path(path):
            blocked_reasons.append(
                _blocker(
                    key="forbidden_staged_path",
                    path=path,
                    workstream=workstream,
                    reason="Forbidden local secret or runtime path is staged.",
                )
            )
        if workstream == "unknown":
            blocked_reasons.append(
                _blocker(
                    key="unknown_staged_path",
                    path=path,
                    workstream=workstream,
                    reason="Staged path does not match a known release workstream.",
                )
            )
            continue
        if path in deferred_paths or workstream in deferred_workstreams:
            blocked_reasons.append(
                _blocker(
                    key="deferred_staged_path",
                    path=path,
                    workstream=workstream,
                    reason="Staged path belongs to a deferred workstream.",
                )
            )
        if path in removed_paths or workstream in removed_workstreams:
            blocked_reasons.append(
                _blocker(
                    key="removed_staged_path",
                    path=path,
                    workstream=workstream,
                    reason="Staged path belongs to a removed workstream.",
                )
            )
        if workstream not in included_workstreams:
            blocked_reasons.append(
                _blocker(
                    key="not_included_workstream",
                    path=path,
                    workstream=workstream,
                    reason="Staged path is not part of an included workstream in the freeze record.",
                )
            )
        elif path not in included_paths:
            blocked_reasons.append(
                _blocker(
                    key="staged_path_not_in_record",
                    path=path,
                    workstream=workstream,
                    reason="Staged path is in an included workstream but not listed in the freeze record.",
                )
            )

    missing_included_paths = sorted(included_paths - staged_paths)
    for path in missing_included_paths:
        blocked_reasons.append(
            _blocker(
                key="included_path_not_staged",
                path=path,
                workstream=_classify_path(path),
                reason="Freeze record includes this path, but it is not staged.",
            )
        )

    status = "blocked" if blocked_reasons else "passed"
    return {
        "version": RELEASE_CANDIDATE_STAGE_SCOPE_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "record_id": record.get("record_id"),
        "candidate_profile": record.get("candidate_profile"),
        "public_release_closure_status": record.get("public_release_closure_status"),
        "staged_count": len(staged_entries),
        "included_workstreams": sorted(included_workstreams),
        "deferred_workstreams": sorted(deferred_workstreams),
        "removed_workstreams": sorted(removed_workstreams),
        "staged_entries": staged_entries,
        "missing_included_paths": missing_included_paths,
        "blocked_reasons": blocked_reasons,
        "policy": {
            "reads_dotenv": False,
            "reads_changed_file_contents": False,
            "reads_record_json": True,
            "uses_git_staged_paths_only": True,
            "starts_services": False,
            "deletes_files": False,
            "stages_files": False,
            "commits_files": False,
        },
        "not_proven_by_this_report": [
            "The staged file contents are correct.",
            "Validation commands have passed.",
            "The release owner has signed off the freeze record.",
            "A release archive has been generated or deployed.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Release Candidate Stage Scope（发布候选暂存范围）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Candidate profile | `{_markdown_cell(report.get('candidate_profile'))}` |",
        f"| Public release closure | `{_markdown_cell(report.get('public_release_closure_status'))}` |",
        f"| Staged count | `{_markdown_cell(report.get('staged_count'))}` |",
        f"| Included workstreams | `{_markdown_cell(', '.join(report.get('included_workstreams') or []))}` |",
        f"| Deferred workstreams | `{_markdown_cell(', '.join(report.get('deferred_workstreams') or []))}` |",
        "",
        "## Blockers",
        "",
        "| Key | Workstream | Path | Reason |",
        "|---|---|---|---|",
    ]
    blockers = report.get("blocked_reasons") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('key'))} | "
                f"{_markdown_cell(item.get('workstream'))} | "
                f"{_markdown_cell(item.get('path'))} | "
                f"{_markdown_cell(item.get('reason'))} |"
            )
    else:
        lines.append("| - | - | - | - |")
    lines.extend(["", "## Boundary", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, required=True, help="Filled release freeze record JSON.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    record = _load_record_json(args.record_json)
    report = build_release_candidate_stage_scope_report(record)
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_markdown(report)
    )
    if args.output is None:
        print(output_text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
