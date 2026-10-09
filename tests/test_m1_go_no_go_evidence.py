import json
from pathlib import Path

from scripts import collect_m1_go_no_go_evidence as go_no_go


PUBLIC_URL = "https://m1.zhixing.com"


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _passed_report(version="fake.v1"):
    return {
        "version": version,
        "status": "passed",
        "section_statuses": {"declared": "passed"},
    }


def _live_chat_approval_report(status="passed"):
    return {
        "version": "live_chat_probe_execution_approval.v1",
        "status": status,
        "decision": "approved_for_one_live_chat_probe" if status == "passed" else "not_ready_for_live_chat_probe",
        "sections": {"approval_record": {"status": status}},
        "blocked_reasons": []
        if status == "passed"
        else [{"key": "approval_not_ready", "finding": "Approval is not ready."}],
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_default_go_no_go_report_is_plan_only():
    report = go_no_go.build_m1_go_no_go_report(environ={})

    assert report["status"] == "not_checked"
    assert report["decision"] == "not_checked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["starts_services"] is False
    assert report["policy"]["executes_rollback"] is False
    assert report["sections"] == {}
    assert "server_domain_tls" in _payload_text(report)


def test_all_declared_evidence_passes_when_all_sections_pass(monkeypatch):
    monkeypatch.setattr(
        go_no_go,
        "build_m1_deployment_gate_report",
        lambda **kwargs: {**_passed_report("gate.v1"), "base_url": kwargs["base_url"]},
    )
    monkeypatch.setattr(
        go_no_go,
        "build_m1_smoke_evidence_report",
        lambda **kwargs: {**_passed_report("smoke.v1"), "target": {"base_url": kwargs["base_url"]}},
    )
    monkeypatch.setattr(
        go_no_go,
        "build_backup_restore_drill_evidence_report",
        lambda **kwargs: _passed_report("backup.v1"),
    )
    monkeypatch.setattr(
        go_no_go,
        "build_postgres_redis_ops_status_report",
        lambda **kwargs: _passed_report("postgres-redis.v1"),
    )
    monkeypatch.setattr(
        go_no_go,
        "build_monitoring_alerting_evidence_report",
        lambda **kwargs: _passed_report("monitoring.v1"),
    )
    monkeypatch.setattr(
        go_no_go,
        "build_incident_rollback_evidence_report",
        lambda **kwargs: _passed_report("incident.v1"),
    )

    report = go_no_go.build_m1_go_no_go_report(
        environ={"ZHIXING_PUBLIC_BASE_URL": PUBLIC_URL},
        include_all_declared_evidence=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert set(report["section_statuses"]) == {
        "m1_deployment_gate",
        "m1_smoke_evidence",
        "backup_restore_drill_evidence",
        "postgres_redis_ops_evidence",
        "monitoring_alerting_evidence",
        "incident_rollback_evidence",
    }
    assert PUBLIC_URL not in payload
    assert "<public-url>" in payload


def test_external_dependency_resilience_record_can_be_included_without_echoing_path(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_external_dependency_record(record, *, raw_text="", generated_at=None):
        captured["record"] = record
        captured["raw_text"] = raw_text
        return {
            "version": "external_dependency_resilience_record.v1",
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "calls_external_providers": False,
                "connects_network": False,
                "connects_ssh": False,
                "record_text_echoed": False,
            },
            "record_summary": {"degradation_scenario_count": 3},
            "blocked_reasons": [],
        }

    monkeypatch.setattr(
        go_no_go,
        "build_external_dependency_resilience_record_report",
        fake_external_dependency_record,
    )
    record_path = tmp_path / "private-external-dependency-record.json"
    record_path.write_text(
        json.dumps({"record_id": "external-dependency-resilience-20260624"}),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_external_dependency_resilience_record=True,
        external_dependency_record_json=record_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["external_dependency_resilience_record"] == "passed"
    assert report["policy"]["reads_external_dependency_resilience_record"] is True
    assert report["policy"]["calls_external_providers_for_dependency_record"] is False
    assert captured["record"]["record_id"] == "external-dependency-resilience-20260624"
    assert str(record_path) not in payload


def test_external_dependency_resilience_missing_record_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_external_dependency_resilience_record=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["external_dependency_resilience_record"] == "blocked"
    assert any(item["key"] == "external_dependency_record_json" for item in report["blockers"])


def test_m1_rollout_execution_record_can_be_included_without_echoing_path(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_rollout_record(record, *, raw_text="", generated_at=None):
        captured["record"] = record
        captured["raw_text"] = raw_text
        return {
            "version": "m1_rollout_execution_record.v1",
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "deploys_code": False,
                "connects_ssh": False,
                "starts_services": False,
                "record_text_echoed": False,
            },
            "record_summary": {"deployment_phase_count": 7},
            "blocked_reasons": [],
        }

    monkeypatch.setattr(
        go_no_go,
        "build_m1_rollout_execution_record_report",
        fake_rollout_record,
    )
    record_path = tmp_path / "private-m1-rollout-record.json"
    record_path.write_text(json.dumps({"rollout_id": "m1-rollout-20260624"}), encoding="utf-8")

    report = go_no_go.build_m1_go_no_go_report(
        include_m1_rollout_execution_record=True,
        m1_rollout_record_json=record_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["m1_rollout_execution_record"] == "passed"
    assert report["policy"]["reads_m1_rollout_execution_record"] is True
    assert report["policy"]["deploys_code_for_rollout_record"] is False
    assert captured["record"]["rollout_id"] == "m1-rollout-20260624"
    assert str(record_path) not in payload


def test_m1_rollout_execution_missing_record_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_m1_rollout_execution_record=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["m1_rollout_execution_record"] == "blocked"
    assert any(item["key"] == "m1_rollout_record_json" for item in report["blockers"])


def test_m1_operations_review_record_can_be_included_without_echoing_path(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_operations_review(record, *, raw_text="", generated_at=None):
        captured["record"] = record
        captured["raw_text"] = raw_text
        return {
            "version": "m1_operations_review_record.v1",
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "connects_ssh": False,
                "queries_database": False,
                "reads_raw_logs": False,
                "record_text_echoed": False,
            },
            "record_summary": {"issue_count": 1, "followup_count": 1},
            "blocked_reasons": [],
        }

    monkeypatch.setattr(
        go_no_go,
        "build_m1_operations_review_record_report",
        fake_operations_review,
    )
    record_path = tmp_path / "private-m1-operations-review.json"
    record_path.write_text(json.dumps({"review_id": "m1-ops-review-20260624"}), encoding="utf-8")

    report = go_no_go.build_m1_go_no_go_report(
        include_m1_operations_review_record=True,
        m1_operations_review_json=record_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["m1_operations_review_record"] == "passed"
    assert report["policy"]["reads_m1_operations_review_record"] is True
    assert report["policy"]["queries_database_for_operations_review"] is False
    assert captured["record"]["review_id"] == "m1-ops-review-20260624"
    assert str(record_path) not in payload


def test_m1_operations_review_missing_record_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_m1_operations_review_record=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["m1_operations_review_record"] == "blocked"
    assert any(item["key"] == "m1_operations_review_json" for item in report["blockers"])


def test_postgres_redis_ops_summary_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-postgres-redis-summary.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "postgres_redis_ops_summary.v1",
                "status": "degraded",
                "decision": "conditional_go_for_m1_with_recorded_stateful_limits",
                "section_statuses": {
                    "ops_status": "degraded",
                    "live_probe": "passed",
                    "recovery_record": "passed",
                },
                "policy": {
                    "reads_dotenv": False,
                    "connects_database": False,
                    "connects_redis": False,
                    "connects_ssh": False,
                },
                "degraded_reasons": [
                    {
                        "section": "ops_status",
                        "key": "single_node_compose",
                        "finding": "Single-node Compose remains an M1 limitation.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_postgres_redis_ops_summary=True,
        postgres_redis_ops_summary_json=report_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["postgres_redis_ops_summary"] == "degraded"
    assert report["policy"]["reads_postgres_redis_ops_summary_evidence"] is True
    assert str(report_path) not in payload
    assert "private-postgres-redis-summary" not in payload


def test_postgres_redis_ops_summary_missing_json_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_postgres_redis_ops_summary=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["postgres_redis_ops_summary"] == "blocked"
    assert any(item["key"] == "postgres_redis_ops_summary_json" for item in report["blockers"])


def test_external_dependency_resilience_bad_record_does_not_echo_private_path(tmp_path: Path):
    record_path = tmp_path / "private-host-secret-record.json"
    record_path.write_text("{not-json", encoding="utf-8")

    report = go_no_go.build_m1_go_no_go_report(
        include_external_dependency_resilience_record=True,
        external_dependency_record_json=record_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert str(record_path) not in payload
    assert "private-host-secret-record" not in payload


def test_requested_not_checked_section_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_smoke_evidence=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["m1_smoke_evidence"] == "not_checked"
    assert any(item["section"] == "m1_smoke_evidence" for item in report["blockers"])


def test_blocked_section_extracts_missing_env_without_echoing_value(monkeypatch):
    def fake_backup(**kwargs):
        return {
            "status": "blocked",
            "blocked_reasons": [
                {
                    "env_var": "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
                    "finding": "Missing or placeholder declaration.",
                    "value_echoed": False,
                }
            ],
        }

    monkeypatch.setattr(go_no_go, "build_backup_restore_drill_evidence_report", fake_backup)

    report = go_no_go.build_m1_go_no_go_report(
        environ={"ZHIXING_POSTGRES_RESTORE_DRILL_STATUS": "secret-should-not-appear"},
        include_backup_restore_evidence=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["missing_inputs_for_user"] == [
        {
            "env_var": "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
            "label": "PostgreSQL 恢复演练状态",
            "value_echoed": False,
            "source_section": "backup_restore_drill_evidence",
        }
    ]
    assert "secret-should-not-appear" not in payload


def test_degraded_section_yields_conditional_go(monkeypatch):
    monkeypatch.setattr(
        go_no_go,
        "build_monitoring_alerting_evidence_report",
        lambda **kwargs: {
            "status": "degraded",
            "degraded_reasons": [{"key": "metric", "reason": "pending retention baseline"}],
        },
    )

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_monitoring_evidence=True,
    )

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["degraded_reasons"]


def test_run_acceptance_smoke_marks_external_api_policy(monkeypatch):
    monkeypatch.setattr(
        go_no_go,
        "build_m1_smoke_evidence_report",
        lambda **kwargs: _passed_report("smoke.v1"),
    )

    report = go_no_go.build_m1_go_no_go_report(
        environ={"ZHIXING_PUBLIC_BASE_URL": PUBLIC_URL},
        include_smoke_evidence=True,
        run_acceptance_smoke=True,
    )

    assert report["status"] == "passed"
    assert report["policy"]["runs_acceptance_smoke"] is True
    assert report["policy"]["may_call_external_apis"] is True
    assert report["policy"]["may_write_runtime_artifacts"] is True


def test_live_server_probe_can_be_included_without_echoing_target(monkeypatch):
    captured = {}

    def fake_live_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {
                "ssh_target": "<server-target>",
                "deploy_dir": "<deploy-dir>",
                "public_base_url": "<public-url>",
            },
            "sections": {
                "compose_services": {"status": "passed"},
                "internal_health": {"status": "passed"},
            },
        }

    monkeypatch.setattr(go_no_go, "build_live_server_probe_report", fake_live_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        base_url=PUBLIC_URL,
        include_live_server_probe=True,
        live_server_ssh_target="root@private-host",
        live_server_deploy_dir="/opt/private-app",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["live_server_probe"] == "passed"
    assert report["policy"]["runs_live_server_probe"] is True
    assert report["policy"]["may_connect_ssh"] is True
    assert captured["ssh_target"] == "root@private-host"
    assert captured["deploy_dir"] == "/opt/private-app"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert PUBLIC_URL not in payload


def test_live_server_probe_missing_target_blocks(monkeypatch):
    def fake_live_probe(**kwargs):
        return {
            "status": "blocked",
            "blocked_reasons": [
                {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
            ],
        }

    monkeypatch.setattr(go_no_go, "build_live_server_probe_report", fake_live_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_live_server_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["live_server_probe"] == "blocked"
    assert any(item["key"] == "missing_target" for item in report["blockers"])


def test_server_preflight_disk_warning_yields_conditional_go(monkeypatch):
    captured = {}

    def fake_server_preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": "warning",
            "policy": {
                "reads_dotenv": False,
                "writes_files": False,
                "starts_services": False,
            },
            "disk_probe": {
                "status": "warning",
                "free_mb": 4096,
                "used_percent": 91,
                "value_echoed": False,
            },
            "warnings": [
                {
                    "key": "disk_probe",
                    "finding": "Disk usage is above the warning threshold.",
                    "value_echoed": False,
                }
            ],
        }

    monkeypatch.setattr(go_no_go, "build_server_preflight_readiness_report", fake_server_preflight)

    report = go_no_go.build_m1_go_no_go_report(
        environ={"ZHIXING_DEPLOY_DIR": "/opt/private-app"},
        include_server_preflight_evidence=True,
        check_server_disk=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["server_preflight_evidence"] == "warning"
    assert report["policy"]["runs_server_preflight_evidence"] is True
    assert report["policy"]["runs_server_disk_probe"] is True
    assert report["degraded_reasons"][0]["key"] == "disk_probe"
    assert captured["check_disk"] is True
    assert captured["check_docker"] is False
    assert "/opt/private-app" not in payload


def test_server_preflight_disk_blocker_yields_no_go(monkeypatch):
    def fake_server_preflight(**kwargs):
        return {
            "status": "blocked",
            "blocked_reasons": [
                {
                    "key": "disk_probe",
                    "finding": "Free disk space is below the minimum runtime-build threshold.",
                    "value_echoed": False,
                }
            ],
        }

    monkeypatch.setattr(go_no_go, "build_server_preflight_readiness_report", fake_server_preflight)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_server_preflight_evidence=True,
        check_server_disk=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["server_preflight_evidence"] == "blocked"
    assert any(item["key"] == "disk_probe" for item in report["blockers"])


def test_postgres_redis_live_probe_can_be_included_without_echoing_target(monkeypatch):
    captured = {}

    def fake_postgres_redis_live_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "degraded",
            "target": {
                "ssh_target": "<server-target>",
                "deploy_dir": "<deploy-dir>",
            },
            "degraded_reasons": [
                {"key": "postgres_container.public_port_binding", "finding": "non-loopback binding"}
            ],
        }

    monkeypatch.setattr(go_no_go, "build_postgres_redis_live_probe_report", fake_postgres_redis_live_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_postgres_redis_live_probe=True,
        live_server_ssh_target="root@private-host",
        live_server_deploy_dir="/opt/private-app",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["postgres_redis_live_probe"] == "degraded"
    assert report["policy"]["runs_postgres_redis_live_probe"] is True
    assert report["policy"]["may_connect_ssh"] is True
    assert captured["ssh_target"] == "root@private-host"
    assert captured["deploy_dir"] == "/opt/private-app"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload


def test_backup_schedule_live_probe_can_be_included_without_echoing_target(monkeypatch):
    captured = {}

    def fake_backup_schedule_live_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "degraded",
            "target": {
                "ssh_target": "<server-target>",
                "deploy_dir": "<deploy-dir>",
                "backup_dir": "<backup-dir>",
            },
            "degraded_reasons": [
                {"key": "backup_schedule.missing_schedule", "finding": "missing schedule"}
            ],
        }

    monkeypatch.setattr(go_no_go, "build_backup_schedule_live_probe_report", fake_backup_schedule_live_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_backup_schedule_live_probe=True,
        live_server_ssh_target="root@private-host",
        live_server_deploy_dir="/opt/private-app",
        live_backup_dir="/private/backups",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["backup_schedule_live_probe"] == "degraded"
    assert report["policy"]["runs_backup_schedule_live_probe"] is True
    assert report["policy"]["may_connect_ssh"] is True
    assert captured["ssh_target"] == "root@private-host"
    assert captured["deploy_dir"] == "/opt/private-app"
    assert captured["backup_dir"] == "/private/backups"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert "/private/backups" not in payload


def test_docker_disk_cleanup_plan_can_be_included_without_deleting(monkeypatch):
    captured = {}

    def fake_cleanup_plan(**kwargs):
        captured.update(kwargs)
        return {
            "status": "degraded",
            "risk_status": "attention_required",
            "policy": {
                "read_only": True,
                "deletes_images": False,
                "runs_prune": False,
            },
            "target": {
                "ssh_target": "<server-target>",
                "deploy_dir": "<deploy-dir>",
            },
            "images": {
                "candidate_count": 12,
                "selected_count": 5,
            },
            "degraded_reasons": [
                {"key": "disk_usage_warning_threshold", "finding": "disk high"}
            ],
        }

    monkeypatch.setattr(go_no_go, "build_docker_disk_cleanup_plan_report", fake_cleanup_plan)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_docker_disk_cleanup_plan=True,
        live_server_ssh_target="root@private-host",
        live_server_deploy_dir="/opt/private-app",
        docker_disk_cleanup_max_candidates=5,
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["docker_disk_cleanup_plan"] == "degraded"
    assert report["policy"]["runs_docker_disk_cleanup_plan"] is True
    assert report["policy"]["may_connect_ssh"] is True
    assert captured["ssh_target"] == "root@private-host"
    assert captured["deploy_dir"] == "/opt/private-app"
    assert captured["max_candidates"] == 5
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert report["sections"]["docker_disk_cleanup_plan"]["policy"]["deletes_images"] is False


def test_docker_build_cache_cleanup_plan_can_be_included_without_deleting(monkeypatch):
    captured = {}

    def fake_build_cache_plan(**kwargs):
        captured.update(kwargs)
        return {
            "status": "degraded",
            "risk_status": "attention_required",
            "policy": {
                "read_only": True,
                "deletes_build_cache": False,
                "deletes_images": False,
                "runs_system_prune": False,
            },
            "target": {
                "ssh_target": "<server-target>",
                "deploy_dir": "<deploy-dir>",
            },
            "build_cache": {
                "reclaimable_mb": 23582.7,
            },
            "degraded_reasons": [
                {"key": "build_cache_reclaimable", "finding": "cache high"}
            ],
        }

    monkeypatch.setattr(go_no_go, "build_docker_build_cache_cleanup_plan_report", fake_build_cache_plan)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_docker_build_cache_cleanup_plan=True,
        live_server_ssh_target="root@private-host",
        live_server_deploy_dir="/opt/private-app",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["docker_build_cache_cleanup_plan"] == "degraded"
    assert report["policy"]["runs_docker_build_cache_cleanup_plan"] is True
    assert report["policy"]["may_connect_ssh"] is True
    assert captured["ssh_target"] == "root@private-host"
    assert captured["deploy_dir"] == "/opt/private-app"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    section_policy = report["sections"]["docker_build_cache_cleanup_plan"]["policy"]
    assert section_policy["deletes_build_cache"] is False
    assert section_policy["runs_system_prune"] is False


def test_restore_drill_feasibility_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-restore-feasibility.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "restore_drill_feasibility.v1",
                "status": "blocked",
                "sections": {
                    "postgres_backup": {"status": "passed"},
                    "restore_workspace_space": {
                        "status": "blocked",
                        "effective_free_mb": 2266,
                        "required_free_mb": 4096,
                    },
                },
                "blocked_reasons": [
                    {
                        "section": "restore_workspace_space",
                        "key": "insufficient_restore_drill_space",
                        "finding": "Not enough restore workspace space.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_restore_drill_feasibility=True,
        restore_drill_feasibility_json=report_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["restore_drill_feasibility"] == "blocked"
    assert report["policy"]["reads_restore_drill_feasibility_evidence"] is True
    assert str(report_path) not in payload
    assert "private-restore-feasibility" not in payload


def test_postgres_restore_drill_live_probe_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-postgres-restore-drill.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "postgres_restore_drill_live_probe.v1",
                "status": "passed",
                "phase": "complete",
                "scope": {
                    "mode": "ephemeral_non_production_restore_container",
                    "production_database_modified": False,
                    "backup_path_echoed": False,
                    "row_data_echoed": False,
                },
                "catalog_check": {
                    "status": "passed",
                    "catalog_line_count": 94,
                },
                "restore_check": {
                    "status": "passed",
                    "restored_table_count": 13,
                    "temp_container_cleaned": True,
                },
                "policy": {
                    "prints_backup_path": False,
                    "prints_row_data": False,
                    "modifies_production_database": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_postgres_restore_drill_live_probe=True,
        postgres_restore_drill_live_probe_json=report_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["postgres_restore_drill_live_probe"] == "passed"
    assert report["policy"]["reads_postgres_restore_drill_live_probe_evidence"] is True
    assert str(report_path) not in payload
    assert "private-postgres-restore-drill" not in payload


def test_postgres_restore_drill_live_probe_missing_json_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_postgres_restore_drill_live_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["postgres_restore_drill_live_probe"] == "blocked"
    assert report["policy"]["reads_postgres_restore_drill_live_probe_evidence"] is True
    assert any(item["key"] == "postgres_restore_drill_live_probe_json" for item in report["blockers"])


def test_disk_remediation_approval_missing_json_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_disk_remediation_approval=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["disk_remediation_approval_gate"] == "blocked"
    assert report["policy"]["reads_disk_remediation_approval_evidence"] is True
    assert any(item["key"] == "disk_remediation_approval_json" for item in report["blockers"])


def test_docker_build_cache_approval_missing_json_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_docker_build_cache_cleanup_approval=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["docker_build_cache_cleanup_approval_gate"] == "blocked"
    assert report["policy"]["reads_docker_build_cache_cleanup_approval_evidence"] is True
    assert any(item["key"] == "docker_build_cache_cleanup_approval_json" for item in report["blockers"])


def test_docker_build_cache_approval_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-build-cache-approval.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "docker_build_cache_cleanup_approval.v1",
                "status": "degraded",
                "decision": "ready_for_explicit_approval",
                "sections": {
                    "build_cache_cleanup_plan": {
                        "status": "degraded",
                        "reclaimable_mb": 23582.7,
                    },
                    "build_cache_cleanup_dry_run": {
                        "status": "degraded",
                        "prune_result": "dry_run",
                    },
                    "approval_record": {
                        "status": "not_checked",
                        "approval_present": False,
                    },
                },
                "policy": {
                    "connects_ssh": False,
                    "deletes_build_cache": False,
                    "runs_system_prune": False,
                },
                "degraded_reasons": [
                    {
                        "key": "approval_record_missing",
                        "finding": "Approval record has not been supplied yet.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_docker_build_cache_cleanup_approval=True,
        docker_build_cache_cleanup_approval_json=report_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["docker_build_cache_cleanup_approval_gate"] == "degraded"
    assert report["policy"]["reads_docker_build_cache_cleanup_approval_evidence"] is True
    assert str(report_path) not in payload
    assert "private-build-cache-approval" not in payload


def test_docker_build_cache_post_cleanup_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-build-cache-post-cleanup.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "docker_build_cache_post_cleanup.v1",
                "status": "passed",
                "decision": "build_cache_remediation_evidence_passed",
                "sections": {
                    "execution": {
                        "status": "passed",
                        "estimated_reclaimable_delta_mb": 23582.7,
                    },
                    "capacity_delta": {
                        "status": "passed",
                        "root_free_delta_mb": 23536,
                    },
                    "restore_feasibility": {
                        "status": "passed",
                    },
                },
                "policy": {
                    "connects_ssh": False,
                    "deletes_build_cache": False,
                    "runs_system_prune": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_docker_build_cache_post_cleanup=True,
        docker_build_cache_post_cleanup_json=report_path,
    )
    payload = _payload_text(report)

    assert report["section_statuses"]["docker_build_cache_post_cleanup"] == "passed"
    assert report["policy"]["reads_docker_build_cache_post_cleanup_evidence"] is True
    assert str(report_path) not in payload
    assert "private-build-cache-post-cleanup" not in payload


def test_storage_expansion_readiness_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-storage-expansion.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "storage_expansion_readiness.v1",
                "status": "blocked",
                "decision": "storage_expansion_required",
                "sections": {
                    "recommendation": {
                        "strategy": "expand_root_volume_or_attach_new_disk_for_docker_data",
                    },
                    "restore_workspace": {
                        "status": "blocked",
                        "gap_mb": 1809,
                    },
                },
                "policy": {
                    "reads_env_file": False,
                    "deletes_images": False,
                },
                "blocked_reasons": [
                    {
                        "section": "restore_workspace",
                        "key": "insufficient_free_space",
                        "finding": "Effective free space is below threshold.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_storage_expansion_readiness=True,
        storage_expansion_readiness_json=report_path,
    )
    payload = _payload_text(report)

    assert report["decision"] == "no_go"
    assert report["section_statuses"]["storage_expansion_readiness"] == "blocked"
    assert report["policy"]["reads_storage_expansion_readiness_evidence"] is True
    assert str(report_path) not in payload
    assert "private-storage-expansion" not in payload


def test_live_concurrency_probe_can_be_included_without_echoing_public_url(monkeypatch):
    captured = {}

    def fake_live_concurrency_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {"base_url": "<public-url>", "base_url_echoed": False},
            "policy": {
                "http_methods": ["GET"],
                "calls_llm": False,
                "calls_external_provider_apis": False,
                "creates_real_payment": False,
            },
        }

    monkeypatch.setattr(go_no_go, "build_live_concurrency_probe_report", fake_live_concurrency_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        base_url=PUBLIC_URL,
        include_live_concurrency_probe=True,
        concurrency_requests_per_endpoint=7,
        concurrency_workers=3,
        concurrency_max_p95_ms=1500,
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["live_concurrency_probe"] == "passed"
    assert report["policy"]["runs_live_concurrency_probe"] is True
    assert report["policy"]["may_call_external_apis"] is False
    assert captured["base_url"] == PUBLIC_URL
    assert captured["requests_per_endpoint"] == 7
    assert captured["concurrency"] == 3
    assert captured["max_p95_ms"] == 1500
    assert PUBLIC_URL not in payload


def test_probe_auth_readiness_can_be_included_without_echoing_credentials(monkeypatch):
    captured = {}

    def fake_probe_auth(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {
                "base_url": "<public-url>",
                "base_url_echoed": False,
                "auth_strategy": "probe_login",
                "username_present": True,
                "password_present": True,
                "username_echoed": False,
                "password_echoed": False,
            },
            "policy": {
                "reads_dotenv": False,
                "execute_login_requested": kwargs["execute_login"],
                "calls_chat": False,
                "calls_llm": False,
                "calls_external_provider_apis": False,
            },
            "observations": {
                "login_performed": True,
                "me_checked": True,
                "token_validated": True,
            },
        }

    monkeypatch.setattr(go_no_go, "build_probe_auth_readiness_report", fake_probe_auth)

    report = go_no_go.build_m1_go_no_go_report(
        environ={
            "ZHIXING_PROBE_USERNAME": "private-user",
            "ZHIXING_PROBE_PASSWORD": "probe-password",
        },
        base_url=PUBLIC_URL,
        include_probe_auth_readiness=True,
        execute_probe_auth_login=True,
        probe_auth_username_env="ZHIXING_PROBE_USERNAME",
        probe_auth_password_env="ZHIXING_PROBE_PASSWORD",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["probe_auth_readiness"] == "passed"
    assert report["policy"]["runs_probe_auth_readiness"] is True
    assert report["policy"]["executes_probe_auth_login"] is True
    assert report["policy"]["may_call_auth_endpoint"] is True
    assert report["policy"]["may_call_external_apis"] is False
    assert captured["base_url"] == PUBLIC_URL
    assert captured["username_env"] == "ZHIXING_PROBE_USERNAME"
    assert captured["password_env"] == "ZHIXING_PROBE_PASSWORD"
    assert PUBLIC_URL not in payload
    assert "private-user" not in payload
    assert "probe-password" not in payload


def test_live_chat_probe_plan_only_blocks_until_execute_flag(monkeypatch):
    captured = {}

    def fake_live_chat_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "not_checked",
            "target": {"base_url": "<public-url>", "base_url_echoed": False},
            "policy": {
                "requires_execute_flag": True,
                "execute_requested": kwargs["execute"],
                "calls_llm": kwargs["execute"],
                "records_prompt": False,
                "records_assistant_text": False,
            },
        }

    monkeypatch.setattr(go_no_go, "build_live_chat_probe_report", fake_live_chat_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={"ZHIXING_PROBE_ACCESS_TOKEN": "secret-token"},
        base_url=PUBLIC_URL,
        include_live_chat_probe=True,
        execute_live_chat_probe=False,
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["live_chat_probe"] == "not_checked"
    assert report["policy"]["runs_live_chat_probe"] is True
    assert report["policy"]["executes_live_chat_probe"] is False
    assert report["policy"]["may_call_external_apis"] is False
    assert captured["execute"] is False
    assert PUBLIC_URL not in payload
    assert "secret-token" not in payload


def test_live_chat_probe_execute_blocks_without_approval(monkeypatch):
    called = {"value": False}

    def fake_live_chat_probe(**kwargs):  # pragma: no cover - must not be called
        called["value"] = True
        return {"status": "passed"}

    monkeypatch.setattr(go_no_go, "build_live_chat_probe_report", fake_live_chat_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={
            "ZHIXING_PROBE_USERNAME": "private-user",
            "ZHIXING_PROBE_PASSWORD": "probe-password",
        },
        base_url=PUBLIC_URL,
        include_live_chat_probe=True,
        execute_live_chat_probe=True,
        live_chat_username_env="ZHIXING_PROBE_USERNAME",
        live_chat_password_env="ZHIXING_PROBE_PASSWORD",
        timeout_seconds=12,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["live_chat_probe_execution_approval"] == "blocked"
    assert report["section_statuses"]["live_chat_probe"] == "blocked"
    assert report["policy"]["requires_live_chat_probe_execution_approval"] is True
    assert report["policy"]["may_call_external_apis"] is False
    assert called["value"] is False


def test_live_chat_probe_can_be_executed_without_echoing_url_or_credentials(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_live_chat_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {
                "base_url": "<public-url>",
                "base_url_echoed": False,
                "access_token_present": True,
                "access_token_echoed": False,
            },
            "policy": {
                "requires_execute_flag": True,
                "execute_requested": kwargs["execute"],
                "calls_llm": kwargs["execute"],
                "calls_external_provider_apis": kwargs["execute"],
                "records_prompt": False,
                "records_assistant_text": False,
            },
            "observations": {
                "conversation_created": True,
                "conversation_id": "<conversation-id>",
                "stream_completed": True,
                "event_type_counts": {"token": 1, "done": 1},
            },
        }

    monkeypatch.setattr(go_no_go, "build_live_chat_probe_report", fake_live_chat_probe)
    approval_path = _write_json(tmp_path / "approval.json", _live_chat_approval_report())

    report = go_no_go.build_m1_go_no_go_report(
        environ={
            "ZHIXING_PROBE_USERNAME": "private-user",
            "ZHIXING_PROBE_PASSWORD": "probe-password",
        },
        base_url=PUBLIC_URL,
        include_live_chat_probe=True,
        execute_live_chat_probe=True,
        live_chat_username_env="ZHIXING_PROBE_USERNAME",
        live_chat_password_env="ZHIXING_PROBE_PASSWORD",
        live_chat_probe_approval_json=approval_path,
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["live_chat_probe"] == "passed"
    assert report["section_statuses"]["live_chat_probe_execution_approval"] == "passed"
    assert report["policy"]["runs_live_chat_probe"] is True
    assert report["policy"]["executes_live_chat_probe"] is True
    assert report["policy"]["reads_live_chat_probe_execution_approval"] is True
    assert report["policy"]["may_call_external_apis"] is True
    assert report["policy"]["may_write_runtime_artifacts"] is True
    assert captured["base_url"] == PUBLIC_URL
    assert captured["username_env"] == "ZHIXING_PROBE_USERNAME"
    assert captured["password_env"] == "ZHIXING_PROBE_PASSWORD"
    assert captured["execute"] is True
    assert PUBLIC_URL not in payload
    assert "private-user" not in payload
    assert "probe-password" not in payload


def test_live_chat_concurrency_probe_json_can_be_included_without_echoing_path(tmp_path: Path):
    report_path = tmp_path / "private-live-chat-concurrency.json"
    report_path.write_text(
        json.dumps(
            {
                "version": "live_chat_concurrency_probe.v1",
                "status": "passed",
                "policy": {
                    "reads_dotenv": False,
                    "calls_llm": True,
                    "calls_external_provider_apis": True,
                    "records_credentials": False,
                    "records_prompt": False,
                    "records_assistant_text": False,
                    "load_test": False,
                },
                "target": {
                    "base_url": "<public-url>",
                    "base_url_echoed": False,
                },
                "observations": {
                    "request_count": 3,
                    "concurrency": 2,
                    "passed_count": 3,
                    "blocked_count": 0,
                    "total_seconds": {"p95": 15.275},
                },
            }
        ),
        encoding="utf-8",
    )

    report = go_no_go.build_m1_go_no_go_report(
        include_live_chat_concurrency_probe=True,
        live_chat_concurrency_probe_json=report_path,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["live_chat_concurrency_probe"] == "passed"
    assert report["policy"]["reads_live_chat_concurrency_probe_evidence"] is True
    assert report["policy"]["may_call_external_apis"] is False
    assert report["policy"]["may_write_runtime_artifacts"] is False
    assert str(report_path) not in payload
    assert "private-live-chat-concurrency" not in payload


def test_live_chat_concurrency_probe_json_missing_blocks_release():
    report = go_no_go.build_m1_go_no_go_report(
        include_live_chat_concurrency_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "no_go"
    assert report["section_statuses"]["live_chat_concurrency_probe"] == "blocked"
    assert any(item["key"] == "live_chat_concurrency_probe_json" for item in report["blockers"])


def test_live_chat_probe_registration_inputs_are_redacted_and_flagged(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_live_chat_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {
                "base_url": "<public-url>",
                "base_url_echoed": False,
                "email_present": True,
                "email_echoed": False,
            },
            "policy": {
                "requires_execute_flag": True,
                "execute_requested": kwargs["execute"],
                "register_probe_user_requested": kwargs["register_probe_user"],
                "creates_probe_user": kwargs["register_probe_user"],
                "writes_runtime_user_record": kwargs["register_probe_user"],
                "calls_llm": kwargs["execute"],
                "calls_external_provider_apis": kwargs["execute"],
            },
            "observations": {
                "registration_attempted": True,
                "registration_performed": True,
                "conversation_created": True,
                "conversation_id": "<conversation-id>",
                "stream_completed": True,
                "event_type_counts": {"token": 1, "done": 1},
            },
        }

    monkeypatch.setattr(go_no_go, "build_live_chat_probe_report", fake_live_chat_probe)
    approval_path = _write_json(tmp_path / "approval.json", _live_chat_approval_report())

    report = go_no_go.build_m1_go_no_go_report(
        environ={
            "ZHIXING_PROBE_USERNAME": "private-user",
            "ZHIXING_PROBE_PASSWORD": "probe-password",
            "ZHIXING_PROBE_EMAIL": "probe@example.com",
        },
        base_url=PUBLIC_URL,
        include_live_chat_probe=True,
        execute_live_chat_probe=True,
        register_live_chat_probe_user=True,
        live_chat_username_env="ZHIXING_PROBE_USERNAME",
        live_chat_password_env="ZHIXING_PROBE_PASSWORD",
        live_chat_email_env="ZHIXING_PROBE_EMAIL",
        live_chat_probe_approval_json=approval_path,
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["policy"]["registers_live_chat_probe_user"] is True
    assert report["policy"]["may_write_runtime_user_record"] is True
    assert report["policy"]["may_call_auth_endpoint"] is True
    assert captured["register_probe_user"] is True
    assert captured["email_env"] == "ZHIXING_PROBE_EMAIL"
    assert "private-user" not in payload
    assert "probe-password" not in payload
    assert "probe@example.com" not in payload


def test_server_capacity_snapshot_can_be_included_without_echoing_target(monkeypatch):
    captured = {}

    def fake_capacity_snapshot(**kwargs):
        captured.update(kwargs)
        return {
            "status": "degraded",
            "target": {
                "ssh_target": "<server-target>",
                "deploy_dir": "<deploy-dir>",
            },
            "policy": {
                "read_only": True,
                "reads_env_file": False,
                "reads_logs": False,
            },
            "sections": {
                "host_capacity": {
                    "status": "degraded",
                    "cpu_count": 2,
                    "disk": {"root": {"used_percent": 97, "status": "degraded"}},
                }
            },
            "degraded_reasons": [
                {"key": "root_disk", "finding": "Disk usage is above warning threshold."}
            ],
        }

    monkeypatch.setattr(go_no_go, "build_server_capacity_snapshot_report", fake_capacity_snapshot)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_server_capacity_snapshot=True,
        live_server_ssh_target="root@private-host",
        live_server_deploy_dir="/opt/private-app",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["decision"] == "conditional_go"
    assert report["section_statuses"]["server_capacity_snapshot"] == "degraded"
    assert report["policy"]["runs_server_capacity_snapshot"] is True
    assert report["policy"]["may_connect_ssh"] is True
    assert captured["ssh_target"] == "root@private-host"
    assert captured["deploy_dir"] == "/opt/private-app"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert report["sections"]["server_capacity_snapshot"]["policy"]["reads_env_file"] is False


def test_rate_limit_live_probe_can_be_included_without_echoing_target(monkeypatch):
    captured = {}

    def fake_rate_limit_live_probe(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {
                "base_url": "<public-url>",
                "path_key": "mock_checkout_status",
                "base_url_echoed": False,
                "path_echoed": False,
            },
            "status_counts": {"200": 120, "429": 10},
        }

    monkeypatch.setattr(go_no_go, "build_rate_limit_live_probe_report", fake_rate_limit_live_probe)

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        base_url=PUBLIC_URL,
        include_rate_limit_live_probe=True,
        rate_limit_request_count=130,
        rate_limit_concurrency=16,
        rate_limit_path="/api/v1/private-path/status",
        timeout_seconds=12,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["decision"] == "go_for_m1_controlled_trial"
    assert report["section_statuses"]["rate_limit_live_probe"] == "passed"
    assert report["policy"]["runs_rate_limit_live_probe"] is True
    assert report["policy"]["may_call_external_apis"] is False
    assert captured["base_url"] == PUBLIC_URL
    assert captured["request_count"] == 130
    assert captured["concurrency"] == 16
    assert captured["path"] == "/api/v1/private-path/status"
    assert PUBLIC_URL not in payload
    assert "/api/v1/private-path/status" not in payload


def test_go_no_go_markdown_keeps_boundary_and_missing_inputs(monkeypatch):
    monkeypatch.setattr(
        go_no_go,
        "build_backup_restore_drill_evidence_report",
        lambda **kwargs: {
            "status": "blocked",
            "blocked_reasons": [
                {
                    "env_var": "ZHIXING_BACKUP_DIR",
                    "finding": "Missing backup directory.",
                }
            ],
        },
    )

    report = go_no_go.build_m1_go_no_go_report(
        environ={},
        include_backup_restore_evidence=True,
    )
    markdown = go_no_go.build_m1_go_no_go_markdown(report)

    assert "M1 Go/No-Go Evidence" in markdown
    assert "Decision" in markdown
    assert "ZHIXING_BACKUP_DIR" in markdown
    assert "Plan-only mode proves no live deployment result" in markdown
