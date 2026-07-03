import json
from pathlib import Path

from scripts import render_postgres_redis_ops_owner_questionnaire as questionnaire


def _request():
    return {
        "version": "postgres_redis_ops_declaration_request.v1",
        "status": "blocked",
        "missing_count": 4,
        "declarations": [
            {
                "env_var": "ZHIXING_POSTGRES_MODE",
                "category": "service_mode",
                "suggested_value": "compose-postgresql single node for M1",
                "evidence_needed": "Live probe evidence.",
                "execution_bucket": "can_prepare_from_live_probe",
            },
            {
                "env_var": "ZHIXING_POSTGRES_BACKUP_STATUS",
                "category": "backup_restore",
                "suggested_value": "passed after backup evidence is collected",
                "evidence_needed": "Backup schedule/live probe or latest dump metadata.",
                "execution_bucket": "requires_backup_or_restore_artifact",
            },
            {
                "env_var": "ZHIXING_RPO_TARGET",
                "category": "rpo_rto",
                "suggested_value": "24h for M1 controlled trial",
                "evidence_needed": "Owner accepts M1 data-loss window.",
                "execution_bucket": "requires_operator_confirmation",
            },
            {
                "env_var": "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS",
                "category": "redis_lock",
                "suggested_value": "0.5",
                "evidence_needed": "M1 latency budget accepts this timeout.",
                "execution_bucket": "requires_owner_acceptance",
            },
        ],
    }


def test_owner_questionnaire_builds_bucketed_questions_without_confirmation():
    report = questionnaire.build_postgres_redis_ops_owner_questionnaire(_request())
    by_env = {item["env_var"]: item for item in report["questions"]}

    assert report["status"] == "action_required"
    assert report["question_count"] == 4
    assert report["execution_bucket_counts"] == {
        "can_prepare_from_live_probe": 1,
        "requires_backup_or_restore_artifact": 1,
        "requires_operator_confirmation": 1,
        "requires_owner_acceptance": 1,
    }
    assert by_env["ZHIXING_POSTGRES_MODE"]["owner_role"] == "database/application owner"
    assert by_env["ZHIXING_POSTGRES_BACKUP_STATUS"]["accepted_value_template"].startswith(
        "<evidence-backed-value-for-"
    )
    assert by_env["SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS"]["accepted_value_template"] == "0.5"
    assert all(item["owner_confirmed"] is False for item in report["questions"])
    assert all(
        item["owner_confirmed"] is False
        for item in report["record_answer_skeleton"]["declarations"]
    )


def test_owner_questionnaire_markdown_contains_questions_and_boundaries():
    report = questionnaire.build_postgres_redis_ops_owner_questionnaire(_request())

    markdown = questionnaire.build_postgres_redis_ops_owner_questionnaire_markdown(report)

    assert "PostgreSQL / Redis Ops Owner Questionnaire" in markdown
    assert "requires_backup_or_restore_artifact" in markdown
    assert "What data-loss window is acceptable" in markdown
    assert "owner_confirmed: `false`" in markdown
    assert "no `.env`" in markdown


def test_owner_questionnaire_blocks_unknown_request_version():
    request = _request()
    request["version"] = "unknown"

    report = questionnaire.build_postgres_redis_ops_owner_questionnaire(request)

    assert report["status"] == "blocked"
    assert report["blocked_reasons"]


def test_owner_questionnaire_cli_writes_markdown(tmp_path: Path):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "questionnaire.md"
    request_path.write_text(json.dumps(_request(), ensure_ascii=False), encoding="utf-8")

    code = questionnaire.main(
        [
            "--request-json",
            str(request_path),
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    assert "ZHIXING_POSTGRES_MODE" in output_path.read_text(encoding="utf-8")
