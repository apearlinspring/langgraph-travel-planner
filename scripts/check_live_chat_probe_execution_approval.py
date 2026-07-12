"""Validate a private live-chat probe execution approval record.

This checker reads an explicit JSON approval record only. It does not read
`.env`, connect to SSH, call auth/chat endpoints, register users, create
conversations, call LLMs, inspect logs, query databases or read Redis keys.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._evidence_record_helpers import (  # noqa: E402
    as_mapping as _as_mapping,
    make_final_text_checker,
    make_path_arg,
    make_placeholder_checker,
    read_optional_json_object as _read_json,
)


LIVE_CHAT_PROBE_EXECUTION_APPROVAL_VERSION = "live_chat_probe_execution_approval.v1"
APPROVAL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{5,80}$")
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
RAW_IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
SECRET_SHAPE_PATTERN = re.compile(
    r"(?i)(sk-[a-z0-9_-]{16,}|akia[0-9a-z]{16}|AIza[0-9A-Za-z_-]{20,}|"
    r"bearer\s+[a-z0-9._-]{16,}|access[_-]?token\s*[:=])"
)
LOCAL_PATH_PATTERN = re.compile(r"(?i)([a-z]:\\Users\\|/home/|/root/|\.env|\.runtime|\.venv|vectorstore)")


_path_arg = make_path_arg(PROJECT_ROOT)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=(),
)
_has_final_text = make_final_text_checker(_looks_placeholder)


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _blocker(key: str, finding: str) -> dict[str, str]:
    return {"key": key, "finding": finding}


def _approval_template() -> dict[str, Any]:
    return {
        "approval_id": "<live-chat-probe-YYYYMMDD>",
        "approved_by_role": "<operator role, not a personal contact>",
        "approved_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "register or reuse one m1_probe test user and execute one live chat SSE probe",
        "reason": "M1 business-link evidence requires one controlled online auth, conversation and SSE chat probe.",
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
        "notes": "<why this single probe is safe enough for M1 controlled trial>",
    }


def _raw_text_blockers(record: Mapping[str, Any]) -> list[dict[str, str]]:
    def iter_string_values(value: Any) -> Iterable[str]:
        if isinstance(value, Mapping):
            for child in value.values():
                yield from iter_string_values(child)
        elif isinstance(value, list | tuple):
            for child in value:
                yield from iter_string_values(child)
        elif isinstance(value, str):
            yield value

    raw = "\n".join(iter_string_values(record))
    blockers: list[dict[str, str]] = []
    if RAW_IPV4_PATTERN.search(raw):
        blockers.append(_blocker("raw_ip_present", "Approval record must not contain raw server IP addresses."))
    if SECRET_SHAPE_PATTERN.search(raw):
        blockers.append(_blocker("secret_shape_present", "Approval record must not contain token or API-key shaped values."))
    if LOCAL_PATH_PATTERN.search(raw):
        blockers.append(_blocker("private_path_present", "Approval record must not contain private paths, .env, runtime or vectorstore references."))
    return blockers


def _approval_status(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {
            "status": "not_checked",
            "decision": "ready_for_explicit_approval",
            "approval_present": False,
            "blocked_reasons": [],
            "degraded_reasons": [
                _blocker("approval_record_missing", "Approval record has not been supplied yet.")
            ],
        }

    blocked = _raw_text_blockers(record)
    if not APPROVAL_ID_PATTERN.match(str(record.get("approval_id") or "")):
        blocked.append(_blocker("invalid_approval_id", "approval_id must be a stable non-placeholder identifier."))
    for key in ("approved_by_role", "approved_at", "scope", "reason", "notes"):
        if not _has_final_text(record.get(key)):
            blocked.append(_blocker(f"missing_{key}", f"{key} must be filled with non-placeholder text."))

    allowed = _as_mapping(record.get("allowed_actions"))
    for key in ("register_or_reuse_probe_user", "create_probe_conversation", "send_one_chat_sse_prompt"):
        if allowed.get(key) is not True:
            blocked.append(_blocker(f"allowed_{key}_missing", f"Approval must explicitly allow {key}."))

    writes = _as_mapping(record.get("runtime_write_acknowledgement"))
    for key in ("may_create_probe_user", "may_create_probe_conversation", "may_write_probe_messages"):
        if writes.get(key) is not True:
            blocked.append(_blocker(f"runtime_write_{key}_missing", f"Approval must acknowledge {key}."))
    try:
        max_conversations = int(writes.get("max_probe_conversations", 0))
    except (TypeError, ValueError):
        max_conversations = 0
    if max_conversations != 1:
        blocked.append(_blocker("max_probe_conversations_not_one", "Approval must limit the run to exactly one probe conversation."))

    forbidden = _as_mapping(record.get("forbidden_actions_confirmed"))
    for key in (
        "real_payment",
        "real_booking",
        "inventory_lock",
        "ticketing",
        "fulfillment",
        "load_test",
        "database_edits",
        "read_env_files",
        "read_logs",
        "query_database_rows",
        "read_redis_keys",
        "export_vectorstores",
    ):
        if forbidden.get(key) is not True:
            blocked.append(_blocker(f"forbidden_{key}_not_confirmed", f"Approval must forbid {key}."))

    post = _as_mapping(record.get("post_execution_required_checks"))
    for key in ("m1_go_no_go_rerun", "acceptance_record_rerender", "redaction_scan"):
        if post.get(key) is not True:
            blocked.append(_blocker(f"post_check_{key}_missing", f"Post execution check {key} must be required."))

    redaction = _as_mapping(record.get("redaction_boundary"))
    for key in (
        "public_url_included",
        "server_ip_included",
        "probe_username_included",
        "probe_password_included",
        "probe_email_included",
        "token_included",
        "prompt_included",
        "assistant_text_included",
    ):
        if redaction.get(key) is not False:
            blocked.append(_blocker(f"redaction_{key}", f"Redaction boundary must mark {key}=false."))

    return {
        "status": "blocked" if blocked else "passed",
        "decision": "not_ready_for_live_chat_probe" if blocked else "approved_for_one_live_chat_probe",
        "approval_present": True,
        "blocked_reasons": blocked,
        "degraded_reasons": [],
    }


def build_live_chat_probe_execution_approval_report(
    *,
    approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a redacted approval report for one live chat probe execution."""

    approval_section = _approval_status(approval)
    status = str(approval_section["status"])
    if status == "not_checked":
        overall_status = "degraded"
    else:
        overall_status = status
    decision = str(approval_section["decision"])
    return {
        "version": LIVE_CHAT_PROBE_EXECUTION_APPROVAL_VERSION,
        "status": overall_status,
        "decision": decision,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "calls_auth_endpoint": False,
            "calls_chat_endpoint": False,
            "calls_llm": False,
            "registers_user": False,
            "creates_conversation": False,
            "writes_runtime_messages": False,
            "records_credentials": False,
            "records_prompt": False,
            "records_assistant_text": False,
            "does_not_echo_private_values": True,
        },
        "sections": {
            "approval_record": approval_section,
        },
        "blocked_reasons": list(approval_section.get("blocked_reasons") or []),
        "degraded_reasons": list(approval_section.get("degraded_reasons") or []),
        "declaration_statuses": {
            "ZHIXING_LIVE_CHAT_PROBE_EXECUTION_APPROVAL_STATUS": overall_status,
        },
    }


def build_live_chat_probe_execution_approval_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Live Chat Probe Execution Approval",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Decision: `{report.get('decision')}`",
        f"- Version: `{report.get('version')}`",
        "- This checker does not register users, create conversations, call chat, call LLMs or read `.env`.",
        "",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
        lines.append("")
    if report.get("degraded_reasons"):
        lines.extend(["## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-json", type=_path_arg, default=None, help="Private live chat probe approval JSON. Path is not echoed.")
    parser.add_argument("--template", action="store_true", help="Write an approval record template.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        payload: Any = _approval_template()
        exit_code = 0
    else:
        approval_record, approval_error = _read_json(args.approval_json, label="approval") if args.approval_json else (None, None)
        report = build_live_chat_probe_execution_approval_report(approval=approval_record)
        if approval_error is not None:
            report["status"] = "blocked"
            report["decision"] = "not_ready_for_live_chat_probe"
            report["sections"]["approval_record"] = {
                "status": "blocked",
                "blocked_reasons": [approval_error],
                "degraded_reasons": [],
            }
            report["blocked_reasons"] = [approval_error]
            report["degraded_reasons"] = []
        payload = report if args.json else build_live_chat_probe_execution_approval_markdown(report)
        exit_code = 2 if str(report.get("status")) == "blocked" else 0

    if args.output is None:
        if isinstance(payload, str):
            print(payload, end="" if payload.endswith("\n") else "\n")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            args.output.write_text(payload, encoding="utf-8")
        else:
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
