"""Render a redacted M1 live evidence summary from go/no-go JSON.

This renderer does not run live probes. It only reads an explicitly provided
go/no-go JSON report and turns the requested evidence sections into a concise
Markdown summary for release review and postmortem-friendly storytelling.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


M1_LIVE_EVIDENCE_SUMMARY_VERSION = "m1_live_evidence_summary.v1"
MAX_REASON_ROWS = 20
EVIDENCE_SECTION_ORDER = [
    "live_server_probe",
    "postgres_redis_live_probe",
    "postgres_redis_ops_summary",
    "backup_schedule_live_probe",
    "server_capacity_snapshot",
    "live_concurrency_probe",
    "rate_limit_live_probe",
    "probe_auth_readiness",
    "live_chat_probe",
    "docker_disk_cleanup_plan",
    "docker_build_cache_cleanup_plan",
    "docker_build_cache_cleanup_approval_gate",
    "docker_build_cache_post_cleanup",
    "restore_drill_feasibility",
    "disk_remediation_approval_gate",
    "storage_expansion_readiness",
    "external_dependency_resilience_record",
    "m1_rollout_execution_record",
    "m1_operations_review_record",
    "m1_smoke_evidence",
    "m1_deployment_gate",
]
SECTION_LABELS = {
    "live_server_probe": "Live server",
    "postgres_redis_live_probe": "PostgreSQL / Redis",
    "postgres_redis_ops_summary": "PostgreSQL / Redis ops summary",
    "backup_schedule_live_probe": "Backup schedule",
    "server_capacity_snapshot": "Capacity snapshot",
    "live_concurrency_probe": "Low-risk concurrency",
    "rate_limit_live_probe": "Rate limit",
    "probe_auth_readiness": "Probe auth",
    "live_chat_probe": "Authenticated chat SSE",
    "docker_disk_cleanup_plan": "Docker disk plan",
    "docker_build_cache_cleanup_plan": "Docker build cache plan",
    "docker_build_cache_cleanup_approval_gate": "Docker build cache approval",
    "docker_build_cache_post_cleanup": "Docker build cache post-cleanup",
    "restore_drill_feasibility": "Restore drill feasibility",
    "disk_remediation_approval_gate": "Disk remediation approval",
    "storage_expansion_readiness": "Storage expansion readiness",
    "external_dependency_resilience_record": "External dependency resilience",
    "m1_rollout_execution_record": "Rollout execution record",
    "m1_operations_review_record": "Operations review",
    "m1_smoke_evidence": "M1 smoke",
    "m1_deployment_gate": "M1 gate",
}


def _run_git(args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read go/no-go JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Go/no-go JSON must be an object: {path}")
    redacted = redact_data(payload)
    return redacted if isinstance(redacted, dict) else {}


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _section(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    sections = report.get("sections")
    if not isinstance(sections, Mapping):
        return {}
    value = sections.get(name)
    return value if isinstance(value, Mapping) else {}


def _section_status(report: Mapping[str, Any], name: str) -> str:
    statuses = report.get("section_statuses")
    if isinstance(statuses, Mapping) and name in statuses:
        return str(statuses.get(name) or "unknown")
    section = _section(report, name)
    return str(section.get("status") or "not_run")


def _get_path(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _short_metrics_for_section(name: str, section: Mapping[str, Any]) -> str:
    if not section:
        return "not requested"
    if name == "live_server_probe":
        compose = _get_path(section, "sections", "compose_services", "status")
        internal = _get_path(section, "sections", "internal_health", "status")
        public = _get_path(section, "sections", "server_side_public_health", "status")
        mock = _get_path(section, "sections", "mock_checkout", "status")
        host = _get_path(section, "sections", "host", "status")
        return f"host={host or '-'}, compose={compose or '-'}, internal={internal or '-'}, public={public or '-'}, mock={mock or '-'}"
    if name == "postgres_redis_live_probe":
        pg = _get_path(section, "sections", "postgres", "status")
        redis = _get_path(section, "sections", "redis", "status")
        compose = _get_path(section, "sections", "compose_services", "status")
        return f"postgres={pg or '-'}, redis={redis or '-'}, compose={compose or '-'}"
    if name == "postgres_redis_ops_summary":
        statuses = section.get("section_statuses")
        if not isinstance(statuses, Mapping):
            statuses = {}
        return (
            f"ops={statuses.get('ops_status') or '-'}, "
            f"live={statuses.get('live_probe') or '-'}, "
            f"recovery={statuses.get('recovery_record') or '-'}, "
            f"decision={section.get('decision') or '-'}"
        )
    if name == "backup_schedule_live_probe":
        schedule = _get_path(section, "sections", "schedule", "status")
        freshness = _get_path(section, "sections", "freshness", "status")
        return f"schedule={schedule or '-'}, freshness={freshness or '-'}"
    if name == "server_capacity_snapshot":
        host = _get_path(section, "sections", "host_capacity", "status") or _get_path(section, "sections", "host", "status")
        container = _get_path(section, "sections", "container_capacity", "status")
        cpu = _get_path(section, "sections", "host_capacity", "cpu_count") or _get_path(section, "sections", "host", "cpu_count")
        root_disk = (
            _get_path(section, "sections", "host_capacity", "disk", "root", "used_percent")
            or _get_path(section, "sections", "host", "disk_checks", "root", "used_percent")
        )
        return f"host={host or '-'}, containers={container or '-'}, cpu={cpu or '-'}, root_disk_used={root_disk or '-'}%"
    if name == "live_concurrency_probe":
        endpoints = section.get("endpoints") if isinstance(section.get("endpoints"), list) else []
        endpoint_count = len(endpoints)
        worst_p95 = None
        worst_error = None
        for item in endpoints:
            if not isinstance(item, Mapping):
                continue
            latency = item.get("latency_ms")
            p95 = latency.get("p95") if isinstance(latency, Mapping) else None
            if isinstance(p95, (int, float)):
                worst_p95 = p95 if worst_p95 is None else max(worst_p95, p95)
            error_rate = item.get("error_rate")
            if isinstance(error_rate, (int, float)):
                worst_error = error_rate if worst_error is None else max(worst_error, error_rate)
        return f"endpoints={endpoint_count}, worst_p95_ms={worst_p95 if worst_p95 is not None else '-'}, worst_error_rate={worst_error if worst_error is not None else '-'}"
    if name == "rate_limit_live_probe":
        request_count = section.get("request_count") or _get_path(section, "thresholds", "request_count")
        status_counts = section.get("status_counts")
        headers = section.get("rate_limit_headers_seen")
        return f"requests={request_count or '-'}, status_counts={status_counts or '-'}, headers={headers or '-'}"
    if name == "probe_auth_readiness":
        observations = section.get("observations") if isinstance(section.get("observations"), Mapping) else {}
        target = section.get("target") if isinstance(section.get("target"), Mapping) else {}
        return (
            f"auth={target.get('auth_strategy') or '-'}, "
            f"login={observations.get('login_performed')}, "
            f"me={observations.get('me_checked')}, "
            f"token_validated={observations.get('token_validated')}"
        )
    if name == "live_chat_probe":
        observations = section.get("observations") if isinstance(section.get("observations"), Mapping) else {}
        target = section.get("target") if isinstance(section.get("target"), Mapping) else {}
        return (
            f"auth={target.get('auth_strategy') or '-'}, "
            f"login={observations.get('login_performed')}, "
            f"stream={observations.get('stream_completed')}, "
            f"first_token_s={observations.get('first_token_seconds') or '-'}, "
            f"total_s={observations.get('total_seconds') or '-'}"
        )
    if name == "docker_disk_cleanup_plan":
        selected = section.get("selected_candidate_count") or _get_path(section, "summary", "selected_candidate_count")
        total = section.get("candidate_count") or _get_path(section, "summary", "candidate_count")
        policy = section.get("policy") if isinstance(section.get("policy"), Mapping) else {}
        return f"candidates={selected or '-'}/{total or '-'}, deletes_images={policy.get('deletes_images')}"
    if name == "docker_build_cache_cleanup_plan":
        reclaimable = _get_path(section, "build_cache", "reclaimable_mb")
        root_used = _get_path(section, "disk", "root", "used_percent")
        policy = section.get("policy") if isinstance(section.get("policy"), Mapping) else {}
        return (
            f"reclaimable={reclaimable or '-'} MB, "
            f"root_used={root_used or '-'}%, "
            f"deletes_build_cache={policy.get('deletes_build_cache')}, "
            f"system_prune={policy.get('runs_system_prune')}"
        )
    if name == "docker_build_cache_cleanup_approval_gate":
        decision = section.get("decision")
        approval = _get_path(section, "sections", "approval_record", "status")
        reclaimable = _get_path(section, "sections", "build_cache_cleanup_plan", "reclaimable_mb")
        dry_run = _get_path(section, "sections", "build_cache_cleanup_dry_run", "prune_result")
        return f"decision={decision or '-'}, approval={approval or '-'}, reclaimable={reclaimable or '-'} MB, dry_run={dry_run or '-'}"
    if name == "docker_build_cache_post_cleanup":
        decision = section.get("decision")
        reclaimed = _get_path(section, "sections", "execution", "estimated_reclaimable_delta_mb")
        root_delta = _get_path(section, "sections", "capacity_delta", "root_free_delta_mb")
        restore = _get_path(section, "sections", "restore_feasibility", "status")
        return f"decision={decision or '-'}, reclaimed={reclaimed or '-'} MB, root_delta={root_delta or '-'} MB, restore={restore or '-'}"
    if name == "restore_drill_feasibility":
        space = _get_path(section, "sections", "restore_workspace_space", "status")
        effective = _get_path(section, "sections", "restore_workspace_space", "effective_free_mb")
        required = _get_path(section, "sections", "restore_workspace_space", "required_free_mb")
        backup = _get_path(section, "sections", "postgres_backup", "status")
        return f"backup={backup or '-'}, space={space or '-'}, free={effective or '-'}/{required or '-'} MB"
    if name == "disk_remediation_approval_gate":
        decision = section.get("decision")
        approval = _get_path(section, "sections", "approval", "status")
        selected = _get_path(section, "sections", "cleanup_plan", "selected_images")
        dry_run = _get_path(section, "sections", "dry_run", "dry_run_count")
        return f"decision={decision or '-'}, approval={approval or '-'}, selected={selected or '-'}, dry_run={dry_run or '-'}"
    if name == "storage_expansion_readiness":
        strategy = _get_path(section, "sections", "recommendation", "strategy")
        gap = _get_path(section, "sections", "restore_workspace", "gap_mb")
        unmounted = _get_path(section, "sections", "block_topology", "unmounted_block_count")
        same_mount = _get_path(section, "sections", "mount_sharing", "root_docker_same_mount")
        return f"strategy={strategy or '-'}, gap={gap or '-'} MB, unmounted={unmounted or '-'}, root_docker_same_mount={same_mount}"
    if name == "external_dependency_resilience_record":
        summary = section.get("record_summary") if isinstance(section.get("record_summary"), Mapping) else {}
        checks = section.get("checks") if isinstance(section.get("checks"), Mapping) else {}
        degradation = checks.get("degradation_drill") if isinstance(checks.get("degradation_drill"), Mapping) else {}
        return (
            f"optional_services={summary.get('optional_service_count') or '-'}, "
            f"degradation_scenarios={summary.get('degradation_scenario_count') or '-'}, "
            f"tool_samples={summary.get('tool_sample_count') or '-'}, "
            f"budget_usage={summary.get('budget_usage_ratio') or '-'}, "
            f"scenarios={degradation.get('scenario_types') or '-'}"
        )
    if name == "m1_rollout_execution_record":
        summary = section.get("record_summary") if isinstance(section.get("record_summary"), Mapping) else {}
        checks = section.get("checks") if isinstance(section.get("checks"), Mapping) else {}
        rollback = checks.get("rollback_readiness") if isinstance(checks.get("rollback_readiness"), Mapping) else {}
        data_safety = checks.get("data_safety") if isinstance(checks.get("data_safety"), Mapping) else {}
        return (
            f"env={summary.get('environment') or '-'}, "
            f"phases={summary.get('deployment_phase_count') or '-'}, "
            f"issues={summary.get('issue_count') if summary.get('issue_count') is not None else '-'}, "
            f"rollback={rollback.get('status') or '-'}, "
            f"data_safety={data_safety.get('status') or '-'}"
        )
    if name == "m1_operations_review_record":
        summary = section.get("record_summary") if isinstance(section.get("record_summary"), Mapping) else {}
        checks = section.get("checks") if isinstance(section.get("checks"), Mapping) else {}
        issue_review = checks.get("issue_review") if isinstance(checks.get("issue_review"), Mapping) else {}
        followups = checks.get("followups") if isinstance(checks.get("followups"), Mapping) else {}
        boundary = checks.get("m1_boundary") if isinstance(checks.get("m1_boundary"), Mapping) else {}
        return (
            f"issues_observed={summary.get('issues_observed')}, "
            f"issues={summary.get('issue_count') if summary.get('issue_count') is not None else '-'}, "
            f"followups={summary.get('followup_count') or '-'}, "
            f"issue_review={issue_review.get('status') or '-'}, "
            f"m1_boundary={boundary.get('status') or '-'}, "
            f"followup_status={followups.get('status') or '-'}"
        )
    if name == "m1_smoke_evidence":
        return f"health={_get_path(section, 'sections', 'health_url', 'status') or '-'}, gate={_get_path(section, 'sections', 'gate', 'status') or '-'}, acceptance={_get_path(section, 'sections', 'acceptance_smoke', 'status') or '-'}"
    if name == "m1_deployment_gate":
        statuses = section.get("section_statuses")
        return f"sections={len(statuses) if isinstance(statuses, Mapping) else '-'}"
    return json.dumps(section, ensure_ascii=False, sort_keys=True)[:180]


def _boundary_for_section(name: str) -> str:
    if name == "live_server_probe":
        return "Read-only server state; not proof current local release is deployed."
    if name == "postgres_redis_live_probe":
        return "Stateful service health only; not a restore drill or load test."
    if name == "postgres_redis_ops_summary":
        return "Aggregates declarations, live probe and recovery record; still not HA, PITR or long soak proof."
    if name == "backup_schedule_live_probe":
        return "Schedule/freshness evidence only; not full restore validation."
    if name == "server_capacity_snapshot":
        return "Point-in-time resources only; not long-duration capacity proof."
    if name == "live_concurrency_probe":
        return "GET-only low-risk endpoints; not chat throughput."
    if name == "rate_limit_live_probe":
        return "One sampled path; not WAF or quota exhaustion proof."
    if name == "probe_auth_readiness":
        return "Probe authentication and /users/me only; not chat or LLM proof."
    if name == "live_chat_probe":
        return "One authenticated SSE turn; may call LLM; not concurrency or fulfillment."
    if name == "docker_disk_cleanup_plan":
        return "Read-only cleanup plan; no deletion or disk recovery unless separately approved."
    if name == "docker_build_cache_cleanup_plan":
        return "Read-only build-cache plan; no cache deletion or disk recovery unless separately approved."
    if name == "docker_build_cache_cleanup_approval_gate":
        return "Approval gate only; it does not connect SSH or delete Docker build cache."
    if name == "docker_build_cache_post_cleanup":
        return "Post-cleanup evidence only; it does not perform cleanup or prove long-term capacity."
    if name == "restore_drill_feasibility":
        return "Safety precheck only; it does not restore PostgreSQL or touch dump contents."
    if name == "disk_remediation_approval_gate":
        return "Approval gate only; it does not connect SSH or delete Docker images."
    if name == "storage_expansion_readiness":
        return "Read-only topology evidence; it does not expand disks, mount filesystems or migrate Docker data."
    if name == "external_dependency_resilience_record":
        return "Operator record only; not provider SLA, hard quota, HA or real transaction proof."
    if name == "m1_rollout_execution_record":
        return "Operator record only; not proof of autoscaling, multi-region HA or long soak."
    if name == "m1_operations_review_record":
        return "Post-rollout review only; not live infrastructure inspection or raw-log evidence."
    if name == "m1_smoke_evidence":
        return "Requested smoke scope only; final report quality depends on scenario evidence."
    return "Section-specific evidence only; keep production claims conservative."


def _evidence_table(report: Mapping[str, Any]) -> list[str]:
    rows = ["| Evidence | Status | What It Shows | Boundary |", "|---|---|---|---|"]
    seen = set()
    for name in EVIDENCE_SECTION_ORDER:
        section = _section(report, name)
        status = _section_status(report, name)
        rows.append(
            "| "
            f"{_markdown_cell(SECTION_LABELS.get(name, name))} | "
            f"`{_markdown_cell(status)}` | "
            f"{_markdown_cell(_short_metrics_for_section(name, section))} | "
            f"{_markdown_cell(_boundary_for_section(name))} |"
        )
        seen.add(name)
    sections = report.get("sections")
    if isinstance(sections, Mapping):
        for name in sorted(str(key) for key in sections.keys() if str(key) not in seen):
            section = _section(report, name)
            rows.append(
                "| "
                f"{_markdown_cell(name)} | "
                f"`{_markdown_cell(_section_status(report, name))}` | "
                f"{_markdown_cell(_short_metrics_for_section(name, section))} | "
                "Additional requested evidence section. |"
            )
    return rows


def _reason_rows(report: Mapping[str, Any], key: str, empty_label: str) -> list[str]:
    rows = ["| Section | Key | Reason |", "|---|---|---|"]
    items = report.get(key)
    if not isinstance(items, list) or not items:
        rows.append(f"| - | - | {empty_label} |")
        return rows
    for item in items[:MAX_REASON_ROWS]:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "| "
            f"{_markdown_cell(item.get('section') or item.get('target') or '-')} | "
            f"{_markdown_cell(item.get('env_var') or item.get('key') or item.get('label') or '-')} | "
            f"{_markdown_cell(item.get('reason') or item.get('finding') or item.get('status') or '-')}"
            " |"
        )
    if len(items) > MAX_REASON_ROWS:
        rows.append(f"| more | {len(items) - MAX_REASON_ROWS} omitted | See source JSON |")
    return rows


def _decision_interpretation(report: Mapping[str, Any]) -> str:
    decision = str(report.get("decision") or "not_checked")
    if decision == "go_for_m1_controlled_trial":
        return "M1 controlled trial can proceed within the documented no-real-payment/no-real-fulfillment boundary."
    if decision == "conditional_go":
        return "No hard blocker was requested, but degraded evidence must be explained and tracked before trial."
    if decision == "no_go":
        return "M1 controlled trial should not proceed until blockers are resolved."
    return "No live go/no-go evidence has been requested yet."


def build_m1_live_evidence_summary_markdown(
    report: Mapping[str, Any],
    *,
    generated_at: datetime | None = None,
    source_name: str = "go_no_go_json",
) -> str:
    """Build a redacted Markdown summary from a go/no-go report."""

    safe_report = redact_data(dict(report))
    if not isinstance(safe_report, dict):
        safe_report = {}
    now = generated_at or datetime.now(UTC)
    release_commit = _run_git(["rev-parse", "--short", "HEAD"])
    policy = safe_report.get("policy") if isinstance(safe_report.get("policy"), Mapping) else {}
    target = safe_report.get("target") if isinstance(safe_report.get("target"), Mapping) else {}
    lines = [
        "# M1 Live Evidence Summary（线上验收摘要）",
        "",
        "## 1. 总览",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Summary version | `{M1_LIVE_EVIDENCE_SUMMARY_VERSION}` |",
        f"| Generated at | `{_markdown_cell(now.isoformat())}` |",
        f"| Source | `{_markdown_cell(source_name)}` |",
        f"| Release commit | `{_markdown_cell(release_commit)}` |",
        f"| Go/no-go version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Decision | `{_markdown_cell(safe_report.get('decision'))}` |",
        f"| Interpretation | {_markdown_cell(_decision_interpretation(safe_report))} |",
        f"| Public URL present | `{_markdown_cell(target.get('public_base_url_present'))}` |",
        f"| Public URL echoed | `{_markdown_cell(target.get('public_base_url_echoed'))}` |",
        f"| Reads `.env` | `{_markdown_cell(policy.get('reads_dotenv'))}` |",
        f"| Starts services | `{_markdown_cell(policy.get('starts_services'))}` |",
        f"| May connect SSH | `{_markdown_cell(policy.get('may_connect_ssh'))}` |",
        f"| May call external APIs | `{_markdown_cell(policy.get('may_call_external_apis'))}` |",
        f"| May write runtime artifacts | `{_markdown_cell(policy.get('may_write_runtime_artifacts'))}` |",
        "| Can claim full production-ready | `no` |",
        "",
        "## 2. 证据矩阵",
        "",
        *_evidence_table(safe_report),
        "",
        "## 3. 阻塞项",
        "",
        *_reason_rows(safe_report, "blockers", "No blockers recorded."),
        "",
        "## 4. 降级项",
        "",
        *_reason_rows(safe_report, "degraded_reasons", "No degraded reasons recorded."),
        "",
        "## 5. 不能证明的事项",
        "",
    ]
    not_proven = safe_report.get("not_proven_by_this_report")
    if isinstance(not_proven, list) and not_proven:
        lines.extend(f"- {_markdown_cell(item)}" for item in not_proven)
    else:
        lines.extend(
            [
                "- 真实服务器已部署当前本地 release。",
                "- 聊天高并发、长时间稳定性、自动扩缩容和正式 SLO。",
                "- 真实支付、真实预订、库存锁价、出票或履约。",
                "- 真实密钥在供应商控制台具备最小权限且额度充足。",
                "- 备份已完成非生产库完整恢复。",
            ]
        )
    lines.extend(
        [
            "",
            "## 6. 复述口径",
            "",
            "- 可以讲：上线前把健康检查、状态服务、备份、容量、限流、低风险并发和单轮认证聊天拆成独立证据，并由 go/no-go 汇总。",
            "- 可以讲：上线执行记录、外部依赖韧性记录和运维复盘记录形成闭环，能说明发布步骤、降级演练、根因、处理动作、复验和后续项。",
            "- 可以讲：M1 范围明确不做真实支付和真实履约，模拟订单只证明前端跳转和安全边界。",
            "- 不能讲：系统已经具备完整生产级高可用、真实交易履约或大规模压测结论。",
            "",
        ]
    )
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go-no-go-json", type=_path_arg, required=True, help="Path to redacted M1 go/no-go JSON.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional Markdown output path. Defaults to stdout.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = _load_json(args.go_no_go_json)
    markdown = build_m1_live_evidence_summary_markdown(
        report,
        source_name=f"go_no_go_json:{args.go_no_go_json.name}",
    )
    if args.output is None:
        print(markdown)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
