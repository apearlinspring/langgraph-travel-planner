import json
from pathlib import Path

from scripts import check_live_chat_concurrency_probe_approval as approval


def _approval_record():
    return {
        "version": approval.LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION,
        "approval_id": "live-chat-concurrency-probe-20260703",
        "approved_by_role": "release operator",
        "approved_at": "2026-07-03T10:00:00+08:00",
        "scope": "register or reuse one probe user and execute a tiny live chat SSE concurrency sample",
        "reason": "M1 needs a bounded chat-path concurrency and long-tail latency sample.",
        "allowed_actions": {
            "register_or_reuse_probe_user": True,
            "create_probe_conversations": True,
            "send_chat_sse_prompts": True,
        },
        "runtime_write_acknowledgement": {
            "may_create_probe_user": True,
            "may_create_probe_conversations": True,
            "may_write_probe_messages": True,
            "max_probe_conversations": 3,
            "max_concurrency": 2,
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
            "redaction_scan": True,
            "public_status_update": True,
            "blocked_or_degraded_reasons_recorded": True,
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
        "notes": "Three chat probes at concurrency two are acceptable for M1.",
    }


def test_live_chat_concurrency_approval_ready_without_record():
    report = approval.build_live_chat_concurrency_probe_approval_report()

    assert report["status"] == "degraded"
    assert report["decision"] == "ready_for_explicit_approval"
    assert report["sections"]["approval_record"]["status"] == "not_checked"
    assert report["policy"]["calls_chat_endpoint"] is False


def test_live_chat_concurrency_approval_passes_with_valid_record():
    report = approval.build_live_chat_concurrency_probe_approval_report(
        approval=_approval_record()
    )

    assert report["status"] == "passed"
    assert report["decision"] == "approved_for_live_chat_concurrency_probe"
    assert report["approved_limits"]["max_probe_conversations"] == 3
    assert report["approved_limits"]["max_concurrency"] == 2


def test_live_chat_concurrency_approval_blocks_load_test_scope():
    record = _approval_record()
    record["forbidden_actions_confirmed"]["load_test"] = False

    report = approval.build_live_chat_concurrency_probe_approval_report(approval=record)

    assert report["status"] == "blocked"
    assert any(
        item["key"] == "forbidden_load_test_not_confirmed"
        for item in report["blocked_reasons"]
    )


def test_live_chat_concurrency_approval_blocks_raw_private_values():
    record = _approval_record()
    raw_ip = "203.0.113" + ".10"
    secret = "sk-" + "private-1234567890123456"
    record["notes"] = f"server is {raw_ip} and token={secret}"

    report = approval.build_live_chat_concurrency_probe_approval_report(approval=record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "raw_ip_present" for item in report["blocked_reasons"])
    assert any(item["key"] == "secret_shape_present" for item in report["blocked_reasons"])


def test_live_chat_concurrency_approval_template_cli_writes_utf8(tmp_path: Path):
    output = tmp_path / "approval-template.json"

    code = approval.main(["--template", "--output", str(output)])

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["allowed_actions"]["send_chat_sse_prompts"] is True
    assert payload["forbidden_actions_confirmed"]["real_payment"] is True


def test_live_chat_concurrency_approval_cli_redacts_path(tmp_path: Path):
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
    assert "approved_for_live_chat_concurrency_probe" in payload
