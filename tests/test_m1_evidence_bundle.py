import json
from pathlib import Path

from scripts.build_m1_evidence_bundle import (
    M1_EVIDENCE_BUNDLE_VERSION,
    PROJECT_ROOT,
    build_m1_evidence_bundle_report,
    main,
)


def _go_no_go_report():
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": "degraded",
        "decision": "conditional_go",
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "may_connect_ssh": True,
            "may_call_external_apis": False,
            "may_write_runtime_artifacts": False,
        },
        "target": {
            "public_base_url_present": True,
            "public_base_url_echoed": False,
            "public_url": "https://prod.example.com",
            "server_ip": "203.0.113.10",
        },
        "section_statuses": {
            "live_server_probe": "passed",
            "postgres_redis_live_probe": "passed",
            "probe_auth_readiness": "degraded",
        },
        "sections": {
            "live_server_probe": {
                "status": "passed",
                "sections": {
                    "host": {"status": "passed", "address": "203.0.113.10"},
                    "compose_services": {"status": "passed"},
                    "internal_health": {"status": "passed"},
                    "server_side_public_health": {
                        "status": "passed",
                        "url": "https://prod.example.com/health/ready",
                    },
                    "mock_checkout": {"status": "passed"},
                },
            },
            "postgres_redis_live_probe": {
                "status": "passed",
                "sections": {
                    "postgres": {"status": "passed"},
                    "redis": {"status": "passed"},
                },
            },
            "probe_auth_readiness": {
                "status": "degraded",
                "target": {"auth_strategy": "probe_login", "username": "probe-user"},
                "observations": {
                    "login_performed": False,
                    "me_checked": False,
                    "token_validated": False,
                },
            },
        },
        "blockers": [],
        "degraded_reasons": [
            {
                "section": "probe_auth_readiness",
                "key": "auth_not_executed",
                "finding": "token sk-live-secret-123456 for 13800138000 was not executed",
            }
        ],
        "not_proven_by_this_report": [
            "A go decision is only for M1 controlled trial traffic.",
        ],
    }


def _write_report(path: Path) -> None:
    path.write_text(json.dumps(_go_no_go_report(), ensure_ascii=False), encoding="utf-8")


def test_evidence_bundle_plan_does_not_write_files(tmp_path: Path):
    source = tmp_path / "go-no-go.json"
    output_dir = tmp_path / "bundle"
    _write_report(source)

    report = build_m1_evidence_bundle_report(
        go_no_go_json=source,
        output_dir=output_dir,
        execute=False,
    )

    assert report["status"] == "ready_to_write"
    assert report["version"] == M1_EVIDENCE_BUNDLE_VERSION
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["writes_files"] is False
    assert report["target"]["source_path_echoed"] is False
    assert output_dir.exists() is False
    assert {item["role"] for item in report["artifact_digests"]} == {
        "redacted_go_no_go_json",
        "live_evidence_summary_markdown",
        "bundle_readme",
    }


def test_evidence_bundle_execute_writes_redacted_artifacts(tmp_path: Path):
    source = tmp_path / "go-no-go.json"
    output_dir = tmp_path / "bundle"
    _write_report(source)

    report = build_m1_evidence_bundle_report(
        go_no_go_json=source,
        output_dir=output_dir,
        execute=True,
    )

    assert report["status"] == "passed"
    assert report["policy"]["writes_files"] is True
    assert {item["role"] for item in report["artifacts"]} == {
        "redacted_go_no_go_json",
        "live_evidence_summary_markdown",
        "bundle_readme",
        "bundle_manifest",
    }
    for relative_path in [
        "m1-go-no-go.redacted.json",
        "m1-live-evidence-summary.md",
        "README.md",
        "manifest.json",
    ]:
        payload = (output_dir / relative_path).read_text(encoding="utf-8")
        assert "https://prod.example.com" not in payload
        assert "203.0.113.10" not in payload
        assert "sk-live-secret-123456" not in payload
        assert "13800138000" not in payload
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["go_no_go"]["decision"] == "conditional_go"
    assert manifest["target"]["output_dir"] == "<private-workdir>"
    assert manifest["target"]["source_path_echoed"] is False


def test_evidence_bundle_blocks_project_output_by_default(tmp_path: Path):
    source = tmp_path / "go-no-go.json"
    _write_report(source)
    output_dir = PROJECT_ROOT / ".tmp-m1-evidence-bundle-test"

    report = build_m1_evidence_bundle_report(
        go_no_go_json=source,
        output_dir=output_dir,
        execute=True,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "project_output_not_allowed"
    assert output_dir.exists() is False


def test_evidence_bundle_cli_writes_bundle(tmp_path: Path):
    source = tmp_path / "go-no-go.json"
    output_dir = tmp_path / "bundle"
    _write_report(source)

    code = main(["--go-no-go-json", str(source), "--output-dir", str(output_dir), "--execute"])

    assert code == 0
    assert (output_dir / "manifest.json").exists()
    assert "M1 Evidence Bundle" in (output_dir / "README.md").read_text(encoding="utf-8")
