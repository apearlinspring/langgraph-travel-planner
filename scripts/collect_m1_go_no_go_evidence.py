"""Collect the final redacted M1 go/no-go evidence package.

This script aggregates existing readiness and operations evidence without
reading .env files, starting services, executing rollback, or echoing secret
values. Live health and acceptance smoke checks run only when explicit flags are
provided.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_deployment_gate import (  # noqa: E402
    DEFAULT_BASE_URL,
    build_m1_deployment_gate_report,
)
from scripts.check_server_preflight_readiness import (  # noqa: E402
    build_server_preflight_readiness_report,
)
from scripts.check_postgres_redis_ops_status import (  # noqa: E402
    build_postgres_redis_ops_status_report,
)
from scripts.check_external_dependency_resilience_record import (  # noqa: E402
    EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION,
    build_external_dependency_resilience_record_report,
)
from scripts.check_m1_rollout_execution_record import (  # noqa: E402
    M1_ROLLOUT_EXECUTION_RECORD_VERSION,
    build_m1_rollout_execution_record_report,
)
from scripts.check_m1_operations_review_record import (  # noqa: E402
    M1_OPERATIONS_REVIEW_RECORD_VERSION,
    build_m1_operations_review_record_report,
)
from scripts.check_probe_auth_readiness import (  # noqa: E402
    DEFAULT_ACCESS_TOKEN_ENV as PROBE_AUTH_DEFAULT_ACCESS_TOKEN_ENV,
    DEFAULT_PASSWORD_ENV as PROBE_AUTH_DEFAULT_PASSWORD_ENV,
    DEFAULT_USERNAME_ENV as PROBE_AUTH_DEFAULT_USERNAME_ENV,
    build_probe_auth_readiness_report,
)
from scripts.check_live_chat_probe_execution_approval import (  # noqa: E402
    LIVE_CHAT_PROBE_EXECUTION_APPROVAL_VERSION,
)
from scripts.collect_backup_restore_drill_evidence import (  # noqa: E402
    build_backup_restore_drill_evidence_report,
)
from scripts.collect_backup_schedule_live_probe import (  # noqa: E402
    build_backup_schedule_live_probe_report,
)
from scripts.collect_docker_disk_cleanup_plan import (  # noqa: E402
    build_docker_disk_cleanup_plan_report,
)
from scripts.collect_docker_build_cache_cleanup_plan import (  # noqa: E402
    build_docker_build_cache_cleanup_plan_report,
)
from scripts.collect_incident_rollback_evidence import (  # noqa: E402
    build_incident_rollback_evidence_report,
)
from scripts.collect_live_server_probe import (  # noqa: E402
    build_live_server_probe_report,
)
from scripts.collect_live_concurrency_probe import (  # noqa: E402
    build_live_concurrency_probe_report,
)
from scripts.collect_live_chat_probe import (  # noqa: E402
    DEFAULT_ACCESS_TOKEN_ENV as LIVE_CHAT_DEFAULT_ACCESS_TOKEN_ENV,
    DEFAULT_EMAIL_ENV as LIVE_CHAT_DEFAULT_EMAIL_ENV,
    DEFAULT_PASSWORD_ENV as LIVE_CHAT_DEFAULT_PASSWORD_ENV,
    DEFAULT_USERNAME_ENV as LIVE_CHAT_DEFAULT_USERNAME_ENV,
    LIVE_CHAT_PROBE_VERSION,
    build_live_chat_probe_report,
)
from scripts.collect_live_chat_concurrency_probe import (  # noqa: E402
    LIVE_CHAT_CONCURRENCY_PROBE_VERSION,
)
from scripts.collect_m1_smoke_evidence import (  # noqa: E402
    PUBLIC_URL_PLACEHOLDER,
    build_m1_smoke_evidence_report,
)
from scripts.collect_monitoring_alerting_evidence import (  # noqa: E402
    build_monitoring_alerting_evidence_report,
)
from scripts.collect_postgres_redis_live_probe import (  # noqa: E402
    build_postgres_redis_live_probe_report,
)
from scripts.collect_postgres_restore_drill_live_probe import (  # noqa: E402
    POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION,
)
from scripts.render_postgres_redis_ops_summary import (  # noqa: E402
    POSTGRES_REDIS_OPS_SUMMARY_VERSION,
)
from scripts.collect_rate_limit_live_probe import (  # noqa: E402
    build_rate_limit_live_probe_report,
)
from scripts.collect_server_capacity_snapshot import (  # noqa: E402
    build_server_capacity_snapshot_report,
)
from scripts.check_restore_drill_feasibility import (  # noqa: E402
    RESTORE_DRILL_FEASIBILITY_VERSION,
)
from scripts.check_disk_remediation_approval import (  # noqa: E402
    DISK_REMEDIATION_APPROVAL_VERSION,
)
from scripts.check_docker_build_cache_cleanup_approval import (  # noqa: E402
    DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_VERSION,
)
from scripts.check_docker_build_cache_post_cleanup import (  # noqa: E402
    DOCKER_BUILD_CACHE_POST_CLEANUP_VERSION,
)
from scripts.collect_storage_expansion_readiness import (  # noqa: E402
    STORAGE_EXPANSION_READINESS_VERSION,
)
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


M1_GO_NO_GO_EVIDENCE_VERSION = "m1_go_no_go_evidence.v1"
BAD_STATUSES = {"blocked", "failed", "unknown", "skipped", "not_checked"}
DEGRADED_STATUSES = {"degraded", "warning"}

ENV_LABELS = {
    "ZHIXING_PUBLIC_BASE_URL": "公网访问地址和 TLS",
    "ZHIXING_BACKUP_DIR": "备份目录",
    "ZHIXING_POSTGRES_BACKUP_STATUS": "PostgreSQL 备份状态",
    "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS": "PostgreSQL 恢复演练状态",
    "ZHIXING_RAG_RESTORE_DRILL_STATUS": "RAG 恢复演练状态",
    "ZHIXING_RESTORE_DRILL_OWNER": "恢复演练负责人",
    "ZHIXING_ACCEPTABLE_DATA_LOSS": "可接受数据丢失窗口",
    "ZHIXING_HEALTH_ALERT_DELIVERY_STATUS": "健康检查告警送达状态",
    "ZHIXING_READINESS_ALERT_DELIVERY_STATUS": "就绪检查告警送达状态",
    "ZHIXING_ALERT_DRILL_OWNER": "告警演练负责人",
    "ZHIXING_ALERT_DRILL_WINDOW": "告警演练窗口",
    "ZHIXING_ERROR_RATE_MONITOR_STATUS": "错误率监控状态",
    "ZHIXING_P95_LATENCY_MONITOR_STATUS": "P95 延迟监控状态",
    "ZHIXING_TOOL_FAILURE_MONITOR_STATUS": "工具失败率监控状态",
    "ZHIXING_COST_ALERT_STATUS": "成本告警状态",
    "ZHIXING_BACKUP_ALERT_STATUS": "备份告警状态",
    "ZHIXING_LOG_REDACTION_SAMPLE_STATUS": "日志脱敏抽样状态",
    "ZHIXING_ROLLBACK_OWNER": "回滚负责人",
    "ZHIXING_INCIDENT_OWNER": "事故响应负责人",
    "ZHIXING_ROLLBACK_DRILL_STATUS": "回滚演练状态",
    "ZHIXING_ROLLBACK_TARGET_STATUS": "回滚目标状态",
    "ZHIXING_POST_ROLLBACK_HEALTH_STATUS": "回滚后健康检查状态",
    "ZHIXING_POST_ROLLBACK_SMOKE_STATUS": "回滚后冒烟状态",
    "ZHIXING_ROLLBACK_DATA_SAFETY_STATUS": "回滚数据安全状态",
    "ZHIXING_INCIDENT_RESPONSE_STATUS": "事故响应状态",
    "ZHIXING_INCIDENT_REVIEW_STATUS": "事故复盘状态",
    "ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS": "事故分级策略状态",
    "ZHIXING_INCIDENT_COMMUNICATION_STATUS": "事故沟通状态",
}


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _resolved_public_url(
    *,
    environ: Mapping[str, str],
    base_url: str | None,
) -> tuple[str, str]:
    if base_url and base_url.strip():
        return base_url.strip(), "argument"
    env_value = _value(environ, "ZHIXING_PUBLIC_BASE_URL")
    if env_value:
        return env_value, "environment"
    return "", "missing"


def _safe_payload(value: Any, *, public_url: str = "") -> Any:
    def sanitize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): sanitize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        if isinstance(item, tuple):
            return [sanitize(child) for child in item]
        if isinstance(item, str):
            text = item
            if public_url:
                text = text.replace(public_url, PUBLIC_URL_PLACEHOLDER)
            return redact_text(text)
        return item

    return redact_data(sanitize(value))


def _status_from_section(section: Mapping[str, Any]) -> str:
    return str(section.get("status") or "unknown")


def _decision_from_statuses(statuses: Iterable[str], *, any_requested: bool) -> tuple[str, str]:
    status_list = [str(status or "unknown") for status in statuses]
    if not any_requested:
        return "not_checked", "not_checked"
    if any(status in BAD_STATUSES for status in status_list):
        return "blocked", "no_go"
    if any(status in DEGRADED_STATUSES for status in status_list):
        return "degraded", "conditional_go"
    return "passed", "go_for_m1_controlled_trial"


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list | tuple):
        for child in value:
            yield from _walk_mappings(child)


def _collect_reason_items(
    *,
    section_name: str,
    section: Mapping[str, Any],
    key_name: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mapping in _walk_mappings(section):
        raw_items = mapping.get(key_name)
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            item = {str(key): value for key, value in raw_item.items()}
            item.setdefault("section", section_name)
            item.setdefault("target", section_name)
            signature = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if signature in seen:
                continue
            seen.add(signature)
            items.append(item)
    return items


def _collect_blockers(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for section_name, section in sections.items():
        blockers.extend(
            _collect_reason_items(
                section_name=section_name,
                section=section,
                key_name="blocked_reasons",
            )
        )
        status = _status_from_section(section)
        if status in BAD_STATUSES and not any(
            item.get("section") == section_name for item in blockers
        ):
            blockers.append(
                {
                    "section": section_name,
                    "target": section_name,
                    "key": section_name,
                    "reason": f"Section status is {status}.",
                }
            )
    return blockers


def _collect_degraded_reasons(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    degraded: list[dict[str, Any]] = []
    for section_name, section in sections.items():
        degraded.extend(
            _collect_reason_items(
                section_name=section_name,
                section=section,
                key_name="degraded_reasons",
            )
        )
        degraded.extend(
            _collect_reason_items(
                section_name=section_name,
                section=section,
                key_name="warnings",
            )
        )
        if _status_from_section(section) in DEGRADED_STATUSES and not any(
            item.get("section") == section_name for item in degraded
        ):
            degraded.append(
                {
                    "section": section_name,
                    "target": section_name,
                    "key": section_name,
                    "reason": "Section status is degraded.",
                }
            )
    return degraded


def _missing_inputs_from_blockers(blockers: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        env_var = str(blocker.get("env_var") or "").strip()
        if env_var and env_var not in seen:
            seen.add(env_var)
            missing.append(
                {
                    "env_var": env_var,
                    "label": ENV_LABELS.get(env_var, env_var),
                    "value_echoed": False,
                    "source_section": blocker.get("section"),
                }
            )
    return missing


def _required_resource_groups() -> list[dict[str, str]]:
    return [
        {
            "key": "server_domain_tls",
            "label": "服务器、公网域名和 TLS",
            "detail": "需要可访问的目标服务器、反向代理、HTTPS 证书和公开健康检查地址。",
        },
        {
            "key": "runtime_secrets",
            "label": "生产环境变量和密钥",
            "detail": "真实值必须留在部署环境或密钥管理系统，不进入 Git，也不由本脚本读取。",
        },
        {
            "key": "database_redis",
            "label": "PostgreSQL、Redis 和持久化卷",
            "detail": "需要完成模式、密钥状态、RPO/RTO、迁移策略、慢查询策略、Redis 锁边界、备份目录和恢复演练声明。",
        },
        {
            "key": "provider_keys_quota",
            "label": "LLM 与外部服务额度",
            "detail": "需要确认大模型、地图、航班、酒店等服务密钥、额度、降级策略和支持渠道。",
        },
        {
            "key": "monitoring_alerting",
            "label": "监控告警",
            "detail": "需要健康/就绪告警、错误率、延迟、工具失败、成本、备份和脱敏抽样证据。",
        },
        {
            "key": "rollback_incident",
            "label": "回滚和事故响应",
            "detail": "需要负责人、回滚演练、回滚后冒烟、数据安全和事故复盘声明。",
        },
    ]


def _command_plan() -> list[dict[str, Any]]:
    return [
        {
            "key": "plan_only",
            "command": "python scripts/collect_m1_go_no_go_evidence.py --json",
            "runs_when": "local planning; no live checks",
        },
        {
            "key": "declared_evidence",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence "
                "--include-server-preflight-evidence --check-server-disk --json"
            ),
            "runs_when": "after target env declarations are present",
        },
        {
            "key": "server_preflight_disk",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-server-preflight-evidence "
                "--check-server-disk --json"
            ),
            "runs_when": "on the target server before runtime image refresh; checks disk without writing files",
        },
        {
            "key": "postgres_redis_ops",
            "command": "python scripts/check_postgres_redis_ops_status.py --check-compose --json --output <private-workdir>/postgres-redis-ops-status.json",
            "runs_when": "before M1 go/no-go and after stateful service declarations are present",
        },
        {
            "key": "postgres_redis_ops_summary",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py "
                "--include-postgres-redis-ops-summary "
                "--postgres-redis-ops-summary-json <private-workdir>/postgres-redis-ops-summary.json "
                "--json"
            ),
            "runs_when": "after PostgreSQL/Redis declarations, live probe and recovery record are summarized",
        },
        {
            "key": "external_dependency_resilience",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py "
                "--include-external-dependency-resilience-record "
                "--external-dependency-record-json <private-workdir>/external-dependency-resilience-record.local.json "
                "--json"
            ),
            "runs_when": (
                "after external API readiness, cost guard, tool failure monitor "
                "and degradation drill evidence are filled in a private record"
            ),
        },
        {
            "key": "m1_rollout_execution_record",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py "
                "--include-m1-rollout-execution-record "
                "--m1-rollout-record-json <private-workdir>/m1-rollout-execution-record.local.json "
                "--json"
            ),
            "runs_when": "after release artifact, deployment steps, health checks and rollback readiness are recorded",
        },
        {
            "key": "m1_operations_review_record",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py "
                "--include-m1-operations-review-record "
                "--m1-operations-review-json <private-workdir>/m1-operations-review-record.local.json "
                "--json"
            ),
            "runs_when": "after rollout evidence and post-rollout operations issues/follow-ups are reviewed",
        },
        {
            "key": "health_and_gate",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence "
                "--include-server-preflight-evidence --check-server-disk --check-health-url --run-gate --json"
            ),
            "runs_when": "after public HTTPS target is deployed",
        },
        {
            "key": "live_server_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-live-server-probe "
                "--live-server-ssh-target <server-target> --live-server-deploy-dir <deploy-dir> "
                "--base-url <public-url> --json"
            ),
            "runs_when": "after SSH read-only access is available",
        },
        {
            "key": "postgres_redis_live_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-postgres-redis-live-probe "
                "--live-server-ssh-target <server-target> --live-server-deploy-dir <deploy-dir> "
                "--timeout-seconds 90 --json"
            ),
            "runs_when": "after SSH read-only access is available and stateful services are running",
        },
        {
            "key": "backup_schedule_live_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-backup-schedule-live-probe "
                "--live-server-ssh-target <server-target> --live-server-deploy-dir <deploy-dir> "
                "--live-backup-dir <backup-dir> --timeout-seconds 90 --json"
            ),
            "runs_when": "after the server backup directory and read-only SSH access are available",
        },
        {
            "key": "docker_disk_cleanup_plan",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-docker-disk-cleanup-plan "
                "--live-server-ssh-target <server-target> --live-server-deploy-dir <deploy-dir> "
                "--docker-disk-cleanup-max-candidates 20 --json"
            ),
            "runs_when": "when live server disk is degraded; read-only plan, no deletion",
        },
        {
            "key": "docker_build_cache_cleanup_plan",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-docker-build-cache-cleanup-plan "
                "--live-server-ssh-target <server-target> --live-server-deploy-dir <deploy-dir> --json"
            ),
            "runs_when": "after image cleanup is insufficient and build cache has reclaimable space; read-only plan, no deletion",
        },
        {
            "key": "docker_build_cache_cleanup_approval_gate",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-docker-build-cache-cleanup-approval "
                "--docker-build-cache-cleanup-approval-json <private-workdir>/docker-build-cache-cleanup-approval-gate.json --json"
            ),
            "runs_when": "before any approved Docker build-cache cleanup execution",
        },
        {
            "key": "docker_build_cache_post_cleanup",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-docker-build-cache-post-cleanup "
                "--docker-build-cache-post-cleanup-json <private-workdir>/docker-build-cache-post-cleanup.json --json"
            ),
            "runs_when": "after approved Docker build-cache cleanup and capacity / restore-feasibility reruns",
        },
        {
            "key": "live_concurrency_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-live-concurrency-probe "
                "--base-url <public-url> --concurrency-requests-per-endpoint 20 "
                "--concurrency-workers 10 --json"
            ),
            "runs_when": "after public HTTPS target is deployed; safe GET-only probe",
        },
        {
            "key": "probe_auth_readiness",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-probe-auth-readiness "
                "--execute-probe-auth-login --base-url <public-url> "
                "--probe-auth-username-env ZHIXING_PROBE_USERNAME "
                "--probe-auth-password-env ZHIXING_PROBE_PASSWORD --json"
            ),
            "alternative_command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-probe-auth-readiness "
                "--execute-probe-auth-login --base-url <public-url> "
                "--probe-auth-access-token-env ZHIXING_PROBE_ACCESS_TOKEN --json"
            ),
            "runs_when": "before live chat probe; verifies probe auth without creating conversations or calling LLMs",
        },
        {
            "key": "live_chat_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-live-chat-probe "
                "--execute-live-chat-probe --live-chat-probe-approval-json <private-approval-report-json> "
                "--base-url <public-url> "
                "--live-chat-access-token-env ZHIXING_PROBE_ACCESS_TOKEN --json"
            ),
            "alternative_command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-live-chat-probe "
                "--execute-live-chat-probe --live-chat-probe-approval-json <private-approval-report-json> "
                "--base-url <public-url> "
                "--live-chat-username-env ZHIXING_PROBE_USERNAME "
                "--live-chat-password-env ZHIXING_PROBE_PASSWORD --json"
            ),
            "registration_command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-live-chat-probe "
                "--execute-live-chat-probe --register-live-chat-probe-user "
                "--live-chat-probe-approval-json <private-approval-report-json> "
                "--base-url <public-url> --live-chat-username-env ZHIXING_PROBE_USERNAME "
                "--live-chat-password-env ZHIXING_PROBE_PASSWORD "
                "--live-chat-email-env ZHIXING_PROBE_EMAIL --json"
            ),
            "runs_when": (
                "after public HTTPS target, private probe auth and explicit approval "
                "for one live chat turn are available"
            ),
            "may_call_external_apis": True,
            "may_write_runtime_artifacts": True,
            "may_write_runtime_user_record_when_registration_enabled": True,
        },
        {
            "key": "live_chat_concurrency_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py "
                "--include-live-chat-concurrency-probe "
                "--live-chat-concurrency-probe-json "
                "<private-workdir>/live-chat-concurrency-probe.json --json"
            ),
            "runs_when": (
                "after a separately approved tiny live chat concurrency probe has "
                "already produced a redacted private report"
            ),
        },
        {
            "key": "server_capacity_snapshot",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-server-capacity-snapshot "
                "--live-server-ssh-target <server-target> --live-server-deploy-dir <deploy-dir> --json"
            ),
            "runs_when": "after SSH read-only access is available; point-in-time host/container capacity snapshot",
        },
        {
            "key": "restore_drill_feasibility",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-restore-drill-feasibility "
                "--restore-drill-feasibility-json <private-workdir>/restore-drill-feasibility.json --json"
            ),
            "runs_when": "after backup schedule probe and server capacity snapshot are available",
        },
        {
            "key": "postgres_restore_drill_live_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-postgres-restore-drill-live-probe "
                "--postgres-restore-drill-live-probe-json <private-workdir>/postgres-restore-drill-live-probe.json --json"
            ),
            "runs_when": "after the PostgreSQL non-production restore drill probe has produced redacted JSON evidence",
        },
        {
            "key": "disk_remediation_approval_gate",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-disk-remediation-approval "
                "--disk-remediation-approval-json <private-workdir>/disk-remediation-approval-gate.json --json"
            ),
            "runs_when": "before any approved Docker image cleanup execution",
        },
        {
            "key": "storage_expansion_readiness",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-storage-expansion-readiness "
                "--storage-expansion-readiness-json <private-workdir>/storage-expansion-readiness.json --json"
            ),
            "runs_when": "after cleanup is insufficient or before requesting disk expansion / new mount",
        },
        {
            "key": "rate_limit_live_probe",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-rate-limit-live-probe "
                "--base-url <public-url> --rate-limit-request-count 130 --rate-limit-concurrency 16 --json"
            ),
            "runs_when": "after API rate limiting is deployed; safe GET-only probe against mock checkout status",
        },
        {
            "key": "final_live_smoke",
            "command": (
                "python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence "
                "--include-server-preflight-evidence --check-server-docker --check-server-deploy-dir "
                "--check-server-disk --check-health-url --run-gate --run-acceptance-smoke --json"
            ),
            "runs_when": "final M1 go/no-go; may call LLM/external APIs",
            "may_call_external_apis": True,
        },
    ]


def _load_existing_evidence_section(
    *,
    path: Path | None,
    version: str,
    key: str,
    missing_finding: str,
) -> dict[str, Any]:
    if path is None:
        return {
            "version": version,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "connects_ssh": False,
                "deletes_images": False,
                "path_echoed": False,
            },
            "blocked_reasons": [
                {
                    "key": key,
                    "finding": missing_finding,
                    "value_echoed": False,
                }
            ],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "version": version,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "connects_ssh": False,
                "deletes_images": False,
                "path_echoed": False,
            },
            "blocked_reasons": [
                {
                    "key": key,
                    "finding": "Evidence JSON could not be read or parsed.",
                    "value_echoed": False,
                }
            ],
        }
    if not isinstance(payload, Mapping):
        return {
            "version": version,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "connects_ssh": False,
                "deletes_images": False,
                "path_echoed": False,
            },
            "blocked_reasons": [
                {
                    "key": key,
                    "finding": "Evidence JSON must be an object.",
                    "value_echoed": False,
                }
            ],
        }
    return _safe_payload(payload)


def build_m1_go_no_go_report(
    *,
    environ: Mapping[str, str] | None = None,
    base_url: str | None = None,
    include_all_declared_evidence: bool = False,
    include_m1_gate: bool = False,
    include_smoke_evidence: bool = False,
    include_backup_restore_evidence: bool = False,
    include_postgres_redis_ops_evidence: bool = False,
    include_postgres_redis_ops_summary: bool = False,
    include_external_dependency_resilience_record: bool = False,
    include_m1_rollout_execution_record: bool = False,
    include_m1_operations_review_record: bool = False,
    include_monitoring_evidence: bool = False,
    include_incident_rollback_evidence: bool = False,
    include_post_rollback_smoke_evidence: bool = False,
    include_server_preflight_evidence: bool = False,
    include_live_server_probe: bool = False,
    include_postgres_redis_live_probe: bool = False,
    include_backup_schedule_live_probe: bool = False,
    include_docker_disk_cleanup_plan: bool = False,
    include_docker_build_cache_cleanup_plan: bool = False,
    include_docker_build_cache_cleanup_approval: bool = False,
    include_docker_build_cache_post_cleanup: bool = False,
    include_live_concurrency_probe: bool = False,
    include_probe_auth_readiness: bool = False,
    include_live_chat_probe: bool = False,
    include_live_chat_concurrency_probe: bool = False,
    include_server_capacity_snapshot: bool = False,
    include_rate_limit_live_probe: bool = False,
    include_restore_drill_feasibility: bool = False,
    include_postgres_restore_drill_live_probe: bool = False,
    include_disk_remediation_approval: bool = False,
    include_storage_expansion_readiness: bool = False,
    live_server_ssh_target: str | None = None,
    live_server_deploy_dir: str | None = None,
    live_backup_dir: str | None = None,
    probe_auth_access_token: str | None = None,
    probe_auth_access_token_env: str = PROBE_AUTH_DEFAULT_ACCESS_TOKEN_ENV,
    probe_auth_username: str | None = None,
    probe_auth_username_env: str = PROBE_AUTH_DEFAULT_USERNAME_ENV,
    probe_auth_password: str | None = None,
    probe_auth_password_env: str = PROBE_AUTH_DEFAULT_PASSWORD_ENV,
    execute_probe_auth_login: bool = False,
    live_chat_access_token: str | None = None,
    live_chat_access_token_env: str = LIVE_CHAT_DEFAULT_ACCESS_TOKEN_ENV,
    live_chat_username: str | None = None,
    live_chat_username_env: str = LIVE_CHAT_DEFAULT_USERNAME_ENV,
    live_chat_password: str | None = None,
    live_chat_password_env: str = LIVE_CHAT_DEFAULT_PASSWORD_ENV,
    live_chat_email: str | None = None,
    live_chat_email_env: str = LIVE_CHAT_DEFAULT_EMAIL_ENV,
    register_live_chat_probe_user: bool = False,
    execute_live_chat_probe: bool = False,
    live_chat_probe_approval_json: Path | None = None,
    live_chat_concurrency_probe_json: Path | None = None,
    concurrency_requests_per_endpoint: int = 20,
    concurrency_workers: int = 10,
    concurrency_max_p95_ms: float = 2000,
    rate_limit_request_count: int = 130,
    rate_limit_concurrency: int = 1,
    rate_limit_path: str | None = None,
    external_dependency_record: Mapping[str, Any] | None = None,
    external_dependency_record_json: Path | None = None,
    m1_rollout_record: Mapping[str, Any] | None = None,
    m1_rollout_record_json: Path | None = None,
    m1_operations_review: Mapping[str, Any] | None = None,
    m1_operations_review_json: Path | None = None,
    postgres_redis_ops_summary_json: Path | None = None,
    restore_drill_feasibility_json: Path | None = None,
    postgres_restore_drill_live_probe_json: Path | None = None,
    disk_remediation_approval_json: Path | None = None,
    docker_build_cache_cleanup_approval_json: Path | None = None,
    docker_build_cache_post_cleanup_json: Path | None = None,
    storage_expansion_readiness_json: Path | None = None,
    docker_disk_cleanup_max_candidates: int = 20,
    check_server_docker: bool = False,
    check_server_deploy_dir: bool = False,
    check_server_disk: bool = False,
    check_health_url: bool = False,
    run_gate: bool = False,
    run_acceptance_smoke: bool = False,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Build a redacted final M1 go/no-go report."""

    env = environ if environ is not None else os.environ
    public_url, public_url_source = _resolved_public_url(environ=env, base_url=base_url)
    include_m1_gate = include_m1_gate or include_all_declared_evidence
    include_smoke_evidence = include_smoke_evidence or include_all_declared_evidence
    include_backup_restore_evidence = (
        include_backup_restore_evidence or include_all_declared_evidence
    )
    include_postgres_redis_ops_evidence = (
        include_postgres_redis_ops_evidence or include_all_declared_evidence
    )
    include_monitoring_evidence = include_monitoring_evidence or include_all_declared_evidence
    include_incident_rollback_evidence = (
        include_incident_rollback_evidence or include_all_declared_evidence
    )

    sections: dict[str, dict[str, Any]] = {}
    gate_base_url = public_url or DEFAULT_BASE_URL

    if include_m1_gate:
        sections["m1_deployment_gate"] = _safe_payload(
            build_m1_deployment_gate_report(
                environ=env,
                base_url=gate_base_url,
                check_backend=check_health_url,
                include_acceptance=True,
                check_server_docker=check_server_docker,
                check_server_deploy_dir=check_server_deploy_dir,
                check_server_disk=check_server_disk,
                check_server_health_url=check_health_url,
                check_monitoring_health_url=check_health_url,
            ),
            public_url=public_url,
        )
    if include_server_preflight_evidence:
        sections["server_preflight_evidence"] = _safe_payload(
            build_server_preflight_readiness_report(
                environ=env,
                check_docker=check_server_docker,
                check_deploy_dir=check_server_deploy_dir,
                check_disk=check_server_disk,
                check_health_url=check_health_url,
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_smoke_evidence:
        sections["m1_smoke_evidence"] = _safe_payload(
            build_m1_smoke_evidence_report(
                environ=env,
                base_url=public_url or None,
                check_health_url=check_health_url,
                run_gate=run_gate,
                run_acceptance_smoke=run_acceptance_smoke,
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_backup_restore_evidence:
        sections["backup_restore_drill_evidence"] = build_backup_restore_drill_evidence_report(
            environ=env,
            include_readiness=True,
            require_restore_drill_declaration=True,
            timeout_seconds=timeout_seconds,
        )
    if include_postgres_redis_ops_evidence:
        sections["postgres_redis_ops_evidence"] = build_postgres_redis_ops_status_report(
            environ=env,
            check_compose=True,
        )
    if include_postgres_redis_ops_summary:
        sections["postgres_redis_ops_summary"] = _load_existing_evidence_section(
            path=postgres_redis_ops_summary_json,
            version=POSTGRES_REDIS_OPS_SUMMARY_VERSION,
            key="postgres_redis_ops_summary_json",
            missing_finding="PostgreSQL/Redis operations summary JSON is required when included.",
        )
    if include_external_dependency_resilience_record:
        if external_dependency_record is not None:
            raw_text = json.dumps(external_dependency_record, ensure_ascii=False)
            sections["external_dependency_resilience_record"] = _safe_payload(
                build_external_dependency_resilience_record_report(
                    external_dependency_record,
                    raw_text=raw_text,
                ),
                public_url=public_url,
            )
        elif external_dependency_record_json is not None:
            try:
                raw_text = external_dependency_record_json.read_text(encoding="utf-8-sig")
                payload = json.loads(raw_text)
                if not isinstance(payload, Mapping):
                    raise ValueError("record_json_not_object")
                sections["external_dependency_resilience_record"] = _safe_payload(
                    build_external_dependency_resilience_record_report(
                        payload,
                        raw_text=raw_text,
                    ),
                    public_url=public_url,
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                sections["external_dependency_resilience_record"] = {
                    "version": EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION,
                    "status": "blocked",
                    "policy": {
                        "reads_dotenv": False,
                        "calls_external_providers": False,
                        "connects_network": False,
                        "connects_ssh": False,
                        "record_path_echoed": False,
                    },
                    "blocked_reasons": [
                        {
                            "key": "external_dependency_record_json",
                            "finding": "External dependency resilience record JSON could not be read or parsed.",
                            "value_echoed": False,
                        }
                    ],
                }
        else:
            sections["external_dependency_resilience_record"] = {
                "version": EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION,
                "status": "blocked",
                "policy": {
                    "reads_dotenv": False,
                    "calls_external_providers": False,
                    "connects_network": False,
                    "connects_ssh": False,
                    "record_path_echoed": False,
                },
                "blocked_reasons": [
                    {
                        "key": "external_dependency_record_json",
                        "finding": "--external-dependency-record-json is required when including external dependency resilience evidence.",
                        "value_echoed": False,
                    }
                ],
            }
    if include_m1_rollout_execution_record:
        if m1_rollout_record is not None:
            raw_text = json.dumps(m1_rollout_record, ensure_ascii=False)
            sections["m1_rollout_execution_record"] = _safe_payload(
                build_m1_rollout_execution_record_report(
                    m1_rollout_record,
                    raw_text=raw_text,
                ),
                public_url=public_url,
            )
        elif m1_rollout_record_json is not None:
            try:
                raw_text = m1_rollout_record_json.read_text(encoding="utf-8-sig")
                payload = json.loads(raw_text)
                if not isinstance(payload, Mapping):
                    raise ValueError("record_json_not_object")
                sections["m1_rollout_execution_record"] = _safe_payload(
                    build_m1_rollout_execution_record_report(
                        payload,
                        raw_text=raw_text,
                    ),
                    public_url=public_url,
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                sections["m1_rollout_execution_record"] = {
                    "version": M1_ROLLOUT_EXECUTION_RECORD_VERSION,
                    "status": "blocked",
                    "policy": {
                        "reads_dotenv": False,
                        "deploys_code": False,
                        "connects_ssh": False,
                        "starts_services": False,
                        "record_path_echoed": False,
                    },
                    "blocked_reasons": [
                        {
                            "key": "m1_rollout_record_json",
                            "finding": "M1 rollout execution record JSON could not be read or parsed.",
                            "value_echoed": False,
                        }
                    ],
                }
        else:
            sections["m1_rollout_execution_record"] = {
                "version": M1_ROLLOUT_EXECUTION_RECORD_VERSION,
                "status": "blocked",
                "policy": {
                    "reads_dotenv": False,
                    "deploys_code": False,
                    "connects_ssh": False,
                    "starts_services": False,
                    "record_path_echoed": False,
                },
                "blocked_reasons": [
                    {
                        "key": "m1_rollout_record_json",
                        "finding": "--m1-rollout-record-json is required when including rollout execution evidence.",
                        "value_echoed": False,
                    }
                ],
            }
    if include_m1_operations_review_record:
        if m1_operations_review is not None:
            raw_text = json.dumps(m1_operations_review, ensure_ascii=False)
            sections["m1_operations_review_record"] = _safe_payload(
                build_m1_operations_review_record_report(
                    m1_operations_review,
                    raw_text=raw_text,
                ),
                public_url=public_url,
            )
        elif m1_operations_review_json is not None:
            try:
                raw_text = m1_operations_review_json.read_text(encoding="utf-8-sig")
                payload = json.loads(raw_text)
                if not isinstance(payload, Mapping):
                    raise ValueError("record_json_not_object")
                sections["m1_operations_review_record"] = _safe_payload(
                    build_m1_operations_review_record_report(
                        payload,
                        raw_text=raw_text,
                    ),
                    public_url=public_url,
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                sections["m1_operations_review_record"] = {
                    "version": M1_OPERATIONS_REVIEW_RECORD_VERSION,
                    "status": "blocked",
                    "policy": {
                        "reads_dotenv": False,
                        "connects_ssh": False,
                        "queries_database": False,
                        "reads_raw_logs": False,
                        "record_path_echoed": False,
                    },
                    "blocked_reasons": [
                        {
                            "key": "m1_operations_review_json",
                            "finding": "M1 operations review record JSON could not be read or parsed.",
                            "value_echoed": False,
                        }
                    ],
                }
        else:
            sections["m1_operations_review_record"] = {
                "version": M1_OPERATIONS_REVIEW_RECORD_VERSION,
                "status": "blocked",
                "policy": {
                    "reads_dotenv": False,
                    "connects_ssh": False,
                    "queries_database": False,
                    "reads_raw_logs": False,
                    "record_path_echoed": False,
                },
                "blocked_reasons": [
                    {
                        "key": "m1_operations_review_json",
                        "finding": "--m1-operations-review-json is required when including operations review evidence.",
                        "value_echoed": False,
                    }
                ],
            }
    if include_monitoring_evidence:
        sections["monitoring_alerting_evidence"] = _safe_payload(
            build_monitoring_alerting_evidence_report(
                environ=env,
                include_readiness=True,
                check_health_url=check_health_url,
                require_alert_delivery_declaration=True,
                require_metric_declaration=True,
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_incident_rollback_evidence:
        sections["incident_rollback_evidence"] = _safe_payload(
            build_incident_rollback_evidence_report(
                environ=env,
                require_ownership_declaration=True,
                require_rollback_drill_declaration=True,
                require_incident_review_declaration=True,
                include_post_rollback_smoke_evidence=include_post_rollback_smoke_evidence,
                check_health_url=check_health_url,
                run_gate=run_gate,
                run_acceptance_smoke=run_acceptance_smoke,
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_live_server_probe:
        sections["live_server_probe"] = _safe_payload(
            build_live_server_probe_report(
                ssh_target=str(live_server_ssh_target or ""),
                deploy_dir=str(live_server_deploy_dir or ""),
                public_base_url=public_url,
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_postgres_redis_live_probe:
        sections["postgres_redis_live_probe"] = _safe_payload(
            build_postgres_redis_live_probe_report(
                ssh_target=str(live_server_ssh_target or ""),
                deploy_dir=str(live_server_deploy_dir or ""),
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_backup_schedule_live_probe:
        sections["backup_schedule_live_probe"] = _safe_payload(
            build_backup_schedule_live_probe_report(
                ssh_target=str(live_server_ssh_target or ""),
                deploy_dir=str(live_server_deploy_dir or ""),
                backup_dir=str(live_backup_dir or ""),
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_docker_disk_cleanup_plan:
        sections["docker_disk_cleanup_plan"] = _safe_payload(
            build_docker_disk_cleanup_plan_report(
                ssh_target=str(live_server_ssh_target or ""),
                deploy_dir=str(live_server_deploy_dir or ""),
                max_candidates=docker_disk_cleanup_max_candidates,
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_docker_build_cache_cleanup_plan:
        sections["docker_build_cache_cleanup_plan"] = _safe_payload(
            build_docker_build_cache_cleanup_plan_report(
                ssh_target=str(live_server_ssh_target or ""),
                deploy_dir=str(live_server_deploy_dir or ""),
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_live_concurrency_probe:
        sections["live_concurrency_probe"] = _safe_payload(
            build_live_concurrency_probe_report(
                base_url=public_url or "",
                requests_per_endpoint=concurrency_requests_per_endpoint,
                concurrency=concurrency_workers,
                timeout_seconds=timeout_seconds,
                max_p95_ms=concurrency_max_p95_ms,
            ),
            public_url=public_url,
        )
    if include_probe_auth_readiness:
        sections["probe_auth_readiness"] = _safe_payload(
            build_probe_auth_readiness_report(
                base_url=public_url or "",
                access_token=probe_auth_access_token,
                access_token_env=probe_auth_access_token_env,
                username=probe_auth_username,
                username_env=probe_auth_username_env,
                password=probe_auth_password,
                password_env=probe_auth_password_env,
                execute_login=execute_probe_auth_login,
                timeout_seconds=timeout_seconds,
                environ=env,
            ),
            public_url=public_url,
        )
    if include_live_chat_probe:
        approval_section: Mapping[str, Any] | None = None
        if execute_live_chat_probe or live_chat_probe_approval_json is not None:
            approval_section = _load_existing_evidence_section(
                path=live_chat_probe_approval_json,
                version=LIVE_CHAT_PROBE_EXECUTION_APPROVAL_VERSION,
                key="live_chat_probe_execution_approval_json",
                missing_finding="Live chat probe execution approval JSON is required before executing the live chat probe.",
            )
            sections["live_chat_probe_execution_approval"] = _safe_payload(
                approval_section,
                public_url=public_url,
            )
        approval_status = str((approval_section or {}).get("status") or "")
        if execute_live_chat_probe and approval_status != "passed":
            sections["live_chat_probe"] = {
                "version": LIVE_CHAT_PROBE_VERSION,
                "status": "blocked",
                "policy": {
                    "requires_execute_flag": True,
                    "execute_requested": True,
                    "approval_required": True,
                    "approval_status": approval_status or "missing",
                    "calls_llm": False,
                    "calls_external_provider_apis": False,
                    "creates_probe_conversation": False,
                    "creates_probe_user": False,
                    "writes_runtime_messages": False,
                    "records_credentials": False,
                    "records_prompt": False,
                    "records_assistant_text": False,
                },
                "blocked_reasons": [
                    {
                        "key": "live_chat_probe_approval_not_passed",
                        "finding": "Live chat probe execution approval must pass before executing the probe.",
                    }
                ],
            }
        else:
            sections["live_chat_probe"] = _safe_payload(
                build_live_chat_probe_report(
                    base_url=public_url or "",
                    access_token=live_chat_access_token,
                    access_token_env=live_chat_access_token_env,
                    username=live_chat_username,
                    username_env=live_chat_username_env,
                    password=live_chat_password,
                    password_env=live_chat_password_env,
                    email=live_chat_email,
                    email_env=live_chat_email_env,
                    register_probe_user=register_live_chat_probe_user,
                    execute=execute_live_chat_probe,
                    timeout_seconds=timeout_seconds,
                    max_total_seconds=timeout_seconds,
                    environ=env,
                ),
                public_url=public_url,
            )
    if include_live_chat_concurrency_probe:
        sections["live_chat_concurrency_probe"] = _load_existing_evidence_section(
            path=live_chat_concurrency_probe_json,
            version=LIVE_CHAT_CONCURRENCY_PROBE_VERSION,
            key="live_chat_concurrency_probe_json",
            missing_finding=(
                "--live-chat-concurrency-probe-json is required when including "
                "live chat concurrency evidence."
            ),
        )
    if include_server_capacity_snapshot:
        sections["server_capacity_snapshot"] = _safe_payload(
            build_server_capacity_snapshot_report(
                ssh_target=str(live_server_ssh_target or ""),
                deploy_dir=str(live_server_deploy_dir or ""),
                timeout_seconds=timeout_seconds,
            ),
            public_url=public_url,
        )
    if include_restore_drill_feasibility:
        sections["restore_drill_feasibility"] = _load_existing_evidence_section(
            path=restore_drill_feasibility_json,
            version=RESTORE_DRILL_FEASIBILITY_VERSION,
            key="restore_drill_feasibility_json",
            missing_finding=(
                "--restore-drill-feasibility-json is required when including "
                "restore drill feasibility evidence."
            ),
        )
    if include_postgres_restore_drill_live_probe:
        sections["postgres_restore_drill_live_probe"] = _load_existing_evidence_section(
            path=postgres_restore_drill_live_probe_json,
            version=POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION,
            key="postgres_restore_drill_live_probe_json",
            missing_finding=(
                "--postgres-restore-drill-live-probe-json is required when including "
                "PostgreSQL restore drill live probe evidence."
            ),
        )
    if include_disk_remediation_approval:
        sections["disk_remediation_approval_gate"] = _load_existing_evidence_section(
            path=disk_remediation_approval_json,
            version=DISK_REMEDIATION_APPROVAL_VERSION,
            key="disk_remediation_approval_json",
            missing_finding=(
                "--disk-remediation-approval-json is required when including "
                "disk remediation approval evidence."
            ),
        )
    if include_docker_build_cache_cleanup_approval:
        sections["docker_build_cache_cleanup_approval_gate"] = _load_existing_evidence_section(
            path=docker_build_cache_cleanup_approval_json,
            version=DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_VERSION,
            key="docker_build_cache_cleanup_approval_json",
            missing_finding=(
                "--docker-build-cache-cleanup-approval-json is required when including "
                "Docker build-cache cleanup approval evidence."
            ),
        )
    if include_docker_build_cache_post_cleanup:
        sections["docker_build_cache_post_cleanup"] = _load_existing_evidence_section(
            path=docker_build_cache_post_cleanup_json,
            version=DOCKER_BUILD_CACHE_POST_CLEANUP_VERSION,
            key="docker_build_cache_post_cleanup_json",
            missing_finding=(
                "--docker-build-cache-post-cleanup-json is required when including "
                "Docker build-cache post-cleanup evidence."
            ),
        )
    if include_storage_expansion_readiness:
        sections["storage_expansion_readiness"] = _load_existing_evidence_section(
            path=storage_expansion_readiness_json,
            version=STORAGE_EXPANSION_READINESS_VERSION,
            key="storage_expansion_readiness_json",
            missing_finding=(
                "--storage-expansion-readiness-json is required when including "
                "storage expansion readiness evidence."
            ),
        )
    if include_rate_limit_live_probe:
        sections["rate_limit_live_probe"] = _safe_payload(
            build_rate_limit_live_probe_report(
                base_url=public_url or "",
                path=rate_limit_path or "/api/v1/mock-checkout/ORDER-RATELIMIT01/status",
                request_count=rate_limit_request_count,
                concurrency=rate_limit_concurrency,
                timeout_seconds=timeout_seconds,
                expect_429=True,
            ),
            public_url=public_url,
        )

    section_statuses = {
        name: _status_from_section(section)
        for name, section in sections.items()
    }
    live_chat_probe_execution_approval_passed = (
        section_statuses.get("live_chat_probe_execution_approval") == "passed"
    )
    status, decision = _decision_from_statuses(
        section_statuses.values(),
        any_requested=bool(sections),
    )
    blockers = _collect_blockers(sections)
    degraded_reasons = _collect_degraded_reasons(sections)
    report = {
        "version": M1_GO_NO_GO_EVIDENCE_VERSION,
        "status": status,
        "decision": decision,
        "decision_policy": {
            "passed": "All requested evidence sections passed.",
            "conditional_go": "No blocker exists, but at least one requested evidence section is degraded or warning.",
            "no_go": "Any blocked, failed, unknown, skipped or not_checked requested section blocks M1 release.",
            "not_checked": "No evidence section was requested.",
        },
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "executes_rollback": False,
            "does_not_echo_values": True,
            "network_probe_requested": check_health_url,
            "runs_m1_deployment_gate": include_m1_gate or run_gate,
            "runs_server_preflight_evidence": include_server_preflight_evidence,
            "runs_server_disk_probe": check_server_disk,
            "reads_external_dependency_resilience_record": include_external_dependency_resilience_record,
            "calls_external_providers_for_dependency_record": False,
            "reads_m1_rollout_execution_record": include_m1_rollout_execution_record,
            "deploys_code_for_rollout_record": False,
            "reads_m1_operations_review_record": include_m1_operations_review_record,
            "queries_database_for_operations_review": False,
            "runs_acceptance_smoke": run_acceptance_smoke,
            "runs_live_server_probe": include_live_server_probe,
            "runs_postgres_redis_live_probe": include_postgres_redis_live_probe,
            "reads_postgres_redis_ops_summary_evidence": include_postgres_redis_ops_summary,
            "runs_backup_schedule_live_probe": include_backup_schedule_live_probe,
            "runs_docker_disk_cleanup_plan": include_docker_disk_cleanup_plan,
            "runs_docker_build_cache_cleanup_plan": include_docker_build_cache_cleanup_plan,
            "reads_docker_build_cache_cleanup_approval_evidence": include_docker_build_cache_cleanup_approval,
            "reads_docker_build_cache_post_cleanup_evidence": include_docker_build_cache_post_cleanup,
            "runs_live_concurrency_probe": include_live_concurrency_probe,
            "runs_probe_auth_readiness": include_probe_auth_readiness,
            "executes_probe_auth_login": execute_probe_auth_login,
            "runs_live_chat_probe": include_live_chat_probe,
            "reads_live_chat_concurrency_probe_evidence": include_live_chat_concurrency_probe,
            "executes_live_chat_probe": execute_live_chat_probe,
            "registers_live_chat_probe_user": register_live_chat_probe_user,
            "reads_live_chat_probe_execution_approval": (
                include_live_chat_probe
                and (execute_live_chat_probe or live_chat_probe_approval_json is not None)
            ),
            "requires_live_chat_probe_execution_approval": (
                include_live_chat_probe and execute_live_chat_probe
            ),
            "runs_server_capacity_snapshot": include_server_capacity_snapshot,
            "runs_rate_limit_live_probe": include_rate_limit_live_probe,
            "reads_restore_drill_feasibility_evidence": include_restore_drill_feasibility,
            "reads_postgres_restore_drill_live_probe_evidence": include_postgres_restore_drill_live_probe,
            "reads_disk_remediation_approval_evidence": include_disk_remediation_approval,
            "reads_storage_expansion_readiness_evidence": include_storage_expansion_readiness,
            "may_connect_ssh": (
                include_live_server_probe
                or include_postgres_redis_live_probe
                or include_backup_schedule_live_probe
                or include_docker_disk_cleanup_plan
                or include_docker_build_cache_cleanup_plan
                or include_server_capacity_snapshot
            ),
            "may_call_external_apis": run_acceptance_smoke
            or (
                include_live_chat_probe
                and execute_live_chat_probe
                and live_chat_probe_execution_approval_passed
            ),
            "may_write_runtime_artifacts": run_acceptance_smoke
            or (
                include_live_chat_probe
                and execute_live_chat_probe
                and live_chat_probe_execution_approval_passed
            ),
            "may_call_auth_endpoint": (
                (include_probe_auth_readiness and execute_probe_auth_login)
                or (
                    include_live_chat_probe
                    and execute_live_chat_probe
                    and live_chat_probe_execution_approval_passed
                )
            ),
            "may_write_runtime_user_record": (
                include_live_chat_probe
                and execute_live_chat_probe
                and register_live_chat_probe_user
                and live_chat_probe_execution_approval_passed
            ),
        },
        "target": {
            "public_base_url_present": bool(public_url),
            "public_base_url_source": public_url_source,
            "public_base_url_echoed": False,
        },
        "section_statuses": section_statuses,
        "blockers": blockers,
        "degraded_reasons": degraded_reasons,
        "missing_inputs_for_user": _missing_inputs_from_blockers(blockers),
        "required_resource_groups": _required_resource_groups(),
        "command_plan": _command_plan(),
        "sections": sections,
        "not_proven_by_this_report": [
            "Plan-only mode proves no live deployment result.",
            "This report does not read .env files or prove that the target server has the real secret values.",
            "This report does not deploy services, execute rollback, restore databases, or send alert messages.",
            "Public health checks and acceptance smoke are not proven unless their explicit flags are used against a live HTTPS target.",
            "Live server probe proves only read-only target server state; it does not prove the current local release has been deployed.",
            "Probe auth readiness proves only probe authentication and /users/me when explicitly executed; it does not create chat conversations.",
            "Live chat probe proves only one authenticated SSE turn when explicitly executed; plan-only mode and missing access token prove no live chat result.",
            "Live chat concurrency evidence proves only the separately approved tiny sample represented by its private report; it is not a load test or long-duration soak result.",
            "A go decision is only for M1 controlled trial traffic; it does not permit real payment, booking, price lock, ticketing, or fulfillment.",
            "Raw logs, provider screenshots, backups, .env files, vector stores and customer data must stay outside Git.",
        ],
    }
    return _safe_payload(report, public_url=public_url)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_m1_go_no_go_markdown(report: Mapping[str, Any]) -> str:
    safe_report = redact_data(dict(report))
    if not isinstance(safe_report, Mapping):
        safe_report = {}
    lines = [
        "# M1 Go/No-Go Evidence（上线前总判定证据）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Decision | `{_markdown_cell(safe_report.get('decision'))}` |",
        f"| Reads `.env` | `{_markdown_cell((safe_report.get('policy') or {}).get('reads_dotenv'))}` |",
        f"| Starts services | `{_markdown_cell((safe_report.get('policy') or {}).get('starts_services'))}` |",
        f"| Calls external APIs | `{_markdown_cell((safe_report.get('policy') or {}).get('may_call_external_apis'))}` |",
        f"| Public URL echoed | `{_markdown_cell((safe_report.get('target') or {}).get('public_base_url_echoed'))}` |",
        "",
        "## Section 状态",
        "",
        "| Section | Status |",
        "|---|---|",
    ]
    statuses = safe_report.get("section_statuses") or {}
    if isinstance(statuses, Mapping) and statuses:
        for section, status in sorted(statuses.items()):
            lines.append(f"| {_markdown_cell(section)} | {_markdown_cell(status)} |")
    else:
        lines.append("| - | not_checked |")

    lines.extend(["", "## Blockers", "", "| Section | Key | Reason |", "|---|---|---|"])
    blockers = safe_report.get("blockers") or []
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            key = item.get("env_var") or item.get("key") or item.get("target")
            reason = item.get("reason") or item.get("finding") or item.get("label") or "blocked"
            lines.append(
                "| "
                f"{_markdown_cell(item.get('section'))} | "
                f"{_markdown_cell(key)} | "
                f"{_markdown_cell(reason)} |"
            )
    else:
        lines.append("| - | - | - |")

    lines.extend(["", "## 需要准备的资源", "", "| Key | Label | Detail |", "|---|---|---|"])
    for item in safe_report.get("required_resource_groups") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"{_markdown_cell(item.get('label'))} | "
            f"{_markdown_cell(item.get('detail'))} |"
        )

    missing_inputs = safe_report.get("missing_inputs_for_user") or []
    if missing_inputs:
        lines.extend(["", "## 缺失输入", "", "| Env Var | Label | Section |", "|---|---|---|"])
        for item in missing_inputs:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| "
                f"`{_markdown_cell(item.get('env_var'))}` | "
                f"{_markdown_cell(item.get('label'))} | "
                f"{_markdown_cell(item.get('source_section'))} |"
            )

    lines.extend(["", "## 执行计划", "", "| Key | Command | Runs when |", "|---|---|---|"])
    for item in safe_report.get("command_plan") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"`{_markdown_cell(item.get('command'))}` | "
            f"{_markdown_cell(item.get('runs_when'))} |"
        )

    lines.extend(["", "## 边界", ""])
    for item in safe_report.get("not_proven_by_this_report") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is human Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    parser.add_argument("--base-url", default=None, help="Public deployment base URL. Falls back to ZHIXING_PUBLIC_BASE_URL.")
    parser.add_argument("--include-all-declared-evidence", action="store_true", help="Include all declared M1 evidence sections.")
    parser.add_argument("--include-m1-gate", action="store_true", help="Include the aggregate M1 deployment gate.")
    parser.add_argument("--include-smoke-evidence", action="store_true", help="Include post-deployment smoke evidence.")
    parser.add_argument("--include-backup-restore-evidence", action="store_true", help="Include backup/restore drill evidence.")
    parser.add_argument("--include-postgres-redis-ops-evidence", action="store_true", help="Include PostgreSQL/Redis operations evidence.")
    parser.add_argument("--include-postgres-redis-ops-summary", action="store_true", help="Include private PostgreSQL/Redis operations summary JSON evidence.")
    parser.add_argument("--include-external-dependency-resilience-record", action="store_true", help="Include private external dependency resilience record validation.")
    parser.add_argument("--include-m1-rollout-execution-record", action="store_true", help="Include private M1 rollout execution record validation.")
    parser.add_argument("--include-m1-operations-review-record", action="store_true", help="Include private M1 operations review record validation.")
    parser.add_argument("--include-monitoring-evidence", action="store_true", help="Include monitoring/alerting evidence.")
    parser.add_argument("--include-incident-rollback-evidence", action="store_true", help="Include incident and rollback evidence.")
    parser.add_argument("--include-post-rollback-smoke-evidence", action="store_true", help="Embed post-rollback smoke evidence inside incident/rollback evidence.")
    parser.add_argument("--include-server-preflight-evidence", action="store_true", help="Include target server preflight evidence.")
    parser.add_argument("--include-live-server-probe", action="store_true", help="Include read-only SSH live server probe evidence.")
    parser.add_argument("--include-postgres-redis-live-probe", action="store_true", help="Include read-only SSH PostgreSQL/Redis live probe evidence.")
    parser.add_argument("--include-backup-schedule-live-probe", action="store_true", help="Include read-only SSH backup schedule and freshness probe evidence.")
    parser.add_argument("--include-docker-disk-cleanup-plan", action="store_true", help="Include read-only Docker disk cleanup plan evidence.")
    parser.add_argument("--include-docker-build-cache-cleanup-plan", action="store_true", help="Include read-only Docker build-cache cleanup plan evidence.")
    parser.add_argument("--include-docker-build-cache-cleanup-approval", action="store_true", help="Include private Docker build-cache cleanup approval gate JSON evidence.")
    parser.add_argument("--include-docker-build-cache-post-cleanup", action="store_true", help="Include private Docker build-cache post-cleanup JSON evidence.")
    parser.add_argument("--include-live-concurrency-probe", action="store_true", help="Include safe GET-only live concurrency probe evidence.")
    parser.add_argument("--include-probe-auth-readiness", action="store_true", help="Include probe authentication readiness evidence.")
    parser.add_argument("--include-live-chat-probe", action="store_true", help="Include authenticated live chat SSE probe evidence.")
    parser.add_argument("--include-live-chat-concurrency-probe", action="store_true", help="Include existing tiny live chat concurrency probe JSON evidence.")
    parser.add_argument("--include-server-capacity-snapshot", action="store_true", help="Include read-only SSH server capacity snapshot evidence.")
    parser.add_argument("--include-rate-limit-live-probe", action="store_true", help="Include safe GET-only API rate-limit live probe evidence.")
    parser.add_argument("--include-restore-drill-feasibility", action="store_true", help="Include private restore drill feasibility JSON evidence.")
    parser.add_argument("--include-postgres-restore-drill-live-probe", action="store_true", help="Include private PostgreSQL restore drill live probe JSON evidence.")
    parser.add_argument("--include-disk-remediation-approval", action="store_true", help="Include private disk remediation approval gate JSON evidence.")
    parser.add_argument("--include-storage-expansion-readiness", action="store_true", help="Include private storage expansion readiness JSON evidence.")
    parser.add_argument("--live-server-ssh-target", default=None, help="SSH target for live server probe. Redacted from output.")
    parser.add_argument("--live-server-deploy-dir", default=None, help="Deploy directory for live server probe. Redacted from output.")
    parser.add_argument("--live-backup-dir", default=None, help="Remote backup directory for live backup probe. Redacted from output.")
    parser.add_argument("--probe-auth-access-token", default=None, help="Bearer token for probe auth readiness. Redacted from output; prefer --probe-auth-access-token-env.")
    parser.add_argument("--probe-auth-access-token-env", default=PROBE_AUTH_DEFAULT_ACCESS_TOKEN_ENV, help="Environment variable containing the probe bearer token.")
    parser.add_argument("--probe-auth-username", default=None, help="Probe username for auth readiness. Redacted from output; prefer --probe-auth-username-env.")
    parser.add_argument("--probe-auth-username-env", default=PROBE_AUTH_DEFAULT_USERNAME_ENV, help="Environment variable containing the probe username.")
    parser.add_argument("--probe-auth-password", default=None, help="Probe password for auth readiness. Redacted from output; prefer --probe-auth-password-env.")
    parser.add_argument("--probe-auth-password-env", default=PROBE_AUTH_DEFAULT_PASSWORD_ENV, help="Environment variable containing the probe password.")
    parser.add_argument("--execute-probe-auth-login", action="store_true", help="Actually verify probe auth and /api/v1/users/me without chat.")
    parser.add_argument("--live-chat-access-token", default=None, help="Bearer token for live chat probe. Redacted from output; prefer --live-chat-access-token-env.")
    parser.add_argument("--live-chat-access-token-env", default=LIVE_CHAT_DEFAULT_ACCESS_TOKEN_ENV, help="Environment variable containing the live chat bearer token.")
    parser.add_argument("--live-chat-username", default=None, help="Probe username for live chat login. Redacted from output; prefer --live-chat-username-env.")
    parser.add_argument("--live-chat-username-env", default=LIVE_CHAT_DEFAULT_USERNAME_ENV, help="Environment variable containing the live chat probe username.")
    parser.add_argument("--live-chat-password", default=None, help="Probe password for live chat login. Redacted from output; prefer --live-chat-password-env.")
    parser.add_argument("--live-chat-password-env", default=LIVE_CHAT_DEFAULT_PASSWORD_ENV, help="Environment variable containing the live chat probe password.")
    parser.add_argument("--live-chat-email", default=None, help="Probe email for optional live chat registration. Redacted from output; prefer --live-chat-email-env.")
    parser.add_argument("--live-chat-email-env", default=LIVE_CHAT_DEFAULT_EMAIL_ENV, help="Environment variable containing the live chat probe email.")
    parser.add_argument("--register-live-chat-probe-user", action="store_true", help="Register the live chat probe user before chat when needed. Writes a runtime test user record.")
    parser.add_argument("--live-chat-probe-approval-json", type=_path_arg, default=None, help="Private approval report JSON required before executing live chat probe. Path is not echoed.")
    parser.add_argument("--live-chat-concurrency-probe-json", type=_path_arg, default=None, help="Private live chat concurrency probe JSON report. Path is not echoed.")
    parser.add_argument("--execute-live-chat-probe", action="store_true", help="Actually run one authenticated live chat SSE turn; may call LLM/external APIs.")
    parser.add_argument("--concurrency-requests-per-endpoint", type=int, default=20, help="Request count per endpoint for live concurrency probe.")
    parser.add_argument("--concurrency-workers", type=int, default=10, help="Worker count for live concurrency probe.")
    parser.add_argument("--concurrency-max-p95-ms", type=float, default=2000, help="P95 latency threshold for live concurrency probe.")
    parser.add_argument("--rate-limit-request-count", type=int, default=130, help="Request count for live rate-limit probe.")
    parser.add_argument("--rate-limit-concurrency", type=int, default=1, help="Concurrent workers for live rate-limit burst probe.")
    parser.add_argument("--rate-limit-path", default=None, help="Relative API path for live rate-limit probe. Redacted from output.")
    parser.add_argument("--external-dependency-record-json", type=_path_arg, default=None, help="Private external dependency resilience JSON record. Path is not echoed.")
    parser.add_argument("--m1-rollout-record-json", type=_path_arg, default=None, help="Private M1 rollout execution JSON record. Path is not echoed.")
    parser.add_argument("--m1-operations-review-json", type=_path_arg, default=None, help="Private M1 operations review JSON record. Path is not echoed.")
    parser.add_argument("--postgres-redis-ops-summary-json", type=_path_arg, default=None, help="Private PostgreSQL/Redis operations summary JSON report. Path is not echoed.")
    parser.add_argument("--restore-drill-feasibility-json", type=_path_arg, default=None, help="Private restore drill feasibility JSON report. Path is not echoed.")
    parser.add_argument("--postgres-restore-drill-live-probe-json", type=_path_arg, default=None, help="Private PostgreSQL restore drill live probe JSON report. Path is not echoed.")
    parser.add_argument("--disk-remediation-approval-json", type=_path_arg, default=None, help="Private disk remediation approval gate JSON report. Path is not echoed.")
    parser.add_argument("--docker-build-cache-cleanup-approval-json", type=_path_arg, default=None, help="Private Docker build-cache cleanup approval gate JSON report. Path is not echoed.")
    parser.add_argument("--docker-build-cache-post-cleanup-json", type=_path_arg, default=None, help="Private Docker build-cache post-cleanup JSON report. Path is not echoed.")
    parser.add_argument("--storage-expansion-readiness-json", type=_path_arg, default=None, help="Private storage expansion readiness JSON report. Path is not echoed.")
    parser.add_argument("--docker-disk-cleanup-max-candidates", type=int, default=20, help="Maximum Docker image cleanup candidates to include in the read-only plan.")
    parser.add_argument("--check-server-docker", action="store_true", help="Check docker and docker compose inside server preflight evidence.")
    parser.add_argument("--check-server-deploy-dir", action="store_true", help="Check ZHIXING_DEPLOY_DIR exists inside server preflight evidence.")
    parser.add_argument("--check-server-disk", action="store_true", help="Check deployment disk capacity inside server preflight evidence.")
    parser.add_argument("--check-health-url", action="store_true", help="Probe public health endpoints in sections that support live probes.")
    parser.add_argument("--run-gate", action="store_true", help="Run the M1 deployment gate inside smoke sections.")
    parser.add_argument("--run-acceptance-smoke", action="store_true", help="Run live acceptance smoke. This may call LLM/external APIs.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout for optional probes.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_go_no_go_report(
        base_url=args.base_url,
        include_all_declared_evidence=args.include_all_declared_evidence,
        include_m1_gate=args.include_m1_gate,
        include_smoke_evidence=args.include_smoke_evidence,
        include_backup_restore_evidence=args.include_backup_restore_evidence,
        include_postgres_redis_ops_evidence=args.include_postgres_redis_ops_evidence,
        include_postgres_redis_ops_summary=args.include_postgres_redis_ops_summary,
        include_external_dependency_resilience_record=args.include_external_dependency_resilience_record,
        include_m1_rollout_execution_record=args.include_m1_rollout_execution_record,
        include_m1_operations_review_record=args.include_m1_operations_review_record,
        include_monitoring_evidence=args.include_monitoring_evidence,
        include_incident_rollback_evidence=args.include_incident_rollback_evidence,
        include_post_rollback_smoke_evidence=args.include_post_rollback_smoke_evidence,
        include_server_preflight_evidence=args.include_server_preflight_evidence,
        include_live_server_probe=args.include_live_server_probe,
        include_postgres_redis_live_probe=args.include_postgres_redis_live_probe,
        include_backup_schedule_live_probe=args.include_backup_schedule_live_probe,
        include_docker_disk_cleanup_plan=args.include_docker_disk_cleanup_plan,
        include_docker_build_cache_cleanup_plan=args.include_docker_build_cache_cleanup_plan,
        include_docker_build_cache_cleanup_approval=args.include_docker_build_cache_cleanup_approval,
        include_docker_build_cache_post_cleanup=args.include_docker_build_cache_post_cleanup,
        include_live_concurrency_probe=args.include_live_concurrency_probe,
        include_probe_auth_readiness=args.include_probe_auth_readiness,
        include_live_chat_probe=args.include_live_chat_probe,
        include_live_chat_concurrency_probe=args.include_live_chat_concurrency_probe,
        include_server_capacity_snapshot=args.include_server_capacity_snapshot,
        include_rate_limit_live_probe=args.include_rate_limit_live_probe,
        include_restore_drill_feasibility=args.include_restore_drill_feasibility,
        include_postgres_restore_drill_live_probe=args.include_postgres_restore_drill_live_probe,
        include_disk_remediation_approval=args.include_disk_remediation_approval,
        include_storage_expansion_readiness=args.include_storage_expansion_readiness,
        live_server_ssh_target=args.live_server_ssh_target,
        live_server_deploy_dir=args.live_server_deploy_dir,
        live_backup_dir=args.live_backup_dir,
        probe_auth_access_token=args.probe_auth_access_token,
        probe_auth_access_token_env=args.probe_auth_access_token_env,
        probe_auth_username=args.probe_auth_username,
        probe_auth_username_env=args.probe_auth_username_env,
        probe_auth_password=args.probe_auth_password,
        probe_auth_password_env=args.probe_auth_password_env,
        execute_probe_auth_login=args.execute_probe_auth_login,
        live_chat_access_token=args.live_chat_access_token,
        live_chat_access_token_env=args.live_chat_access_token_env,
        live_chat_username=args.live_chat_username,
        live_chat_username_env=args.live_chat_username_env,
        live_chat_password=args.live_chat_password,
        live_chat_password_env=args.live_chat_password_env,
        live_chat_email=args.live_chat_email,
        live_chat_email_env=args.live_chat_email_env,
        register_live_chat_probe_user=args.register_live_chat_probe_user,
        live_chat_probe_approval_json=args.live_chat_probe_approval_json,
        live_chat_concurrency_probe_json=args.live_chat_concurrency_probe_json,
        execute_live_chat_probe=args.execute_live_chat_probe,
        concurrency_requests_per_endpoint=args.concurrency_requests_per_endpoint,
        concurrency_workers=args.concurrency_workers,
        concurrency_max_p95_ms=args.concurrency_max_p95_ms,
        rate_limit_request_count=args.rate_limit_request_count,
        rate_limit_concurrency=args.rate_limit_concurrency,
        rate_limit_path=args.rate_limit_path,
        external_dependency_record_json=args.external_dependency_record_json,
        m1_rollout_record_json=args.m1_rollout_record_json,
        m1_operations_review_json=args.m1_operations_review_json,
        postgres_redis_ops_summary_json=args.postgres_redis_ops_summary_json,
        restore_drill_feasibility_json=args.restore_drill_feasibility_json,
        postgres_restore_drill_live_probe_json=args.postgres_restore_drill_live_probe_json,
        disk_remediation_approval_json=args.disk_remediation_approval_json,
        docker_build_cache_cleanup_approval_json=args.docker_build_cache_cleanup_approval_json,
        docker_build_cache_post_cleanup_json=args.docker_build_cache_post_cleanup_json,
        storage_expansion_readiness_json=args.storage_expansion_readiness_json,
        docker_disk_cleanup_max_candidates=args.docker_disk_cleanup_max_candidates,
        check_server_docker=args.check_server_docker,
        check_server_deploy_dir=args.check_server_deploy_dir,
        check_server_disk=args.check_server_disk,
        check_health_url=args.check_health_url,
        run_gate=args.run_gate,
        run_acceptance_smoke=args.run_acceptance_smoke,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_m1_go_no_go_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(output_text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
