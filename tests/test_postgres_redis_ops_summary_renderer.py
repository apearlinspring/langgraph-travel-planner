import json
from pathlib import Path

from scripts import render_postgres_redis_ops_summary as summary


def _ops_status(status="passed"):
    return {
        "version": "postgres_redis_ops_status.v1",
        "status": status,
        "declaration_statuses": {
            "ZHIXING_POSTGRES_REDIS_OPS_STATUS": status,
            "ZHIXING_POSTGRES_OPS_STATUS": status,
            "ZHIXING_REDIS_OPS_STATUS": status,
        },
        "blocked_reasons": [],
        "degraded_reasons": (
            [
                {
                    "env_var": "ZHIXING_POSTGRES_MODE",
                    "finding": "single-node Compose is acceptable for M1 but not HA",
                }
            ]
            if status == "degraded"
            else []
        ),
    }


def _live_probe(status="passed"):
    return {
        "version": "postgres_redis_live_probe.v1",
        "status": status,
        "target": {
            "ssh_target": "<server-target>",
            "deploy_dir": "<deploy-dir>",
        },
        "sections": {
            "postgres_container": {
                "status": status,
                "state": "running",
                "health": "healthy",
                "ports": {"public_bindings": []},
                "mounts": {"expected_destination_present": True},
            },
            "postgres_pg_isready": {"status": "passed"},
            "redis_container": {
                "status": status,
                "state": "running",
                "health": "healthy",
                "ports": {"public_bindings": []},
                "mounts": {"expected_destination_present": True},
            },
            "redis_ping": {"status": "passed"},
            "redis_appendonly": {"status": "passed"},
        },
        "declaration_statuses": {
            "ZHIXING_POSTGRES_LIVE_STATUS": status,
            "ZHIXING_REDIS_LIVE_STATUS": status,
            "ZHIXING_POSTGRES_REDIS_LIVE_STATUS": status,
        },
        "blocked_reasons": [],
        "degraded_reasons": [],
    }


def _recovery_record(status="passed"):
    return {
        "version": "postgres_redis_recovery_record.v1",
        "status": status,
        "record_summary": {
            "mode": "combined_stateful_recovery_drill",
            "affected_services": ["postgres", "redis"],
            "owner_roles_present": 4,
            "action_count": 4,
        },
        "checks": {
            "data_safety": {"status": status},
            "post_recovery_health": {"status": status},
            "observed_metrics": {"status": status},
        },
        "declaration_statuses": {
            "ZHIXING_POSTGRES_REDIS_RECOVERY_RECORD_STATUS": status,
            "ZHIXING_POSTGRES_RECOVERY_STATUS": status,
            "ZHIXING_REDIS_RECOVERY_STATUS": status,
            "ZHIXING_STATEFUL_DATA_SAFETY_STATUS": status,
        },
        "blocked_reasons": [],
        "degraded_reasons": [],
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_ops_summary_passes_when_all_stateful_evidence_passes():
    report = summary.build_postgres_redis_ops_summary_report(
        ops_status=_ops_status(),
        live_probe=_live_probe(),
        recovery_record=_recovery_record(),
    )

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_stateful_ops"
    assert report["blocked_reasons"] == []
    assert report["section_statuses"] == {
        "ops_status": "passed",
        "live_probe": "passed",
        "recovery_record": "passed",
    }
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["connects_database"] is False
    assert report["policy"]["connects_redis"] is False


def test_ops_summary_blocks_missing_live_probe():
    report = summary.build_postgres_redis_ops_summary_report(
        ops_status=_ops_status(),
        live_probe=None,
        recovery_record=_recovery_record(),
    )

    assert report["status"] == "blocked"
    assert report["section_statuses"]["live_probe"] == "not_checked"
    assert any(item["key"] == "live_probe_json" for item in report["blocked_reasons"])


def test_ops_summary_degrades_single_node_but_keeps_claim_boundary():
    report = summary.build_postgres_redis_ops_summary_report(
        ops_status=_ops_status(status="degraded"),
        live_probe=_live_probe(),
        recovery_record=_recovery_record(),
    )

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go_for_m1_with_recorded_stateful_limits"
    assert any("HA" in item for item in report["claim_boundaries"]["cannot_claim"])
    assert any(item["section"] == "ops_status" for item in report["degraded_reasons"])


def test_ops_summary_redacts_raw_url_ip_and_secret_like_reason():
    ops = _ops_status(status="blocked")
    raw_url = "https://" + "prod." + "example.com"
    raw_ip = "203.0." + "113.10"
    raw_secret = "secret-value-" + "123456"
    ops["blocked_reasons"] = [
        {
            "env_var": "ZHIXING_REDIS_SECRET_STATUS",
            "finding": f"see {raw_url} and {raw_ip} pass" + f"word={raw_secret}",
        }
    ]

    report = summary.build_postgres_redis_ops_summary_report(
        ops_status=ops,
        live_probe=_live_probe(),
        recovery_record=_recovery_record(),
    )
    markdown = summary.build_postgres_redis_ops_summary_markdown(report)
    payload = _payload_text(report) + markdown

    assert report["status"] == "blocked"
    assert raw_url not in payload
    assert raw_ip not in payload
    assert raw_secret not in payload
    assert "[REDACTED_URL]" in payload
    assert "[REDACTED_IP]" in payload


def test_ops_summary_cli_writes_markdown(tmp_path: Path):
    ops_path = tmp_path / "ops.json"
    live_path = tmp_path / "live.json"
    recovery_path = tmp_path / "recovery.json"
    output_path = tmp_path / "summary.md"
    ops_path.write_text(json.dumps(_ops_status(), ensure_ascii=False), encoding="utf-8")
    live_path.write_text(json.dumps(_live_probe(), ensure_ascii=False), encoding="utf-8")
    recovery_path.write_text(json.dumps(_recovery_record(), ensure_ascii=False), encoding="utf-8")

    code = summary.main(
        [
            "--ops-status-json",
            str(ops_path),
            "--live-probe-json",
            str(live_path),
            "--recovery-record-json",
            str(recovery_path),
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    content = output_path.read_text(encoding="utf-8")
    assert "PostgreSQL / Redis Operations Summary" in content
    assert "go_for_m1_stateful_ops" in content
