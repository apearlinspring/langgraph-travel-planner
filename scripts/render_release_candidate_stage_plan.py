"""Render a safe staging plan from a release candidate freeze record.

The plan is read-only: it does not run git add, does not stage files, does not
commit, and does not read changed file contents. It converts a filled or draft
freeze record into explicit include/defer path lists and follow-up gates.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_release_candidate_freeze import _is_forbidden_release_path  # noqa: E402
from scripts.export_acceptance_evidence import redact_text  # noqa: E402
from scripts.render_release_candidate_freeze_record import (  # noqa: E402
    RELEASE_CANDIDATE_FREEZE_RECORD_VERSION,
)


RELEASE_CANDIDATE_STAGE_PLAN_VERSION = "release_candidate_stage_plan.v1"
DEFAULT_BATCH_SIZE = 25


def _load_record_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read release freeze record JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Release freeze record JSON must be an object: {path}")
    return payload


def _normalize_repo_path(path: str | Path) -> str:
    text = Path(str(path).replace("\\", "/")).as_posix()
    return text[2:] if text.startswith("./") else text


def _decision_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("decision_rows")
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, Mapping)]


def _row_paths(row: Mapping[str, Any]) -> list[dict[str, str]]:
    paths: list[dict[str, str]] = []
    for item in row.get("paths") or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        paths.append(
            {
                "status": str(item.get("status") or ""),
                "path": _normalize_repo_path(path),
            }
        )
    return sorted(paths, key=lambda item: item["path"])


def _ps_quote(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def _batches(items: list[str], *, batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        batch_size = DEFAULT_BATCH_SIZE
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _git_add_commands(paths: list[str], *, batch_size: int) -> list[str]:
    return [
        "git add -- " + " ".join(_ps_quote(path) for path in batch)
        for batch in _batches(paths, batch_size=batch_size)
    ]


def build_release_candidate_stage_plan(
    record: Mapping[str, Any],
    *,
    record_json_label: str = "<filled-freeze-record.json>",
    batch_size: int = DEFAULT_BATCH_SIZE,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    include_rows: list[dict[str, Any]] = []
    defer_rows: list[dict[str, Any]] = []
    remove_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    for row in _decision_rows(record):
        if int(row.get("changed_count") or 0) <= 0:
            continue
        decision = str(row.get("decision") or "").strip().lower()
        target = {
            "include": include_rows,
            "defer": defer_rows,
            "remove": remove_rows,
        }.get(decision, other_rows)
        target.append(row)

    include_paths = sorted({item["path"] for row in include_rows for item in _row_paths(row)})
    defer_paths = sorted({item["path"] for row in defer_rows for item in _row_paths(row)})
    remove_paths = sorted({item["path"] for row in remove_rows for item in _row_paths(row)})
    other_paths = sorted({item["path"] for row in other_rows for item in _row_paths(row)})
    forbidden_include_paths = [path for path in include_paths if _is_forbidden_release_path(path)]

    blocked_reasons: list[dict[str, Any]] = []
    if str(record.get("version")) != RELEASE_CANDIDATE_FREEZE_RECORD_VERSION:
        blocked_reasons.append(
            {"key": "record_version", "reason": "Freeze record version is missing or unsupported."}
        )
    public_closure_status = str(record.get("public_release_closure_status") or "").lower()
    if public_closure_status and public_closure_status != "passed":
        blocked_reasons.append(
            {"key": "public_release_closure", "reason": "Public release closure is not passed."}
        )
    if not include_paths:
        blocked_reasons.append(
            {"key": "no_include_paths", "reason": "Freeze record has no include paths to stage."}
        )
    for path in forbidden_include_paths:
        blocked_reasons.append(
            {
                "key": "forbidden_include_path",
                "path": path,
                "reason": "Included path is forbidden for public release.",
            }
        )
    if other_rows:
        blocked_reasons.append(
            {
                "key": "undecided_workstream",
                "reason": "Some changed workstreams are not include/defer/remove.",
                "workstreams": [str(row.get("workstream") or "") for row in other_rows],
            }
        )

    status = "blocked" if blocked_reasons else "ready_to_stage"
    follow_up_commands = [
        f"uv run python scripts\\check_release_candidate_stage_scope.py --record-json {record_json_label} --json",
        f"uv run python scripts\\check_release_candidate_freeze_signoff.py --record-json {record_json_label} --check-current-worktree --json",
        "uv run python scripts\\check_public_release_boundary.py --json",
        "uv run python scripts\\check_m1_public_release_closure.py --json",
    ]
    return {
        "version": RELEASE_CANDIDATE_STAGE_PLAN_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "record_id": record.get("record_id"),
        "candidate_profile": record.get("candidate_profile"),
        "candidate_goal": record.get("candidate_goal"),
        "public_release_closure_status": record.get("public_release_closure_status"),
        "include_workstreams": [str(row.get("workstream") or "") for row in include_rows],
        "defer_workstreams": [str(row.get("workstream") or "") for row in defer_rows],
        "remove_workstreams": [str(row.get("workstream") or "") for row in remove_rows],
        "undecided_workstreams": [str(row.get("workstream") or "") for row in other_rows],
        "include_path_count": len(include_paths),
        "defer_path_count": len(defer_paths),
        "remove_path_count": len(remove_paths),
        "include_paths": include_paths,
        "defer_paths": defer_paths,
        "remove_paths": remove_paths,
        "undecided_paths": other_paths,
        "forbidden_include_paths": forbidden_include_paths,
        "git_add_commands": _git_add_commands(include_paths, batch_size=batch_size),
        "follow_up_commands": follow_up_commands,
        "blocked_reasons": blocked_reasons,
        "policy": {
            "reads_dotenv": False,
            "reads_changed_file_contents": False,
            "reads_record_json": True,
            "stages_files": False,
            "commits_files": False,
            "deletes_files": False,
            "starts_services": False,
        },
        "not_proven_by_this_plan": [
            "The listed paths have actually been staged.",
            "The staged file contents are correct.",
            "Release owner signoff has passed.",
            "Validation commands have passed.",
            "A release artifact has been generated or deployed.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_markdown(plan: Mapping[str, Any]) -> str:
    lines = [
        "# Release Candidate Stage Plan（发布候选暂存计划）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(plan.get('version'))}` |",
        f"| Status | `{_markdown_cell(plan.get('status'))}` |",
        f"| Candidate profile | `{_markdown_cell(plan.get('candidate_profile'))}` |",
        f"| Public release closure | `{_markdown_cell(plan.get('public_release_closure_status'))}` |",
        f"| Include paths | `{_markdown_cell(plan.get('include_path_count'))}` |",
        f"| Defer paths | `{_markdown_cell(plan.get('defer_path_count'))}` |",
        "",
        "## Git Add Commands",
        "",
    ]
    commands = plan.get("git_add_commands") or []
    if commands:
        for command in commands:
            lines.append(f"```powershell\n{_markdown_cell(command)}\n```")
    else:
        lines.append("- No include paths.")
    lines.extend(["", "## Follow-Up Gates", ""])
    for command in plan.get("follow_up_commands") or []:
        lines.append(f"- `{_markdown_cell(command)}`")
    lines.extend(["", "## Deferred Paths", ""])
    for path in plan.get("defer_paths") or []:
        lines.append(f"- `{_markdown_cell(path)}`")
    lines.extend(["", "## Blockers", "", "| Key | Path | Reason |", "|---|---|---|"])
    blockers = plan.get("blocked_reasons") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('key'))} | "
                f"{_markdown_cell(item.get('path'))} | "
                f"{_markdown_cell(item.get('reason'))} |"
            )
    else:
        lines.append("| - | - | - |")
    lines.extend(["", "## Boundary", ""])
    for item in plan.get("not_proven_by_this_plan") or []:
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
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    record = _load_record_json(args.record_json)
    label = str(args.record_json)
    plan = build_release_candidate_stage_plan(record, record_json_label=label, batch_size=args.batch_size)
    output_text = (
        json.dumps(plan, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_markdown(plan)
    )
    if args.output is None:
        print(output_text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0 if plan["status"] == "ready_to_stage" else 2


if __name__ == "__main__":
    raise SystemExit(main())
