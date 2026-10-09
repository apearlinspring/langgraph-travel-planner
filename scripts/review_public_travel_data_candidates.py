"""Review and stage public travel-data candidates for RAG ingestion.

This script never downloads data, calls external APIs, reads `.env`, builds a
vector store, or commits files. It reads a private candidate JSON produced by
``collect_public_travel_data_candidates.py`` and an optional human review JSON.
Only explicitly approved candidates with license, attribution, content-quality
and boundary checks can be staged into a private output directory.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION = "public_travel_candidate_review.v1"
PUBLIC_TRAVEL_CANDIDATE_REVIEW_DECISION_VERSION = "public_travel_candidate_review_decisions.v1"
PRIVATE_OUTPUT_PLACEHOLDER = "<private-workdir>"
REQUIRED_CANDIDATE_FIELDS = {
    "candidate_id",
    "candidate_type",
    "source_key",
    "source_name",
    "license",
    "attribution",
    "retrieved_at",
    "source_url",
    "review_required",
    "commit_ready",
    "content_boundary",
}
REQUIRED_APPROVAL_FLAGS = {
    "license_reviewed",
    "attribution_reviewed",
    "content_quality_reviewed",
    "boundary_reviewed",
}


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path.name}")
    return payload


def _finding(key: str, finding: str, *, target: str = "public_travel_candidate_review") -> dict[str, str]:
    return {"key": key, "target": target, "finding": finding}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    return str(candidate.get("candidate_id") or f"index:{index}")


def _validate_candidates(payload: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[dict[str, str]]]:
    candidates = payload.get("candidates")
    findings: list[dict[str, str]] = []
    if not isinstance(candidates, list) or not candidates:
        return [], [_finding("missing_candidates", "Candidate JSON must contain a non-empty candidates list.")]
    valid_candidates: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(candidates):
        if not isinstance(item, Mapping):
            findings.append(_finding("candidate_shape", "Candidate must be an object.", target=f"index:{index}"))
            continue
        candidate_key = _candidate_id(item, index)
        if candidate_key in seen:
            findings.append(_finding("duplicate_candidate_id", "candidate_id must be unique.", target=candidate_key))
        seen.add(candidate_key)
        for field in sorted(REQUIRED_CANDIDATE_FIELDS):
            if field == "commit_ready":
                continue
            if _is_blank(item.get(field)):
                findings.append(_finding(field, "Required candidate field is missing.", target=candidate_key))
        if item.get("commit_ready") is not False:
            findings.append(_finding("commit_ready", "Raw candidates must be commit_ready=false before human review.", target=candidate_key))
        if item.get("review_required") is not True:
            findings.append(_finding("review_required", "Raw candidates must be review_required=true.", target=candidate_key))
        valid_candidates.append(item)
    return valid_candidates, findings


def _decision_target(decision: Mapping[str, Any]) -> str:
    if not _is_blank(decision.get("candidate_id")):
        return str(decision.get("candidate_id"))
    if not _is_blank(decision.get("candidate_index")):
        return f"index:{decision.get('candidate_index')}"
    return ""


def _decisions_by_target(review_payload: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, str]]]:
    decisions = review_payload.get("decisions")
    findings: list[dict[str, str]] = []
    if not isinstance(decisions, list) or not decisions:
        return {}, [_finding("missing_decisions", "Review JSON must contain a non-empty decisions list.", target="review_json")]
    mapped: dict[str, Mapping[str, Any]] = {}
    for index, decision in enumerate(decisions):
        if not isinstance(decision, Mapping):
            findings.append(_finding("decision_shape", "Review decision must be an object.", target=f"decision:{index}"))
            continue
        target = _decision_target(decision)
        if not target:
            findings.append(_finding("candidate_id", "Decision must specify candidate_id or candidate_index.", target=f"decision:{index}"))
            continue
        if target in mapped:
            findings.append(_finding("duplicate_decision", "Only one decision is allowed per candidate.", target=target))
            continue
        mapped[target] = decision
    return mapped, findings


def _approved_candidates(
    candidates: list[Mapping[str, Any]],
    review_payload: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    if review_payload is None:
        return [], [], 0
    decisions, findings = _decisions_by_target(review_payload)
    candidate_by_id = {_candidate_id(candidate, index): candidate for index, candidate in enumerate(candidates)}
    candidate_by_index = {f"index:{index}": candidate for index, candidate in enumerate(candidates)}
    approved: list[dict[str, Any]] = []
    rejected_count = 0
    for target, decision in decisions.items():
        candidate = candidate_by_id.get(target) or candidate_by_index.get(target)
        if candidate is None:
            findings.append(_finding("unknown_candidate", "Review decision points to an unknown candidate.", target=target))
            continue
        decision_value = str(decision.get("decision") or "").strip().lower()
        if decision_value in {"reject", "rejected", "defer", "deferred"}:
            rejected_count += 1
            continue
        if decision_value not in {"approve", "approved"}:
            findings.append(_finding("decision", "Decision must be approve, reject or defer.", target=target))
            continue
        for flag in sorted(REQUIRED_APPROVAL_FLAGS):
            if decision.get(flag) is not True:
                findings.append(_finding(flag, "Approval requires explicit true review flag.", target=target))
        if any(item["target"] == target for item in findings):
            continue
        reviewed = dict(candidate)
        reviewed.update(
            {
                "review_status": "approved",
                "commit_ready": True,
                "reviewed_at": review_payload.get("reviewed_at") or datetime.now(UTC).date().isoformat(),
                "reviewer_role": review_payload.get("reviewer_role") or "data_reviewer",
                "review_notes": decision.get("review_notes") or "",
            }
        )
        approved.append(reviewed)
    return approved, findings, rejected_count


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return safe.strip(".-_") or "candidate"


def _markdown_for_destination_candidate(candidate: Mapping[str, Any]) -> str:
    title = str(candidate.get("title") or candidate.get("city_name") or "Public travel candidate").strip()
    city_key = str(candidate.get("city_key") or "unknown").strip()
    return (
        "---\n"
        f"title: {title} public travel source candidate\n"
        "category: destinations\n"
        "source_type: destination_guide\n"
        "visibility: public\n"
        "applicable_modes:\n"
        "  - free_planning\n"
        "  - agency_plan\n"
        "evidence_level: guide\n"
        f"last_reviewed: {candidate.get('reviewed_at') or datetime.now(UTC).date().isoformat()}\n"
        f"source_key: {candidate.get('source_key')}\n"
        f"source_name: {candidate.get('source_name')}\n"
        f"source_url: {candidate.get('source_url')}\n"
        f"license: {candidate.get('license')}\n"
        f"attribution: {candidate.get('attribution')}\n"
        f"retrieved_at: {candidate.get('retrieved_at')}\n"
        "data_origin: external_public_license\n"
        "content_boundary: reference_only_no_inventory_or_price_lock\n"
        "---\n\n"
        f"# {title} public travel source candidate\n\n"
        "> Reviewed public-source candidate for RAG ingestion. This document is reference-only and does not represent real inventory, realtime pricing, booking confirmation, ticketing or fulfillment.\n\n"
        f"City key: `{city_key}`\n\n"
        "## Summary\n\n"
        f"{candidate.get('summary') or ''}\n\n"
        "## Attribution\n\n"
        f"- Source: {candidate.get('source_name')}\n"
        f"- URL: {candidate.get('source_url')}\n"
        f"- License: {candidate.get('license')}\n"
        f"- Attribution: {candidate.get('attribution')}\n"
    )


def _readme(report: Mapping[str, Any]) -> str:
    return (
        "# Reviewed Public Travel Data Candidates\n\n"
        "This private folder contains reviewed public-data candidates staged for later RAG ingestion.\n\n"
        "## Boundary\n\n"
        "- Staged artifacts are not automatically committed by this script.\n"
        "- Destination Markdown drafts still require a final human pass before copying into `data/documents/`.\n"
        "- Approved metadata does not prove facts are fresh or that media reuse is fully cleared beyond the recorded review.\n"
        "- No artifact proves real inventory, price lock, booking, ticketing or fulfillment.\n\n"
        f"Approved candidates: `{report.get('approved_count')}`\n"
    )


def build_public_travel_candidate_review_report(
    *,
    candidate_json: Path,
    review_json: Path | None = None,
    output_dir: Path | None = None,
    execute: bool = False,
    allow_project_output: bool = False,
    require_approved: bool = False,
) -> dict[str, Any]:
    """Validate candidate review state and optionally stage approved artifacts."""

    try:
        candidate_payload = _load_json(candidate_json, label="candidate JSON")
    except ValueError as exc:
        return {
            "version": PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION,
            "status": "blocked",
            "blockers": [_finding("candidate_json", str(exc), target="candidate_json")],
        }
    review_payload: dict[str, Any] | None = None
    if review_json is not None:
        try:
            review_payload = _load_json(review_json, label="review JSON")
        except ValueError as exc:
            return {
                "version": PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION,
                "status": "blocked",
                "blockers": [_finding("review_json", str(exc), target="review_json")],
            }
    candidates, candidate_findings = _validate_candidates(candidate_payload)
    approved, review_findings, rejected_count = _approved_candidates(candidates, review_payload)
    blockers = [*candidate_findings, *review_findings]
    inside_project = bool(output_dir and _is_relative_to(output_dir, PROJECT_ROOT))
    report: dict[str, Any] = {
        "version": PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION,
        "status": "blocked",
        "policy": {
            "reads_dotenv": False,
            "downloads_data": False,
            "calls_external_apis": False,
            "builds_vectorstore": False,
            "writes_files": execute,
            "records_source_path": False,
            "output_should_remain_private": True,
        },
        "target": {
            "candidate_json": candidate_json.name,
            "review_json": review_json.name if review_json else "",
            "output_dir": PRIVATE_OUTPUT_PLACEHOLDER if output_dir else "",
            "output_dir_inside_project": inside_project,
            "allow_project_output": allow_project_output,
        },
        "candidate_count": len(candidates),
        "approved_count": len(approved),
        "rejected_or_deferred_count": rejected_count,
        "not_proven_by_this_review": [
            "Review does not download or refresh public source data.",
            "Approved candidates still require final editorial review before committing to public RAG documents.",
            "Approval does not prove facts are fresh, media reuse is fully cleared, or vector-store retrieval passes.",
            "Approval does not prove real inventory, realtime price, booking, ticketing or fulfillment.",
        ],
    }
    if blockers:
        report["status"] = "blocked"
        report["blockers"] = blockers
        return report
    if require_approved and not approved:
        report["status"] = "blocked"
        report["blockers"] = [_finding("no_approved_candidates", "No approved candidates are available.")]
        return report
    if review_payload is None or not approved:
        report["status"] = "ready_for_review"
        return report
    if not execute:
        report["status"] = "ready_to_write"
        return report
    if output_dir is None:
        report["status"] = "blocked"
        report["blockers"] = [_finding("missing_output_dir", "Execution requires --output-dir outside the Git workspace.")]
        return report
    if inside_project and not allow_project_output:
        report["status"] = "blocked"
        report["blockers"] = [
            _finding("project_output_not_allowed", "Use a private output directory outside the Git workspace or pass --allow-project-output.")
        ]
        return report

    output_dir.mkdir(parents=True, exist_ok=True)
    approved_payload = {
        "version": PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION,
        "review_decision_version": PUBLIC_TRAVEL_CANDIDATE_REVIEW_DECISION_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "approved_count": len(approved),
        "approved_candidates": approved,
    }
    approved_path = output_dir / "approved-public-travel-candidates.json"
    approved_path.write_text(json.dumps(approved_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    draft_dir = output_dir / "destination-guides"
    draft_count = 0
    for candidate in approved:
        if candidate.get("candidate_type") != "destination_text_summary":
            continue
        draft_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(str(candidate.get("candidate_id") or candidate.get("title") or "destination")) + ".md"
        (draft_dir / filename).write_text(_markdown_for_destination_candidate(candidate), encoding="utf-8")
        draft_count += 1
    readme_path = output_dir / "README.md"
    report["staged_destination_draft_count"] = draft_count
    readme_path.write_text(_readme(report), encoding="utf-8")
    report.update(
        {
            "status": "passed",
            "artifact_paths": [
                {"role": "approved_candidates", "path": approved_path.name},
                {"role": "review_readme", "path": readme_path.name},
                {"role": "destination_guide_drafts", "path": "destination-guides/"},
            ],
        }
    )
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-json", type=_path_arg, required=True)
    parser.add_argument("--review-json", type=_path_arg, default=None)
    parser.add_argument("--output-dir", type=_path_arg, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-project-output", action="store_true")
    parser.add_argument("--require-approved", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_public_travel_candidate_review_report(
        candidate_json=args.candidate_json,
        review_json=args.review_json,
        output_dir=args.output_dir,
        execute=args.execute,
        allow_project_output=args.allow_project_output,
        require_approved=args.require_approved,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
