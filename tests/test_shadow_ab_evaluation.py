import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evaluation.experiment import (
    ExperimentDefinition,
    ExperimentVariant,
    ScenarioSet,
    compare_acceptance_summaries,
    experiment_definition_from_dict,
    render_comparison_markdown,
    summarize_acceptance_run,
)
from scripts.compare_acceptance_runs import main as compare_main


def _gate(status: str, score: float, failures: list[str] | None = None) -> dict:
    failure_records = [
        {
            "scenario_id": "scenario",
            "dimension": dimension,
            "dimension_label": dimension,
            "findings": ["redacted aggregate finding"],
        }
        for dimension in failures or []
    ]
    return {
        "status": status,
        "passed": status == "passed",
        "dimensions": {
            "agent_quality": {
                "score": score,
                "passed": status == "passed",
                "threshold": 82,
            }
        },
        "failures": failure_records,
        "degradations": [],
    }


def _result(
    scenario_id: str,
    *,
    status: str,
    score: float,
    elapsed: float,
    tokens: int,
    tool_counts: dict[str, int],
    failures: list[str] | None = None,
) -> dict:
    return {
        "scenario_id": scenario_id,
        "scenario_name": f"Scenario {scenario_id}",
        "status": status,
        "passed": status == "passed",
        "agent_score": score,
        "elapsed_seconds": elapsed,
        "runtime_metrics": {
            "total_elapsed_seconds": elapsed,
            "tool_call_count": sum(tool_counts.values()),
            "tool_failure_count": 0,
            "fallback_count": 0,
            "estimated_input_tokens": tokens // 2,
            "estimated_output_tokens": tokens - tokens // 2,
            "estimated_total_tokens": tokens,
        },
        "tool_counts": tool_counts,
        "acceptance_gate": _gate(status, score, failures),
    }


def _summary(results: list[dict]) -> dict:
    failures = [
        failure
        for result in results
        for failure in result["acceptance_gate"]["failures"]
    ]
    passed_count = sum(1 for result in results if result["passed"])
    return {
        "version": "acceptance_run_summary.v1",
        "created_at": "2026-05-11T00:00:00+00:00",
        "status": "passed" if passed_count == len(results) else "failed",
        "passed": passed_count == len(results),
        "selected_count": len(results),
        "passed_count": passed_count,
        "status_counts": {
            "passed": passed_count,
            "failed": len(results) - passed_count,
        },
        "average_agent_score": round(
            sum(result["agent_score"] for result in results) / len(results),
            2,
        ),
        "results": results,
        "failures": failures,
        "degradations": [],
    }


def _experiment() -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id="qwen-prompt-regression",
        mode="offline-ab",
        scenario_set=ScenarioSet(
            scenario_set_id="acceptance-core",
            scenario_ids=("agency_couple", "hotel_fallback"),
            source="data/evaluation/report_quality_scenarios.json",
        ),
        baseline=ExperimentVariant(
            variant_id="baseline",
            model_profile="planner",
            prompt_ref="app/agents/handoffs/step_config.py",
        ),
        candidate=ExperimentVariant(
            variant_id="candidate",
            model_profile="planner",
            tool_strategy="more_aggressive_hotel_search",
            metadata={
                "owner_email": "owner@example.com",
                "phone": "13800138000",
                "api_key": "sk-testvalue123456789",
            },
        ),
        description="Compare candidate prompt without routing users.",
    )


def test_experiment_definition_from_dict_validates_mode_and_redacts_metadata():
    definition = experiment_definition_from_dict(
        {
            "experiment_id": "shadow-observe",
            "mode": "shadow-only",
            "scenario_set": {
                "scenario_set_id": "smoke",
                "scenario_ids": ["agency_couple"],
            },
            "baseline": {"variant_id": "base"},
            "candidate": {
                "variant_id": "cand",
                "metadata": {"email": "owner@example.com"},
            },
        }
    )

    assert definition.mode == "shadow-only"
    assert definition.scenario_set.scenario_ids == ("agency_couple",)
    assert definition.to_dict()["candidate"]["metadata"]["email"] == "[REDACTED]"
    with pytest.raises(ValueError, match="Experiment mode"):
        experiment_definition_from_dict(
            {
                "experiment_id": "bad",
                "mode": "online-ab",
                "scenario_set": "smoke",
            }
        )


def test_compare_acceptance_summaries_reports_quality_runtime_and_tool_deltas():
    baseline = _summary(
        [
            _result(
                "agency_couple",
                status="passed",
                score=90,
                elapsed=10,
                tokens=100,
                tool_counts={"query_transport_options": 1},
            ),
            _result(
                "hotel_fallback",
                status="passed",
                score=85,
                elapsed=11,
                tokens=80,
                tool_counts={"query_hotel_options": 1},
            ),
        ]
    )
    candidate = _summary(
        [
            _result(
                "agency_couple",
                status="passed",
                score=92,
                elapsed=12,
                tokens=130,
                tool_counts={"query_transport_options": 2},
            ),
            _result(
                "hotel_fallback",
                status="failed",
                score=70,
                elapsed=13,
                tokens=120,
                tool_counts={"query_hotel_options": 2},
                failures=["tool_quality"],
            ),
        ]
    )

    comparison = compare_acceptance_summaries(
        baseline,
        candidate,
        experiment=_experiment(),
        created_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
    )
    serialized = json.dumps(comparison, ensure_ascii=False)

    assert comparison["version"] == "shadow_ab_acceptance_comparison.v1"
    assert comparison["mode"] == "offline-ab"
    assert comparison["online_traffic_split"] is False
    assert comparison["verdict"] == "regressed"
    assert comparison["passed"] is False
    assert comparison["deltas"]["pass_rate_points"] == -50
    assert comparison["deltas"]["average_agent_score"] == -6.5
    assert comparison["deltas"]["elapsed_seconds"] == 4
    assert comparison["deltas"]["estimated_total_tokens"] == 70
    assert comparison["failure_dimension_delta"]["tool_quality"]["candidate"] == 1
    assert comparison["tool_call_delta"]["query_hotel_options"]["delta"] == 1
    assert comparison["scenario_comparisons"][1]["regressions"] == [
        "passed_to_failed",
        "score_drop_ge_5",
    ]
    assert "owner@example.com" not in serialized
    assert "13800138000" not in serialized
    assert "sk-testvalue123456789" not in serialized


def test_summarize_acceptance_run_falls_back_to_result_runtime_metrics():
    summary = _summary(
        [
            _result(
                "agency_couple",
                status="passed",
                score=90,
                elapsed=10,
                tokens=100,
                tool_counts={"query_transport_options": 1},
            )
        ]
    )

    metrics = summarize_acceptance_run(summary, variant_id="baseline")

    assert metrics.pass_rate == 1
    assert metrics.runtime_totals["elapsed_seconds"] == 10
    assert metrics.runtime_totals["estimated_total_tokens"] == 100
    assert metrics.tool_counts == {"query_transport_options": 1}


def test_render_comparison_markdown_mentions_offline_contract():
    comparison = compare_acceptance_summaries(
        _summary(
            [
                _result(
                    "agency_couple",
                    status="passed",
                    score=90,
                    elapsed=10,
                    tokens=100,
                    tool_counts={},
                )
            ]
        ),
        _summary(
            [
                _result(
                    "agency_couple",
                    status="passed",
                    score=91,
                    elapsed=9,
                    tokens=90,
                    tool_counts={},
                )
            ]
        ),
        experiment=_experiment(),
    )

    markdown = render_comparison_markdown(comparison)

    assert "online_traffic_split: False" in markdown
    assert "估算 token（文本令牌）" in markdown
    assert "verdict: improved" in markdown


def test_compare_acceptance_runs_script_writes_outputs_and_fails_on_regression(
    tmp_path: Path,
):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "comparison.json"
    baseline_path.write_text(
        json.dumps(
            _summary(
                [
                    _result(
                        "agency_couple",
                        status="passed",
                        score=90,
                        elapsed=10,
                        tokens=100,
                        tool_counts={},
                    )
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(
            _summary(
                [
                    _result(
                        "agency_couple",
                        status="failed",
                        score=70,
                        elapsed=12,
                        tokens=120,
                        tool_counts={},
                        failures=["report_quality"],
                    )
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = compare_main(
        [
            str(baseline_path),
            str(candidate_path),
            "--experiment-id",
            "script-smoke",
            "--output-json",
            str(output_path),
            "--json",
            "--fail-on-regression",
        ]
    )

    assert exit_code == 2
    comparison = json.loads(output_path.read_text(encoding="utf-8"))
    assert comparison["experiment"]["experiment_id"] == "script-smoke"
    assert comparison["verdict"] == "regressed"
