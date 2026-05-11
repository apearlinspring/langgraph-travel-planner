from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evaluation.acceptance_gate import (
    build_acceptance_gate_result,
    build_acceptance_run_summary,
    build_skipped_acceptance_gate_result,
    render_acceptance_markdown,
    write_acceptance_summary_files,
)
from app.evaluation.preflight import required_capabilities_for_scenarios, run_acceptance_preflight
from app.evaluation.live_runner import (
    build_quality_summary,
    build_snapshot_payload,
    infer_tool_policy_from_scenario,
    parse_sse_event_line,
    runtime_budget_for_scenario,
    scenario_message_sequence,
    select_scenarios,
    snapshot_path_for,
)
from app.evaluation.scenarios import EvaluationScenario
from scripts.run_evaluation_scenarios import (
    _preflight_only_exit_code,
    _preflight_skip_reason,
)
from tests.test_report_quality_evaluation import _valid_report_data


def _scenario(scenario_id: str, mode: str = "agency_plan") -> EvaluationScenario:
    return EvaluationScenario(
        id=scenario_id,
        name=f"Scenario {scenario_id}",
        category=mode,
        prompt="Plan a trip",
        expected_mode=mode,
        min_score=80,
        focus=["contract"],
        tags=["agency" if mode == "agency_plan" else "free"],
        requirements={
            "real_llm": True,
            "real_mcp": True,
            "mcp_servers": ["weather", "search", "amap"],
            "external_apis": ["amap", "tavily"],
        },
    )


def test_select_scenarios_preserves_catalog_order():
    scenarios = [_scenario("a"), _scenario("b"), _scenario("c")]

    selected = select_scenarios(scenarios, ["c", "a"])

    assert [scenario.id for scenario in selected] == ["a", "c"]


def test_select_scenarios_rejects_unknown_id():
    with pytest.raises(KeyError, match="Unknown evaluation scenario ids"):
        select_scenarios([_scenario("a")], ["missing"])


def test_parse_sse_event_line_reads_data_payload():
    event = parse_sse_event_line(b'data: {"type":"token","content":"hello"}\n')

    assert event == {"type": "token", "content": "hello"}
    assert parse_sse_event_line(b": keepalive\n") is None


def test_snapshot_path_for_uses_scenario_id_and_timestamp(tmp_path: Path):
    path = snapshot_path_for(
        _scenario("agency/couple"),
        tmp_path,
        now=datetime(2026, 5, 9, 12, 30, 0),
    )

    assert path == tmp_path / "20260509-123000-agency-couple.json"


def test_build_snapshot_payload_contains_report_and_evaluation_summary():
    scenario = _scenario("agency_couple")
    payload = build_snapshot_payload(
        scenario=scenario,
        conversation={"id": "conversation-id"},
        events=[{"type": "token", "content": "hello"}],
        assistant_text="hello",
        report_data={"version": "travel_report.v1"},
        evaluation={"normalized_score": 90, "passed": True},
        elapsed_seconds=12.345,
        base_url="http://127.0.0.1:8000",
        turns=[{"turn_index": 1, "produced_report_data": True}],
    )

    assert payload["version"] == "evaluation_live_snapshot.v1"
    assert payload["scenario"]["id"] == "agency_couple"
    assert payload["summary"]["elapsed_seconds"] == 12.35
    assert payload["summary"]["has_report_data"] is True
    assert payload["summary"]["evaluation"]["normalized_score"] == 90
    assert payload["summary"]["tool_event_count"] == 0
    assert payload["tool_events"] == []
    assert payload["turns"][0]["produced_report_data"] is True


def test_build_snapshot_payload_preserves_turn_error():
    scenario = _scenario("agency_error")
    payload = build_snapshot_payload(
        scenario=scenario,
        conversation={"id": "conversation-id"},
        events=[],
        assistant_text="",
        report_data=None,
        evaluation=None,
        elapsed_seconds=1,
        base_url="http://127.0.0.1:8000",
        turns=[{"turn_index": 1, "error": "temporary stream error"}],
        error="final failure",
    )

    assert payload["summary"]["error"] == "final failure"
    assert payload["turns"][0]["error"] == "temporary stream error"


def test_scenario_message_sequence_adds_default_finalize_followup():
    messages = scenario_message_sequence(_scenario("agency_couple"))

    assert messages[0] == "Plan a trip"
    assert len(messages) > 2
    assert "\u8bb0\u5f55\u9700\u6c42" in messages[1]
    assert "\u6700\u7ec8\u65c5\u6e38\u89c4\u5212\u62a5\u544a" in messages[-1]


def test_scenario_message_sequence_uses_scenario_followups():
    scenario = EvaluationScenario(
        id="custom",
        name="Custom",
        category="agency_plan",
        prompt="Plan a trip",
        expected_mode="agency_plan",
        min_score=80,
        focus=["contract"],
        tags=["agency"],
        followups=["Finalize now"],
    )

    assert scenario_message_sequence(scenario) == ["Plan a trip", "Finalize now"]


def test_runtime_budget_for_scenario_uses_long_context_profile_and_overrides():
    scenario = EvaluationScenario(
        id="long",
        name="Long",
        category="long_conversation",
        prompt="Plan a trip",
        expected_mode="agency_plan",
        min_score=80,
        focus=["contract"],
        tags=["agency", "long-context"],
        runtime_budget={"max_tool_call_count": 50},
    )

    budget = runtime_budget_for_scenario(scenario)

    assert budget.max_total_elapsed_seconds == 1200
    assert budget.max_first_token_seconds == 90
    assert budget.max_tool_call_count == 50


def test_infer_tool_policy_from_scenario_uses_tags():
    scenario = EvaluationScenario(
        id="hotel_fallback",
        name="Hotel fallback",
        category="edge_case",
        prompt="Find hotel",
        expected_mode="agency_plan",
        min_score=80,
        focus=["hotel"],
        tags=["hotel", "fallback"],
    )

    policy = infer_tool_policy_from_scenario(scenario)

    assert policy["expected_tools"] == {"query_hotel_options"}
    assert policy["requires_fallback"] is True


def test_build_quality_summary_contains_agent_scores():
    scenario = _scenario("agency_couple")
    events = [
        {"type": "tool_call", "tool": "query_transport_options", "turn_index": 1},
        {"type": "token", "content": "hello", "turn_index": 1, "elapsed_since_scenario_start": 0.5},
        {"type": "report_data", "turn_index": 1},
    ]
    turns = [
        {
            "turn_index": 1,
            "user_message": "Plan a trip",
            "event_count": 3,
            "elapsed_seconds": 1.0,
            "tool_call_count": 1,
            "produced_report_data": True,
        }
    ]
    report_evaluation = {
        "normalized_score": 100,
        "passed": True,
        "grade": "A",
        "total_score": 100,
        "max_score": 100,
        "summary": [],
        "criteria": [],
    }

    summary = build_quality_summary(
        scenario=scenario,
        events=events,
        turns=turns,
        assistant_text="hello",
        report_data=_valid_report_data(),
        report_evaluation=report_evaluation,
        elapsed_seconds=1.0,
        timeout_seconds=900.0,
    )

    assert summary["version"] == "agent_quality_summary.v1"
    assert summary["aggregate"]["normalized_score"] == 100
    assert summary["rag_quality"]["passed"] is True
    assert summary["runtime_metrics"]["report_event_count"] == 1
    assert summary["runtime_quality"]["budget_gate"]["passed"] is True
    assert summary["runtime_governance"]["status"] == "pass"


def test_build_quality_summary_fails_aggregate_when_runtime_budget_fails():
    scenario = _scenario("agency_couple")
    report_evaluation = {
        "normalized_score": 100,
        "passed": True,
        "grade": "A",
        "total_score": 100,
        "max_score": 100,
        "summary": [],
        "criteria": [],
    }

    summary = build_quality_summary(
        scenario=scenario,
        events=[
            {"type": "token", "content": "hello", "turn_index": 1, "elapsed_since_scenario_start": 10},
            {"type": "report_data", "turn_index": 1},
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 10}],
        assistant_text="hello",
        report_data=_valid_report_data(),
        report_evaluation=report_evaluation,
        elapsed_seconds=10,
        timeout_seconds=900.0,
        runtime_budget=runtime_budget_for_scenario(
            EvaluationScenario(
                id="strict",
                name="Strict",
                category="agency_plan",
                prompt="Plan",
                expected_mode="agency_plan",
                min_score=80,
                focus=["contract"],
                tags=["agency"],
                runtime_budget={"max_total_elapsed_seconds": 1},
            )
        ),
    )

    assert summary["runtime_quality"]["budget_gate"]["passed"] is False
    assert summary["aggregate"]["passed"] is False


def test_acceptance_gate_passes_valid_quality_summary(tmp_path: Path):
    scenario = _scenario("agency_couple")
    report_data = _valid_report_data()
    report_evaluation = {
        "normalized_score": 100,
        "passed": True,
        "grade": "A",
        "total_score": 100,
        "max_score": 100,
        "summary": [],
        "criteria": [],
    }
    quality_summary = build_quality_summary(
        scenario=scenario,
        events=[
            {"type": "token", "content": "hello", "turn_index": 1, "elapsed_since_scenario_start": 0.5},
            {"type": "report_data", "turn_index": 1},
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 1.0}],
        assistant_text="hello",
        report_data=report_data,
        report_evaluation=report_evaluation,
        elapsed_seconds=1.0,
        timeout_seconds=900.0,
    )

    gate = build_acceptance_gate_result(
        scenario=scenario,
        quality_summary=quality_summary,
        report_data=report_data,
        snapshot_path="snapshot.json",
    )
    run_summary = build_acceptance_run_summary(
        results=[
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "passed": True,
                "snapshot_path": "snapshot.json",
                "acceptance_gate": gate,
            }
        ],
        scenarios=[scenario],
        base_url="http://127.0.0.1:8000",
        output_dir=tmp_path,
        created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    markdown = render_acceptance_markdown(run_summary)
    paths = write_acceptance_summary_files(
        run_summary,
        tmp_path,
        created_at=datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert gate["passed"] is True
    assert run_summary["passed"] is True
    assert "RAG（检索增强生成）" in markdown
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()


def test_acceptance_gate_flags_budget_confidence_gap():
    scenario = _scenario("agency_couple")
    report_data = _valid_report_data()
    report_data["budget_confidence"]["verification_items"] = []
    report_evaluation = {
        "normalized_score": 100,
        "passed": True,
        "grade": "A",
        "total_score": 100,
        "max_score": 100,
        "summary": [],
        "criteria": [],
    }
    quality_summary = build_quality_summary(
        scenario=scenario,
        events=[
            {"type": "token", "content": "hello", "turn_index": 1, "elapsed_since_scenario_start": 0.5},
            {"type": "report_data", "turn_index": 1},
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 1.0}],
        assistant_text="hello",
        report_data=_valid_report_data(),
        report_evaluation=report_evaluation,
        elapsed_seconds=1.0,
        timeout_seconds=900.0,
    )

    gate = build_acceptance_gate_result(
        scenario=scenario,
        quality_summary=quality_summary,
        report_data=report_data,
    )

    assert gate["passed"] is False
    assert gate["dimensions"]["budget_confidence"]["passed"] is False
    assert any(failure["dimension"] == "budget_confidence" for failure in gate["failures"])


def test_preflight_blocks_when_real_credentials_are_missing():
    scenario = _scenario("agency_couple")

    preflight = run_acceptance_preflight(
        [scenario],
        base_url="http://127.0.0.1:8000",
        environ={},
        check_backend=False,
    )

    assert preflight.status == "blocked"
    assert "real_llm" in preflight.missing_required
    assert "report_quality" in preflight.skipped_metrics


def test_preflight_declares_scenario_capability_requirements():
    scenario = _scenario("agency_couple")

    capabilities = required_capabilities_for_scenarios([scenario])

    assert capabilities["real_llm"] is True
    assert capabilities["real_mcp"] is True
    assert "weather" in capabilities["mcp_servers"]
    assert {"amap", "tavily"}.issubset(capabilities["external_apis"])


def test_preflight_only_passed_exit_code_is_success():
    preflight = {
        "status": "passed",
        "checks": [],
        "missing_required": [],
        "degraded_optional": [],
    }

    assert _preflight_only_exit_code(preflight) == 0
    assert "Preflight-only passed" in _preflight_skip_reason(preflight)


def test_preflight_only_blocked_exit_code_is_failure():
    preflight = {
        "status": "blocked",
        "checks": [
            {
                "label": "Backend live health endpoint",
                "status": "blocked",
                "findings": ["connection refused"],
            }
        ],
        "missing_required": ["backend_live"],
        "degraded_optional": [],
    }

    assert _preflight_only_exit_code(preflight) == 2
    assert "Backend live health endpoint" in _preflight_skip_reason(preflight)


def test_blocked_preflight_summary_cannot_pass_acceptance(tmp_path: Path):
    scenario = _scenario("agency_couple")
    preflight = run_acceptance_preflight(
        [scenario],
        base_url="http://127.0.0.1:8000",
        environ={},
        check_backend=False,
    ).to_dict()
    skipped_gate = build_skipped_acceptance_gate_result(
        scenario=scenario,
        reason="Preflight blocked live acceptance",
    )

    summary = build_acceptance_run_summary(
        results=[
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "status": "skipped",
                "passed": False,
                "acceptance_gate": skipped_gate,
            }
        ],
        scenarios=[scenario],
        base_url="http://127.0.0.1:8000",
        output_dir=tmp_path,
        preflight=preflight,
    )
    markdown = render_acceptance_markdown(summary)

    assert summary["status"] == "blocked"
    assert summary["passed"] is False
    assert summary["skipped_count"] == 1
    assert "指标不可判定" in markdown
