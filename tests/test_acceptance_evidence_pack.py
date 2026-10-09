import json
import os
from pathlib import Path

from scripts.export_acceptance_evidence import (
    build_acceptance_evidence_markdown,
    export_acceptance_evidence,
    find_latest_acceptance_summary,
)


def _scenario(index: int, *, mode: str = "agency_plan") -> dict:
    return {
        "id": f"scenario_{index}",
        "name": f"Scenario {index}",
        "expected_mode": mode,
    }


def _result(
    scenario_id: str,
    *,
    status: str = "passed",
    first_token_seconds: float | None = 1.234,
    tool_call_count: int | None = 3,
    runtime_budget_passed: bool | None = True,
    evidence_passed: bool = True,
    evidence_missing: list[str] | None = None,
) -> dict:
    passed = status == "passed"
    runtime_budget_status = (
        "passed"
        if runtime_budget_passed is True
        else "failed"
        if runtime_budget_passed is False
        else "skipped"
    )
    return {
        "scenario_id": scenario_id,
        "scenario_name": f"Scenario {scenario_id}",
        "status": status,
        "passed": passed,
        "first_token_seconds": first_token_seconds,
        "tool_call_count": tool_call_count,
        "runtime_budget_passed": runtime_budget_passed,
        "runtime_metrics": {
            "first_token_seconds": first_token_seconds,
            "tool_call_count": tool_call_count,
            "total_elapsed_seconds": 12.0,
            "estimated_total_tokens": 1200,
        },
        "tool_counts": {"query_destination_info": tool_call_count or 0},
        "evidence_closure": {
            "passed": evidence_passed,
            "missing": evidence_missing or [],
            "checks": {
                "snapshot": True,
                "report_data": True,
                "budget": True,
                "budget_confidence": True,
                "risk": True,
                "verification_items": True,
                "agency_business_evidence": True,
            },
        },
        "acceptance_gate": {
            "status": status,
            "passed": passed,
            "dimensions": {
                "runtime_budget": {
                    "status": runtime_budget_status,
                    "passed": runtime_budget_passed,
                }
            },
            "failures": [],
            "degradations": [],
        },
    }


def _summary(*, status: str = "passed", results: list[dict] | None = None) -> dict:
    selected = [_scenario(index, mode="free_planning" if index <= 2 else "agency_plan") for index in range(1, 10)]
    run_results = results if results is not None else [_result(item["id"]) for item in selected]
    status_counts: dict[str, int] = {}
    for result in run_results:
        result_status = result.get("status") or "failed"
        status_counts[result_status] = status_counts.get(result_status, 0) + 1
    return {
        "version": "acceptance_run_summary.v1",
        "created_at": "2026-05-14T05:44:48+00:00",
        "status": status,
        "passed": status == "passed",
        "selected_count": len(selected),
        "result_count": len(run_results),
        "passed_count": sum(1 for result in run_results if result.get("status") == "passed"),
        "status_counts": status_counts,
        "selected_scenarios": selected,
        "results": run_results,
        "runtime_totals": {
            "elapsed_seconds": 321.123,
            "average_elapsed_seconds": 35.681,
            "tool_call_count": sum(result.get("tool_call_count") or 0 for result in run_results),
            "tool_failure_count": 0,
            "fallback_count": 1,
            "estimated_total_tokens": 36000,
            "tool_counts": {"query_destination_info": 9},
        },
        "tool_counts": {"query_destination_info": 9},
        "evidence_closure": {
            "version": "acceptance_evidence_closure_summary.v1",
            "result_count": len(run_results),
            "passed_count": sum(
                1
                for result in run_results
                if (result.get("evidence_closure") or {}).get("passed") is True
            ),
            "counts": {
                "snapshot": len(run_results),
                "report_data": len(run_results),
                "budget": len(run_results),
                "budget_confidence": len(run_results),
                "risk": len(run_results),
                "verification_items": len(run_results),
                "agency_business_evidence": len(run_results),
            },
            "missing_by_scenario": {},
        },
        "run_context": {
            "version": "acceptance_run_context.v1",
            "partial": len(run_results) < len(selected),
            "partial_reason": None,
            "completed_scenario_ids": [result["scenario_id"] for result in run_results],
            "pending_scenario_ids": [
                item["id"]
                for item in selected
                if item["id"] not in {result["scenario_id"] for result in run_results}
            ],
            "failure_classification_counts": {},
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_export_picks_latest_runtime_summary_and_renders_nine_scenarios(tmp_path: Path):
    runtime_dir = tmp_path / ".runtime"
    old_summary = runtime_dir / "old" / "20260513-120000-acceptance-summary.json"
    latest_summary = runtime_dir / "acceptance-core" / "20260514-134448-acceptance-summary.json"
    _write_json(old_summary, _summary(status="failed", results=[_result("scenario_1", status="failed")]))
    payload = _summary()
    payload["results"][0]["first_token_seconds"] = 12.345
    payload["results"][0]["tool_call_count"] = 14
    _write_json(latest_summary, payload)
    os.utime(old_summary, (1, 1))
    os.utime(latest_summary, (2, 2))

    output_path = tmp_path / "docs" / "acceptance-core-report.md"
    result = export_acceptance_evidence(
        runtime_dir=runtime_dir,
        output_path=output_path,
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert result.summary_path == latest_summary
    assert result.status == "passed"
    assert find_latest_acceptance_summary(runtime_dir) == latest_summary
    assert "Acceptance Core Evidence Pack（核心验收证据包）" in markdown
    assert markdown.count("| scenario_") == 9
    assert "12.345s" in markdown
    assert "| 14 |" in markdown
    assert "证据闭环" in markdown
    assert "运行预算" in markdown
    assert "20260514-134448-acceptance-summary.json" in markdown


def test_evidence_pack_explains_partial_failed_and_degraded_summary(tmp_path: Path):
    results = [
        _result("scenario_1", status="passed", first_token_seconds=9.0, tool_call_count=2),
        _result(
            "scenario_2",
            status="degraded",
            first_token_seconds=58.0,
            tool_call_count=30,
            runtime_budget_passed=True,
        ),
        _result(
            "scenario_3",
            status="failed",
            first_token_seconds=None,
            tool_call_count=None,
            runtime_budget_passed=False,
            evidence_passed=False,
            evidence_missing=["verification_items"],
        ),
    ]
    payload = _summary(status="failed", results=results)
    payload["evidence_closure"]["missing_by_scenario"] = {
        "scenario_3": ["verification_items"]
    }
    payload["run_context"]["partial"] = True
    payload["run_context"]["partial_reason"] = "global_timeout"
    payload["run_context"]["failure_classification_counts"] = {
        "runtime_budget": 1,
        "global_timeout": 1,
    }

    markdown = build_acceptance_evidence_markdown(
        payload,
        source_path=tmp_path / ".runtime" / "20260514-134448-acceptance-summary.json",
    )

    assert "failed（失败）" in markdown
    assert "degraded（降级）" in markdown
    assert "pending（待运行）" in markdown
    assert "partial summary（部分摘要）: 是" in markdown
    assert "global_timeout" in markdown
    assert "missing: verification_items" in markdown
    assert "runtime_budget=1" in markdown


def test_missing_runtime_summary_writes_clear_non_passing_report(tmp_path: Path):
    output_path = tmp_path / "docs" / "acceptance-core-report.md"

    result = export_acceptance_evidence(
        runtime_dir=tmp_path / ".runtime",
        output_path=output_path,
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert result.missing_summary is True
    assert result.status == "missing_summary"
    assert "missing_summary（缺少摘要）" in markdown
    assert "不能作为 acceptance-core（核心验收）通过证据" in markdown
    assert ".runtime/" in markdown


def test_evidence_pack_redacts_secrets_and_pii(tmp_path: Path):
    email = "test" + "@example.com"
    phone = "138" + "00138000"
    api_key = "sk-" + "testvalue123456789"
    jwt = ".".join(["eyJabcdefgh", "ijklmnopqr", "stuvwxyz12"])
    payload = _summary(
        status="failed",
        results=[
            _result(
                f"scenario_{email}_{phone}",
                status="failed",
                evidence_passed=False,
                evidence_missing=[f"api_key={api_key}"],
            )
        ],
    )
    payload["run_context"]["partial_reason"] = f"Bearer {jwt} failed for {phone}"

    markdown = build_acceptance_evidence_markdown(
        payload,
        source_path=tmp_path / ".runtime" / "summary.json",
    )

    assert email not in markdown
    assert phone not in markdown
    assert api_key not in markdown
    assert jwt not in markdown
    assert "[REDACTED]" in markdown
