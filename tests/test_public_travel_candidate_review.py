import json
from pathlib import Path

from scripts.review_public_travel_data_candidates import (
    PROJECT_ROOT,
    PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION,
    build_public_travel_candidate_review_report,
    main,
)


def _candidate_payload():
    return {
        "version": "public_travel_data_candidates.v1",
        "candidate_count": 2,
        "review_status": "human_review_required",
        "commit_ready_count": 0,
        "candidates": [
            {
                "candidate_id": "xian:wikivoyage:summary",
                "candidate_type": "destination_text_summary",
                "city_key": "xian",
                "city_name": "西安",
                "source_key": "wikivoyage",
                "source_name": "Wikivoyage",
                "source_url": "https://en.wikivoyage.org/wiki/Xi%27an",
                "license": "CC BY-SA 4.0",
                "attribution": "Wikivoyage contributors",
                "retrieved_at": "2026-06-24",
                "title": "Xi'an",
                "summary": "Xi'an is a historic city.",
                "review_required": True,
                "commit_ready": False,
                "content_boundary": "reference_only_no_inventory_or_price_lock",
            },
            {
                "candidate_id": "xian:openstreetmap:node:100",
                "candidate_type": "poi_metadata",
                "city_key": "xian",
                "city_name": "西安",
                "source_key": "openstreetmap",
                "source_name": "OpenStreetMap",
                "source_url": "https://www.openstreetmap.org/copyright",
                "license": "ODbL",
                "attribution": "OpenStreetMap contributors",
                "retrieved_at": "2026-06-24",
                "name": "Ancient City Wall",
                "tourism": "attraction",
                "review_required": True,
                "commit_ready": False,
                "content_boundary": "metadata_only_no_inventory_or_price_lock",
            },
        ],
    }


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _review_payload(*, complete=True):
    decision = {
        "candidate_id": "xian:wikivoyage:summary",
        "decision": "approve",
        "license_reviewed": True,
        "attribution_reviewed": True,
        "content_quality_reviewed": True,
        "boundary_reviewed": True,
        "review_notes": "Suitable small attributed summary.",
    }
    if not complete:
        decision["boundary_reviewed"] = False
    return {
        "version": "public_travel_candidate_review_decisions.v1",
        "reviewed_at": "2026-06-24",
        "reviewer_role": "data_reviewer",
        "decisions": [decision, {"candidate_id": "xian:openstreetmap:node:100", "decision": "defer"}],
    }


def test_candidate_review_without_review_json_is_ready_for_review(tmp_path: Path):
    candidate_json = tmp_path / "candidates.json"
    _write_json(candidate_json, _candidate_payload())

    report = build_public_travel_candidate_review_report(candidate_json=candidate_json)

    assert report["version"] == PUBLIC_TRAVEL_CANDIDATE_REVIEW_VERSION
    assert report["status"] == "ready_for_review"
    assert report["candidate_count"] == 2
    assert report["approved_count"] == 0
    assert report["policy"]["calls_external_apis"] is False
    assert report["policy"]["writes_files"] is False


def test_candidate_review_executes_approved_private_artifacts(tmp_path: Path):
    candidate_json = tmp_path / "candidates.json"
    review_json = tmp_path / "review.json"
    output_dir = tmp_path / "approved"
    _write_json(candidate_json, _candidate_payload())
    _write_json(review_json, _review_payload())

    report = build_public_travel_candidate_review_report(
        candidate_json=candidate_json,
        review_json=review_json,
        output_dir=output_dir,
        execute=True,
    )

    assert report["status"] == "passed"
    assert report["approved_count"] == 1
    assert report["rejected_or_deferred_count"] == 1
    assert report["staged_destination_draft_count"] == 1
    approved = json.loads((output_dir / "approved-public-travel-candidates.json").read_text(encoding="utf-8"))
    assert approved["approved_candidates"][0]["commit_ready"] is True
    assert (output_dir / "destination-guides" / "xian-wikivoyage-summary.md").exists()
    markdown = (output_dir / "destination-guides" / "xian-wikivoyage-summary.md").read_text(encoding="utf-8")
    assert "source_key: wikivoyage" in markdown
    assert "real inventory" in markdown


def test_candidate_review_blocks_incomplete_approval(tmp_path: Path):
    candidate_json = tmp_path / "candidates.json"
    review_json = tmp_path / "review.json"
    _write_json(candidate_json, _candidate_payload())
    _write_json(review_json, _review_payload(complete=False))

    report = build_public_travel_candidate_review_report(
        candidate_json=candidate_json,
        review_json=review_json,
        require_approved=True,
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "boundary_reviewed" for item in report["blockers"])


def test_candidate_review_blocks_project_output_by_default(tmp_path: Path):
    candidate_json = tmp_path / "candidates.json"
    review_json = tmp_path / "review.json"
    output_dir = PROJECT_ROOT / ".tmp-public-travel-candidate-review-test"
    _write_json(candidate_json, _candidate_payload())
    _write_json(review_json, _review_payload())

    report = build_public_travel_candidate_review_report(
        candidate_json=candidate_json,
        review_json=review_json,
        output_dir=output_dir,
        execute=True,
    )

    assert report["status"] == "blocked"
    assert report["blockers"][0]["key"] == "project_output_not_allowed"
    assert output_dir.exists() is False


def test_candidate_review_cli_ready_for_review(tmp_path: Path):
    candidate_json = tmp_path / "candidates.json"
    _write_json(candidate_json, _candidate_payload())

    code = main(["--candidate-json", str(candidate_json)])

    assert code == 0
