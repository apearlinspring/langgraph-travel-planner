"""Render a private PostgreSQL/Redis operations owner questionnaire.

The questionnaire turns a declaration request into owner-facing questions and
answer skeletons. It does not read `.env`, connect to PostgreSQL/Redis/SSH, or
write server env files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_REDIS_OPS_OWNER_QUESTIONNAIRE_VERSION = "postgres_redis_ops_owner_questionnaire.v1"
POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION = "postgres_redis_ops_declaration_request.v1"
SAFE_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,100}$")


QUESTION_GUIDANCE: dict[str, dict[str, str]] = {
    "ZHIXING_POSTGRES_MODE": {
        "owner_role": "database/application owner",
        "question": "Is PostgreSQL running as single-node Compose for M1, or as managed/HA PostgreSQL?",
        "acceptable_answer": "compose-postgresql single node for M1, or managed-postgresql with HA evidence",
        "reject_if": "The answer does not mention postgres, or claims HA without managed/cluster evidence.",
    },
    "ZHIXING_REDIS_MODE": {
        "owner_role": "application/runtime owner",
        "question": "Is Redis running as single-node Compose for M1, or as managed/cluster Redis?",
        "acceptable_answer": "compose-redis single node for M1, or managed-redis with cluster/HA evidence",
        "reject_if": "The answer does not mention redis, or claims HA without managed/cluster evidence.",
    },
    "ZHIXING_DATABASE_SECRET_STATUS": {
        "owner_role": "secret owner",
        "question": "Are database credentials stored outside Git and owned for rotation?",
        "acceptable_answer": "ready/configured/rotated, with real value stored only in server shared env or secret manager",
        "reject_if": "The answer includes a credential value, says unknown, or is still a placeholder.",
    },
    "ZHIXING_REDIS_SECRET_STATUS": {
        "owner_role": "secret/runtime owner",
        "question": "Is Redis authentication or network boundary explicitly owned, and are any credentials outside Git?",
        "acceptable_answer": "ready/configured, with Redis auth or private-network boundary documented",
        "reject_if": "The answer includes a credential value, says unknown, or leaves Redis auth/network boundary unclear.",
    },
    "ZHIXING_POSTGRES_BACKUP_STATUS": {
        "owner_role": "database owner",
        "question": "Is there a current PostgreSQL backup point for M1?",
        "acceptable_answer": "passed after backup evidence is collected",
        "reject_if": "No backup artifact, schedule evidence, or latest dump metadata exists.",
    },
    "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS": {
        "owner_role": "database owner/verifier",
        "question": "Has PostgreSQL restore readiness been checked with restore drill or pg_restore catalog inspection?",
        "acceptable_answer": "passed only after restore drill or pg_restore --list/catalog check evidence",
        "reject_if": "The answer is based on intent only, without a private restore/check report.",
    },
    "ZHIXING_RPO_TARGET": {
        "owner_role": "release owner",
        "question": "What data-loss window is acceptable for the M1 controlled trial?",
        "acceptable_answer": "A numeric window such as 24h or 60min",
        "reject_if": "The answer has no number or no time unit.",
    },
    "ZHIXING_RTO_TARGET": {
        "owner_role": "release owner",
        "question": "What recovery-time window is acceptable for the M1 controlled trial?",
        "acceptable_answer": "A numeric window such as 30min or 1h",
        "reject_if": "The answer has no number or no time unit.",
    },
    "ZHIXING_POSTGRES_MIGRATION_POLICY": {
        "owner_role": "database/application owner",
        "question": "What is the migration and rollback boundary for database schema changes?",
        "acceptable_answer": "backup before migration, Alembic migration, rollback plan",
        "reject_if": "The answer does not mention migration plus backup or rollback.",
    },
    "ZHIXING_POSTGRES_SLOW_QUERY_POLICY": {
        "owner_role": "database/application owner",
        "question": "How are slow queries and long-running statements bounded for M1?",
        "acceptable_answer": "statement timeout, slow query review and index review",
        "reject_if": "The answer does not mention slow query, timeout, statement, index, or EXPLAIN review.",
    },
    "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS": {
        "owner_role": "application owner",
        "question": "What Redis lock operation timeout is accepted for M1 latency budget?",
        "acceptable_answer": "0.5 seconds, or another numeric value no higher than 5 seconds",
        "reject_if": "The answer is non-numeric, zero/negative, or higher than the M1 target without risk acceptance.",
    },
    "ZHIXING_REDIS_PERSISTENCE_STATUS": {
        "owner_role": "runtime owner",
        "question": "What Redis persistence mode protects lock/cache recovery for M1?",
        "acceptable_answer": "AOF appendonly ready, or managed Redis snapshot/RDB policy",
        "reject_if": "The answer does not mention appendonly/AOF/snapshot/RDB/persistence.",
    },
    "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS": {
        "owner_role": "runtime/security owner",
        "question": "Is Redis blocked from public internet exposure?",
        "acceptable_answer": "private internal network, not exposed, or firewalled from public internet",
        "reject_if": "The answer implies 0.0.0.0/public open/open to internet, or omits private/firewall wording.",
    },
    "ZHIXING_REDIS_RECOVERY_STRATEGY": {
        "owner_role": "runtime/application owner",
        "question": "How should Redis recover, and what session-lock/cache impact is accepted?",
        "acceptable_answer": "restore from AOF/RDB snapshot or restart/rebuild, with active session impact documented",
        "reject_if": "The answer does not mention restart, restore, snapshot, AOF, rebuild, or recovery impact.",
    },
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} JSON could not be read or parsed.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} JSON must be an object.")
    return payload


def _accepted_value_template(item: Mapping[str, Any]) -> str:
    bucket = str(item.get("execution_bucket") or "")
    env_var = str(item.get("env_var") or "")
    if bucket in {"can_prepare_from_live_probe", "requires_owner_acceptance"}:
        return str(item.get("suggested_value") or "")
    if bucket == "requires_backup_or_restore_artifact":
        return f"<evidence-backed-value-for-{env_var}>"
    return f"<owner-confirmed-value-for-{env_var}>"


def _question_for(item: Mapping[str, Any]) -> dict[str, Any]:
    env_var = str(item.get("env_var") or "").strip()
    guidance = QUESTION_GUIDANCE.get(
        env_var,
        {
            "owner_role": "operations owner",
            "question": "What accepted non-secret operations declaration should be used?",
            "acceptable_answer": "A non-secret, evidence-backed operations declaration.",
            "reject_if": "The answer is a placeholder, secret-like value, URL, IP address or unverified claim.",
        },
    )
    return {
        "env_var": env_var,
        "category": item.get("category"),
        "execution_bucket": item.get("execution_bucket"),
        "owner_role": guidance["owner_role"],
        "question": guidance["question"],
        "suggested_answer": item.get("suggested_value"),
        "accepted_value_template": _accepted_value_template(item),
        "acceptable_answer": guidance["acceptable_answer"],
        "evidence_needed": item.get("evidence_needed"),
        "reject_if": guidance["reject_if"],
        "owner_confirmed": False,
        "evidence_ref": "<private-evidence-ref>",
        "value_echoed": False,
    }


def build_postgres_redis_ops_owner_questionnaire(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build owner-facing questions from a declaration request."""

    blocked_reasons = []
    if request.get("version") != POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION:
        blocked_reasons.append({"check": "request", "finding": "Declaration request version is not recognized."})

    questions = []
    for item in _as_list(request.get("declarations")):
        if not isinstance(item, Mapping):
            continue
        env_var = str(item.get("env_var") or "").strip()
        if not SAFE_ENV_NAME_PATTERN.fullmatch(env_var):
            continue
        questions.append(_question_for(item))

    if not questions:
        blocked_reasons.append({"check": "request", "finding": "Declaration request has no owner questions."})

    bucket_counts = {
        bucket: sum(1 for item in questions if item["execution_bucket"] == bucket)
        for bucket in sorted({str(item["execution_bucket"]) for item in questions})
    }
    record_answer_skeleton = {
        "record_id": "<postgres-redis-ops-declaration-YYYYMMDD>",
        "accepted_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "M1 PostgreSQL/Redis non-secret operations declarations",
        "owner": "<operations-owner-role>",
        "declarations": [
            {
                "env_var": item["env_var"],
                "accepted_value": item["accepted_value_template"],
                "source_bucket": item["execution_bucket"],
                "owner_confirmed": False,
                "evidence_ref": "<private-evidence-ref>",
                "value_echoed": False,
            }
            for item in questions
        ],
    }
    return {
        "version": POSTGRES_REDIS_OPS_OWNER_QUESTIONNAIRE_VERSION,
        "status": "blocked" if blocked_reasons else ("passed" if not questions else "action_required"),
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "connects_ssh": False,
            "writes_server_env": False,
            "echoes_secret_values": False,
            "safe_to_commit": False,
        },
        "source_status": {
            "request_status": request.get("status"),
            "request_missing_count": request.get("missing_count"),
        },
        "question_count": len(questions),
        "execution_bucket_counts": bucket_counts,
        "questions": questions,
        "record_answer_skeleton": record_answer_skeleton,
        "blocked_reasons": blocked_reasons,
        "not_proven_by_this_questionnaire": [
            "Owner answers have not been accepted by this questionnaire.",
            "The accepted declarations have not been written to the server.",
            "Backup and restore evidence still require private artifacts.",
            "M1 single-node Compose declarations remain degraded for full production HA.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_postgres_redis_ops_owner_questionnaire_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL / Redis Ops Owner Questionnaire",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Questions: `{_markdown_cell(report.get('question_count'))}`",
        "- Policy: no `.env`, no database rows, no Redis keys, no SSH, no server env writes.",
        "",
        "## Execution Buckets",
        "",
    ]
    for bucket, count in _as_mapping(report.get("execution_bucket_counts")).items():
        lines.append(f"- `{_markdown_cell(bucket)}`: `{_markdown_cell(count)}`")
    lines.extend(
        [
            "",
            "## Questions",
            "",
            "| Env Var | Bucket | Owner | Question | Acceptable Answer | Evidence Needed | Reject If |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in _as_list(report.get("questions")):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"{_markdown_cell(item.get('execution_bucket'))} | "
            f"{_markdown_cell(item.get('owner_role'))} | "
            f"{_markdown_cell(item.get('question'))} | "
            f"{_markdown_cell(item.get('acceptable_answer'))} | "
            f"{_markdown_cell(item.get('evidence_needed'))} | "
            f"{_markdown_cell(item.get('reject_if'))} |"
        )
    lines.extend(["", "## Answer Skeleton", ""])
    for item in _as_list(_as_mapping(report.get("record_answer_skeleton")).get("declarations")):
        if not isinstance(item, Mapping):
            continue
        lines.append(f"```text\n{_markdown_cell(item.get('env_var'))}={_markdown_cell(item.get('accepted_value'))}\n```")
        lines.append("- owner_confirmed: `false`")
        lines.append("- evidence_ref: `<private-evidence-ref>`")
    lines.extend(["", "## Boundary", ""])
    for item in _as_list(report.get("not_proven_by_this_questionnaire")):
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", type=_path_arg, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        request = _read_json(args.request_json, label="request")
        report = build_postgres_redis_ops_owner_questionnaire(request)
    except ValueError as exc:
        report = {
            "version": POSTGRES_REDIS_OPS_OWNER_QUESTIONNAIRE_VERSION,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "connects_database": False,
                "connects_redis": False,
                "connects_ssh": False,
                "writes_server_env": False,
            },
            "blocked_reasons": [{"check": "input", "finding": str(exc)}],
        }
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.json and not args.markdown
        else build_postgres_redis_ops_owner_questionnaire_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + ("\n" if not output_text.endswith("\n") else ""), encoding="utf-8")
    else:
        print(output_text, end="" if output_text.endswith("\n") else "\n")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
