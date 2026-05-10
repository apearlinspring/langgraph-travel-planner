import pytest

from app.evaluation.tool_quality import (
    evaluate_tool_quality,
    extract_tool_events,
    redundant_tool_calls,
)
from tests.test_report_quality_evaluation import _valid_report_data


def test_evaluate_tool_quality_passes_expected_tool_call():
    events = [
        {"type": "tool_call", "tool": "query_transport_options", "turn_index": 1},
        {"type": "report_data", "turn_index": 1},
    ]

    result = evaluate_tool_quality(
        events,
        report_data=_valid_report_data(),
        expected_tools={"query_transport_options"},
    )

    assert result.passed is True
    assert result.normalized_score == 100
    assert result.tool_counts["query_transport_options"] == 1


def test_evaluate_tool_quality_flags_forbidden_tool():
    events = [{"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1}]

    result = evaluate_tool_quality(
        events,
        report_data=_valid_report_data(),
        forbidden_tools={"query_hotel_options"},
    )

    assert result.passed is False
    assert any("forbidden tool" in item.lower() for item in result.summary)


def test_evaluate_tool_quality_flags_redundant_calls():
    events = [
        {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
        {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
    ]
    records = extract_tool_events(events)

    result = evaluate_tool_quality(
        events,
        report_data=_valid_report_data(),
        expected_tools={"query_hotel_options"},
    )

    assert redundant_tool_calls(records) == ["turn-1:query_hotel_options called 2 times"]
    assert result.passed is False
    assert any("Redundant tool calls" in item for item in result.summary)


def test_evaluate_tool_quality_requires_fallback_pending_checks():
    events = [{"type": "error", "message": "hotel MCP timeout"}]

    result = evaluate_tool_quality(events, requires_fallback=True)

    assert result.passed is False
    assert any("pending verification checks" in item for item in result.summary)


def test_extract_tool_events_supports_langgraph_tool_names():
    events = [
        {"event": "on_tool_start", "name": "query_destination_info", "turn_index": 2},
        {"type": "token", "content": "hello"},
    ]

    records = extract_tool_events(events)

    assert len(records) == 1
    assert records[0].tool == "query_destination_info"
    assert records[0].turn_index == 2


def test_evaluate_tool_quality_rejects_non_list_events():
    with pytest.raises(TypeError):
        evaluate_tool_quality(None)  # type: ignore[arg-type]
