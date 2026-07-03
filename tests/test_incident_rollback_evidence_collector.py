import json

from scripts import collect_incident_rollback_evidence as evidence


PUBLIC_URL = "https://m1.zhixing.com"


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _valid_env() -> dict[str, str]:
    return {
        "ZHIXING_PUBLIC_BASE_URL": PUBLIC_URL,
        "ZHIXING_ROLLBACK_OWNER": "alice release owner",
        "ZHIXING_INCIDENT_OWNER": "bob incident owner",
        "ZHIXING_ROLLBACK_DRILL_STATUS": "passed",
        "ZHIXING_ROLLBACK_TARGET_STATUS": "passed",
        "ZHIXING_POST_ROLLBACK_HEALTH_STATUS": "passed",
        "ZHIXING_POST_ROLLBACK_SMOKE_STATUS": "passed",
        "ZHIXING_ROLLBACK_DATA_SAFETY_STATUS": "passed",
        "ZHIXING_INCIDENT_RESPONSE_STATUS": "passed",
        "ZHIXING_INCIDENT_REVIEW_STATUS": "passed",
        "ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS": "passed",
        "ZHIXING_INCIDENT_COMMUNICATION_STATUS": "passed",
    }


def test_default_incident_rollback_evidence_is_plan_only():
    report = evidence.build_incident_rollback_evidence_report(environ={})

    assert report["status"] == "not_checked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["executes_rollback"] is False
    assert report["sections"] == {}
    assert "manual rollback drill" in _payload_text(report)


def test_ownership_declaration_blocks_missing_values():
    report = evidence.build_incident_rollback_evidence_report(
        environ={},
        require_ownership_declaration=True,
    )

    assert report["status"] == "blocked"
    blockers = report["sections"]["ownership_declaration"]["blocked_reasons"]
    assert {item["env_var"] for item in blockers} == {
        "ZHIXING_ROLLBACK_OWNER",
        "ZHIXING_INCIDENT_OWNER",
    }


def test_all_declarations_pass_without_echoing_values():
    report = evidence.build_incident_rollback_evidence_report(
        environ=_valid_env(),
        require_ownership_declaration=True,
        require_rollback_drill_declaration=True,
        require_incident_review_declaration=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["sections"]["ownership_declaration"]["status"] == "passed"
    assert report["sections"]["rollback_drill_declaration"]["status"] == "passed"
    assert report["sections"]["incident_review_declaration"]["status"] == "passed"
    assert "alice release owner" not in payload
    assert "bob incident owner" not in payload
    assert PUBLIC_URL not in payload


def test_degraded_rollback_drill_status_marks_report_degraded():
    env = _valid_env()
    env["ZHIXING_POST_ROLLBACK_SMOKE_STATUS"] = "degraded"

    report = evidence.build_incident_rollback_evidence_report(
        environ=env,
        require_ownership_declaration=True,
        require_rollback_drill_declaration=True,
        require_incident_review_declaration=True,
    )

    assert report["status"] == "degraded"
    rollback = report["sections"]["rollback_drill_declaration"]
    assert rollback["status"] == "degraded"
    assert any(item["env_var"] == "ZHIXING_POST_ROLLBACK_SMOKE_STATUS" for item in rollback["degraded_reasons"])


def test_post_rollback_smoke_evidence_is_embedded_and_redacted(monkeypatch):
    captured = {}

    def fake_smoke(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "target": {"base_url": kwargs["environ"]["ZHIXING_PUBLIC_BASE_URL"]},
        }

    monkeypatch.setattr(evidence, "build_m1_smoke_evidence_report", fake_smoke)

    report = evidence.build_incident_rollback_evidence_report(
        environ=_valid_env(),
        include_post_rollback_smoke_evidence=True,
        check_health_url=True,
        run_gate=True,
        run_acceptance_smoke=False,
        timeout_seconds=1.5,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert captured["check_health_url"] is True
    assert captured["run_gate"] is True
    assert captured["run_acceptance_smoke"] is False
    assert captured["timeout_seconds"] == 1.5
    assert report["sections"]["post_rollback_smoke_evidence"]["target"]["base_url"] == "<public-url>"
    assert PUBLIC_URL not in payload


def test_incident_rollback_markdown_keeps_boundary():
    report = evidence.build_incident_rollback_evidence_report(environ={})

    markdown = evidence.build_incident_rollback_evidence_markdown(report)

    assert "Incident Rollback Evidence" in markdown
    assert "Plan-only mode proves no rollback" in markdown
    assert "Executes rollback" in markdown
