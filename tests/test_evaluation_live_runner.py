from datetime import datetime
from pathlib import Path

import pytest

from app.evaluation.live_runner import (
    build_snapshot_payload,
    parse_sse_event_line,
    scenario_message_sequence,
    select_scenarios,
    snapshot_path_for,
)
from app.evaluation.scenarios import EvaluationScenario


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
