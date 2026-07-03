"""Validate a private live-chat concurrency probe approval record.

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
LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION = "live_chat_concurrency_probe_approval.v1"
APPROVAL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{5,80}$")
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
RAW_IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
RAW_URL_PATTERN = re.compile(r"(?i)\bhttps?://")
SECRET_SHAPE_PATTERN = re.compile(
    r"(?i)(sk-[a-z0-9_-]{16,}|akia[0-9a-z]{16}|AIza[0-9A-Za-z_-]{20,}|"
    r"bearer\s+[a-z0-9._-]{16,}|access[_-]?token\s*[:=])"
)
LOCAL_PATH_PATTERN = re.compile(r"(?i)([a-z]:\\Users\\|/home/|/root/|\.env|\.runtime|\.venv|vectorstore)")


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, {"key": f"missing_{label}", "finding": f"{label} JSON path is required.", "path_echoed": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {"key": f"unreadable_{label}", "finding": f"{label} JSON could not be read.", "path_echoed": False}
    if not isinstance(payload, dict):
        return None, {"key": f"invalid_{label}", "finding": f"{label} JSON must be an object.", "path_echoed": False}
    return payload, None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _looks_placeholder(value: Any) -> bool:
    text = str(value or "").strip().strip("'\"").lower()
    if text in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(text.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _has_final_text(value: Any) -> bool:
    return bool(str(value or "").strip()) and not _looks_placeholder(value)


def _blocker(key: str, finding: str) -> dict[str, str]:
    return {"key": key, "finding": finding}


def _approval_template() -> dict[str, Any]:
    return {
        "version": LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION,
        "approval_id": "<live-chat-concurrency-probe-YYYYMMDD>",
        "approved_by_role": "<operator role, not a personal contact>",
        "approved_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "register or reuse one probe user and execute a tiny live chat SSE concurrency sample",
        "reason": "M1 needs a bounded chat-path concurrency and long-tail latency sample after formal deployment switch.",
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
        "notes": "<why this bounded sample is safe enough for M1 controlled trial>",
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
    if RAW_URL_PATTERN.search(raw):
        blockers.append(_blocker("raw_url_present", "Approval record must not contain public URLs."))
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
            "approved_limits": {},
            "blocked_reasons": [],
            "degraded_reasons": [
                _blocker("approval_record_missing", "Approval record has not been supplied yet.")
            ],
        }

    blocked = _raw_text_blockers(record)
    if record.get("version") != LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION:
        blocked.append(_blocker("invalid_version", "Approval record version must match the live chat concurrency probe approval schema."))
    if not APPROVAL_ID_PATTERN.match(str(record.get("approval_id") or "")):
        blocked.append(_blocker("invalid_approval_id", "approval_id must be a stable non-placeholder identifier."))
    for key in ("approved_by_role", "approved_at", "scope", "reason", "notes"):
        if not _has_final_text(record.get(key)):
            blocked.append(_blocker(f"missing_{key}", f"{key} must be filled with non-placeholder text."))

    allowed = _as_mapping(record.get("allowed_actions"))
    for key in ("register_or_reuse_probe_user", "create_probe_conversations", "send_chat_sse_prompts"):
        if allowed.get(key) is not True:
            blocked.append(_blocker(f"allowed_{key}_missing", f"Approval must explicitly allow {key}."))

    writes = _as_mapping(record.get("runtime_write_acknowledgement"))
    for key in ("may_create_probe_user", "may_create_probe_conversations", "may_write_probe_messages"):
        if writes.get(key) is not True:
            blocked.append(_blocker(f"runtime_write_{key}_missing", f"Approval must acknowledge {key}."))
    try:
        max_conversations = int(writes.get("max_probe_conversations", 0))
    except (TypeError, ValueError):
        max_conversations = 0
    try:
        max_concurrency = int(writes.get("max_concurrency", 0))
    except (TypeError, ValueError):
        max_concurrency = 0
    if not 2 <= max_conversations <= 5:
        blocked.append(_blocker("max_probe_conversations_out_of_bounds", "Approval must limit probe conversations to 2..5."))
    if not 1 <= max_concurrency <= 3:
        blocked.append(_blocker("max_concurrency_out_of_bounds", "Approval must limit chat concurrency to 1..3."))
    if max_concurrency > max_conversations > 0:
        blocked.append(_blocker("max_concurrency_exceeds_conversations", "Approval concurrency must not exceed probe conversations."))

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
    for key in ("redaction_scan", "public_status_update", "blocked_or_degraded_reasons_recorded"):
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
        "decision": "not_ready_for_live_chat_concurrency_probe" if blocked else "approved_for_live_chat_concurrency_probe",
        "approval_present": True,
        "approved_limits": {
            "max_probe_conversations": max_conversations,
            "max_concurrency": max_concurrency,
        },
        "approved_actions": dict(allowed),
        "blocked_reasons": blocked,
        "degraded_reasons": [],
    }


def build_live_chat_concurrency_probe_approval_report(
    *,
    approval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a redacted approval report for a tiny live chat concurrency probe."""

    approval_section = _approval_status(approval)
    status = str(approval_section["status"])
    overall_status = "degraded" if status == "not_checked" else status
    decision = str(approval_section["decision"])
    return {
        "version": LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION,
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
        "approved_limits": dict(approval_section.get("approved_limits") or {}),
        "approved_actions": dict(approval_section.get("approved_actions") or {}),
        "blocked_reasons": list(approval_section.get("blocked_reasons") or []),
        "degraded_reasons": list(approval_section.get("degraded_reasons") or []),
        "declaration_statuses": {
            "ZHIXING_LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_STATUS": overall_status,
        },
    }


def build_live_chat_concurrency_probe_approval_markdown(report: Mapping[str, Any]) -> str:
    limits = report.get("approved_limits") if isinstance(report.get("approved_limits"), Mapping) else {}
    lines = [
        "# Live Chat Concurrency Probe Approval",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Decision: `{report.get('decision')}`",
        f"- Version: `{report.get('version')}`",
        f"- Max probe conversations: `{limits.get('max_probe_conversations', '-')}`",
        f"- Max concurrency: `{limits.get('max_concurrency', '-')}`",
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
    parser.add_argument("--approval-json", type=_path_arg, default=None, help="Private live chat concurrency approval JSON. Path is not echoed.")
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
        report = build_live_chat_concurrency_probe_approval_report(approval=approval_record)
        if approval_error is not None:
            report["status"] = "blocked"
            report["decision"] = "not_ready_for_live_chat_concurrency_probe"
            report["sections"]["approval_record"] = {
                "status": "blocked",
                "blocked_reasons": [approval_error],
                "degraded_reasons": [],
                "approved_limits": {},
            }
            report["approved_limits"] = {}
            report["approved_actions"] = {}
            report["blocked_reasons"] = [approval_error]
            report["degraded_reasons"] = []
        payload = report if args.json else build_live_chat_concurrency_probe_approval_markdown(report)
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
