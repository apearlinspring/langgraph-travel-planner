import json
from pathlib import Path

from scripts import check_live_chat_probe_execution_approval as approval


def _approval_record():
    return {
        "approval_id": "live-chat-probe-20260625",
        "approved_by_role": "release operator",
        "approved_at": "2026-06-25T10:00:00+08:00",
        "scope": "register or reuse one m1_probe test user and execute one live chat SSE probe",
        "reason": "M1 business-link evidence requires one controlled probe.",
        "allowed_actions": {
            "register_or_reuse_probe_user": True,
            "create_probe_conversation": True,
            "send_one_chat_sse_prompt": True,
        },
        "runtime_write_acknowledgement": {
            "may_create_probe_user": True,
            "may_create_probe_conversation": True,
            "may_write_probe_messages": True,
            "max_probe_conversations": 1,
        },
        "forbidden_actions_confirmed": {
            "real_payment": True,
            "real_booking": True,
            "inventory_lock": True,
            "ticketing": True,
            "fulfillment": True,
            "load_test": True,
            "database_edits": True,
            "read_env_files": True,
            "read_logs": True,
            "query_database_rows": True,
            "read_redis_keys": True,
            "export_vectorstores": True,
        },
        "post_execution_required_checks": {
            "m1_go_no_go_rerun": True,
            "acceptance_record_rerender": True,
            "redaction_scan": True,
        },
        "redaction_boundary": {
            "public_url_included": False,
            "server_ip_included": False,
            "probe_username_included": False,
            "probe_password_included": False,
            "probe_email_included": False,
            "token_included": False,
            "prompt_included": False,
            "assistant_text_included": False,
        },
        "notes": "One controlled M1 probe is acceptable.",
    }


def test_live_chat_probe_execution_approval_ready_without_record():
    report = approval.build_live_chat_probe_execution_approval_report()

    assert report["status"] == "degraded"
    assert report["decision"] == "ready_for_explicit_approval"
    assert report["sections"]["approval_record"]["status"] == "not_checked"
    assert report["policy"]["calls_chat_endpoint"] is False


def test_live_chat_probe_execution_approval_passes_with_valid_record():
    report = approval.build_live_chat_probe_execution_approval_report(
        approval=_approval_record()
    )

    assert report["status"] == "passed"
    assert report["decision"] == "approved_for_one_live_chat_probe"
    assert report["sections"]["approval_record"]["status"] == "passed"


def test_live_chat_probe_execution_approval_blocks_real_payment_scope():
    record = _approval_record()
    record["forbidden_actions_confirmed"]["real_payment"] = False

    report = approval.build_live_chat_probe_execution_approval_report(approval=record)

    assert report["status"] == "blocked"
    assert report["decision"] == "not_ready_for_live_chat_probe"
    assert any(
        item["key"] == "forbidden_real_payment_not_confirmed"
        for item in report["blocked_reasons"]
    )


def test_live_chat_probe_execution_approval_blocks_raw_private_values():
    record = _approval_record()
    raw_ip = "203.0.113" + ".10"
    secret = "sk-" + "private-1234567890123456"
    record["notes"] = f"server is {raw_ip} and token={secret}"

    report = approval.build_live_chat_probe_execution_approval_report(approval=record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "raw_ip_present" for item in report["blocked_reasons"])
    assert any(item["key"] == "secret_shape_present" for item in report["blocked_reasons"])


def test_live_chat_probe_execution_approval_template_cli_writes_utf8(tmp_path: Path):
    output = tmp_path / "approval-template.json"

    code = approval.main(["--template", "--output", str(output)])

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["allowed_actions"]["send_one_chat_sse_prompt"] is True
    assert payload["forbidden_actions_confirmed"]["real_payment"] is True


def test_live_chat_probe_execution_approval_cli_redacts_path(tmp_path: Path):
    record_path = tmp_path / "approval.json"
    output = tmp_path / "approval-report.json"
    record_path.write_text(json.dumps(_approval_record()), encoding="utf-8")

    code = approval.main(
        [
            "--approval-json",
            str(record_path),
            "--json",
            "--output",
            str(output),
        ]
    )
    payload = output.read_text(encoding="utf-8")

    assert code == 0
    assert str(record_path) not in payload
    assert "approved_for_one_live_chat_probe" in payload
