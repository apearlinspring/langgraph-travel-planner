import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.evaluation.acceptance_gate import (
    build_acceptance_gate_result,
    build_error_acceptance_gate_result,
    build_acceptance_run_summary,
    build_skipped_acceptance_gate_result,
    render_acceptance_markdown,
    write_acceptance_summary_files,
)
from app.evaluation.preflight import (
    _check_backend_ready,
    required_capabilities_for_scenarios,
    run_acceptance_preflight,
)
from app.evaluation.live_runner import (
    DEFAULT_BASE_URL,
    LiveRunConfig,
    _classify_live_error_status,
    build_acceptance_evidence_closure,
    build_quality_summary,
    build_snapshot_payload,
    classify_live_failure_category,
    infer_tool_policy_from_scenario,
    parse_sse_event_line,
    run_live_scenario,
    runtime_budget_for_scenario,
    scenario_message_sequence,
    select_scenarios,
    snapshot_path_for,
)
from app.evaluation.scenarios import EvaluationScenario
from app.evaluation.scenarios import ACCEPTANCE_SMOKE_TAG, acceptance_smoke_scenarios
from scripts.run_evaluation_scenarios import (
    RUNTIME_ARTIFACT_ROOT,
    _build_and_optionally_write_summary,
    _build_live_error_result,
    _failure_classification_counts,
    _require_runtime_artifact_dir,
    build_cli_json_payload,
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
        conversation={"id": "conversation-id", "email": "test@example.com"},
        events=[
            {"type": "token", "content": "hello 13800138000"},
            {
                "type": "turn_observability",
                "observability": {
                    "degradation_status": "ok",
                    "last_error": "联系 test@example.com",
                },
            },
        ],
        assistant_text="hello 13800138000",
        report_data={"version": "travel_report.v1", "api_key": "sk-testvalue123456789"},
        evaluation={"normalized_score": 90, "passed": True},
        elapsed_seconds=12.345,
        base_url="http://127.0.0.1:8000",
        turns=[{"turn_index": 1, "produced_report_data": True, "error": "test@example.com"}],
        quality_summary={"aggregate": {"normalized_score": 90}},
        llm_judge_evaluation={"status": "blocked", "findings": ["missing key"]},
    )
    serialized = str(payload)

    assert payload["version"] == "evaluation_live_snapshot.v1"
    assert payload["scenario"]["id"] == "agency_couple"
    assert payload["summary"]["elapsed_seconds"] == 12.35
    assert payload["summary"]["has_report_data"] is True
    assert payload["summary"]["evaluation"]["normalized_score"] == 90
    assert payload["summary"]["tool_event_count"] == 0
    assert payload["summary"]["has_quality_summary"] is True
    assert payload["summary"]["has_llm_judge"] is True
    assert payload["summary"]["llm_judge"]["status"] == "blocked"
    assert payload["llm_judge"]["status"] == "blocked"
    assert payload["summary"]["has_turn_observability"] is True
    assert payload["quality_summary"]["aggregate"]["normalized_score"] == 90
    assert payload["evidence_closure"]["checks"]["report_data"] is True
    assert payload["turn_observability"] == [
        {"degradation_status": "ok", "last_error": "联系 [REDACTED]"}
    ]
    assert payload["tool_events"] == []
    assert payload["turns"][0]["produced_report_data"] is True
    assert "test@example.com" not in serialized
    assert "13800138000" not in serialized
    assert "sk-testvalue123456789" not in serialized


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
        {
            "type": "turn_observability",
            "observability": {
                "tool_call_count": 1,
                "tool_failure_count": 0,
                "fallback_count": 0,
                "degradation_status": "ok",
                "estimated_input_tokens": 3,
                "estimated_output_tokens": 2,
                "estimated_total_tokens": 5,
            },
        },
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


def test_acceptance_evidence_closure_tracks_live_report_requirements():
    scenario = _scenario("agency_couple")

    closure = build_acceptance_evidence_closure(
        scenario=scenario,
        report_data=_valid_report_data(),
        snapshot_path=".runtime/evaluations/snapshot.json",
    )

    assert closure["passed"] is True
    assert closure["checks"]["report_data"] is True
    assert closure["checks"]["budget"] is True
    assert closure["checks"]["risk"] is True
    assert closure["checks"]["verification_items"] is True
    assert closure["checks"]["agency_business_evidence"] is True
    assert {"products", "pricing", "risk"}.issubset(
        set(closure["agency_evidence_categories"])
    )


def test_acceptance_evidence_closure_blocks_missing_real_report_evidence():
    scenario = _scenario("agency_couple")
    report_data = _valid_report_data()
    report_data["risks"] = []
    report_data["budget_confidence"]["verification_items"] = []
    report_data["quote_policy"]["verification_required"] = []
    report_data["tool_audit_summary"]["pending_checks"] = []

    closure = build_acceptance_evidence_closure(
        scenario=scenario,
        report_data=report_data,
        snapshot_path=".runtime/evaluations/snapshot.json",
    )

    assert closure["passed"] is False
    assert "risk" in closure["missing"]
    assert "verification_items" in closure["missing"]


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
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 0,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "ok",
                    "estimated_input_tokens": 1,
                    "estimated_output_tokens": 2,
                    "estimated_total_tokens": 3,
                },
            },
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
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 0,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "ok",
                    "estimated_input_tokens": 1,
                    "estimated_output_tokens": 2,
                    "estimated_total_tokens": 3,
                },
            },
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
    assert run_summary["evidence_closure"]["result_count"] == 0
    assert "RAG（检索增强生成）" in markdown
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()


def test_acceptance_gate_marks_runtime_warnings_as_degraded():
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
            {"type": "token", "content": "hello", "turn_index": 1, "elapsed_since_scenario_start": 6},
            {"type": "report_data", "turn_index": 1},
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 0,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "ok",
                    "estimated_input_tokens": 1,
                    "estimated_output_tokens": 2,
                    "estimated_total_tokens": 3,
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 8.5}],
        assistant_text="hello",
        report_data=report_data,
        report_evaluation=report_evaluation,
        elapsed_seconds=8.5,
        timeout_seconds=900.0,
        runtime_budget=runtime_budget_for_scenario(
            EvaluationScenario(
                id="warn",
                name="Warn",
                category="agency_plan",
                prompt="Plan",
                expected_mode="agency_plan",
                min_score=80,
                focus=["contract"],
                tags=["agency"],
                runtime_budget={
                    "max_total_elapsed_seconds": 10,
                    "warning_total_elapsed_ratio": 0.5,
                },
            )
        ),
    )

    gate = build_acceptance_gate_result(
        scenario=scenario,
        quality_summary=quality_summary,
        report_data=report_data,
    )

    assert gate["status"] == "degraded"
    assert gate["passed"] is False
    assert gate["dimensions"]["runtime_budget"]["status"] == "degraded"
    assert gate["degradations"][0]["dimension"] == "runtime_budget"


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
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 0,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "ok",
                    "estimated_input_tokens": 1,
                    "estimated_output_tokens": 2,
                    "estimated_total_tokens": 3,
                },
            },
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


def test_preflight_blocks_requested_llm_judge_without_real_credentials():
    scenario = EvaluationScenario(
        id="offline_judge",
        name="Offline judge",
        category="snapshot",
        prompt="Plan a trip",
        expected_mode="agency_plan",
        min_score=80,
        focus=["judge"],
        tags=["agency"],
        requirements={"real_llm": False},
    )

    preflight = run_acceptance_preflight(
        [scenario],
        base_url="http://127.0.0.1:8000",
        environ={},
        check_backend=False,
        require_llm_judge=True,
    )

    assert preflight.status == "blocked"
    assert "llm_judge" in preflight.missing_required
    assert "llm_judge" in preflight.skipped_metrics


def test_preflight_declares_scenario_capability_requirements():
    scenario = _scenario("agency_couple")

    capabilities = required_capabilities_for_scenarios([scenario])

    assert capabilities["real_llm"] is True
    assert capabilities["real_mcp"] is True
    assert "weather" in capabilities["mcp_servers"]
    assert {"amap", "tavily"}.issubset(capabilities["external_apis"])


def test_preflight_service_table_blocks_required_mcp_without_credentials():
    scenario = EvaluationScenario(
        id="hotel_required",
        name="Hotel Required",
        category="agency_plan",
        prompt="Plan a trip",
        expected_mode="agency_plan",
        min_score=80,
        focus=["hotel"],
        tags=["agency"],
        requirements={
            "real_llm": False,
            "real_mcp": True,
            "mcp_servers": ["aigohotel-mcp"],
            "external_apis": [],
        },
    )

    preflight = run_acceptance_preflight(
        [scenario],
        base_url="http://127.0.0.1:8000",
        environ={},
        check_backend=False,
    )
    real_mcp = next(check for check in preflight.checks if check.key == "real_mcp")

    assert preflight.status == "blocked"
    assert "real_mcp" in preflight.missing_required
    assert preflight.mcp_services["aigohotel-mcp"]["status"] == "blocked"
    assert real_mcp.details["services"]["aigohotel-mcp"]["status"] == "blocked"


def test_backend_ready_degraded_by_unselected_mcp_can_pass_selected_smoke(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "status": "degraded",
                    "degraded_optional": ["mcp"],
                    "services": {
                        "mcp": {
                            "servers": {
                                "weather": {"status": "healthy"},
                                "search": {"status": "healthy"},
                                "amap": {"status": "unavailable"},
                            }
                        }
                    },
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        "app.evaluation.preflight.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    check = _check_backend_ready(
        "http://127.0.0.1:8000",
        required_mcp_servers=["weather", "search"],
    )

    assert check.status == "passed"
    assert "outside the selected scenario set" in check.findings[0]


def test_backend_ready_blocks_when_service_health_marks_selected_mcp_degraded(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "status": "ready",
                    "services": {
                        "mcp": {
                            "service_health": {
                                "weather": {"status": "healthy"},
                                "search": {
                                    "status": "degraded",
                                    "reason": "Missing real value for one of: TAVILY_API_KEY",
                                },
                            }
                        }
                    },
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        "app.evaluation.preflight.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    check = _check_backend_ready(
        "http://127.0.0.1:8000",
        required_mcp_servers=["weather", "search"],
    )

    assert check.status == "blocked"
    assert "search=degraded" in check.findings[0]
    assert check.details["mcp_services"]["search"]["status"] == "degraded"


def test_backend_ready_blocks_when_selected_mcp_is_unavailable(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "status": "degraded",
                    "degraded_optional": ["mcp"],
                    "services": {
                        "mcp": {
                            "servers": {
                                "weather": {"status": "healthy"},
                                "amap": {"status": "unavailable"},
                            }
                        }
                    },
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        "app.evaluation.preflight.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    check = _check_backend_ready(
        "http://127.0.0.1:8000",
        required_mcp_servers=["weather", "amap"],
    )

    assert check.status == "blocked"
    assert "amap" in check.findings[0]


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


def test_live_dependency_errors_are_classified_as_blocked():
    error = RuntimeError("Missing real value for one of: DASHSCOPE_API_KEY")

    assert _classify_live_error_status(error, events=[]) == "blocked"
    assert _classify_live_error_status(RuntimeError("report_data missing"), events=[{"type": "token"}]) == "failed"


def test_live_timeout_writes_redacted_partial_snapshot(monkeypatch, tmp_path: Path):
    scenario = _scenario("slow_timeout")

    class SlowClient:
        def __init__(self, base_url: str, timeout_seconds: float = 900.0):
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        def post_json(self, path, payload, *, token=None, timeout_seconds=None):
            if path.endswith("/login"):
                return {"access_token": "token"}
            return {"id": "conversation-id"}

        def stream_json_events(self, path, payload, *, token, timeout_seconds=None):
            time.sleep(0.02)
            yield {"type": "token", "content": "hello 13800138000"}

    monkeypatch.setattr("app.evaluation.live_runner.EvaluationApiClient", SlowClient)

    result = run_live_scenario(
        scenario,
        LiveRunConfig(
            base_url=DEFAULT_BASE_URL,
            output_dir=tmp_path,
            timeout_seconds=1.0,
            scenario_timeout_seconds=0.001,
        ),
    )

    assert result.status == "failed"
    assert result.failure_category == "timeout"
    assert result.snapshot_path is not None
    snapshot_text = Path(result.snapshot_path).read_text(encoding="utf-8")
    assert "13800138000" not in snapshot_text
    assert "[REDACTED]" in snapshot_text


def test_live_session_busy_is_classified_without_waiting_for_all_followups(monkeypatch, tmp_path: Path):
    scenario = _scenario("busy_conversation")

    class BusyClient:
        def __init__(self, base_url: str, timeout_seconds: float = 900.0):
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        def post_json(self, path, payload, *, token=None, timeout_seconds=None):
            if path.endswith("/login"):
                return {"access_token": "token"}
            return {"id": "conversation-id"}

        def stream_json_events(self, path, payload, *, token, timeout_seconds=None):
            yield {
                "type": "session_busy",
                "message": "Conversation is busy for test@example.com",
            }

    monkeypatch.setattr("app.evaluation.live_runner.EvaluationApiClient", BusyClient)

    result = run_live_scenario(
        scenario,
        LiveRunConfig(
            output_dir=tmp_path,
            timeout_seconds=1.0,
            scenario_timeout_seconds=1.0,
        ),
    )

    assert result.status == "failed"
    assert result.failure_category == "conversation_busy"
    assert result.snapshot_path is not None
    assert "test@example.com" not in Path(result.snapshot_path).read_text(encoding="utf-8")


def test_failure_category_prefers_runtime_budget_and_evidence_closure():
    runtime_gate = {
        "passed": False,
        "dimensions": {
            "runtime_budget": {"passed": False},
        },
        "failures": [{"dimension": "runtime_budget", "findings": ["too slow"]}],
    }
    evidence_closure = {
        "passed": False,
        "missing": ["verification_items"],
        "checks": {"verification_items": False},
    }

    assert classify_live_failure_category(acceptance_gate=runtime_gate) == "runtime_budget"
    assert classify_live_failure_category(evidence_closure=evidence_closure) == "evidence_closure"


def test_partial_summary_files_include_run_context_and_failure_categories(tmp_path: Path):
    scenarios = [_scenario("finished"), _scenario("pending")]
    result = _build_live_error_result(
        scenarios[0],
        error="Global timeout after api_key=sk-testvalue123456789",
        failure_category="global_timeout",
    )

    summary, paths = _build_and_optionally_write_summary(
        results=[result],
        scenarios=scenarios,
        base_url=DEFAULT_BASE_URL,
        output_dir=tmp_path,
        preflight={"status": "passed", "checks": []},
        write_files=True,
        prefix="partial",
        partial_reason="global_timeout",
    )
    serialized = json.dumps(summary, ensure_ascii=False)
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert summary["run_context"]["partial"] is True
    assert summary["run_context"]["partial_reason"] == "global_timeout"
    assert summary["run_context"]["pending_scenario_ids"] == ["pending"]
    assert summary["run_context"]["failure_classification_counts"] == {"global_timeout": 1}
    assert _failure_classification_counts([result]) == {"global_timeout": 1}
    assert Path(paths["json"]).exists()
    assert "partial summary（部分摘要）" in markdown
    assert "sk-testvalue123456789" not in serialized + markdown


def test_blocked_preflight_summary_cannot_pass_acceptance(tmp_path: Path):
    scenario = _scenario("agency_couple")
    preflight = run_acceptance_preflight(
        [scenario],
        base_url="http://127.0.0.1:8000",
        environ={},
        check_backend=False,
    ).to_dict()
    blocked_gate = build_error_acceptance_gate_result(
        scenario=scenario,
        error="Preflight blocked live acceptance",
        status="blocked",
    )

    summary = build_acceptance_run_summary(
        results=[
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "status": "blocked",
                "passed": False,
                "acceptance_gate": blocked_gate,
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
    assert summary["blocked_count"] == 1
    assert any(failure["dimension"] == "environment_dependencies" for failure in summary["failures"])
    assert "指标不可判定" in markdown


def test_degraded_preflight_summary_remains_degraded(tmp_path: Path):
    scenario = _scenario("agency_couple")
    preflight = {
        "status": "degraded",
        "checks": [
            {
                "key": "backend_ready",
                "label": "Backend ready health endpoint",
                "status": "degraded",
                "findings": ["optional MCP service degraded"],
            }
        ],
        "missing_required": [],
        "degraded_optional": ["backend_ready"],
        "skipped_metrics": [],
    }
    skipped_gate = build_skipped_acceptance_gate_result(
        scenario=scenario,
        reason="Preflight-only degraded",
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

    assert summary["status"] == "degraded"
    assert summary["degraded_count"] == 0
    assert summary["degradations"][0]["dimension"] == "environment_dependencies"


def test_acceptance_smoke_scenarios_select_minimal_live_contract():
    scenarios = acceptance_smoke_scenarios()
    pricing_smoke = next(
        scenario
        for scenario in scenarios
        if scenario.id == "pricing_agency_quote_explanation"
    )

    assert scenarios
    assert all(ACCEPTANCE_SMOKE_TAG in scenario.tags for scenario in scenarios)
    assert any(scenario.id == "pricing_agency_quote_explanation" for scenario in scenarios)
    assert all(scenario.expected_mode == "agency_plan" for scenario in scenarios)
    assert all(scenario.requirements.get("real_llm") is True for scenario in scenarios)
    assert all(scenario.requirements.get("real_mcp") is True for scenario in scenarios)
    assert any(
        "省心" in scenario.prompt and ("费用" in scenario.prompt or "报价" in scenario.name)
        for scenario in scenarios
    )
    assert "2026-06-20" in pricing_smoke.prompt
    assert "人均预算1500-2500元" in pricing_smoke.prompt
    assert any("高铁" in followup for followup in pricing_smoke.followups)
    assert any("舒适型酒店" in followup for followup in pricing_smoke.followups)
    assert any("本地小吃加特色餐厅" in followup for followup in pricing_smoke.followups)
    assert pricing_smoke.requirements["mcp_servers"] == ["weather", "search"]
    assert pricing_smoke.runtime_budget["max_first_token_seconds"] == 90
    assert pricing_smoke.runtime_budget["warning_first_token_ratio"] == 0.99
    assert pricing_smoke.runtime_budget["max_tool_call_count"] == 36
    assert pricing_smoke.runtime_budget["warning_tool_call_ratio"] == 0.99
    budget = runtime_budget_for_scenario(pricing_smoke)
    assert budget.warning_first_token_ratio == 0.99
    assert budget.max_tool_call_count == 36
    assert budget.warning_tool_call_ratio == 0.99
    assert any("report_data" in followup for followup in pricing_smoke.followups)


def test_acceptance_smoke_scenarios_require_agency_quote_coverage():
    scenario = EvaluationScenario(
        id="smoke_without_quote",
        name="Smoke without quote",
        category="free_planning",
        prompt="周末自由行两天。",
        expected_mode="free_planning",
        min_score=80,
        focus=["route"],
        tags=[ACCEPTANCE_SMOKE_TAG, "free"],
        requirements={"real_llm": True, "real_mcp": True},
    )

    with pytest.raises(ValueError, match="quote or budget explanation"):
        acceptance_smoke_scenarios([scenario], min_count=1)


def test_cli_json_payload_surfaces_preflight_blockers_and_health_checks():
    preflight = {
        "status": "blocked",
        "missing_required": ["runtime_config", "backend_ready"],
        "degraded_optional": [],
        "checks": [
            {
                "key": "runtime_config",
                "label": "Runtime config readiness matrix",
                "status": "blocked",
                "required": True,
                "findings": ["Missing api_key=sk-testvalue123456789 for test@example.com"],
                "env_vars": ["DASHSCOPE_API_KEY"],
                "suggestion": "Set real credentials.",
            },
            {
                "key": "backend_ready",
                "label": "Backend ready health endpoint",
                "status": "blocked",
                "required": True,
                "findings": ["Bearer eyJabcdefgh.ijklmnopqr.stuvwxyz12 rejected"],
                "env_vars": [],
                "suggestion": "Start backend.",
            },
        ],
    }

    payload = build_cli_json_payload(
        results=[],
        acceptance_summary=None,
        summary_paths=None,
        preflight=preflight,
    )
    serialized = str(payload)

    assert payload["status"] == "blocked"
    assert payload["passed"] is False
    assert payload["missing_required"] == ["runtime_config", "backend_ready"]
    assert [item["key"] for item in payload["health_checks"]] == ["backend_ready"]
    assert [item["key"] for item in payload["blocking_reasons"]] == [
        "runtime_config",
        "backend_ready",
    ]
    assert "test@example.com" not in serialized
    assert "sk-testvalue123456789" not in serialized
    assert "eyJabcdefgh.ijklmnopqr.stuvwxyz12" not in serialized


def test_cli_json_payload_keeps_degraded_preflight_from_passing_without_summary():
    payload = build_cli_json_payload(
        results=[{"scenario_id": "smoke", "status": "passed", "passed": True}],
        acceptance_summary=None,
        summary_paths=None,
        preflight={
            "status": "degraded",
            "missing_required": [],
            "degraded_optional": ["backend_ready"],
            "checks": [],
        },
    )

    assert payload["status"] == "degraded"
    assert payload["passed"] is False


def test_cli_json_payload_preflight_blocked_overrides_stale_passed_summary():
    payload = build_cli_json_payload(
        results=[{"scenario_id": "smoke", "status": "passed", "passed": True}],
        acceptance_summary={"status": "passed", "passed": True},
        summary_paths=None,
        preflight={
            "status": "blocked",
            "missing_required": ["real_llm"],
            "degraded_optional": [],
            "checks": [
                {
                    "key": "real_llm",
                    "label": "Real LLM provider",
                    "status": "blocked",
                    "required": True,
                    "findings": ["Missing real value for one of: DASHSCOPE_API_KEY"],
                }
            ],
        },
    )

    assert payload["status"] == "blocked"
    assert payload["passed"] is False
    assert payload["missing_required"] == ["real_llm"]


def test_acceptance_artifact_dirs_must_stay_under_runtime(tmp_path: Path):
    inside = Path(".runtime") / "evaluations"

    assert _require_runtime_artifact_dir(inside, flag_name="--output-dir") == inside
    assert _require_runtime_artifact_dir(
        RUNTIME_ARTIFACT_ROOT / "smoke",
        flag_name="--summary-dir",
    ) == RUNTIME_ARTIFACT_ROOT / "smoke"
    with pytest.raises(ValueError, match="inside"):
        _require_runtime_artifact_dir(tmp_path, flag_name="--output-dir")


def test_acceptance_summary_redacts_sensitive_report_text(tmp_path: Path):
    scenario = EvaluationScenario(
        id="sensitive_summary",
        name="Sensitive Summary",
        category="agency_plan",
        prompt="请联系 test@example.com，手机号 13800138000",
        expected_mode="agency_plan",
        min_score=80,
        focus=["contract"],
        tags=["agency"],
    )
    gate = build_error_acceptance_gate_result(
        scenario=scenario,
        error="authorization=Bearer eyJabcdefgh.ijklmnopqr.stuvwxyz12 failed",
        status="blocked",
    )

    summary = build_acceptance_run_summary(
        results=[
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "status": "blocked",
                "passed": False,
                "runtime_metrics": {"estimated_total_tokens": 120},
                "acceptance_gate": gate,
            }
        ],
        scenarios=[scenario],
        base_url="http://127.0.0.1:8000",
        output_dir=tmp_path,
    )
    markdown = render_acceptance_markdown(summary)
    serialized = str(summary) + markdown

    assert summary["runtime_totals"]["estimated_total_tokens"] == 120
    assert "test@example.com" not in serialized
    assert "13800138000" not in serialized
    assert "eyJabcdefgh.ijklmnopqr.stuvwxyz12" not in serialized
