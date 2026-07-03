import json
from pathlib import Path

from scripts import render_postgres_redis_ops_env_patch as patch


def _record():
    return {
        "record_id": "postgres-redis-ops-declaration-20260625",
        "accepted_at": "2026-06-25T10:00:00+08:00",
        "scope": "M1 PostgreSQL/Redis non-secret operations declarations",
        "owner": "operations owner",
        "declarations": [
            {
                "env_var": "ZHIXING_POSTGRES_MODE",
                "accepted_value": "compose-postgresql single node for M1",
                "execution_bucket": "can_prepare_from_live_probe",
                "owner_confirmed": True,
            },
            {
                "env_var": "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS",
                "accepted_value": "0.5",
                "execution_bucket": "requires_owner_acceptance",
                "owner_confirmed": True,
            },
        ],
    }


def _record_report(status="degraded", ready="passed"):
    return {
        "version": "postgres_redis_ops_declaration_record.v1",
        "status": status,
        "declaration_statuses": {
            "ZHIXING_POSTGRES_REDIS_DECLARATION_READY_TO_WRITE_STATUS": ready,
        },
        "degraded_reasons": [
            {
                "env_var": "ZHIXING_POSTGRES_MODE",
                "finding": "single-node Compose scoped",
            }
        ]
        if status == "degraded"
        else [],
    }


def _payload_text(payload):
    return json.dumps(payload, ensure_ascii=False)


def test_env_patch_renders_degraded_private_env_lines():
    report = patch.build_postgres_redis_ops_env_patch_report(
        record=_record(),
        record_report=_record_report(),
    )
    markdown = patch.build_postgres_redis_ops_env_patch_markdown(report)

    assert report["status"] == "degraded"
    assert report["env_line_count"] == 2
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["writes_server_env"] is False
    assert 'ZHIXING_POSTGRES_MODE="compose-postgresql single node for M1"' in markdown
    assert 'SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS="0.5"' in markdown


def test_env_patch_blocks_when_record_report_is_blocked():
    report = patch.build_postgres_redis_ops_env_patch_report(
        record=_record(),
        record_report=_record_report(status="blocked", ready="blocked"),
    )
    markdown = patch.build_postgres_redis_ops_env_patch_markdown(report)

    assert report["status"] == "blocked"
    assert report["env_line_count"] == 0
    assert report["env_entries"] == []
    assert "No writable env lines" in markdown


def test_env_patch_blocks_unconfirmed_or_unsafe_values():
    record = _record()
    raw_secret = "secret-value-" + "123456"
    record["declarations"][0]["owner_confirmed"] = False
    record["declarations"][1]["accepted_value"] = "REDIS_" + "PASSWORD" + "=" + raw_secret

    report = patch.build_postgres_redis_ops_env_patch_report(
        record=record,
        record_report=_record_report(status="passed", ready="passed"),
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["env_entries"] == []
    assert raw_secret not in payload


def test_env_patch_blocks_raw_url_or_ip_values():
    record = _record()
    record["declarations"][0]["accepted_value"] = "private at https://prod.example.com"

    report = patch.build_postgres_redis_ops_env_patch_report(
        record=record,
        record_report=_record_report(status="passed", ready="passed"),
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["env_entries"] == []
    assert "prod.example.com" not in payload


def test_env_patch_cli_writes_blocked_markdown(tmp_path: Path):
    record_path = tmp_path / "record.json"
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "patch.md"
    record_path.write_text(json.dumps(_record(), ensure_ascii=False), encoding="utf-8")
    report_path.write_text(json.dumps(_record_report(status="blocked", ready="blocked"), ensure_ascii=False), encoding="utf-8")

    code = patch.main(
        [
            "--record-json",
            str(record_path),
            "--record-report-json",
            str(report_path),
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    assert "No writable env lines" in output_path.read_text(encoding="utf-8")
