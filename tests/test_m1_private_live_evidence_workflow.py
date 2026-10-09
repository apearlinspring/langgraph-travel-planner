import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import run_m1_private_live_evidence_workflow as workflow


def _passed_go_no_go_report():
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": "passed",
        "decision": "go_for_m1_controlled_trial",
        "target": {
            "public_base_url_present": True,
            "public_base_url_echoed": False,
            "raw_url": "https://prod.example.com",
            "server_ip": "203.0.113.10",
        },
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "may_connect_ssh": True,
            "may_call_external_apis": False,
            "may_write_runtime_artifacts": False,
        },
        "section_statuses": {
            "live_server_probe": "passed",
            "postgres_redis_live_probe": "passed",
            "probe_auth_readiness": "passed",
        },
        "sections": {},
        "blockers": [],
        "degraded_reasons": [],
    }


def test_private_live_evidence_workflow_plan_mode_does_not_write_or_call(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(**kwargs):
        raise AssertionError("plan mode must not call live evidence collectors")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)

    output_dir = tmp_path / "workflow"
    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=output_dir,
        include_standard_live_probes=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    assert report["status"] == "ready_to_execute"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["writes_files"] is False
    assert "live_server_probe" in report["selected_sections"]
    assert report["target"]["output_dir"] == "<private-workdir>"
    phases = [item["phase"] for item in report["execution_sequence"]]
    assert phases[:3] == [
        "m1_launch_inputs_template",
        "m1_launch_inputs_validate",
        "server_preflight",
    ]
    assert "postgres_redis_live_probe" in phases
    assert "private_workflow_preflight" in phases
    assert "rollout_record_draft_from_evidence" in phases
    assert "rollout_record_validate" in phases
    assert "operations_review_draft_from_evidence" in phases
    assert "operations_review_validate" in phases
    assert "private_evidence_signoff" in phases
    operations_draft = next(
        item for item in report["execution_sequence"]
        if item["phase"] == "operations_review_draft_from_evidence"
    )
    assert "--external-dependency-json" not in operations_draft["command"]
    signoff = next(
        item for item in report["execution_sequence"]
        if item["phase"] == "private_evidence_signoff"
    )
    assert "--rollout-report-json" not in signoff["command"]
    assert "--operations-review-report-json" not in signoff["command"]
    assert output_dir.exists() is False


def test_private_live_evidence_workflow_execute_writes_redacted_artifacts(
    monkeypatch, tmp_path: Path
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        return _passed_go_no_go_report()

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(
        workflow,
        "build_m1_live_evidence_summary_markdown",
        lambda report, **kwargs: (
            "# summary\n"
            "https://prod.example.com\n"
            "203.0.113.10\n"
            "TEST_ONLY_LIVE_SECRET_TOKEN_123456"
        ),
    )
    monkeypatch.setattr(
        workflow,
        "build_m1_evidence_bundle_report",
        lambda **kwargs: {
            "status": "passed",
            "manifest_sha256": "abc123",
            "target": {"output_dir": "https://prod.example.com"},
        },
    )
    env = {
        "ZHIXING_PUBLIC_BASE_URL": "https://prod.example.com",
        "ZHIXING_DEPLOY_USER": "root",
        "ZHIXING_DEPLOY_HOST": "203.0.113.10",
        "ZHIXING_DEPLOY_DIR": "/opt/private-app",
        "ZHIXING_BACKUP_DIR": "/var/backups/private-app",
        "ZHIXING_PROBE_ACCESS_TOKEN": "TEST_ONLY_LIVE_SECRET_TOKEN_123456",
    }
    output_dir = tmp_path / "workflow"

    report = workflow.build_m1_private_live_evidence_workflow_report(
        environ=env,
        output_dir=output_dir,
        execute=True,
        include_standard_live_probes=True,
        execute_probe_auth_login=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)
    summary = (output_dir / "m1-live-evidence-summary.md").read_text(encoding="utf-8")
    go_no_go = (output_dir / "m1-go-no-go.private.json").read_text(encoding="utf-8")

    assert report["status"] == "passed"
    assert report["go_no_go"]["decision"] == "go_for_m1_controlled_trial"
    assert captured["include_live_server_probe"] is True
    assert captured["include_postgres_redis_live_probe"] is True
    assert captured["include_probe_auth_readiness"] is True
    assert captured["execute_probe_auth_login"] is True
    assert captured["execute_live_chat_probe"] is False
    assert captured["live_server_ssh_target"] == "root@203.0.113.10"
    assert captured["live_server_deploy_dir"] == "/opt/private-app"
    assert captured["live_backup_dir"] == "/var/backups/private-app"
    assert (output_dir / "workflow-report.json").exists()
    assert (output_dir / "m1-evidence-bundle").name in payload
    for text in [payload, summary, go_no_go]:
        assert "https://prod.example.com" not in text
        assert "203.0.113.10" not in text
        assert "TEST_ONLY_LIVE_SECRET_TOKEN_123456" not in text
    assert "[REDACTED_URL]" in summary
    assert "[REDACTED_IP]" in summary
    artifact_digests = {
        item["role"]: item.get("sha256")
        for item in report["artifacts"]
        if "sha256" in item
    }
    assert artifact_digests["private_go_no_go_json"]
    assert artifact_digests["live_evidence_summary_markdown"]


def test_private_live_evidence_workflow_passes_external_dependency_record(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        report = _passed_go_no_go_report()
        report["section_statuses"] = {"external_dependency_resilience_record": "passed"}
        return report

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(workflow, "build_m1_live_evidence_summary_markdown", lambda report, **kwargs: "# summary")
    monkeypatch.setattr(workflow, "build_m1_evidence_bundle_report", lambda **kwargs: {"status": "passed"})

    record_path = tmp_path / "external-dependency-resilience-record.local.json"
    record_path.write_text(json.dumps({"record_id": "external-dependency"}), encoding="utf-8")

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_external_dependency_resilience_record=True,
        external_dependency_record_json=record_path,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["reads_external_dependency_resilience_record"] is True
    assert captured["include_external_dependency_resilience_record"] is True
    assert captured["external_dependency_record_json"] == record_path
    operations_draft = next(
        item for item in report["execution_sequence"]
        if item["phase"] == "operations_review_draft_from_evidence"
    )
    assert "--external-dependency-json" in operations_draft["command"]
    assert str(record_path) not in payload


def test_private_live_evidence_workflow_passes_rollout_execution_record(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        report = _passed_go_no_go_report()
        report["section_statuses"] = {"m1_rollout_execution_record": "passed"}
        return report

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(workflow, "build_m1_live_evidence_summary_markdown", lambda report, **kwargs: "# summary")
    monkeypatch.setattr(workflow, "build_m1_evidence_bundle_report", lambda **kwargs: {"status": "passed"})

    record_path = tmp_path / "m1-rollout-execution-record.local.json"
    record_path.write_text(json.dumps({"rollout_id": "m1-rollout"}), encoding="utf-8")

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_m1_rollout_execution_record=True,
        m1_rollout_record_json=record_path,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["reads_m1_rollout_execution_record"] is True
    assert captured["include_m1_rollout_execution_record"] is True
    assert captured["m1_rollout_record_json"] == record_path
    signoff = next(
        item for item in report["execution_sequence"]
        if item["phase"] == "private_evidence_signoff"
    )
    assert "--rollout-report-json" in signoff["command"]
    assert "--operations-review-report-json" not in signoff["command"]
    assert str(record_path) not in payload


def test_private_live_evidence_workflow_passes_operations_review_record(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        report = _passed_go_no_go_report()
        report["section_statuses"] = {"m1_operations_review_record": "passed"}
        return report

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(workflow, "build_m1_live_evidence_summary_markdown", lambda report, **kwargs: "# summary")
    monkeypatch.setattr(workflow, "build_m1_evidence_bundle_report", lambda **kwargs: {"status": "passed"})

    record_path = tmp_path / "m1-operations-review-record.local.json"
    record_path.write_text(json.dumps({"review_id": "m1-ops-review"}), encoding="utf-8")

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_m1_operations_review_record=True,
        m1_operations_review_json=record_path,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["reads_m1_operations_review_record"] is True
    assert captured["include_m1_operations_review_record"] is True
    assert captured["m1_operations_review_json"] == record_path
    signoff = next(
        item for item in report["execution_sequence"]
        if item["phase"] == "private_evidence_signoff"
    )
    assert "--operations-review-report-json" in signoff["command"]
    assert "--rollout-report-json" not in signoff["command"]
    assert str(record_path) not in payload


def test_private_live_evidence_workflow_imports_live_chat_concurrency_probe(
    monkeypatch,
    tmp_path: Path,
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        report = _passed_go_no_go_report()
        report["section_statuses"] = {"live_chat_concurrency_probe": "passed"}
        return report

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(workflow, "build_m1_live_evidence_summary_markdown", lambda report, **kwargs: "# summary")
    monkeypatch.setattr(workflow, "build_m1_evidence_bundle_report", lambda **kwargs: {"status": "passed"})

    record_path = tmp_path / "live-chat-concurrency-probe.json"
    record_path.write_text(
        json.dumps({"version": "live_chat_concurrency_probe.v1", "status": "passed"}),
        encoding="utf-8",
    )

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_live_chat_concurrency_probe=True,
        live_chat_concurrency_probe_json=record_path,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert "live_chat_concurrency_probe" in report["selected_sections"]
    assert report["policy"]["reads_live_chat_concurrency_probe_evidence"] is True
    assert report["policy"]["runs_live_probes"] is False
    assert captured["include_live_chat_concurrency_probe"] is True
    assert captured["live_chat_concurrency_probe_json"] == record_path
    assert report["private_record_statuses"][0]["key"] == "live_chat_concurrency_probe_json"
    assert str(record_path) not in payload


def test_private_live_evidence_workflow_blocks_missing_live_chat_concurrency_json(
    monkeypatch,
    tmp_path: Path,
):
    def fail_if_called(**kwargs):
        raise AssertionError("missing live chat concurrency evidence should block first")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_live_chat_concurrency_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "private_record_inputs_not_ready"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["reads_live_chat_concurrency_probe_evidence"] is False
    assert report["private_record_blockers"][0]["key"] == "live_chat_concurrency_probe_json"
    assert (tmp_path / "workflow").exists() is False


def test_private_live_evidence_workflow_blocks_project_output_by_default(tmp_path: Path):
    output_dir = workflow.PROJECT_ROOT / ".tmp-m1-private-live-evidence-workflow"

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=output_dir,
        execute=True,
        include_standard_live_probes=True,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "project_output_not_allowed"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["writes_files"] is False
    assert output_dir.exists() is False


def test_private_live_evidence_workflow_blocks_missing_inputs_before_live_calls(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(**kwargs):
        raise AssertionError("missing inputs should block before live collectors run")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)

    report = workflow.build_m1_private_live_evidence_workflow_report(
        environ={},
        output_dir=tmp_path / "workflow",
        execute=True,
        include_standard_live_probes=True,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_private_execution_inputs"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["connects_ssh"] is False
    assert report["policy"]["writes_files"] is False
    assert {item["key"] for item in report["missing_inputs_for_user"]} == {
        "public_base_url",
        "ssh_target",
        "deploy_dir",
        "backup_dir",
        "probe_auth",
    }
    assert (tmp_path / "workflow").exists() is False


def test_private_live_evidence_workflow_blocks_missing_selected_record_before_collectors(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(**kwargs):
        raise AssertionError("missing private record path should block before collectors run")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_external_dependency_resilience_record=True,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "private_record_inputs_not_ready"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["writes_files"] is False
    assert report["private_record_statuses"][0]["present"] is False
    assert report["private_record_blockers"][0]["key"] == "external_dependency_record_json"
    assert (tmp_path / "workflow").exists() is False


def test_private_live_evidence_workflow_blocks_private_record_inside_project(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(**kwargs):
        raise AssertionError("record path inside Git should block before collectors run")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_m1_rollout_execution_record=True,
        m1_rollout_record_json=workflow.PROJECT_ROOT / "README.md",
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "private_record_inputs_not_ready"
    assert report["private_record_statuses"][0]["inside_project"] is True
    assert report["private_record_statuses"][0]["path_echoed"] is False
    assert "README.md" not in payload
    assert (tmp_path / "workflow").exists() is False


def test_private_live_evidence_workflow_blocks_secret_like_record_path(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(**kwargs):
        raise AssertionError("secret-like record path should block before collectors run")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)
    record_path = tmp_path / ".env.local"
    record_path.write_text("{}", encoding="utf-8")

    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        execute=True,
        include_m1_operations_review_record=True,
        m1_operations_review_json=record_path,
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "blocked"
    assert report["private_record_statuses"][0]["forbidden_path"] is True
    assert report["private_record_blockers"][0]["key"] == "m1_operations_review_json"
    assert ".env.local" not in payload
    assert (tmp_path / "workflow").exists() is False


def test_private_live_evidence_workflow_markdown_shows_preflight_without_values(tmp_path: Path):
    record_path = tmp_path / ".env.local"
    record_path.write_text("{}", encoding="utf-8")
    report = workflow.build_m1_private_live_evidence_workflow_report(
        environ={
            "ZHIXING_PUBLIC_BASE_URL": "https://prod.example.com",
            "ZHIXING_DEPLOY_USER": "root",
            "ZHIXING_DEPLOY_HOST": "203.0.113.10",
            "ZHIXING_DEPLOY_DIR": "/opt/private-app",
        },
        output_dir=tmp_path / "workflow",
        execute=True,
        include_standard_live_probes=True,
        include_m1_operations_review_record=True,
        m1_operations_review_json=record_path,
    )

    markdown = workflow.build_m1_private_live_evidence_workflow_markdown(report)

    assert "M1 Private Live Evidence Workflow Checklist" in markdown
    assert "推荐执行顺序" in markdown
    assert "m1_launch_inputs_template" in markdown
    assert "server_preflight" in markdown
    assert "postgres_redis_live_probe" in markdown
    assert "private_workflow_execute" in markdown
    assert "rollout_record_draft_from_evidence" in markdown
    assert "rollout_record_validate" in markdown
    assert "operations_review_draft_from_evidence" in markdown
    assert "operations_review_validate" in markdown
    assert "private_evidence_signoff" in markdown
    assert "Live 输入检查" in markdown
    assert "私有记录 JSON 检查" in markdown
    assert "missing_private_execution_inputs" in markdown
    assert "private_record_inputs_not_ready" in markdown
    assert "backup_dir" in markdown
    assert "probe_auth" in markdown
    assert "m1_operations_review_json" in markdown
    assert "https://prod.example.com" not in markdown
    assert "203.0.113.10" not in markdown
    assert "/opt/private-app" not in markdown
    assert ".env.local" not in markdown


def test_private_live_evidence_workflow_cli_can_print_markdown(capsys, tmp_path: Path):
    code = workflow.main(
        [
            "--markdown",
            "--output-dir",
            str(tmp_path / "workflow"),
            "--include-standard-live-probes",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "M1 Private Live Evidence Workflow Checklist" in captured.out
    assert "private_live_evidence_workflow" in captured.out
    assert "推荐执行顺序" in captured.out
    assert "check_m1_launch_inputs.py" in captured.out
    assert "collect_postgres_redis_live_probe.py" in captured.out
    assert "check_m1_rollout_execution_record.py --draft-from-evidence" in captured.out
    assert "check_m1_rollout_execution_record.py --record-json" in captured.out
    assert "check_m1_operations_review_record.py --draft-from-evidence" in captured.out
    assert "check_m1_operations_review_record.py --record-json" in captured.out
    assert "<private-workdir>" in captured.out


def test_private_live_evidence_workflow_live_chat_concurrency_plan_mentions_import(
    tmp_path: Path,
):
    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        include_live_chat_concurrency_probe=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    command = report["command_plan"][0]["command"]

    assert "--include-live-chat-concurrency-probe" in command
    assert "live-chat-concurrency-probe.json" in command
    assert "live_chat_concurrency_probe" in report["selected_sections"]


def test_private_live_evidence_workflow_live_chat_requires_explicit_execute_flag(
    monkeypatch, tmp_path: Path
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        return _passed_go_no_go_report()

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(workflow, "build_m1_live_evidence_summary_markdown", lambda report, **kwargs: "# summary")
    monkeypatch.setattr(workflow, "build_m1_evidence_bundle_report", lambda **kwargs: {"status": "passed"})

    report = workflow.build_m1_private_live_evidence_workflow_report(
        environ={
            "ZHIXING_PUBLIC_BASE_URL": "https://prod.example.com",
            "ZHIXING_PROBE_ACCESS_TOKEN": "TEST_ONLY_LIVE_SECRET_TOKEN_123456",
        },
        output_dir=tmp_path / "workflow",
        execute=True,
        include_live_chat_probe=True,
    )

    assert report["status"] == "passed"
    assert captured["include_live_chat_probe"] is True
    assert captured["execute_live_chat_probe"] is False
    assert captured["live_chat_probe_approval_json"] is None
    assert report["policy"]["may_call_external_apis"] is False


def test_private_live_evidence_workflow_live_chat_execute_requires_approval_report(
    monkeypatch, tmp_path: Path
):
    def fail_if_called(**kwargs):
        raise AssertionError("missing live chat approval should block before collectors run")

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fail_if_called)

    report = workflow.build_m1_private_live_evidence_workflow_report(
        environ={
            "ZHIXING_PUBLIC_BASE_URL": "https://prod.example.com",
            "ZHIXING_PROBE_ACCESS_TOKEN": "TEST_ONLY_LIVE_SECRET_TOKEN_123456",
        },
        output_dir=tmp_path / "workflow",
        execute=True,
        include_live_chat_probe=True,
        execute_live_chat_probe=True,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "private_record_inputs_not_ready"
    assert report["policy"]["runs_live_probes"] is False
    assert report["policy"]["may_call_auth_endpoint"] is False
    assert report["policy"]["may_call_external_apis"] is False
    assert report["policy"]["reads_live_chat_probe_execution_approval"] is False
    assert report["policy"]["requires_live_chat_probe_execution_approval"] is True
    assert report["private_record_blockers"][0]["key"] == "live_chat_probe_approval_json"
    assert (tmp_path / "workflow").exists() is False


def test_private_live_evidence_workflow_passes_live_chat_approval_json(
    monkeypatch, tmp_path: Path
):
    captured = {}

    def fake_go_no_go(**kwargs):
        captured.update(kwargs)
        return _passed_go_no_go_report()

    monkeypatch.setattr(workflow, "build_m1_go_no_go_report", fake_go_no_go)
    monkeypatch.setattr(workflow, "build_m1_live_evidence_summary_markdown", lambda report, **kwargs: "# summary")
    monkeypatch.setattr(workflow, "build_m1_evidence_bundle_report", lambda **kwargs: {"status": "passed"})

    approval_path = tmp_path / "live-chat-probe-execution-approval-report.json"
    approval_path.write_text('{"version":"live_chat_probe_execution_approval.v1","status":"passed"}', encoding="utf-8")

    report = workflow.build_m1_private_live_evidence_workflow_report(
        environ={
            "ZHIXING_PUBLIC_BASE_URL": "https://prod.example.com",
            "ZHIXING_PROBE_ACCESS_TOKEN": "TEST_ONLY_LIVE_SECRET_TOKEN_123456",
        },
        output_dir=tmp_path / "workflow",
        execute=True,
        include_live_chat_probe=True,
        live_chat_probe_approval_json=approval_path,
        execute_live_chat_probe=True,
    )

    assert report["status"] == "passed"
    assert captured["include_live_chat_probe"] is True
    assert captured["execute_live_chat_probe"] is True
    assert captured["live_chat_probe_approval_json"] == approval_path
    assert report["policy"]["reads_live_chat_probe_execution_approval"] is True
    assert report["policy"]["requires_live_chat_probe_execution_approval"] is True
    assert report["private_record_statuses"][0]["key"] == "live_chat_probe_approval_json"
    assert report["private_record_statuses"][0]["exists"] is True


def test_private_live_evidence_workflow_live_chat_plan_mentions_approval_gate(
    tmp_path: Path,
):
    report = workflow.build_m1_private_live_evidence_workflow_report(
        output_dir=tmp_path / "workflow",
        include_live_chat_probe=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    command = report["command_plan"][0]["command"]
    phases = [item["phase"] for item in report["execution_sequence"]]

    assert "--live-chat-probe-approval-json" in command
    assert "live-chat-probe-execution-approval-report.json" in command
    assert "live_chat_probe_execution_approval_template" in phases
    assert "live_chat_probe_execution_approval_validate" in phases
    assert "private_workflow_live_chat_execute" in phases
