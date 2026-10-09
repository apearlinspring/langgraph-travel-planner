import json
from pathlib import Path

from scripts.collect_public_travel_data_candidates import (
    PROJECT_ROOT,
    PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION,
    build_public_travel_data_candidates_report,
    main,
)


def _fake_get_json(url, params, timeout_seconds):
    if "wikivoyage" in url:
        return {
            "title": "Xi'an",
            "extract": "Xi'an is a historic city with ancient city walls and museums.",
            "content_urls": {"desktop": {"page": "https://en.wikivoyage.org/wiki/Xi%27an"}},
        }
    if "commons.wikimedia.org" in url:
        return {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Xian city wall.jpg",
                        "imageinfo": [
                            {
                                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Xian_city_wall.jpg",
                                "thumburl": "https://upload.wikimedia.org/thumb/example.jpg",
                                "mime": "image/jpeg",
                                "extmetadata": {
                                    "Artist": {"value": "Example author"},
                                    "UsageTerms": {"value": "CC BY-SA 4.0"},
                                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                },
                            }
                        ],
                    }
                }
            }
        }
    raise AssertionError(f"Unexpected GET URL: {url}")


def _fake_post_json(url, params, timeout_seconds):
    assert "overpass" in url
    assert "tourism" in params["data"]
    return {
        "elements": [
            {
                "type": "node",
                "id": 100,
                "lat": 34.25,
                "lon": 108.95,
                "tags": {"name": "Ancient City Wall", "tourism": "attraction"},
            }
        ]
    }


def test_public_travel_data_candidates_plan_does_not_call_network():
    def fail_get(url, params, timeout_seconds):
        raise AssertionError("network should not be called")

    report = build_public_travel_data_candidates_report(
        city_keys=("xian",),
        execute=False,
        get_json=fail_get,
        post_json=fail_get,
    )

    assert report["status"] == "not_checked"
    assert report["version"] == PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION
    assert report["policy"]["calls_external_apis"] is False
    assert report["policy"]["writes_files"] is False
    assert report["planned_city_count"] == 1


def test_public_travel_data_candidates_execute_writes_private_artifacts(tmp_path: Path):
    output_dir = tmp_path / "candidates"

    report = build_public_travel_data_candidates_report(
        city_keys=("xian",),
        execute=True,
        output_dir=output_dir,
        max_pois=1,
        max_images=1,
        get_json=_fake_get_json,
        post_json=_fake_post_json,
    )

    assert report["status"] == "passed"
    assert report["candidate_count"] == 3
    assert report["commit_ready_count"] == 0
    payload = json.loads((output_dir / "public-travel-data-candidates.json").read_text(encoding="utf-8"))
    assert payload["review_status"] == "human_review_required"
    assert {item["candidate_type"] for item in payload["candidates"]} == {
        "destination_text_summary",
        "poi_metadata",
        "image_metadata",
    }
    assert all(item["review_required"] is True for item in payload["candidates"])
    assert all(item["commit_ready"] is False for item in payload["candidates"])
    assert (output_dir / "README.md").exists()


def test_public_travel_data_candidates_blocks_project_output_by_default(tmp_path: Path):
    output_dir = PROJECT_ROOT / ".tmp-public-travel-data-candidates-test"

    report = build_public_travel_data_candidates_report(
        city_keys=("xian",),
        execute=True,
        output_dir=output_dir,
        get_json=_fake_get_json,
        post_json=_fake_post_json,
    )

    assert report["status"] == "blocked"
    assert report["blockers"][0]["key"] == "project_output_not_allowed"
    assert output_dir.exists() is False


def test_public_travel_data_candidates_degrades_when_one_source_fails(tmp_path: Path):
    def failing_get(url, params, timeout_seconds):
        if "wikivoyage" in url:
            raise TimeoutError("timeout")
        return _fake_get_json(url, params, timeout_seconds)

    report = build_public_travel_data_candidates_report(
        city_keys=("xian",),
        execute=True,
        output_dir=tmp_path / "candidates",
        max_pois=1,
        max_images=1,
        get_json=failing_get,
        post_json=_fake_post_json,
    )

    assert report["status"] == "degraded"
    assert report["candidate_count"] == 2
    assert report["degraded_reasons"][0]["key"] == "wikivoyage_fetch_failed"


def test_public_travel_data_candidates_cli_plan_returns_zero():
    code = main(["--city", "xian"])

    assert code == 0
