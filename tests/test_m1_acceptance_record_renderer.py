from datetime import UTC, datetime
import json
from pathlib import Path

from scripts.render_m1_acceptance_record import (
    M1_ACCEPTANCE_RECORD_VERSION,
    build_m1_acceptance_record_markdown,
    build_m1_go_no_go_acceptance_record_markdown,
    main,
)


def _gate_report(status: str = "blocked") -> dict:
    return {
        "version": "m1_deployment_gate.v1",
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "does_not_echo_secret_values": True,
            "starts_services": False,
        },
        "section_statuses": {
            "public_release_boundary": "passed",
            "m1_launch_inputs": status,
            "compose_config": "passed",
            "runtime_readiness": "blocked" if status == "blocked" else "passed",
        },
        "sections": {
            "m1_launch_inputs": {
                "status": status,
                "input_count": 30,
                "passed_count": 29 if status == "blocked" else 30,
                "blocked_count": 1 if status == "blocked" else 0,
                "category_statuses": {
                    "scope": "passed",
                    "backup": status,
                },
            },
            "runtime_readiness": {
                "status": "blocked" if status == "blocked" else "passed",
                "target_statuses": {
                    "production": "blocked" if status == "blocked" else "passed",
                },
            },
        },
        "blocked_reasons": [
            {
                "section": "m1_launch_inputs",
                "env_var": "ZHIXING_BACKUP_TARGET",
                "finding": "Missing required launch input.",
            }
        ]
        if status == "blocked"
        else [],
        "not_proven_by_this_gate": [
            "Real secrets are valid with their upstream providers.",
            "Acceptance smoke has passed against the target URL.",
        ],
    }


def _go_no_go_report(status: str = "degraded") -> dict:
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": status,
        "decision": "conditional_go" if status == "degraded" else "go_for_m1_controlled_trial",
        "section_statuses": {
            "public_health": "passed",
            "postgres_redis_ops_summary": status,
            "postgres_restore_drill_live_probe": "passed",
        },
        "sections": {
            "public_health": {"status": "passed"},
            "postgres_redis_ops_summary": {"status": status},
            "postgres_restore_drill_live_probe": {"status": "passed"},
        },
        "blocked_reasons": [],
        "degraded_reasons": [
            {
                "section": "ops_status",
                "target": "postgres_redis_ops_summary",
                "key": "ZHIXING_POSTGRES_MODE",
                "finding": "PostgreSQL mode is acceptable for M1 but still single-node / Compose scoped.",
            }
        ]
        if status == "degraded"
        else [],
        "not_proven_by_this_report": [
            "Live chat concurrency evidence is not a load test.",
        ],
    }


def _blocked_go_no_go_without_explicit_reasons() -> dict:
    payload = _go_no_go_report("degraded")
    payload["status"] = "blocked"
    payload["decision"] = "no_go"
    payload["section_statuses"]["live_chat_probe"] = "not_checked"
    payload["sections"]["live_chat_probe"] = {"status": "not_checked"}
    payload["blocked_reasons"] = None
    return payload


def test_m1_acceptance_record_renders_blocked_gate_without_claiming_production():
    markdown = build_m1_acceptance_record_markdown(
        _gate_report("blocked"),
        record_id="m1-test",
        environment="staging",
        generated_at=datetime(2026, 6, 23, 10, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert "M1 Acceptance Record" in markdown
    assert M1_ACCEPTANCE_RECORD_VERSION in markdown
    assert "| Gate status | `blocked` |" in markdown
    assert "| M1 trial status | `blocked` |" in markdown
    assert "| Can claim production-ready | `no` |" in markdown
    assert "ZHIXING_BACKUP_TARGET" in markdown
    assert "Missing required launch input." in markdown
    assert "Acceptance smoke has passed against the target URL." in markdown


def test_m1_acceptance_record_renders_passed_gate_as_m1_only():
    markdown = build_m1_acceptance_record_markdown(
        _gate_report("passed"),
        record_id="m1-pass",
        environment="staging",
        generated_at=datetime(2026, 6, 23, 10, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert "| Gate status | `passed` |" in markdown
    assert "| M1 trial status | `passed` |" in markdown
    assert "| Can claim production-ready | `no` |" in markdown
    assert "| public_release_boundary | passed |" in markdown


def test_m1_acceptance_record_renders_degraded_go_no_go_as_conditional_m1():
    markdown = build_m1_go_no_go_acceptance_record_markdown(
        _go_no_go_report("degraded"),
        record_id="m1-conditional",
        environment="staging",
        generated_at=datetime(2026, 6, 25, 10, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert "| Evidence status | `degraded` |" in markdown
    assert "| Go/no-go decision | `conditional_go` |" in markdown
    assert "| M1 trial status | `degraded` |" in markdown
    assert "| Can claim production-ready | `no` |" in markdown
    assert "ZHIXING_POSTGRES_MODE" in markdown
    assert "Live chat concurrency evidence is not a load test." in markdown
    assert "完整生产可用" in markdown


def test_m1_acceptance_record_synthesizes_blocked_section_rows_for_go_no_go():
    markdown = build_m1_go_no_go_acceptance_record_markdown(
        _blocked_go_no_go_without_explicit_reasons(),
        record_id="m1-business-gap",
        environment="staging",
        generated_at=datetime(2026, 6, 25, 10, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert "| Evidence status | `blocked` |" in markdown
    assert "| M1 trial status | `blocked` |" in markdown
    assert "| live_chat_probe | live_chat_probe | Section status is not_checked. |" in markdown


def test_m1_acceptance_record_redacts_sensitive_values():
    secret = "sk-" + "m1record1234567890"
    phone = "138" + "00138000"
    email = "ops" + "@example.com"
    gate = _gate_report("blocked")
    gate["blocked_reasons"].append(
        {
            "section": "runtime_readiness",
            "key": "llm",
            "reason": f"api_key={secret} failed for {email} and {phone}",
        }
    )

    markdown = build_m1_acceptance_record_markdown(gate, record_id="m1-redact")

    assert secret not in markdown
    assert phone not in markdown
    assert email not in markdown
    assert "[REDACTED]" in markdown


def test_m1_acceptance_record_cli_reads_gate_json_and_writes_markdown(tmp_path: Path):
    gate_path = tmp_path / "gate.json"
    output_path = tmp_path / "record.md"
    gate_path.write_text(json.dumps(_gate_report("blocked")), encoding="utf-8")

    code = main(
        [
            "--gate-json",
            str(gate_path),
            "--output",
            str(output_path),
            "--record-id",
            "m1-cli",
        ]
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 2
    assert "m1-cli" in markdown
    assert "gate_json:gate.json" in markdown
    assert "ZHIXING_BACKUP_TARGET" in markdown


def test_m1_acceptance_record_cli_reads_go_no_go_json_and_allows_degraded(tmp_path: Path):
    go_no_go_path = tmp_path / "go-no-go.json"
    output_path = tmp_path / "record.md"
    go_no_go_path.write_text(json.dumps(_go_no_go_report("degraded")), encoding="utf-8")

    code = main(
        [
            "--go-no-go-json",
            str(go_no_go_path),
            "--output",
            str(output_path),
            "--record-id",
            "m1-go-no-go",
        ]
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "m1-go-no-go" in markdown
    assert "go_no_go_json:go-no-go.json" in markdown
    assert "| M1 trial status | `degraded` |" in markdown


def test_m1_acceptance_record_cli_reads_utf8_bom_gate_json(tmp_path: Path):
    gate_path = tmp_path / "gate-bom.json"
    output_path = tmp_path / "record.md"
    gate_path.write_text(
        "\ufeff" + json.dumps(_gate_report("passed"), ensure_ascii=False),
        encoding="utf-8",
    )

    code = main(
        [
            "--gate-json",
            str(gate_path),
            "--output",
            str(output_path),
            "--record-id",
            "m1-bom",
        ]
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "m1-bom" in markdown
    assert "gate_json:gate-bom.json" in markdown
