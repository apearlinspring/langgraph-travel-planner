"""Render a release candidate freeze decision record.

The record turns the machine-readable freeze report into a review checklist for
the release owner. It does not read .env files, does not inspect changed file
contents, and does not start services.
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

from scripts.check_release_candidate_freeze import (  # noqa: E402
    build_release_candidate_freeze_report,
)
from scripts.export_acceptance_evidence import redact_text  # noqa: E402


RELEASE_CANDIDATE_FREEZE_RECORD_VERSION = "release_candidate_freeze_record.v1"


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _load_freeze_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read release freeze JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Release freeze JSON must be an object: {path}")
    return payload


def _suggested_decision_for(
    stream: Mapping[str, Any],
    *,
    freeze_report: Mapping[str, Any],
) -> dict[str, str]:
    changed_count = int(stream.get("changed_count") or 0)
    key = str(stream.get("key") or "")
    if changed_count <= 0:
        return {
            "suggested_decision": "not_changed",
            "suggested_reason": "No changed paths in this workstream.",
        }
    if freeze_report.get("forbidden_paths"):
        return {
            "suggested_decision": "hold",
            "suggested_reason": "Forbidden release paths exist; resolve them before including any workstream.",
        }
    if freeze_report.get("unknown_paths"):
        return {
            "suggested_decision": "hold",
            "suggested_reason": "Unknown changed paths exist; route or remove them before selecting the candidate.",
        }
    if key in {"deployment_runtime", "tool_security_governance", "test_validation", "project_docs"}:
        return {
            "suggested_decision": "include",
            "suggested_reason": "Release-control, security/governance, documentation, or validation support is directly relevant to M1 deployment readiness.",
        }
    return {
        "suggested_decision": "review_include_or_defer",
        "suggested_reason": "Review whether this workstream belongs to the first M1 deployment candidate or should ship after the release-control baseline.",
    }


def _evidence_template(stream: Mapping[str, Any]) -> str:
    commands = [str(item) for item in stream.get("validation_commands") or []]
    if not commands:
        return "Run the relevant workstream validation and record status, command, and remaining risk."
    return "Run and record: " + "; ".join(commands)


def _apply_baseline_draft(row: dict[str, Any]) -> None:
    suggested_decision = str(row.get("suggested_decision") or "")
    if suggested_decision == "include":
        row.update(
            {
                "decision": "include",
                "decision_reason": row.get("suggested_reason") or "",
                "validation_status": "not_run",
                "validation_evidence": row.get("suggested_validation_evidence") or "",
                "risk_status": "accepted",
                "risk_evidence": row.get("suggested_risk_evidence") or "",
                "remaining_risk": (
                    "M1 remains blocked until the selected candidate is committed, "
                    "the release artifact is built from a clean HEAD, and target server/env evidence passes."
                ),
            }
        )
    elif suggested_decision == "review_include_or_defer":
        row.update(
            {
                "decision": "defer",
                "decision_reason": (
                    "Defer from the first release-control candidate until the deployment-control "
                    "baseline is frozen and committed."
                ),
                "validation_status": "not_required",
                "validation_evidence": "Deferred workstream; validate when selected for a later candidate.",
                "risk_status": "not_required",
                "risk_evidence": "No release risk in the current candidate because this workstream is deferred.",
                "remaining_risk": "Deferred changes must be reviewed before a later candidate.",
            }
        )


def _decision_rows(
    freeze_report: Mapping[str, Any],
    *,
    include_suggestions: bool = False,
    draft_baseline_decisions: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in freeze_report.get("workstreams") or []:
        if not isinstance(stream, Mapping):
            continue
        changed_count = int(stream.get("changed_count") or 0)
        row = {
            "workstream": stream.get("key"),
            "owner": stream.get("owner"),
            "changed_count": changed_count,
            "decision": "pending" if changed_count else "not_changed",
            "decision_reason": "",
            "validation_status": "pending" if changed_count else "not_required",
            "validation_evidence": "",
            "risk_status": "pending" if changed_count else "not_required",
            "risk_evidence": "",
            "remaining_risk": "",
            "signoff": "",
            "paths": stream.get("paths") or [],
            "validation_commands": stream.get("validation_commands") or [],
        }
        if include_suggestions or draft_baseline_decisions:
            row.update(_suggested_decision_for(stream, freeze_report=freeze_report))
            row["suggested_validation_evidence"] = _evidence_template(stream)
            row["suggested_risk_evidence"] = (
                "Record whether this workstream changes runtime behavior, deployment safety, "
                "secret handling, data boundaries, or acceptance scope."
            )
        if draft_baseline_decisions:
            _apply_baseline_draft(row)
        rows.append(row)
    return rows


def build_release_candidate_freeze_record_report(
    freeze_report: Mapping[str, Any],
    *,
    record_id: str | None = None,
    generated_at: datetime | None = None,
    source: str = "live_freeze_report",
    include_suggestions: bool = False,
    draft_baseline_decisions: bool = False,
) -> dict[str, Any]:
    """Build a redacted release freeze record payload."""

    now = generated_at or datetime.now(UTC)
    resolved_record_id = record_id or f"release-freeze-{now.strftime('%Y%m%d%H%M%S')}"
    public_closure = freeze_report.get("public_release_closure")
    public_closure = public_closure if isinstance(public_closure, Mapping) else {}
    decision_rows = _decision_rows(
        freeze_report,
        include_suggestions=include_suggestions,
        draft_baseline_decisions=draft_baseline_decisions,
    )
    changed_rows = [row for row in decision_rows if int(row.get("changed_count") or 0) > 0]
    status = "blocked" if str(freeze_report.get("status")) == "blocked" else "ready_for_freeze_signoff"
    if changed_rows:
        signoff_status = "pending"
    elif status == "ready_for_freeze_signoff":
        signoff_status = "not_required_clean_worktree"
    else:
        signoff_status = "blocked"
    candidate_profile = (
        "m1_deployment_control_baseline"
        if draft_baseline_decisions
        else "manual_release_candidate"
    )
    included_workstreams = [
        str(row.get("workstream"))
        for row in changed_rows
        if str(row.get("decision")) == "include"
    ]
    deferred_workstreams = [
        str(row.get("workstream"))
        for row in changed_rows
        if str(row.get("decision")) == "defer"
    ]
    removed_workstreams = [
        str(row.get("workstream"))
        for row in changed_rows
        if str(row.get("decision")) == "remove"
    ]
    report = {
        "version": RELEASE_CANDIDATE_FREEZE_RECORD_VERSION,
        "status": status,
        "record_id": resolved_record_id,
        "candidate_profile": candidate_profile,
        "candidate_goal": (
            "Freeze the public deployment-control baseline before selecting broader RAG, "
            "frontend, business API or dependency changes."
            if candidate_profile == "m1_deployment_control_baseline"
            else "Manual release candidate selection."
        ),
        "generated_at": now.isoformat(),
        "source": source,
        "freeze_report_version": freeze_report.get("version"),
        "freeze_status": freeze_report.get("status"),
        "freeze_state": freeze_report.get("freeze_state"),
        "branch": freeze_report.get("branch"),
        "dirty_count": freeze_report.get("dirty_count"),
        "forbidden_paths": freeze_report.get("forbidden_paths") or [],
        "unknown_paths": freeze_report.get("unknown_paths") or [],
        "public_release_closure_status": public_closure.get("status"),
        "public_release_closure_checked": public_closure.get("checked"),
        "public_release_closure_section_statuses": public_closure.get("section_statuses") or {},
        "signoff_status": signoff_status,
        "changed_workstream_count": len(changed_rows),
        "included_workstreams": included_workstreams,
        "deferred_workstreams": deferred_workstreams,
        "removed_workstreams": removed_workstreams,
        "include_suggestions": include_suggestions or draft_baseline_decisions,
        "draft_baseline_decisions": draft_baseline_decisions,
        "decision_rows": decision_rows,
        "blocked_reasons": freeze_report.get("blocked_reasons") or [],
        "required_actions": freeze_report.get("required_actions") or [],
        "policy": {
            "reads_dotenv": False,
            "reads_file_contents": False,
            "starts_services": False,
            "safe_to_commit": True,
            "records_decisions_only": True,
            "suggestions_are_not_signoff": include_suggestions or draft_baseline_decisions,
            "draft_decisions_are_not_signoff": draft_baseline_decisions,
        },
        "not_proven_by_this_record": [
            "The release owner has actually signed off each pending workstream.",
            "Validation commands have actually been executed.",
            "The selected release candidate has been committed.",
            "A release archive and manifest have been generated.",
            "The release has been uploaded or deployed to a server.",
            "Server secrets, backups, monitoring, smoke tests, and go/no-go have passed.",
        ],
    }
    return report


def build_release_candidate_freeze_record_markdown(report: Mapping[str, Any]) -> str:
    """Build a Markdown freeze decision record."""

    lines = [
        "# Release Candidate Freeze Record（发布候选冻结记录）",
        "",
        "## 1. 基本信息",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(report.get('version'))}` |",
        f"| Record ID | `{_markdown_cell(report.get('record_id'))}` |",
        f"| Candidate profile | `{_markdown_cell(report.get('candidate_profile'))}` |",
        f"| Candidate goal | {_markdown_cell(report.get('candidate_goal'))} |",
        f"| Generated at | `{_markdown_cell(report.get('generated_at'))}` |",
        f"| Source | `{_markdown_cell(report.get('source'))}` |",
        f"| Branch | `{_markdown_cell(report.get('branch'))}` |",
        f"| Freeze status | `{_markdown_cell(report.get('freeze_status'))}` |",
        f"| Freeze state | `{_markdown_cell(report.get('freeze_state'))}` |",
        f"| Dirty count | `{_markdown_cell(report.get('dirty_count'))}` |",
        f"| Forbidden paths | `{_markdown_cell(len(report.get('forbidden_paths') or []))}` |",
        f"| Unknown paths | `{_markdown_cell(len(report.get('unknown_paths') or []))}` |",
        f"| Public release closure | `{_markdown_cell(report.get('public_release_closure_status'))}` |",
        f"| Signoff status | `{_markdown_cell(report.get('signoff_status'))}` |",
        f"| Changed workstreams | `{_markdown_cell(report.get('changed_workstream_count'))}` |",
        f"| Included workstreams | `{_markdown_cell(', '.join(report.get('included_workstreams') or []))}` |",
        f"| Deferred workstreams | `{_markdown_cell(', '.join(report.get('deferred_workstreams') or []))}` |",
        f"| Includes suggestions | `{_markdown_cell(report.get('include_suggestions'))}` |",
        f"| Draft baseline decisions | `{_markdown_cell(report.get('draft_baseline_decisions'))}` |",
        "",
        "## 2. Workstream 决策表",
        "",
        "| Workstream | Owner | Changed | Decision | Validation | Risk |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("decision_rows") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(row.get('workstream'))} | "
            f"{_markdown_cell(row.get('owner'))} | "
            f"{_markdown_cell(row.get('changed_count'))} | "
            f"{_markdown_cell(row.get('decision'))} | "
            f"{_markdown_cell(row.get('validation_status'))} | "
            f"{_markdown_cell(row.get('risk_status'))} |"
        )

    lines.extend(["", "## 3. 待决策路径", ""])
    for row in report.get("decision_rows") or []:
        if not isinstance(row, Mapping) or int(row.get("changed_count") or 0) <= 0:
            continue
        lines.extend(
            [
                f"### `{_markdown_cell(row.get('workstream'))}`",
                "",
                f"- Decision: `{_markdown_cell(row.get('decision'))}`",
                f"- Include/defer/remove reason: {_markdown_cell(row.get('decision_reason'))}",
                f"- Validation result: `{_markdown_cell(row.get('validation_status'))}`",
                f"- Validation evidence: {_markdown_cell(row.get('validation_evidence'))}",
                f"- Remaining risk: {_markdown_cell(row.get('remaining_risk'))}",
                f"- Risk status: `{_markdown_cell(row.get('risk_status'))}`",
                f"- Risk evidence: {_markdown_cell(row.get('risk_evidence'))}",
                f"- Sign-off: {_markdown_cell(row.get('signoff'))}",
            ]
        )
        if report.get("include_suggestions"):
            lines.extend(
                [
                    f"- Suggested decision: `{_markdown_cell(row.get('suggested_decision'))}`",
                    f"- Suggested reason: {_markdown_cell(row.get('suggested_reason'))}",
                    f"- Suggested validation evidence: {_markdown_cell(row.get('suggested_validation_evidence'))}",
                    f"- Suggested risk evidence: {_markdown_cell(row.get('suggested_risk_evidence'))}",
                ]
            )
        lines.extend(["", "| Status | Path |", "|---|---|"])
        for item in row.get("paths") or []:
            if not isinstance(item, Mapping):
                continue
            lines.append(f"| {_markdown_cell(item.get('status'))} | `{_markdown_cell(item.get('path'))}` |")
        lines.extend(["", "Validation commands:"])
        for command in row.get("validation_commands") or []:
            lines.append(f"- `{_markdown_cell(command)}`")
        lines.append("")

    lines.extend(["## 4. 阻塞项", "", "| Key | Reason |", "|---|---|"])
    blockers = report.get("blocked_reasons") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(f"| {_markdown_cell(item.get('key'))} | {_markdown_cell(item.get('reason'))} |")
    else:
        lines.append("| - | - |")

    lines.extend(["", "## 5. 必做动作", ""])
    for item in report.get("required_actions") or []:
        lines.append(f"- {_markdown_cell(item)}")

    lines.extend(["", "## 6. 本记录不能证明的事项", ""])
    for item in report.get("not_proven_by_this_record") or []:
        lines.append(f"- {_markdown_cell(item)}")

    lines.extend(
        [
            "",
            "## 7. 填写规则",
            "",
            "- `Decision` 只能写 `include`、`defer` 或 `remove`。",
            "- `Validation` 只能写 `passed`、`blocked`、`not_run` 或 `not_required`。",
            "- 只要任一进入本次候选的 workstream 没有验收结果和验证证据摘要，不能生成正式发布包。",
            "- 建议字段只用于辅助填写，不等于签核，不能替代 release owner 的 `signoff`。",
            "- `--draft-baseline-decisions` 只生成拟填写稿，仍必须由 release owner 补充验证结果和签核。",
            "- 签核校验建议追加 `--check-current-worktree`，确认记录里的 workstream/path 没有落后于当前 Git 状态。",
            "- 冻结后必须重新运行 `scripts/check_release_candidate_freeze.py --json`，直到 `status=passed`。",
        ]
    )
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-json", type=_path_arg, default=None, help="Optional existing freeze report JSON.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    parser.add_argument("--record-id", default=None, help="Optional record id.")
    parser.add_argument(
        "--check-public-closure",
        action="store_true",
        help="When building a live freeze report, include the M1 public release closure check.",
    )
    parser.add_argument(
        "--with-suggestions",
        action="store_true",
        help="Add non-binding include/defer suggestions and evidence templates.",
    )
    parser.add_argument(
        "--draft-baseline-decisions",
        action="store_true",
        help="Prefill a non-signoff baseline candidate draft; release owner must still validate and sign off.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.freeze_json is None:
        freeze_report = build_release_candidate_freeze_report(check_public_closure=args.check_public_closure)
        source = "live_freeze_report"
    else:
        freeze_report = _load_freeze_json(args.freeze_json)
        source = f"freeze_json:{args.freeze_json.name}"
    report = build_release_candidate_freeze_record_report(
        freeze_report,
        record_id=args.record_id,
        source=source,
        include_suggestions=args.with_suggestions,
        draft_baseline_decisions=args.draft_baseline_decisions,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_release_candidate_freeze_record_markdown(report)
    )
    if args.output is None:
        print(output_text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return 0 if str(report.get("freeze_status")) == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
