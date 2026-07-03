"""Validate a filled release candidate freeze decision record.

This check is a pre-commit release-control gate. It reads a freeze record JSON
created by render_release_candidate_freeze_record.py, validates that changed
workstreams have explicit include/defer/remove decisions, and never reads .env
files, changed source contents, runtime folders, or starts services.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_acceptance_evidence import redact_text  # noqa: E402
from scripts.render_release_candidate_freeze_record import (  # noqa: E402
    RELEASE_CANDIDATE_FREEZE_RECORD_VERSION,
    build_release_candidate_freeze_record_report,
)
from scripts.check_release_candidate_freeze import build_release_candidate_freeze_report  # noqa: E402


RELEASE_CANDIDATE_FREEZE_SIGNOFF_VERSION = "release_candidate_freeze_signoff.v1"

VALID_DECISIONS = {"include", "defer", "remove"}
VALID_VALIDATION_STATUSES = {"passed", "blocked", "not_run", "not_required"}
VALID_RISK_STATUSES = {"none", "low", "accepted", "mitigated", "blocked", "not_required"}
PLACEHOLDER_VALUES = {"", "-", "pending", "todo", "tbd", "unknown", "n/a", "na"}


def _normalized(value: Any) -> str:
    return redact_text(str(value or "")).strip()


def _is_filled(value: Any) -> bool:
    return _normalized(value).lower() not in PLACEHOLDER_VALUES


def _load_record_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read release freeze record JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Release freeze record JSON must be an object: {path}")
    return payload


def _decision_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("decision_rows")
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, Mapping)]


def _path_entries(row_or_stream: Mapping[str, Any]) -> list[str]:
    entries: list[str] = []
    for item in row_or_stream.get("paths") or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            entries.append(path)
    return sorted(entries)


def _rows_by_workstream(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        _normalized(row.get("workstream") or row.get("key")): row
        for row in rows
        if _normalized(row.get("workstream") or row.get("key"))
    }


def _blocker(*, workstream: str, key: str, reason: str) -> dict[str, str]:
    return {
        "workstream": workstream,
        "key": key,
        "reason": reason,
    }


def _validate_changed_row(row: Mapping[str, Any]) -> list[dict[str, str]]:
    workstream = _normalized(row.get("workstream")) or "unknown"
    decision = _normalized(row.get("decision")).lower()
    validation_status = _normalized(row.get("validation_status")).lower()
    risk_status = _normalized(row.get("risk_status")).lower()
    blockers: list[dict[str, str]] = []

    if decision not in VALID_DECISIONS:
        blockers.append(
            _blocker(
                workstream=workstream,
                key="decision",
                reason="Changed workstream must choose include, defer, or remove.",
            )
        )
    elif decision == "include":
        if validation_status != "passed":
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="validation_status",
                    reason="Included workstream must have validation_status=passed.",
                )
            )
        if not _is_filled(row.get("validation_evidence")):
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="validation_evidence",
                    reason="Included workstream must include a validation evidence summary.",
                )
            )
        if risk_status not in {"none", "low", "accepted", "mitigated"}:
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="risk_status",
                    reason="Included workstream must have an accepted low/none/mitigated risk status.",
                )
            )
        if risk_status in {"low", "accepted", "mitigated"} and not _is_filled(row.get("remaining_risk")):
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="remaining_risk",
                    reason="Included workstream with non-none risk must describe the remaining risk.",
                )
            )
    elif decision in {"defer", "remove"}:
        if validation_status not in VALID_VALIDATION_STATUSES:
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="validation_status",
                    reason="Deferred or removed workstream must use a valid validation status.",
                )
            )
        if risk_status not in VALID_RISK_STATUSES:
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="risk_status",
                    reason="Deferred or removed workstream must use a valid risk status.",
                )
            )
        if not _is_filled(row.get("decision_reason")):
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="decision_reason",
                    reason="Deferred or removed workstream must explain why it is not in this candidate.",
                )
            )

    if not _is_filled(row.get("signoff")):
        blockers.append(
            _blocker(
                workstream=workstream,
                key="signoff",
                reason="Changed workstream must include a release-owner signoff.",
            )
        )
    return blockers


def _validate_current_freeze_match(
    record: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    current_freeze_report: Mapping[str, Any],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    current_dirty_count = current_freeze_report.get("dirty_count")
    record_dirty_count = record.get("dirty_count")
    if record_dirty_count != current_dirty_count:
        blockers.append(
            _blocker(
                workstream="record",
                key="dirty_count_mismatch",
                reason="Freeze record dirty_count does not match the current Git worktree.",
            )
        )

    current_branch = _normalized(current_freeze_report.get("branch"))
    record_branch = _normalized(record.get("branch"))
    if record_branch and current_branch and record_branch != current_branch:
        blockers.append(
            _blocker(
                workstream="record",
                key="branch_mismatch",
                reason="Freeze record branch does not match the current Git branch status.",
            )
        )

    current_forbidden = current_freeze_report.get("forbidden_paths") or []
    if current_forbidden:
        blockers.append(
            _blocker(
                workstream="record",
                key="current_forbidden_paths",
                reason="Current Git worktree still contains forbidden release paths.",
            )
        )
    current_unknown = current_freeze_report.get("unknown_paths") or []
    if current_unknown:
        blockers.append(
            _blocker(
                workstream="record",
                key="current_unknown_paths",
                reason="Current Git worktree still contains paths without a release workstream owner.",
            )
        )
    current_public_closure = current_freeze_report.get("public_release_closure")
    current_public_closure = current_public_closure if isinstance(current_public_closure, Mapping) else {}
    current_public_closure_status = _normalized(current_public_closure.get("status")).lower()
    if current_public_closure_status and current_public_closure_status != "passed":
        blockers.append(
            _blocker(
                workstream="record",
                key="current_public_release_closure",
                reason="Current M1 public release closure is not passed.",
            )
        )

    record_by_stream = _rows_by_workstream(rows)
    current_by_stream = _rows_by_workstream(
        [
            {
                "workstream": stream.get("key"),
                "changed_count": stream.get("changed_count"),
                "paths": stream.get("paths") or [],
            }
            for stream in current_freeze_report.get("workstreams") or []
            if isinstance(stream, Mapping)
        ]
    )
    for workstream, current_row in current_by_stream.items():
        record_row = record_by_stream.get(workstream)
        current_changed_count = int(current_row.get("changed_count") or 0)
        record_changed_count = int(record_row.get("changed_count") or 0) if record_row else 0
        if current_changed_count != record_changed_count:
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="workstream_changed_count_mismatch",
                    reason="Freeze record changed_count does not match the current Git worktree.",
                )
            )
            continue
        if current_changed_count <= 0:
            continue
        if record_row is None:
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="workstream_missing",
                    reason="Current Git worktree has changed paths missing from the freeze record.",
                )
            )
            continue
        if _path_entries(record_row) != _path_entries(current_row):
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="workstream_paths_mismatch",
                    reason="Freeze record paths do not match the current Git worktree.",
                )
            )
    for workstream, record_row in record_by_stream.items():
        if workstream not in current_by_stream and int(record_row.get("changed_count") or 0) > 0:
            blockers.append(
                _blocker(
                    workstream=workstream,
                    key="workstream_no_longer_changed",
                    reason="Freeze record contains changed paths that are no longer dirty in the current Git worktree.",
                )
            )
    return blockers


def build_release_candidate_freeze_signoff_report(
    record: Mapping[str, Any],
    *,
    current_freeze_report: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
    source: str = "record_json",
) -> dict[str, Any]:
    """Validate a release candidate freeze decision record."""

    now = generated_at or datetime.now(UTC)
    rows = _decision_rows(record)
    blocked_reasons: list[dict[str, str]] = []
    if str(record.get("version")) != RELEASE_CANDIDATE_FREEZE_RECORD_VERSION:
        blocked_reasons.append(
            _blocker(
                workstream="record",
                key="version",
                reason="Record version is missing or unsupported.",
            )
        )
    if not rows:
        blocked_reasons.append(
            _blocker(
                workstream="record",
                key="decision_rows",
                reason="Record has no decision_rows.",
            )
        )
    public_closure_status = _normalized(record.get("public_release_closure_status")).lower()
    if public_closure_status and public_closure_status != "passed":
        blocked_reasons.append(
            _blocker(
                workstream="record",
                key="public_release_closure",
                reason="Public release closure must be passed before release candidate signoff.",
            )
        )

    changed_rows = [row for row in rows if int(row.get("changed_count") or 0) > 0]
    for row in changed_rows:
        blocked_reasons.extend(_validate_changed_row(row))
    if current_freeze_report is not None:
        blocked_reasons.extend(_validate_current_freeze_match(record, rows, current_freeze_report))

    status = "blocked" if blocked_reasons else "passed"
    included = [row for row in changed_rows if _normalized(row.get("decision")).lower() == "include"]
    deferred = [row for row in changed_rows if _normalized(row.get("decision")).lower() == "defer"]
    removed = [row for row in changed_rows if _normalized(row.get("decision")).lower() == "remove"]
    current_public_closure = current_freeze_report.get("public_release_closure") if current_freeze_report else None
    current_public_closure = current_public_closure if isinstance(current_public_closure, Mapping) else {}
    return {
        "version": RELEASE_CANDIDATE_FREEZE_SIGNOFF_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "source": source,
        "record_id": record.get("record_id"),
        "candidate_profile": record.get("candidate_profile"),
        "candidate_goal": record.get("candidate_goal"),
        "freeze_status": record.get("freeze_status"),
        "freeze_state": record.get("freeze_state"),
        "dirty_count": record.get("dirty_count"),
        "public_release_closure_status": record.get("public_release_closure_status"),
        "current_worktree_checked": current_freeze_report is not None,
        "current_freeze_status": current_freeze_report.get("status") if current_freeze_report else None,
        "current_dirty_count": current_freeze_report.get("dirty_count") if current_freeze_report else None,
        "current_public_release_closure_status": current_public_closure.get("status"),
        "changed_workstream_count": len(changed_rows),
        "included_workstream_count": len(included),
        "deferred_workstream_count": len(deferred),
        "removed_workstream_count": len(removed),
        "blocked_reasons": blocked_reasons,
        "policy": {
            "reads_dotenv": False,
            "reads_file_contents": bool(current_public_closure),
            "starts_services": False,
            "uses_git_status_only_for_current_check": current_freeze_report is not None and not current_public_closure,
            "current_check_includes_public_release_closure": bool(current_public_closure),
            "validates_decisions_only": True,
        },
        "next_actions": [
            "Fill decision, validation_status, risk_status, decision_reason when needed, and signoff for every changed workstream.",
            "Run each included workstream validation command and record the result before setting validation_status=passed.",
            "Record validation_evidence for each included workstream; status-only signoff is not enough for a production release candidate.",
            "After signoff passes, stage and commit only the selected public release candidate.",
            "Rerun check_release_candidate_freeze.py until status=passed, then build the release artifact.",
        ],
        "not_proven_by_this_check": [
            "Validation commands have actually passed unless their evidence is recorded outside this JSON.",
            "The selected files have been staged or committed.",
            "The release archive or manifest has been generated.",
            "The release has been deployed to a server.",
            "Target environment secrets, backups, monitoring, and smoke tests have passed.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_release_candidate_freeze_signoff_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Release Candidate Freeze Signoff（发布候选签核校验）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Status | `{_markdown_cell(report.get('status'))}` |",
        f"| Record ID | `{_markdown_cell(report.get('record_id'))}` |",
        f"| Candidate profile | `{_markdown_cell(report.get('candidate_profile'))}` |",
        f"| Candidate goal | {_markdown_cell(report.get('candidate_goal'))} |",
        f"| Freeze status | `{_markdown_cell(report.get('freeze_status'))}` |",
        f"| Dirty count | `{_markdown_cell(report.get('dirty_count'))}` |",
        f"| Public release closure | `{_markdown_cell(report.get('public_release_closure_status'))}` |",
        f"| Current worktree checked | `{_markdown_cell(report.get('current_worktree_checked'))}` |",
        f"| Current freeze status | `{_markdown_cell(report.get('current_freeze_status'))}` |",
        f"| Current dirty count | `{_markdown_cell(report.get('current_dirty_count'))}` |",
        f"| Current public release closure | `{_markdown_cell(report.get('current_public_release_closure_status'))}` |",
        f"| Changed workstreams | `{_markdown_cell(report.get('changed_workstream_count'))}` |",
        f"| Included | `{_markdown_cell(report.get('included_workstream_count'))}` |",
        f"| Deferred | `{_markdown_cell(report.get('deferred_workstream_count'))}` |",
        f"| Removed | `{_markdown_cell(report.get('removed_workstream_count'))}` |",
        "",
        "## Blockers",
        "",
        "| Workstream | Key | Reason |",
        "|---|---|---|",
    ]
    blockers = report.get("blocked_reasons") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('workstream'))} | "
                f"{_markdown_cell(item.get('key'))} | "
                f"{_markdown_cell(item.get('reason'))} |"
            )
    else:
        lines.append("| - | - | - |")

    lines.extend(["", "## Next Actions", ""])
    for item in report.get("next_actions") or []:
        lines.append(f"- {_markdown_cell(item)}")
    lines.extend(["", "## Boundary", ""])
    for item in report.get("not_proven_by_this_check") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Filled freeze record JSON.")
    parser.add_argument(
        "--check-current-worktree",
        action="store_true",
        help="Compare the filled record with the current git status workstream/path snapshot.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    return parser.parse_args(list(argv) if argv is not None else None)


def _default_pending_record() -> dict[str, Any]:
    return build_release_candidate_freeze_record_report(
        build_release_candidate_freeze_report(check_public_closure=True),
        source="live_freeze_report",
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.record_json is None:
        record = _default_pending_record()
        source = "live_pending_record"
    else:
        record = _load_record_json(args.record_json)
        source = f"record_json:{args.record_json.name}"
    current_freeze_report = (
        build_release_candidate_freeze_report(check_public_closure=True)
        if args.check_current_worktree
        else None
    )
    report = build_release_candidate_freeze_signoff_report(
        record,
        current_freeze_report=current_freeze_report,
        source=source,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_release_candidate_freeze_signoff_markdown(report)
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
