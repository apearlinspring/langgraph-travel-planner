"""Optional LLM-as-Judge evaluation for travel report acceptance artifacts."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.config import has_real_env_value, load_effective_environment
from app.utils.llm_factory import build_chat_model, resolve_model_name
from app.utils.security import redact_sensitive_data, redact_sensitive_text


LLM_JUDGE_VERSION = "llm_judge_evaluation.v1"
LLM_JUDGE_INPUT_VERSION = "llm_judge_input.v1"
LLM_JUDGE_ENV_VARS = ("DASHSCOPE_API_KEY",)
LLM_JUDGE_STATUSES = {"passed", "failed", "blocked", "skipped"}
DEFAULT_LLM_JUDGE_THRESHOLD = 80.0


@dataclass(frozen=True)
class LLMJudgeRubricItem:
    """One qualitative rubric dimension scored by the judge model."""

    key: str
    label: str
    max_score: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManualReviewRecord:
    """Reserved human review fields for future supervised evaluation datasets."""

    status: str = "not_reviewed"
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    overall_score: float | None = None
    decision: str | None = None
    notes: str = ""
    labels: list[str] = field(default_factory=list)
    dataset_candidate: bool = False
    corrections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return redact_sensitive_data(asdict(self))


@dataclass
class LLMJudgeEvaluationResult:
    """Serializable optional judge result that never gates deterministic checks."""

    version: str
    status: str
    enabled: bool
    passed: bool
    normalized_score: float | None
    threshold: float
    model_profile: str
    model_name: str | None
    rubric: list[LLMJudgeRubricItem]
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    factuality_notes: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    manual_review: ManualReviewRecord = field(default_factory=ManualReviewRecord)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rubric"] = [item.to_dict() for item in self.rubric]
        payload["manual_review"] = self.manual_review.to_dict()
        return redact_sensitive_data(payload)


DEFAULT_LLM_JUDGE_RUBRIC = [
    LLMJudgeRubricItem(
        key="business_alignment",
        label="Business alignment",
        max_score=20,
        description=(
            "Does the report match the requested travel mode, user constraints, "
            "confirmed preferences, and agency service boundaries?"
        ),
    ),
    LLMJudgeRubricItem(
        key="factual_faithfulness",
        label="Factual faithfulness",
        max_score=20,
        description=(
            "Does the report avoid inventing real prices, inventory, weather, "
            "contacts, payment links, or unsupported external facts?"
        ),
    ),
    LLMJudgeRubricItem(
        key="deliverability",
        label="Deliverability",
        max_score=20,
        description=(
            "Is the output ready for a consultant handoff with route, budget, "
            "verification items, and export-friendly structure?"
        ),
    ),
    LLMJudgeRubricItem(
        key="risk_communication",
        label="Risk communication",
        max_score=20,
        description=(
            "Are risks, Plan B choices, pending checks, and uncertainty expressed "
            "clearly without overstating confidence?"
        ),
    ),
    LLMJudgeRubricItem(
        key="agency_professionalism",
        label="Agency professionalism",
        max_score=20,
        description=(
            "Does the answer sound like a professional travel agency consultant "
            "rather than a generic chatbot response?"
        ),
    ),
]


def build_manual_review_record(payload: Mapping[str, Any] | None = None) -> ManualReviewRecord:
    """Normalize optional manual review metadata without storing PII."""

    if payload is None:
        return ManualReviewRecord()
    if not isinstance(payload, Mapping):
        raise TypeError("manual_review must be a mapping")

    labels = payload.get("labels") or []
    corrections = payload.get("corrections") or []
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("manual_review.labels must be a string list")
    if not isinstance(corrections, list) or not all(isinstance(item, str) for item in corrections):
        raise ValueError("manual_review.corrections must be a string list")

    score = payload.get("overall_score")
    if score is not None:
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            raise ValueError("manual_review.overall_score must be between 0 and 100")
        score = round(float(score), 2)

    return ManualReviewRecord(
        status=str(payload.get("status") or "not_reviewed"),
        reviewer_id=(
            redact_sensitive_text(str(payload["reviewer_id"]))
            if payload.get("reviewer_id") is not None
            else None
        ),
        reviewed_at=(
            redact_sensitive_text(str(payload["reviewed_at"]))
            if payload.get("reviewed_at") is not None
            else None
        ),
        overall_score=score,
        decision=(
            redact_sensitive_text(str(payload["decision"]))
            if payload.get("decision") is not None
            else None
        ),
        notes=redact_sensitive_text(str(payload.get("notes") or "")),
        labels=[redact_sensitive_text(item) for item in labels],
        dataset_candidate=bool(payload.get("dataset_candidate", False)),
        corrections=[redact_sensitive_text(item) for item in corrections],
    )


def llm_judge_skipped_result(
    *,
    reason: str = "LLM judge is disabled by default.",
    threshold: float = DEFAULT_LLM_JUDGE_THRESHOLD,
    manual_review: Mapping[str, Any] | None = None,
) -> LLMJudgeEvaluationResult:
    """Return the default skipped result without touching any model provider."""

    return LLMJudgeEvaluationResult(
        version=LLM_JUDGE_VERSION,
        status="skipped",
        enabled=False,
        passed=False,
        normalized_score=None,
        threshold=threshold,
        model_profile="report",
        model_name=None,
        rubric=DEFAULT_LLM_JUDGE_RUBRIC,
        findings=[redact_sensitive_text(reason)],
        manual_review=build_manual_review_record(manual_review),
        metadata={"supplemental_only": True},
    )


def _blocked_result(
    *,
    reason: str,
    threshold: float,
    manual_review: Mapping[str, Any] | None,
) -> LLMJudgeEvaluationResult:
    return LLMJudgeEvaluationResult(
        version=LLM_JUDGE_VERSION,
        status="blocked",
        enabled=True,
        passed=False,
        normalized_score=None,
        threshold=threshold,
        model_profile="report",
        model_name=None,
        rubric=DEFAULT_LLM_JUDGE_RUBRIC,
        findings=[redact_sensitive_text(reason)],
        manual_review=build_manual_review_record(manual_review),
        metadata={
            "supplemental_only": True,
            "required_env_vars": list(LLM_JUDGE_ENV_VARS),
        },
    )


def _effective_env_has_judge_key(
    *,
    environ: Mapping[str, str] | None,
    dotenv_path: Path | None,
) -> bool:
    env, _ = load_effective_environment(environ=environ, dotenv_path=dotenv_path)
    return any(has_real_env_value(env.get(name)) for name in LLM_JUDGE_ENV_VARS)


def _as_redacted_list(value: Any, *, limit: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    return [
        redact_sensitive_text(str(item)).strip()
        for item in items[:limit]
        if str(item).strip()
    ]


def _clip_text(value: Any, *, limit: int = 4000) -> Any:
    if isinstance(value, str):
        text = redact_sensitive_text(value)
        return text if len(text) <= limit else text[:limit] + "...[truncated]"
    if isinstance(value, dict):
        return {str(key): _clip_text(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip_text(item, limit=limit) for item in value[:80]]
    return value


def build_llm_judge_input(
    *,
    scenario: Mapping[str, Any] | None,
    report_data: Mapping[str, Any],
    deterministic_evaluation: Mapping[str, Any] | None = None,
    assistant_text: str = "",
) -> dict[str, Any]:
    """Build the redacted input payload sent to the judge model."""

    payload = {
        "version": LLM_JUDGE_INPUT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario or {},
        "report_data": report_data,
        "deterministic_evaluation": deterministic_evaluation or {},
        "assistant_text_excerpt": assistant_text[:6000],
        "rubric": [item.to_dict() for item in DEFAULT_LLM_JUDGE_RUBRIC],
        "instructions": {
            "supplemental_only": True,
            "do_not_override_deterministic_gate": True,
            "do_not_invent_facts": True,
        },
    }
    return redact_sensitive_data(_clip_text(payload))


def _judge_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    rubric_lines = "\n".join(
        f"- {item.key}: 0-{int(item.max_score)} points. {item.description}"
        for item in DEFAULT_LLM_JUDGE_RUBRIC
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a strict LLM-as-Judge evaluator for Chinese travel-agency "
                "planning reports. Return JSON only. Do not expose personal data, "
                "credentials, contact details, or raw hidden inputs."
            ),
        },
        {
            "role": "user",
            "content": (
                "Evaluate the redacted travel planning artifact using this rubric:\n"
                f"{rubric_lines}\n\n"
                "Return a JSON object with: overall_score, passed, summary, strengths, "
                "concerns, recommendations, factuality_notes, and scores. The scores "
                "object must contain each rubric key with score and reason. Treat this "
                "as supplemental feedback only; never claim the deterministic gate passed "
                "or failed because of your score.\n\n"
                f"Redacted evaluation input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
            ),
        },
    ]


def _content_to_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Judge response must be a JSON object")
    return payload


def _normalize_score(value: Any, *, max_score: float) -> float | None:
    raw_score = value.get("score") if isinstance(value, dict) else value
    if not isinstance(raw_score, (int, float)):
        return None
    score = float(raw_score)
    if score < 0:
        return 0.0
    if score > max_score:
        return max_score
    return round(score, 2)


def _normalize_scores(payload: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, Mapping):
        raw_scores = {}
    scores: dict[str, dict[str, Any]] = {}
    findings: list[str] = []
    for item in DEFAULT_LLM_JUDGE_RUBRIC:
        raw_item = raw_scores.get(item.key)
        score = _normalize_score(raw_item, max_score=item.max_score)
        reason = ""
        if isinstance(raw_item, Mapping):
            reason = str(raw_item.get("reason") or raw_item.get("rationale") or "")
        if score is None:
            findings.append(f"Judge response missing numeric score for {item.key}")
            score = 0.0
        scores[item.key] = {
            "score": score,
            "max_score": item.max_score,
            "ratio": round(score / item.max_score, 4) if item.max_score else 0.0,
            "reason": redact_sensitive_text(reason),
        }
    return scores, findings


def _result_from_payload(
    payload: Mapping[str, Any],
    *,
    threshold: float,
    model_name: str,
    manual_review: Mapping[str, Any] | None,
) -> LLMJudgeEvaluationResult:
    scores, findings = _normalize_scores(payload)
    total_score = round(sum(item["score"] for item in scores.values()), 2)
    max_score = round(sum(item.max_score for item in DEFAULT_LLM_JUDGE_RUBRIC), 2)
    normalized = round(total_score / max_score * 100, 2) if max_score else 0.0
    if isinstance(payload.get("overall_score"), (int, float)):
        normalized = round(max(0.0, min(float(payload["overall_score"]), 100.0)), 2)
    passed = normalized >= threshold and not findings
    if payload.get("passed") is False:
        passed = False
    if normalized < threshold:
        findings.insert(0, f"LLM judge score {normalized} is below threshold {threshold}")
    status = "passed" if passed else "failed"
    return LLMJudgeEvaluationResult(
        version=LLM_JUDGE_VERSION,
        status=status,
        enabled=True,
        passed=passed,
        normalized_score=normalized,
        threshold=threshold,
        model_profile="report",
        model_name=redact_sensitive_text(model_name),
        rubric=DEFAULT_LLM_JUDGE_RUBRIC,
        scores=scores,
        summary=_as_redacted_list(payload.get("summary"), limit=5),
        strengths=_as_redacted_list(payload.get("strengths"), limit=5),
        concerns=_as_redacted_list(payload.get("concerns"), limit=8),
        recommendations=_as_redacted_list(payload.get("recommendations"), limit=8),
        factuality_notes=_as_redacted_list(payload.get("factuality_notes"), limit=8),
        findings=findings[:10],
        manual_review=build_manual_review_record(manual_review),
        metadata={"supplemental_only": True, "total_score": total_score, "max_score": max_score},
    )


def evaluate_llm_judge(
    *,
    report_data: Mapping[str, Any],
    scenario: Mapping[str, Any] | None = None,
    deterministic_evaluation: Mapping[str, Any] | None = None,
    assistant_text: str = "",
    enabled: bool = False,
    threshold: float = DEFAULT_LLM_JUDGE_THRESHOLD,
    manual_review: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> LLMJudgeEvaluationResult:
    """Run the optional judge model, returning skipped/blocked when unavailable."""

    if not enabled:
        return llm_judge_skipped_result(threshold=threshold, manual_review=manual_review)
    if not isinstance(report_data, Mapping):
        raise TypeError("report_data must be a mapping")
    if not 0 <= threshold <= 100:
        raise ValueError("threshold must be between 0 and 100")
    if not _effective_env_has_judge_key(environ=environ, dotenv_path=dotenv_path):
        return _blocked_result(
            reason="LLM judge requested but no real DASHSCOPE_API_KEY is configured.",
            threshold=threshold,
            manual_review=manual_review,
        )

    redacted_input = build_llm_judge_input(
        scenario=scenario,
        report_data=report_data,
        deterministic_evaluation=deterministic_evaluation,
        assistant_text=assistant_text,
    )
    model_name = resolve_model_name(profile="report")
    try:
        model = build_chat_model(
            profile="report",
            temperature=0,
            max_tokens=1600,
            streaming=False,
        )
        response = model.invoke(_judge_messages(redacted_input))
        payload = redact_sensitive_data(_extract_json_object(_content_to_text(response)))
        return _result_from_payload(
            payload,
            threshold=threshold,
            model_name=model_name,
            manual_review=manual_review,
        )
    except Exception as exc:  # pragma: no cover - exercised through integration paths.
        return LLMJudgeEvaluationResult(
            version=LLM_JUDGE_VERSION,
            status="failed",
            enabled=True,
            passed=False,
            normalized_score=None,
            threshold=threshold,
            model_profile="report",
            model_name=redact_sensitive_text(model_name),
            rubric=DEFAULT_LLM_JUDGE_RUBRIC,
            findings=[f"LLM judge failed: {redact_sensitive_text(str(exc))}"],
            manual_review=build_manual_review_record(manual_review),
            metadata={"supplemental_only": True},
        )
