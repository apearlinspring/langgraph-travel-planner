from datetime import UTC, datetime
import json
from pathlib import Path

from scripts.render_m1_live_evidence_summary import (
    M1_LIVE_EVIDENCE_SUMMARY_VERSION,
    build_m1_live_evidence_summary_markdown,
    main,
)


def _go_no_go_report(status="degraded", decision="conditional_go"):
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": status,
        "decision": decision,
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "may_connect_ssh": True,
            "may_call_external_apis": True,
            "may_write_runtime_artifacts": True,
        },
        "target": {
            "public_base_url_present": True,
            "public_base_url_echoed": False,
        },
        "section_statuses": {
            "live_server_probe": "degraded",
            "postgres_redis_live_probe": "passed",
            "postgres_redis_ops_summary": "degraded",
            "backup_schedule_live_probe": "passed",
            "server_capacity_snapshot": "degraded",
            "live_concurrency_probe": "passed",
            "rate_limit_live_probe": "passed",
            "probe_auth_readiness": "passed",
            "live_chat_probe": "passed",
            "docker_disk_cleanup_plan": "degraded",
            "docker_build_cache_cleanup_plan": "degraded",
            "docker_build_cache_cleanup_approval_gate": "degraded",
            "docker_build_cache_post_cleanup": "passed",
            "restore_drill_feasibility": "blocked",
            "disk_remediation_approval_gate": "blocked",
            "storage_expansion_readiness": "blocked",
            "external_dependency_resilience_record": "passed",
            "m1_rollout_execution_record": "passed",
            "m1_operations_review_record": "passed",
        },
        "sections": {
            "live_server_probe": {
                "status": "degraded",
                "sections": {
                    "host": {"status": "degraded"},
                    "compose_services": {"status": "passed"},
                    "internal_health": {"status": "passed"},
                    "server_side_public_health": {"status": "passed"},
                    "mock_checkout": {"status": "passed"},
                },
            },
            "postgres_redis_live_probe": {
                "status": "passed",
                "sections": {
                    "postgres": {"status": "passed"},
                    "redis": {"status": "passed"},
                },
            },
            "postgres_redis_ops_summary": {
                "status": "degraded",
                "decision": "conditional_go_for_m1_with_recorded_stateful_limits",
                "section_statuses": {
                    "ops_status": "degraded",
                    "live_probe": "passed",
                    "recovery_record": "passed",
                },
            },
            "backup_schedule_live_probe": {
                "status": "passed",
                "sections": {
                    "schedule": {"status": "passed"},
                    "freshness": {"status": "passed"},
                },
            },
            "server_capacity_snapshot": {
                "status": "degraded",
                "sections": {
                    "host_capacity": {
                        "status": "degraded",
                        "cpu_count": 2,
                        "disk": {"root": {"used_percent": 97}},
                    },
                    "container_capacity": {"status": "passed"},
                },
            },
            "live_concurrency_probe": {
                "status": "passed",
                "endpoints": [
                    {"endpoint_key": "health_live", "error_rate": 0, "latency_ms": {"p95": 120}},
                    {"endpoint_key": "mock_checkout", "error_rate": 0, "latency_ms": {"p95": 240}},
                ],
            },
            "rate_limit_live_probe": {
                "status": "passed",
                "request_count": 130,
                "status_counts": {"200": 120, "429": 10},
                "rate_limit_headers_seen": {"retry-after": True},
            },
            "probe_auth_readiness": {
                "status": "passed",
                "target": {"auth_strategy": "probe_login"},
                "observations": {
                    "login_performed": True,
                    "me_checked": True,
                    "token_validated": True,
                },
            },
            "live_chat_probe": {
                "status": "passed",
                "target": {"auth_strategy": "probe_login"},
                "observations": {
                    "login_performed": True,
                    "stream_completed": True,
                    "first_token_seconds": 3.2,
                    "total_seconds": 9.8,
                },
            },
            "docker_disk_cleanup_plan": {
                "status": "degraded",
                "summary": {"selected_candidate_count": 20, "candidate_count": 639},
                "policy": {"deletes_images": False},
            },
            "docker_build_cache_cleanup_plan": {
                "status": "degraded",
                "build_cache": {"reclaimable_mb": 23582.7},
                "disk": {"root": {"used_percent": 96}},
                "policy": {"deletes_build_cache": False, "runs_system_prune": False},
            },
            "docker_build_cache_cleanup_approval_gate": {
                "status": "degraded",
                "decision": "ready_for_explicit_approval",
                "sections": {
                    "approval_record": {"status": "not_checked"},
                    "build_cache_cleanup_plan": {"reclaimable_mb": 23582.7},
                    "build_cache_cleanup_dry_run": {"prune_result": "dry_run"},
                },
            },
            "docker_build_cache_post_cleanup": {
                "status": "passed",
                "decision": "build_cache_remediation_evidence_passed",
                "sections": {
                    "execution": {"estimated_reclaimable_delta_mb": 23582.7},
                    "capacity_delta": {"root_free_delta_mb": 23536},
                    "restore_feasibility": {"status": "passed"},
                },
            },
            "restore_drill_feasibility": {
                "status": "blocked",
                "sections": {
                    "postgres_backup": {"status": "passed"},
                    "restore_workspace_space": {
                        "status": "blocked",
                        "effective_free_mb": 2266,
                        "required_free_mb": 4096,
                    },
                },
            },
            "disk_remediation_approval_gate": {
                "status": "blocked",
                "decision": "ready_for_explicit_approval",
                "sections": {
                    "approval": {"status": "blocked"},
                    "cleanup_plan": {"selected_images": 20},
                    "dry_run": {"dry_run_count": 20},
                },
            },
            "storage_expansion_readiness": {
                "status": "blocked",
                "decision": "storage_expansion_required",
                "sections": {
                    "recommendation": {
                        "strategy": "expand_root_volume_or_attach_new_disk_for_docker_data",
                    },
                    "restore_workspace": {"gap_mb": 1809},
                    "block_topology": {"unmounted_block_count": 0},
                    "mount_sharing": {"root_docker_same_mount": True},
                },
            },
            "external_dependency_resilience_record": {
                "status": "passed",
                "record_summary": {
                    "optional_service_count": 4,
                    "degradation_scenario_count": 3,
                    "tool_sample_count": 28,
                    "budget_usage_ratio": 0.42,
                },
                "checks": {
                    "degradation_drill": {
                        "status": "passed",
                        "scenario_types": ["provider_5xx", "rate_limit", "timeout"],
                    }
                },
            },
            "m1_rollout_execution_record": {
                "status": "passed",
                "record_summary": {
                    "environment": "m1_controlled_trial",
                    "deployment_phase_count": 7,
                    "issue_count": 1,
                },
                "checks": {
                    "rollback_readiness": {"status": "passed"},
                    "data_safety": {"status": "passed"},
                },
            },
            "m1_operations_review_record": {
                "status": "passed",
                "record_summary": {
                    "issues_observed": True,
                    "issue_count": 1,
                    "followup_count": 2,
                },
                "checks": {
                    "issue_review": {"status": "passed"},
                    "m1_boundary": {"status": "passed"},
                    "followups": {"status": "passed"},
                },
            },
        },
        "blockers": [],
        "degraded_reasons": [
            {"section": "server_capacity_snapshot", "key": "root_disk", "finding": "Disk usage is above warning threshold."}
        ],
        "not_proven_by_this_report": [
            "A go decision is only for M1 controlled trial traffic.",
        ],
    }


def test_live_evidence_summary_renders_key_operational_sections():
    markdown = build_m1_live_evidence_summary_markdown(
        _go_no_go_report(),
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
        source_name="unit-test",
    )

    assert "M1 Live Evidence Summary" in markdown
    assert M1_LIVE_EVIDENCE_SUMMARY_VERSION in markdown
    assert "| Decision | `conditional_go` |" in markdown
    assert "PostgreSQL / Redis" in markdown
    assert "postgres=passed, redis=passed" in markdown
    assert "PostgreSQL / Redis ops summary" in markdown
    assert "ops=degraded, live=passed, recovery=passed" in markdown
    assert "root_disk_used=97%" in markdown
    assert "worst_p95_ms=240" in markdown
    assert "Probe auth" in markdown
    assert "auth=probe_login, login=True, me=True, token_validated=True" in markdown
    assert "auth=probe_login, login=True, stream=True" in markdown
    assert "candidates=20/639" in markdown
    assert "Docker build cache plan" in markdown
    assert "reclaimable=23582.7 MB" in markdown
    assert "Docker build cache approval" in markdown
    assert "approval=not_checked" in markdown
    assert "Docker build cache post-cleanup" in markdown
    assert "root_delta=23536 MB" in markdown
    assert "Restore drill feasibility" in markdown
    assert "free=2266/4096 MB" in markdown
    assert "Disk remediation approval" in markdown
    assert "ready_for_explicit_approval" in markdown
    assert "Storage expansion readiness" in markdown
    assert "expand_root_volume_or_attach_new_disk_for_docker_data" in markdown
    assert "gap=1809 MB" in markdown
    assert "External dependency resilience" in markdown
    assert "degradation_scenarios=3" in markdown
    assert "Rollout execution record" in markdown
    assert "env=m1_controlled_trial, phases=7, issues=1, rollback=passed, data_safety=passed" in markdown
    assert "Operations review" in markdown
    assert "issues_observed=True, issues=1, followups=2" in markdown
    assert "上线执行记录、外部依赖韧性记录和运维复盘记录形成闭环" in markdown
    assert "Can claim full production-ready | `no`" in markdown


def test_live_evidence_summary_redacts_sensitive_values():
    report = _go_no_go_report(status="blocked", decision="no_go")
    token_value = "sk-" + "live-summary-sentinel-123456"
    phone = "138" + "00138000"
    report["blockers"] = [
        {
            "section": "live_chat_probe",
            "key": "auth",
            "reason": f"token {token_value} failed for phone {phone}",
        }
    ]

    markdown = build_m1_live_evidence_summary_markdown(report)

    assert token_value not in markdown
    assert phone not in markdown
    assert "[REDACTED]" in markdown
    assert "| Decision | `no_go` |" in markdown


def test_live_evidence_summary_cli_reads_go_no_go_json(tmp_path: Path):
    input_path = tmp_path / "go-no-go.json"
    output_path = tmp_path / "summary.md"
    input_path.write_text(json.dumps(_go_no_go_report(), ensure_ascii=False), encoding="utf-8")

    code = main(["--go-no-go-json", str(input_path), "--output", str(output_path)])
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "go_no_go_json:go-no-go.json" in markdown
    assert "Low-risk concurrency" in markdown


def test_live_evidence_summary_cli_reads_utf8_bom_json(tmp_path: Path):
    input_path = tmp_path / "go-no-go-bom.json"
    output_path = tmp_path / "summary.md"
    input_path.write_text(
        "\ufeff" + json.dumps(_go_no_go_report(), ensure_ascii=False),
        encoding="utf-8",
    )

    code = main(["--go-no-go-json", str(input_path), "--output", str(output_path)])
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "go_no_go_json:go-no-go-bom.json" in markdown
