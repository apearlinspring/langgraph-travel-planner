import json
from pathlib import Path

from scripts import render_postgres_redis_ops_declaration_request as request


def _ops_status():
    return {
        "version": "postgres_redis_ops_status.v1",
        "status": "blocked",
        "blocked_reasons": [
            {
                "key": "postgres_mode",
                "env_var": "ZHIXING_POSTGRES_MODE",
                "finding": "Required operations declaration is missing or placeholder-like.",
            },
            {
                "key": "redis_public_exposure",
                "env_var": "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS",
                "finding": "Required operations declaration is missing or placeholder-like.",
            },
            {
                "key": "postgres_restore_drill",
                "env_var": "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
                "finding": "Required operations declaration is missing or placeholder-like.",
            },
        ],
    }


def _live_probe():
    return {
        "version": "postgres_redis_live_probe.v1",
        "status": "passed",
        "declaration_statuses": {
            "ZHIXING_POSTGRES_LIVE_STATUS": "passed",
            "ZHIXING_REDIS_LIVE_STATUS": "passed",
        },
        "sections": {
            "postgres_container": {
                "ports": {"public_bindings": []},
            },
            "redis_container": {
                "ports": {"public_bindings": []},
            },
            "redis_appendonly": {"status": "passed"},
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_declaration_request_extracts_missing_ops_vars_without_values():
    report = request.build_postgres_redis_ops_declaration_request(
        ops_status=_ops_status(),
        live_probe=_live_probe(),
    )
    by_name = {item["env_var"]: item for item in report["declarations"]}

    assert report["status"] == "blocked"
    assert report["missing_count"] == 3
    assert by_name["ZHIXING_POSTGRES_MODE"]["suggested_value"] == "compose-postgresql single node for M1"
    assert by_name["ZHIXING_POSTGRES_MODE"]["confidence"] == "suggested_from_live_probe"
    assert by_name["ZHIXING_POSTGRES_MODE"]["execution_bucket"] == "can_prepare_from_live_probe"
    assert by_name["ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS"]["confidence"] == "suggested_from_live_probe"
    assert (
        by_name["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["execution_bucket"]
        == "requires_backup_or_restore_artifact"
    )
    assert by_name["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["confidence"] == "requires_operator_confirmation"
    assert report["execution_bucket_counts"] == {
        "can_prepare_from_live_probe": 2,
        "requires_backup_or_restore_artifact": 1,
    }
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["writes_server_env"] is False


def test_declaration_request_markdown_contains_template_lines():
    report = request.build_postgres_redis_ops_declaration_request(
        ops_status=_ops_status(),
        live_probe=_live_probe(),
    )

    markdown = request.build_postgres_redis_ops_declaration_request_markdown(report)

    assert "PostgreSQL / Redis Ops Declaration Request" in markdown
    assert "ZHIXING_POSTGRES_MODE" in markdown
    assert "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS" in markdown
    assert "can_prepare_from_live_probe" in markdown
    assert "requires_backup_or_restore_artifact" in markdown
    assert "no `.env`" in markdown
    assert "## Boundary" in markdown
    assert "The declarations have been written to the server." in markdown


def test_declaration_request_redacts_sensitive_shaped_input():
    ops = _ops_status()
    raw_secret = "secret-value-" + "123456"
    sensitive_env_name = "POSTGRES_" + "PASSWORD"
    ops["blocked_reasons"].append(
        {
            "key": "unsafe_echo",
            "env_var": f"{sensitive_env_name}={raw_secret}",
            "finding": "Operator accidentally pasted a secret-shaped env assignment.",
        }
    )

    report = request.build_postgres_redis_ops_declaration_request(
        ops_status=ops,
        live_probe=_live_probe(),
    )
    payload = _payload_text(report)

    assert raw_secret not in payload
    assert sensitive_env_name in payload
    assert f"{sensitive_env_name}={raw_secret}" not in payload


def test_declaration_request_cli_writes_markdown(tmp_path: Path):
    ops_path = tmp_path / "ops.json"
    live_path = tmp_path / "live.json"
    output_path = tmp_path / "request.md"
    ops_path.write_text(json.dumps(_ops_status(), ensure_ascii=False), encoding="utf-8")
    live_path.write_text(json.dumps(_live_probe(), ensure_ascii=False), encoding="utf-8")

    code = request.main(
        [
            "--ops-status-json",
            str(ops_path),
            "--live-probe-json",
            str(live_path),
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    assert "ZHIXING_POSTGRES_MODE" in output_path.read_text(encoding="utf-8")
