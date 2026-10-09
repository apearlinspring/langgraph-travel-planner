import json
from pathlib import Path

from scripts import check_m1_rollout_execution_record as rollout


def _valid_record():
    return {
        "rollout_id": "m1-rollout-20260624",
        "started_at": "2026-06-24T17:00:00+08:00",
        "ended_at": "2026-06-24T17:30:00+08:00",
        "environment": "m1_controlled_trial",
        "release_id": "zhixing-release-abcdef1",
        "scope": "M1 controlled trial rollout",
        "owners": {
            "release_owner": "release owner",
            "deployment_owner": "deployment owner",
            "verifier": "verifier",
            "rollback_owner": "rollback owner",
            "communications_owner": "communications owner",
        },
        "release_artifact": {
            "version": "release_artifact.v1",
            "status": "passed",
            "section_statuses": {
                "git_worktree": "passed",
                "git_identity": "passed",
                "public_release_boundary": "passed",
                "artifact_write": "passed",
            },
            "artifact": {
                "archive_written": True,
                "manifest_written": True,
                "archive_sha256": "a" * 64,
                "archive_path_echoed": False,
                "manifest_path_echoed": False,
            },
            "sections": {"git_identity": {"tracked_file_count": 128}},
        },
        "deployment_steps": [
            {"phase": "release_freeze", "status": "passed", "summary": "Release candidate freeze signed off."},
            {"phase": "artifact_upload", "status": "passed", "summary": "Release archive uploaded and sha256 verified."},
            {"phase": "pre_deploy_backup", "status": "passed", "summary": "Backup point verified before rollout."},
            {"phase": "release_extract", "status": "passed", "summary": "Release extracted without touching runtime data."},
            {"phase": "runtime_refresh", "status": "passed", "summary": "Backend and caddy refreshed."},
            {"phase": "health_check", "status": "passed", "summary": "Live and ready checks passed."},
            {"phase": "post_deploy_smoke", "status": "passed", "summary": "M1 smoke checks passed."},
        ],
        "rag_rebuild_decision": {
            "required": False,
            "executed": False,
            "reason": "RAG docs unchanged, rebuild not required.",
        },
        "server_preflight": {
            "status": "passed",
            "docker_ready": "passed",
            "deploy_dir_ready": "passed",
            "disk_status": "passed",
            "health_url_ready": "passed",
            "server_target_echoed": False,
        },
        "runtime_services": {
            "backend": "passed",
            "caddy": "passed",
            "postgres": "passed",
            "redis": "passed",
        },
        "post_deploy_checks": {
            "internal_live": "passed",
            "internal_ready": "passed",
            "public_live": "passed",
            "public_ready": "passed",
            "m1_gate": "passed",
            "mock_checkout_boundary": "passed",
            "acceptance_smoke": "not_applicable",
            "acceptance_smoke_reason": "M1 rollout scoped to health, gate and mock checkout.",
        },
        "issue_log": {
            "issues_observed": True,
            "items": [
                {
                    "severity": "P2",
                    "symptom": "disk usage warning during image refresh",
                    "root_cause": "old image layers accumulated",
                    "action_taken": "recorded cleanup plan and kept release conditional until capacity was verified",
                    "verification": "server preflight and health checks reran after mitigation",
                    "status": "resolved",
                }
            ],
            "lessons_learned": "Keep disk cleanup plan ready before runtime image refresh.",
        },
        "rollback_readiness": {
            "previous_release_preserved": "passed",
            "rollback_command_documented": "passed",
            "rollback_owner_confirmed": "passed",
            "post_rollback_smoke_plan_ready": "passed",
            "backup_point_verified": "passed",
            "database_migration_rollback_plan": "not_needed",
        },
        "data_safety": {
            "dotenv_untouched": "passed",
            "postgres_volume_untouched": "passed",
            "redis_volume_untouched": "passed",
            "vectorstore_runtime_untouched_or_rebuilt_safely": "passed",
            "logs_not_committed": "passed",
            "no_runtime_data_uploaded_from_local": "passed",
            "used_git_reset_hard": False,
            "used_bulk_delete": False,
            "deleted_volumes": False,
            "printed_env_values": False,
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_server_paths_included": False,
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _server_preflight_report():
    return {
        "version": "server_preflight_readiness.v1",
        "status": "passed",
        "checks": [
            {"key": "docker_status", "status": "passed"},
            {"key": "deploy_dir", "status": "passed"},
        ],
        "docker_probe": {"status": "passed"},
        "deploy_dir_probe": {"status": "passed"},
        "disk_probe": {"status": "passed"},
        "health_probe": {"status": "passed"},
    }


def _postgres_redis_report():
    return {
        "version": "postgres_redis_live_probe.v1",
        "status": "passed",
        "declaration_statuses": {
            "ZHIXING_POSTGRES_LIVE_STATUS": "passed",
            "ZHIXING_REDIS_LIVE_STATUS": "passed",
            "ZHIXING_POSTGRES_REDIS_LIVE_STATUS": "passed",
        },
    }


def _workflow_report():
    return {
        "version": "m1_private_live_evidence_workflow.v1",
        "status": "passed",
        "go_no_go": {
            "status": "passed",
            "decision": "go_for_m1_controlled_trial",
            "section_statuses": {
                "live_server_probe": "passed",
                "m1_deployment_gate": "passed",
                "m1_smoke_evidence": "passed",
            },
        },
    }


def test_valid_rollout_execution_record_passes_without_echoing_private_text():
    report = rollout.build_m1_rollout_execution_record_report(_valid_record())
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_M1_ROLLOUT_EXECUTION_STATUS": "passed",
        "ZHIXING_RELEASE_ARTIFACT_USED_STATUS": "passed",
        "ZHIXING_POST_DEPLOY_HEALTH_STATUS": "passed",
        "ZHIXING_ROLLOUT_ROLLBACK_READY_STATUS": "passed",
        "ZHIXING_ROLLOUT_DATA_SAFETY_STATUS": "passed",
    }
    assert report["record_summary"]["deployment_phase_count"] == 7
    assert report["record_summary"]["issue_count"] == 1
    assert report["policy"]["deploys_code"] is False
    assert "release owner" not in payload
    assert "disk usage warning" not in payload
    assert "zhixing-release-abcdef1" not in payload


def test_rollout_record_blocks_missing_release_artifact_sha():
    record = _valid_record()
    record["release_artifact"]["artifact"]["archive_sha256"] = "abc"

    report = rollout.build_m1_rollout_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["release_artifact"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_RELEASE_ARTIFACT_USED_STATUS"] == "blocked"


def test_rollout_record_blocks_missing_deployment_phase():
    record = _valid_record()
    record["deployment_steps"] = record["deployment_steps"][:-1]

    report = rollout.build_m1_rollout_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["deployment_steps"]["status"] == "blocked"
    assert "post_deploy_smoke" in report["checks"]["deployment_steps"]["missing_phases"]


def test_rollout_record_blocks_unsafe_data_boundary():
    record = _valid_record()
    record["data_safety"]["deleted_volumes"] = True

    report = rollout.build_m1_rollout_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["data_safety"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_ROLLOUT_DATA_SAFETY_STATUS"] == "blocked"


def test_rollout_record_blocks_missing_post_deploy_ready():
    record = _valid_record()
    record["post_deploy_checks"]["public_ready"] = "blocked"

    report = rollout.build_m1_rollout_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["post_deploy_checks"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_POST_DEPLOY_HEALTH_STATUS"] == "blocked"


def test_rollout_record_blocks_issue_log_without_resolution():
    record = _valid_record()
    record["issue_log"]["items"][0]["status"] = "open"

    report = rollout.build_m1_rollout_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["issue_log"]["status"] == "blocked"


def test_rollout_record_blocks_raw_url_ip_secret_and_does_not_echo():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\nhttps://prod.example.com\n203.0.113.10\napi_key=secret-value-123456"

    report = rollout.build_m1_rollout_execution_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "prod.example.com" not in payload
    assert "203.0.113.10" not in payload
    assert "secret-value-123456" not in payload


def test_rollout_template_placeholders_do_not_validate_as_real_record():
    template = rollout._template_record()

    report = rollout.build_m1_rollout_execution_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"


def test_rollout_record_cli_reads_private_json(tmp_path: Path):
    record_path = tmp_path / "rollout-record.json"
    output_path = tmp_path / "rollout-report.json"
    record_path.write_text(json.dumps(_valid_record(), ensure_ascii=False), encoding="utf-8")

    code = rollout.main(["--record-json", str(record_path), "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "passed"


def test_rollout_record_draft_backfills_statuses_from_evidence():
    draft = rollout.build_m1_rollout_execution_record_draft(
        server_preflight_report=_server_preflight_report(),
        postgres_redis_report=_postgres_redis_report(),
        workflow_report=_workflow_report(),
    )
    validation = rollout.build_m1_rollout_execution_record_report(draft)

    assert draft["draft_backfill"]["status"] == "needs_manual_completion"
    assert draft["draft_backfill"]["source_paths_echoed"] is False
    assert draft["server_preflight"] == {
        "status": "passed",
        "docker_ready": "passed",
        "deploy_dir_ready": "passed",
        "disk_status": "passed",
        "health_url_ready": "passed",
        "server_target_echoed": False,
    }
    assert draft["runtime_services"]["postgres"] == "passed"
    assert draft["runtime_services"]["redis"] == "passed"
    assert draft["runtime_services"]["backend"] == "passed"
    assert draft["post_deploy_checks"]["m1_gate"] == "passed"
    assert draft["post_deploy_checks"]["acceptance_smoke"] == "passed"
    assert validation["status"] == "blocked"
    assert validation["checks"]["required_fields"]["status"] == "blocked"


def test_rollout_record_draft_cli_reads_private_evidence_without_echoing_paths(tmp_path: Path):
    server_path = tmp_path / "server-preflight.json"
    postgres_path = tmp_path / "postgres-redis.json"
    workflow_path = tmp_path / "workflow-report.json"
    output_path = tmp_path / "rollout-draft.json"
    server_path.write_text(json.dumps(_server_preflight_report()), encoding="utf-8")
    postgres_path.write_text(json.dumps(_postgres_redis_report()), encoding="utf-8")
    workflow_path.write_text(json.dumps(_workflow_report()), encoding="utf-8")

    code = rollout.main(
        [
            "--draft-from-evidence",
            "--server-preflight-json",
            str(server_path),
            "--postgres-redis-json",
            str(postgres_path),
            "--workflow-report-json",
            str(workflow_path),
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")
    draft = json.loads(payload)

    assert code == 0
    assert draft["draft_backfill"]["status"] == "needs_manual_completion"
    assert "server-preflight.json" not in payload
    assert "workflow-report.json" not in payload


def test_rollout_record_draft_blocks_raw_sensitive_evidence_without_echoing(tmp_path: Path):
    server_path = tmp_path / "server-preflight.json"
    postgres_path = tmp_path / "postgres-redis.json"
    workflow_path = tmp_path / "workflow-report.json"
    output_path = tmp_path / "rollout-draft.json"
    server_path.write_text(
        json.dumps({"status": "passed", "raw": "https://prod.example.com"}),
        encoding="utf-8",
    )
    postgres_path.write_text(json.dumps(_postgres_redis_report()), encoding="utf-8")
    workflow_path.write_text(json.dumps(_workflow_report()), encoding="utf-8")

    code = rollout.main(
        [
            "--draft-from-evidence",
            "--server-preflight-json",
            str(server_path),
            "--postgres-redis-json",
            str(postgres_path),
            "--workflow-report-json",
            str(workflow_path),
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")
    draft = json.loads(payload)

    assert code == 2
    assert draft["draft_backfill"]["status"] == "blocked"
    assert "prod.example.com" not in payload
    assert "server-preflight.json" not in payload
