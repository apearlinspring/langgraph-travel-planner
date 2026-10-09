import json
from types import SimpleNamespace

import pytest

from app.evaluation.llm_judge import (
    DEFAULT_LLM_JUDGE_RUBRIC,
    build_llm_judge_input,
    build_manual_review_record,
    evaluate_llm_judge,
)
from app.evaluation.acceptance_gate import build_acceptance_gate_result
from app.evaluation.scenarios import EvaluationScenario
from tests.test_report_quality_evaluation import _valid_report_data


class _FakeJudgeModel:
    def __init__(self, response: dict):
        self.response = response
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=json.dumps(self.response, ensure_ascii=False))


def _real_key_env() -> dict[str, str]:
    return {"DASHSCOPE_API_KEY": "dashscope-live-value-abcdef123456"}


def test_llm_judge_is_skipped_by_default_without_model_call(monkeypatch):
    def fail_build_chat_model(**kwargs):  # pragma: no cover - should not be called
        raise AssertionError("model should not be created when judge is disabled")

    monkeypatch.setattr("app.evaluation.llm_judge.build_chat_model", fail_build_chat_model)

    result = evaluate_llm_judge(
        report_data=_valid_report_data(),
        enabled=False,
        environ={},
    ).to_dict()

    assert result["status"] == "skipped"
    assert result["enabled"] is False
    assert result["passed"] is False
    assert result["normalized_score"] is None


def test_llm_judge_blocks_missing_real_api_key(monkeypatch):
    def fail_build_chat_model(**kwargs):  # pragma: no cover - should not be called
        raise AssertionError("model should not be created without a real key")

    monkeypatch.setattr("app.evaluation.llm_judge.build_chat_model", fail_build_chat_model)

    result = evaluate_llm_judge(
        report_data=_valid_report_data(),
        enabled=True,
        environ={"DASHSCOPE_API_KEY": "test-key-placeholder"},
    ).to_dict()

    assert result["status"] == "blocked"
    assert result["passed"] is False
    assert "DASHSCOPE_API_KEY" in result["metadata"]["required_env_vars"]


def test_llm_judge_uses_mocked_factory_and_redacts_input_output(monkeypatch):
    report_data = _valid_report_data()
    report_data["traveler_phone"] = "13800138000"
    deterministic = {
        "normalized_score": 100,
        "summary": ["Contact test@example.com before departure."],
    }
    fake_model = _FakeJudgeModel(
        {
            "overall_score": 88,
            "passed": True,
            "summary": ["Ready for consultant review."],
            "strengths": ["Clear route and agency boundaries."],
            "concerns": ["Call 13800138000 to confirm details."],
            "recommendations": ["Email test@example.com with final package."],
            "factuality_notes": ["No live inventory was invented."],
            "scores": {
                item.key: {"score": 18, "reason": "Solid"}
                for item in DEFAULT_LLM_JUDGE_RUBRIC
            },
        }
    )

    monkeypatch.setattr(
        "app.evaluation.llm_judge.build_chat_model",
        lambda **kwargs: fake_model,
    )
    monkeypatch.setattr(
        "app.evaluation.llm_judge.resolve_model_name",
        lambda **kwargs: "qwen-report-mock",
    )

    result = evaluate_llm_judge(
        report_data=report_data,
        scenario={"id": "agency_couple", "prompt": "Plan for 13800138000"},
        deterministic_evaluation=deterministic,
        assistant_text="Traveler email is test@example.com",
        enabled=True,
        threshold=80,
        environ=_real_key_env(),
        manual_review={"reviewer_id": "qa@example.com", "labels": ["pilot"]},
    ).to_dict()
    serialized_result = json.dumps(result, ensure_ascii=False)
    serialized_prompt = json.dumps(fake_model.messages, ensure_ascii=False)

    assert result["status"] == "passed"
    assert result["normalized_score"] == 88
    assert result["metadata"]["supplemental_only"] is True
    assert result["manual_review"]["reviewer_id"] == "[REDACTED]"
    assert "13800138000" not in serialized_prompt
    assert "test@example.com" not in serialized_prompt
    assert "13800138000" not in serialized_result
    assert "test@example.com" not in serialized_result


def test_llm_judge_malformed_response_is_failed_not_passed(monkeypatch):
    class BadModel:
        def invoke(self, messages):
            return SimpleNamespace(content="not json")

    monkeypatch.setattr("app.evaluation.llm_judge.build_chat_model", lambda **kwargs: BadModel())

    result = evaluate_llm_judge(
        report_data=_valid_report_data(),
        enabled=True,
        environ=_real_key_env(),
    ).to_dict()

    assert result["status"] == "failed"
    assert result["passed"] is False
    assert result["normalized_score"] is None
    assert any("LLM judge failed" in item for item in result["findings"])


def test_build_llm_judge_input_redacts_sensitive_values():
    payload = build_llm_judge_input(
        scenario={"id": "s1", "prompt": "Phone 13800138000"},
        report_data={"api_key": "sk-testvalue123456789", "note": "Email test@example.com"},
        deterministic_evaluation={"summary": ["Call 13800138000"]},
    )
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["version"] == "llm_judge_input.v1"
    assert "sk-testvalue123456789" not in serialized
    assert "13800138000" not in serialized
    assert "test@example.com" not in serialized


def test_manual_review_record_validates_future_dataset_fields():
    record = build_manual_review_record(
        {
            "status": "reviewed",
            "reviewer_id": "lead@example.com",
            "overall_score": 91,
            "decision": "accept",
            "labels": ["agency", "golden"],
            "dataset_candidate": True,
            "corrections": ["No correction"],
        }
    ).to_dict()

    assert record["status"] == "reviewed"
    assert record["reviewer_id"] == "[REDACTED]"
    assert record["overall_score"] == 91
    assert record["dataset_candidate"] is True


def test_scenario_accepts_optional_manual_review_fields():
    scenario = EvaluationScenario(
        id="manual-ready",
        name="Manual ready",
        category="agency_plan",
        prompt="Plan a trip",
        expected_mode="agency_plan",
        min_score=80,
        focus=["manual"],
        tags=["agency"],
        manual_review={"status": "not_reviewed", "dataset_candidate": True},
    )

    assert scenario.to_dict()["manual_review"]["dataset_candidate"] is True


def test_manual_review_rejects_invalid_score():
    with pytest.raises(ValueError, match="overall_score"):
        build_manual_review_record({"overall_score": 101})


def test_failed_llm_judge_does_not_override_deterministic_acceptance_gate():
    scenario = EvaluationScenario(
        id="agency",
        name="Agency",
        category="agency_plan",
        prompt="Plan",
        expected_mode="agency_plan",
        min_score=80,
        focus=["quality"],
        tags=["agency"],
    )
    passed_quality = {
        "aggregate": {"normalized_score": 100, "passed": True},
        "report_quality": {"normalized_score": 100, "passed": True, "summary": [], "criteria": []},
        "rag_quality": {"normalized_score": 100, "passed": True, "summary": [], "criteria": []},
        "tool_quality": {"normalized_score": 100, "passed": True, "summary": [], "criteria": []},
        "runtime_quality": {
            "normalized_score": 100,
            "passed": True,
            "summary": [],
            "criteria": [],
            "budget_gate": {"passed": True, "violations": [], "warnings": []},
        },
        "runtime_metrics": {"turn_observability_event_count": 1},
        "agent_metrics": {
            "version": "agent_industrial_metrics.v1",
            "normalized_score": 100,
            "passed": True,
            "summary": [],
            "criteria": [],
            "unsupported_claims": {
                "unsupported_claim_rate": 0.0,
                "unsupported_claim_count": 0,
            },
            "metric_values": {
                "intent_accuracy": 1.0,
                "tool_call_precision": 1.0,
                "tool_call_recall": 1.0,
                "stage_transition_accuracy": 1.0,
                "unsupported_claim_rate": 0.0,
            },
        },
    }
    llm_judge = {
        "status": "failed",
        "passed": False,
        "normalized_score": 42,
        "threshold": 80,
        "findings": ["Tone is too generic."],
    }

    gate = build_acceptance_gate_result(
        scenario=scenario,
        quality_summary=passed_quality,
        report_data=_valid_report_data(),
        llm_judge_evaluation=llm_judge,
    )

    assert gate["passed"] is True
    assert gate["status"] == "passed"
    assert gate["supplemental_dimensions"]["llm_judge"]["status"] == "failed"
    assert gate["failures"] == []
