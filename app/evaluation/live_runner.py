"""Live evaluation runner for scenario-based report quality checks."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.evaluation.acceptance_gate import (
    build_acceptance_gate_result,
    build_error_acceptance_gate_result,
)
from app.evaluation.agent_metrics import evaluate_agent_metrics
from app.evaluation.rag_quality import evaluate_rag_quality
from app.evaluation.report_quality import evaluate_report_quality
from app.evaluation.llm_judge import DEFAULT_LLM_JUDGE_THRESHOLD, evaluate_llm_judge
from app.evaluation.runtime_metrics import (
    DEFAULT_RUNTIME_BUDGET,
    RuntimeBudget,
    collect_runtime_metrics,
    evaluate_runtime_metrics,
    runtime_budget_from_dict,
)
from app.evaluation.scenarios import EvaluationScenario
from app.evaluation.tool_quality import evaluate_tool_quality, extract_tool_events
from app.utils.security import redact_sensitive_data, redact_sensitive_text


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT_DIR = Path(".runtime") / "evaluations"
DEFAULT_FINALIZE_FOLLOWUPS = [
    (
        "\u4ee5\u4e0a\u9700\u6c42\u786e\u8ba4\u65e0\u8bef\uff0c"
        "\u8bf7\u5148\u8bb0\u5f55\u9700\u6c42\uff0c\u7136\u540e\u7ee7\u7eed\u63a8\u8fdb\u89c4\u5212\u3002"
    ),
    (
        "\u76ee\u7684\u5730\u5c31\u6309\u4f60\u63a8\u8350\u7684\u6700\u5408\u9002\u65b9\u6848\u786e\u8ba4\uff1b"
        "\u5982\u679c\u6211\u5df2\u7ecf\u7ed9\u4e86\u76ee\u7684\u5730\uff0c\u5c31\u786e\u8ba4\u8be5\u76ee\u7684\u5730\u3002"
    ),
    (
        "\u4ea4\u901a\u6309\u7701\u5fc3\u548c\u65f6\u95f4\u5408\u7406\u4f18\u5148\uff0c"
        "\u8bf7\u76f4\u63a5\u8bb0\u5f55\u4f60\u63a8\u8350\u7684\u65b9\u5f0f\uff1b"
        "\u5b9e\u65f6\u73ed\u6b21\u548c\u4ef7\u683c\u6807\u6ce8\u5f85\u6838\u9a8c\u3002"
    ),
    (
        "\u4f4f\u5bbf\u6309\u7701\u5fc3\u3001\u5e72\u51c0\u3001\u52a8\u7ebf\u65b9\u4fbf"
        "\u7684\u65b9\u6848\u8bb0\u5f55\uff1b\u5982\u679c\u6ca1\u6709\u771f\u5b9e\u9501\u4ef7\uff0c"
        "\u8bf7\u6807\u6ce8\u5f85\u6838\u9a8c\u3002"
    ),
    (
        "\u9910\u996e\u6309\u672c\u5730\u7279\u8272\u548c\u8f7b\u677e\u8282\u594f\u5b89\u6392\uff0c"
        "\u8bf7\u76f4\u63a5\u8bb0\u5f55\u63a8\u8350\u65b9\u5411\u3002"
    ),
    (
        "\u8bf7\u751f\u6210\u5e76\u8bb0\u5f55\u6700\u7ec8\u884c\u7a0b\uff0c"
        "\u5929\u6570\u5fc5\u987b\u548c\u9700\u6c42\u4e00\u81f4\u3002"
    ),
    (
        "\u8bf7\u6c47\u603b\u9884\u7b97\uff0c\u5305\u542b\u4ea4\u901a\u3001"
        "\u4f4f\u5bbf\u3001\u9910\u996e\u3001\u666f\u70b9\u4f53\u9a8c\u548c"
        "\u5176\u4ed6\u673a\u52a8\u8d39\u7528\u3002"
    ),
    (
        "\u4fe1\u606f\u786e\u8ba4\uff0c\u8bf7\u6309\u5f53\u524d\u4fe1\u606f\u76f4\u63a5"
        "\u751f\u6210\u6700\u7ec8\u65c5\u6e38\u89c4\u5212\u62a5\u544a\uff1b"
        "\u5982\u679c\u8fd8\u6709\u7ec6\u8282\u4e0d\u786e\u5b9a\uff0c\u8bf7\u57fa\u4e8e"
        "\u5e38\u89c4\u65c5\u884c\u793e\u7ecf\u9a8c\u5408\u7406\u5047\u8bbe\uff0c"
        "\u5e76\u5728\u62a5\u544a\u4e2d\u6807\u6ce8\u5f85\u6838\u9a8c\u9879\u3002"
    )
]


@dataclass(frozen=True)
class LiveRunConfig:
    base_url: str = DEFAULT_BASE_URL
    username: str = "test"
    password: str = "000000"
    output_dir: Path = DEFAULT_OUTPUT_DIR
    timeout_seconds: float = 900.0
    scenario_timeout_seconds: float | None = 900.0
    conversation_title_prefix: str = "eval"
    runtime_budget: RuntimeBudget = DEFAULT_RUNTIME_BUDGET
    enable_llm_judge: bool = False
    llm_judge_threshold: float = DEFAULT_LLM_JUDGE_THRESHOLD


@dataclass
class LiveScenarioResult:
    scenario_id: str
    scenario_name: str
    passed: bool
    normalized_score: float | None
    grade: str | None
    snapshot_path: str | None
    elapsed_seconds: float
    status: str = "failed"
    agent_score: float | None = None
    runtime_budget_passed: bool | None = None
    runtime_findings: list[str] | None = None
    runtime_metrics: dict[str, Any] | None = None
    first_token_seconds: float | None = None
    tool_call_count: int | None = None
    tool_counts: dict[str, int] | None = None
    agent_metrics: dict[str, Any] | None = None
    evidence_closure: dict[str, Any] | None = None
    acceptance_gate: dict[str, Any] | None = None
    failure_category: str | None = None
    failure_details: list[str] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveScenarioTimeoutError(RuntimeError):
    """Raised when one evaluation scenario exceeds its scenario-level deadline."""

    failure_category = "timeout"


class LiveScenarioConversationBusyError(RuntimeError):
    """Raised when the backend rejects a turn because the conversation lock is busy."""

    failure_category = "conversation_busy"


def select_scenarios(
    scenarios: Iterable[EvaluationScenario],
    scenario_ids: Iterable[str] | None,
) -> list[EvaluationScenario]:
    """Return selected scenarios, preserving catalog order."""

    all_scenarios = list(scenarios)
    if not scenario_ids:
        return all_scenarios

    wanted = list(scenario_ids)
    by_id = {scenario.id: scenario for scenario in all_scenarios}
    missing = [scenario_id for scenario_id in wanted if scenario_id not in by_id]
    if missing:
        raise KeyError(f"Unknown evaluation scenario ids: {', '.join(missing)}")
    return [scenario for scenario in all_scenarios if scenario.id in set(wanted)]


def parse_sse_event_line(line: bytes) -> dict[str, Any] | None:
    """Parse one SSE data line emitted by the chat endpoint."""

    text = line.decode("utf-8", errors="replace").strip()
    if not text.startswith("data:"):
        return None
    payload = text.removeprefix("data:").strip()
    if not payload:
        return None
    return json.loads(payload)


def _scenario_deadline(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None:
        return None
    if timeout_seconds <= 0:
        raise ValueError("scenario_timeout_seconds must be positive or None")
    return time.perf_counter() + float(timeout_seconds)


def _remaining_deadline_seconds(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return deadline - time.perf_counter()


def _request_timeout_seconds(
    *,
    configured_timeout_seconds: float,
    deadline: float | None,
    scenario_id: str,
) -> float:
    remaining = _remaining_deadline_seconds(deadline)
    if remaining is None:
        return configured_timeout_seconds
    if remaining <= 0:
        raise LiveScenarioTimeoutError(
            f"Scenario {scenario_id} exceeded timeout budget before the next request"
        )
    return max(0.001, min(float(configured_timeout_seconds), remaining))


def _raise_if_scenario_deadline_exceeded(
    *,
    deadline: float | None,
    scenario_id: str,
    timeout_seconds: float | None,
) -> None:
    remaining = _remaining_deadline_seconds(deadline)
    if remaining is not None and remaining <= 0:
        raise LiveScenarioTimeoutError(
            f"Scenario {scenario_id} exceeded timeout budget {timeout_seconds}s"
        )


def _is_timeout_exception(exc: BaseException) -> bool:
    message = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timed out" in message or "timeout" in message


def _is_transient_llm_api_error_event(event: dict[str, Any]) -> bool:
    if not isinstance(event, dict):
        return False
    if str(event.get("type") or event.get("event") or "") != "error":
        return False
    error_type = str(event.get("error_type") or "").lower()
    message = str(event.get("message") or event.get("content") or "").lower()
    if "apiconnectionerror" in error_type or "api connection error" in message:
        return True
    if "api connection" in error_type or "llm_api_connection" in error_type:
        return True
    return False


def _mark_recovered_runtime_errors(
    events: list[dict[str, Any]],
    *,
    report_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Tag transient LLM API connection errors recovered before final report_data."""

    if not isinstance(report_data, dict) or not report_data:
        return events
    report_indexes = [
        index
        for index, event in enumerate(events)
        if isinstance(event, dict)
        and str(event.get("type") or event.get("event") or "") == "report_data"
    ]
    if not report_indexes:
        return events
    first_report_index = min(report_indexes)
    marked_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if index < first_report_index and _is_transient_llm_api_error_event(event):
            marked_events.append(
                {
                    **event,
                    "recovered": True,
                    "recovery_category": "transient_llm_api_connection",
                    "recovery_status": "final_report_data_produced",
                }
            )
        else:
            marked_events.append(event)
    return marked_events


def _has_conversation_busy_event(events: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(event, dict)
        and str(event.get("type") or event.get("event") or "") == "session_busy"
        for event in events
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _agency_evidence_categories(report_data: dict[str, Any] | None) -> list[str]:
    report = _as_dict(report_data)
    agency_context = _as_dict(report.get("agency_context"))
    categories: set[str] = set()
    for item in _as_list(agency_context.get("evidence")):
        evidence = _as_dict(item)
        if evidence.get("source_type") == "agency_internal" and _has_text(evidence.get("category")):
            categories.add(str(evidence["category"]).strip())
    for category, value in _as_dict(agency_context.get("categories")).items():
        if _has_text(category) and value:
            categories.add(str(category).strip())
    bundle_categories = _as_dict(_as_dict(report.get("evidence_bundle")).get("agency_categories"))
    for category, value in bundle_categories.items():
        if _has_text(category) and isinstance(value, (int, float)) and value > 0:
            categories.add(str(category).strip())
    return sorted(categories)


def build_acceptance_evidence_closure(
    *,
    scenario: EvaluationScenario,
    report_data: dict[str, Any] | None,
    snapshot_path: str | None = None,
    require_snapshot: bool = True,
) -> dict[str, Any]:
    """Summarize the live evidence that makes an acceptance result auditable."""

    report = _as_dict(report_data)
    budget = _as_dict(report.get("budget"))
    budget_confidence = _as_dict(report.get("budget_confidence"))
    quote_policy = _as_dict(report.get("quote_policy"))
    tool_audit = _as_dict(report.get("tool_audit_summary"))
    agency_categories = _agency_evidence_categories(report_data)
    verification_items = [
        *_as_list(budget_confidence.get("verification_items")),
        *_as_list(quote_policy.get("verification_required")),
        *_as_list(tool_audit.get("pending_checks")),
    ]

    checks = {
        "snapshot": bool(snapshot_path) if require_snapshot else True,
        "report_data": bool(report),
        "budget": bool(_as_list(budget.get("items"))) or bool(budget.get("total")),
        "budget_confidence": (
            _has_text(budget_confidence.get("level"))
            and bool(
                _as_list(budget_confidence.get("confirmed_items"))
                or _as_list(budget_confidence.get("estimated_items"))
            )
        ),
        "risk": bool(_as_list(report.get("risks"))),
        "verification_items": bool(verification_items),
        "agency_business_evidence": (
            len(agency_categories) >= 3
            if scenario.expected_mode == "agency_plan"
            else True
        ),
    }
    missing = [key for key, passed in checks.items() if not passed]
    return {
        "version": "acceptance_evidence_closure.v1",
        "scenario_id": scenario.id,
        "expected_mode": scenario.expected_mode,
        "passed": not missing,
        "checks": checks,
        "missing": missing,
        "agency_evidence_categories": agency_categories,
        "verification_item_count": len(verification_items),
        "snapshot_path": snapshot_path,
    }


def build_snapshot_payload(
    *,
    scenario: EvaluationScenario,
    conversation: dict[str, Any],
    events: list[dict[str, Any]],
    assistant_text: str,
    report_data: dict[str, Any] | None,
    evaluation: dict[str, Any] | None,
    elapsed_seconds: float,
    base_url: str,
    turns: list[dict[str, Any]] | None = None,
    quality_summary: dict[str, Any] | None = None,
    llm_judge_evaluation: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON artifact saved after a live scenario run."""

    tool_events = [record.to_dict() for record in extract_tool_events(events)]
    observability_events = [
        event.get("observability")
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "turn_observability"
        and isinstance(event.get("observability"), dict)
    ]
    payload = {
        "version": "evaluation_live_snapshot.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "scenario": scenario.to_dict(),
        "conversation": conversation,
        "summary": {
            "elapsed_seconds": round(elapsed_seconds, 2),
            "event_count": len(events),
            "assistant_chars": len(assistant_text),
            "has_report_data": report_data is not None,
            "has_quality_summary": quality_summary is not None,
            "has_llm_judge": llm_judge_evaluation is not None,
            "has_turn_observability": bool(observability_events),
            "evaluation": evaluation,
            "quality_summary": quality_summary,
            "llm_judge": llm_judge_evaluation,
            "tool_event_count": len(tool_events),
            "observability_event_count": len(observability_events),
            "error": error,
        },
        "turns": turns or [],
        "assistant_text": assistant_text,
        "report_data": report_data,
        "tool_events": tool_events,
        "turn_observability": observability_events,
        "quality_summary": quality_summary,
        "llm_judge": llm_judge_evaluation,
        "evidence_closure": build_acceptance_evidence_closure(
            scenario=scenario,
            report_data=report_data,
            snapshot_path=None,
            require_snapshot=False,
        ),
        "observability_events": observability_events,
        "events": events,
    }
    return redact_sensitive_data(payload)


def snapshot_path_for(
    scenario: EvaluationScenario,
    output_dir: Path,
    *,
    now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in scenario.id)
    return output_dir / f"{timestamp}-{safe_id}.json"


class EvaluationApiClient:
    """Small stdlib HTTP client for the local FastAPI evaluation flow."""

    def __init__(self, base_url: str, timeout_seconds: float = 900.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        request = self._request(path, payload, token=token)
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds or self.timeout_seconds,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def stream_json_events(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str,
        timeout_seconds: float | None = None,
    ) -> Iterable[dict[str, Any]]:
        request = self._request(path, payload, token=token)
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds or self.timeout_seconds,
        ) as response:
            for line in response:
                event = parse_sse_event_line(line)
                if event is not None:
                    yield event

    def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None = None,
    ) -> urllib.request.Request:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )


def _login(
    client: EvaluationApiClient,
    username: str,
    password: str,
    *,
    timeout_seconds: float | None = None,
) -> str:
    payload = client.post_json(
        "/api/v1/users/login",
        {"username": username, "password": password},
        timeout_seconds=timeout_seconds,
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Login response did not contain access_token")
    return token


def _create_conversation(
    client: EvaluationApiClient,
    token: str,
    scenario: EvaluationScenario,
    title_prefix: str,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    title = f"{title_prefix}: {scenario.id}"
    return client.post_json(
        "/api/v1/conversations",
        {"title": title},
        token=token,
        timeout_seconds=timeout_seconds,
    )


def scenario_message_sequence(scenario: EvaluationScenario) -> list[str]:
    """Return the first prompt plus follow-up messages used to reach a report."""

    followups = scenario.followups or DEFAULT_FINALIZE_FOLLOWUPS
    return [scenario.prompt, *followups]


def infer_tool_policy_from_scenario(scenario: EvaluationScenario) -> dict[str, Any]:
    """Infer a lightweight tool policy from scenario tags for snapshot scoring."""

    tags = set(scenario.tags)
    expected_tools: set[str] = set()
    forbidden_tools: set[str] = set()

    if "hotel" in tags:
        expected_tools.add("query_hotel_options")
    if "transport" in tags:
        expected_tools.add("query_transport_options")
    if "weather" in tags or "destination" in tags:
        expected_tools.add("query_destination_info")
    if "free" in tags and "budget" in tags and "transport" not in tags and "hotel" not in tags:
        forbidden_tools.update({"query_hotel_options", "query_transport_options"})

    return {
        "expected_tools": expected_tools,
        "forbidden_tools": forbidden_tools,
        "requires_fallback": bool({"fallback", "risk", "weather"} & tags),
        "max_duplicate_calls": 1,
    }


def runtime_budget_for_scenario(
    scenario: EvaluationScenario,
    *,
    base_budget: RuntimeBudget | None = None,
) -> RuntimeBudget:
    """Return the deterministic runtime budget for one evaluation scenario."""

    budget = base_budget or DEFAULT_RUNTIME_BUDGET
    tags = set(scenario.tags)
    category = scenario.category.lower()
    if "long-context" in tags or "long_conversation" in category:
        budget = runtime_budget_from_dict(
            {
                "max_total_elapsed_seconds": 1200,
                "max_first_token_seconds": 90,
                "max_tool_call_count": 45,
                "max_estimated_total_tokens": 180000,
            },
            base=budget,
        )
    if {"hotel", "transport", "weather", "fallback"} & tags:
        budget = runtime_budget_from_dict(
            {
                "max_tool_call_count": max(budget.max_tool_call_count, 36),
            },
            base=budget,
        )
    if scenario.runtime_budget:
        budget = runtime_budget_from_dict(scenario.runtime_budget, base=budget)
    return budget


def _classify_live_error_status(exc: BaseException, *, events: list[dict[str, Any]]) -> str:
    """Classify live-run failures without hiding real environment blockers."""

    if isinstance(exc, (LiveScenarioTimeoutError, LiveScenarioConversationBusyError)):
        return "failed"
    if _has_conversation_busy_event(events):
        return "failed"
    if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403, 502, 503, 504}:
        return "blocked"
    if isinstance(exc, urllib.error.URLError) and not events:
        return "blocked"
    if events and _is_timeout_exception(exc):
        return "failed"

    message = str(exc).lower()
    blocked_markers = (
        "connection refused",
        "network is unreachable",
        "no route to host",
        "name or service not known",
        "nodename nor servname",
        "missing real value",
        "not configured",
        "credential",
        "api key",
        "api_key",
        "access_token",
        "health endpoint",
        "dependency",
    )
    if any(marker in message for marker in blocked_markers):
        return "blocked"
    return "failed"


def classify_live_failure_category(
    *,
    exc: BaseException | None = None,
    events: list[dict[str, Any]] | None = None,
    acceptance_gate: dict[str, Any] | None = None,
    evidence_closure: dict[str, Any] | None = None,
) -> str | None:
    """Return a stable failure bucket for machine summaries and runbooks."""

    event_records = events or []
    if exc is not None:
        explicit_category = getattr(exc, "failure_category", None)
        if isinstance(explicit_category, str) and explicit_category:
            return explicit_category
        if _is_timeout_exception(exc):
            return "timeout"
    if _has_conversation_busy_event(event_records):
        return "conversation_busy"

    gate = acceptance_gate or {}
    dimensions = _as_dict(gate.get("dimensions"))
    failures = _as_list(gate.get("failures"))
    failed_dimensions = {
        str(failure.get("dimension"))
        for failure in failures
        if isinstance(failure, dict) and failure.get("dimension")
    }
    failed_dimensions.update(
        key
        for key, value in dimensions.items()
        if isinstance(value, dict) and value.get("passed") is False
    )
    if "runtime_budget" in failed_dimensions:
        return "runtime_budget"
    if "runtime_quality" in failed_dimensions:
        return "runtime_budget"
    if "agent_industrial_metrics" in failed_dimensions:
        return "agent_industrial_metrics"

    closure = evidence_closure or {}
    if closure and closure.get("passed") is False:
        return "evidence_closure"

    if gate and gate.get("passed") is False:
        return "acceptance_gate"
    return None


def _failure_details_from_category(
    *,
    category: str | None,
    acceptance_gate: dict[str, Any] | None = None,
    evidence_closure: dict[str, Any] | None = None,
    error: str | None = None,
) -> list[str] | None:
    details: list[str] = []
    if error:
        details.append(redact_sensitive_text(error))
    if category == "runtime_budget":
        for failure in _as_list(_as_dict(acceptance_gate).get("failures")):
            if isinstance(failure, dict) and failure.get("dimension") in {
                "runtime_budget",
                "runtime_quality",
            }:
                details.extend(str(item) for item in _as_list(failure.get("findings")))
    elif category == "agent_industrial_metrics":
        for failure in _as_list(_as_dict(acceptance_gate).get("failures")):
            if isinstance(failure, dict) and failure.get("dimension") == "agent_industrial_metrics":
                details.extend(str(item) for item in _as_list(failure.get("findings")))
    elif category == "evidence_closure":
        missing = _as_list(_as_dict(evidence_closure).get("missing"))
        if missing:
            details.append("evidence_closure missing: " + ", ".join(str(item) for item in missing))
    return [redact_sensitive_text(item) for item in details[:5]] or None


def _partial_runtime_metrics_dict(
    *,
    events: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    assistant_text: str,
    elapsed_seconds: float,
) -> dict[str, Any] | None:
    """Return best-effort runtime metrics for failed or interrupted scenarios."""

    if not events and not turns and not assistant_text:
        return None
    return collect_runtime_metrics(
        events=events,
        turns=turns,
        assistant_text=assistant_text,
        elapsed_seconds=elapsed_seconds,
    ).to_dict()


def build_quality_summary(
    *,
    scenario: EvaluationScenario,
    events: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    assistant_text: str,
    report_data: dict[str, Any],
    report_evaluation: dict[str, Any],
    elapsed_seconds: float,
    timeout_seconds: float,
    runtime_budget: RuntimeBudget | None = None,
    llm_judge_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the combined Agent run quality score saved in live snapshots."""

    events = _mark_recovered_runtime_errors(events, report_data=report_data)
    tool_policy = infer_tool_policy_from_scenario(scenario)
    scenario_runtime_budget = runtime_budget or runtime_budget_for_scenario(
        scenario,
        base_budget=runtime_budget_from_dict(
            {"max_total_elapsed_seconds": timeout_seconds},
            base=DEFAULT_RUNTIME_BUDGET,
        ),
    )
    rag_result = evaluate_rag_quality(
        report_data,
        expected_mode=scenario.expected_mode,
        pass_threshold=80.0,
    ).to_dict()
    tool_result = evaluate_tool_quality(
        events,
        report_data=report_data,
        expected_tools=tool_policy["expected_tools"],
        forbidden_tools=tool_policy["forbidden_tools"],
        max_duplicate_calls=tool_policy["max_duplicate_calls"],
        requires_fallback=tool_policy["requires_fallback"],
        pass_threshold=80.0,
    ).to_dict()
    metrics = collect_runtime_metrics(
        events=events,
        turns=turns,
        assistant_text=assistant_text,
        elapsed_seconds=elapsed_seconds,
    )
    runtime_result = evaluate_runtime_metrics(
        metrics,
        budget=scenario_runtime_budget,
        tool_counts=tool_result["tool_counts"],
        redundant_calls=tool_result["redundant_calls"],
        pass_threshold=80.0,
    ).to_dict()
    agent_metrics_result = evaluate_agent_metrics(
        events,
        scenario=scenario,
        report_data=report_data,
        assistant_text=assistant_text,
        pass_threshold=80.0,
    ).to_dict()
    weighted_score = round(
        report_evaluation["normalized_score"] * 0.5
        + rag_result["normalized_score"] * 0.2
        + tool_result["normalized_score"] * 0.2
        + runtime_result["normalized_score"] * 0.1,
        2,
    )
    aggregate = {
        "version": "agent_quality_summary.v1",
        "normalized_score": weighted_score,
        "passed": (
            bool(report_evaluation.get("passed"))
            and rag_result["passed"]
            and tool_result["passed"]
            and runtime_result["passed"]
            and weighted_score >= scenario.min_score
        ),
        "weights": {
            "report_quality": 0.5,
            "rag_quality": 0.2,
            "tool_quality": 0.2,
            "runtime_quality": 0.1,
        },
    }
    summary = {
        "version": "agent_quality_summary.v1",
        "aggregate": aggregate,
        "report_quality": report_evaluation,
        "rag_quality": rag_result,
        "tool_quality": tool_result,
        "runtime_quality": runtime_result,
        "agent_metrics": agent_metrics_result,
        "runtime_metrics": metrics.to_dict(),
        "runtime_governance": runtime_result["governance_summary"],
        "tool_policy": {
            "expected_tools": sorted(tool_policy["expected_tools"]),
            "forbidden_tools": sorted(tool_policy["forbidden_tools"]),
            "max_duplicate_calls": tool_policy["max_duplicate_calls"],
            "requires_fallback": tool_policy["requires_fallback"],
        },
    }
    if llm_judge_evaluation is not None:
        summary["llm_judge"] = llm_judge_evaluation
    return summary


def run_live_scenario(
    scenario: EvaluationScenario,
    config: LiveRunConfig,
) -> LiveScenarioResult:
    """Run one scenario through the live API and save a scored snapshot."""

    started_at = time.perf_counter()
    deadline = _scenario_deadline(config.scenario_timeout_seconds)
    client = EvaluationApiClient(config.base_url, timeout_seconds=config.timeout_seconds)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    assistant_parts: list[str] = []
    report_data: dict[str, Any] | None = None
    conversation: dict[str, Any] = {}

    try:
        token = _login(
            client,
            config.username,
            config.password,
            timeout_seconds=_request_timeout_seconds(
                configured_timeout_seconds=config.timeout_seconds,
                deadline=deadline,
                scenario_id=scenario.id,
            ),
        )
        _raise_if_scenario_deadline_exceeded(
            deadline=deadline,
            scenario_id=scenario.id,
            timeout_seconds=config.scenario_timeout_seconds,
        )
        conversation = _create_conversation(
            client,
            token,
            scenario,
            config.conversation_title_prefix,
            timeout_seconds=_request_timeout_seconds(
                configured_timeout_seconds=config.timeout_seconds,
                deadline=deadline,
                scenario_id=scenario.id,
            ),
        )
        _raise_if_scenario_deadline_exceeded(
            deadline=deadline,
            scenario_id=scenario.id,
            timeout_seconds=config.scenario_timeout_seconds,
        )
        conversation_id = conversation.get("id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise RuntimeError("Conversation response did not contain id")

        for turn_index, user_message in enumerate(scenario_message_sequence(scenario), start=1):
            _raise_if_scenario_deadline_exceeded(
                deadline=deadline,
                scenario_id=scenario.id,
                timeout_seconds=config.scenario_timeout_seconds,
            )
            turn_started_at = time.perf_counter()
            turn_assistant_parts: list[str] = []
            turn_event_count_before = len(events)
            turn_error: str | None = None
            turn_observability: dict[str, Any] | None = None

            try:
                for event in client.stream_json_events(
                    f"/api/v1/chat/stream/{conversation_id}",
                    {"content": user_message},
                    token=token,
                    timeout_seconds=_request_timeout_seconds(
                        configured_timeout_seconds=config.timeout_seconds,
                        deadline=deadline,
                        scenario_id=scenario.id,
                    ),
                ):
                    event_with_turn = {
                        **event,
                        "turn_index": turn_index,
                        "elapsed_since_scenario_start": round(time.perf_counter() - started_at, 3),
                        "elapsed_since_turn_start": round(time.perf_counter() - turn_started_at, 3),
                    }
                    events.append(event_with_turn)
                    event_type = event.get("type")
                    if event_type == "token":
                        content = event.get("content")
                        if isinstance(content, str):
                            assistant_parts.append(content)
                            turn_assistant_parts.append(content)
                    elif event_type == "report_data" and isinstance(event.get("report_data"), dict):
                        report_data = event["report_data"]
                    elif event_type == "turn_observability" and isinstance(
                        event.get("observability"),
                        dict,
                    ):
                        turn_observability = event["observability"]
                    elif event_type == "session_busy":
                        turn_error = redact_sensitive_text(
                            str(
                                event.get("message")
                                or "Conversation is busy and the scenario cannot continue"
                            )
                        )
                        raise LiveScenarioConversationBusyError(turn_error)
                    elif event_type == "error":
                        turn_error = redact_sensitive_text(
                            str(event.get("message") or "SSE error event")
                        )
                        break
                    elif event_type == "done":
                        break
                    _raise_if_scenario_deadline_exceeded(
                        deadline=deadline,
                        scenario_id=scenario.id,
                        timeout_seconds=config.scenario_timeout_seconds,
                    )
            except (urllib.error.URLError, OSError) as exc:
                if _is_timeout_exception(exc):
                    raise LiveScenarioTimeoutError(
                        f"Scenario {scenario.id} exceeded timeout budget "
                        f"{config.scenario_timeout_seconds}s: {redact_sensitive_text(str(exc))}"
                    ) from exc
                turn_error = redact_sensitive_text(str(exc))

            turn_events = events[turn_event_count_before:]
            turns.append(
                {
                    "turn_index": turn_index,
                    "user_message": user_message,
                    "assistant_chars": len("".join(turn_assistant_parts)),
                    "event_count": len(events) - turn_event_count_before,
                    "tool_call_count": sum(1 for event in turn_events if event.get("type") == "tool_call"),
                    "elapsed_seconds": round(time.perf_counter() - turn_started_at, 2),
                    "produced_report_data": report_data is not None,
                    "observability": turn_observability,
                    "error": turn_error,
                }
            )
            if report_data is not None:
                break

        if report_data is None:
            last_error = next((turn.get("error") for turn in reversed(turns) if turn.get("error")), None)
            message = "Live scenario did not produce structured report_data"
            if last_error:
                message = (
                    f"{message}; last turn error: "
                    f"{redact_sensitive_text(str(last_error))}"
                )
            raise RuntimeError(message)

        evaluation = evaluate_report_quality(
            report_data,
            expected_mode=scenario.expected_mode,
            pass_threshold=scenario.min_score,
        ).to_dict()
        events = _mark_recovered_runtime_errors(events, report_data=report_data)
        assistant_text = "".join(assistant_parts)
        elapsed_seconds = time.perf_counter() - started_at
        quality_summary = build_quality_summary(
            scenario=scenario,
            events=events,
            turns=turns,
            assistant_text=assistant_text,
            report_data=report_data,
            report_evaluation=evaluation,
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=config.timeout_seconds,
            runtime_budget=runtime_budget_for_scenario(
                scenario,
                base_budget=config.runtime_budget,
            ),
        )
        llm_judge_evaluation = None
        if config.enable_llm_judge:
            llm_judge_evaluation = evaluate_llm_judge(
                report_data=report_data,
                scenario=scenario.to_dict(),
                deterministic_evaluation=evaluation,
                assistant_text=assistant_text,
                enabled=True,
                threshold=config.llm_judge_threshold,
                manual_review=scenario.manual_review,
            ).to_dict()
            quality_summary["llm_judge"] = llm_judge_evaluation
        snapshot = build_snapshot_payload(
            scenario=scenario,
            conversation=conversation,
            events=events,
            assistant_text=assistant_text,
            report_data=report_data,
            evaluation=evaluation,
            elapsed_seconds=elapsed_seconds,
            base_url=config.base_url,
            turns=turns,
            quality_summary=quality_summary,
            llm_judge_evaluation=llm_judge_evaluation,
        )
        path = snapshot_path_for(scenario, config.output_dir)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        acceptance_gate = build_acceptance_gate_result(
            scenario=scenario,
            quality_summary=quality_summary,
            report_data=report_data,
            snapshot_path=str(path),
            llm_judge_evaluation=llm_judge_evaluation,
        )
        evidence_closure = build_acceptance_evidence_closure(
            scenario=scenario,
            report_data=report_data,
            snapshot_path=str(path),
        )
        failure_category = classify_live_failure_category(
            events=events,
            acceptance_gate=acceptance_gate,
            evidence_closure=evidence_closure,
        )
        failure_details = _failure_details_from_category(
            category=failure_category,
            acceptance_gate=acceptance_gate,
            evidence_closure=evidence_closure,
        )
        effective_passed = bool(acceptance_gate["passed"]) and bool(evidence_closure["passed"])
        effective_status = str(acceptance_gate["status"])
        if not effective_passed and effective_status == "passed":
            effective_status = "failed"
        runtime_metrics = _as_dict(quality_summary.get("runtime_metrics"))

        return LiveScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=effective_passed,
            normalized_score=float(evaluation["normalized_score"]),
            grade=str(evaluation["grade"]),
            snapshot_path=str(path),
            elapsed_seconds=round(elapsed_seconds, 2),
            status=effective_status,
            agent_score=float(quality_summary["aggregate"]["normalized_score"]),
            runtime_budget_passed=bool(
                quality_summary["runtime_quality"]["budget_gate"]["passed"]
            ),
            runtime_findings=[
                *quality_summary["runtime_quality"]["budget_gate"]["violations"],
                *quality_summary["runtime_quality"]["budget_gate"]["warnings"],
            ][:5],
            runtime_metrics=runtime_metrics,
            first_token_seconds=(
                float(runtime_metrics["first_token_seconds"])
                if isinstance(runtime_metrics.get("first_token_seconds"), (int, float))
                else None
            ),
            tool_call_count=(
                int(runtime_metrics["tool_call_count"])
                if isinstance(runtime_metrics.get("tool_call_count"), int)
                else None
            ),
            tool_counts=quality_summary["tool_quality"]["tool_counts"],
            agent_metrics=quality_summary["agent_metrics"],
            evidence_closure=evidence_closure,
            acceptance_gate=acceptance_gate,
            failure_category=failure_category,
            failure_details=failure_details,
        )
    except (
        LiveScenarioTimeoutError,
        LiveScenarioConversationBusyError,
        urllib.error.URLError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        elapsed_seconds = time.perf_counter() - started_at
        snapshot_path: str | None = None
        partial_runtime_metrics = _partial_runtime_metrics_dict(
            events=events,
            turns=turns,
            assistant_text="".join(assistant_parts),
            elapsed_seconds=elapsed_seconds,
        )
        if events or turns:
            snapshot = build_snapshot_payload(
                scenario=scenario,
                conversation=conversation,
                events=events,
                assistant_text="".join(assistant_parts),
                report_data=report_data,
                evaluation=None,
                elapsed_seconds=elapsed_seconds,
                base_url=config.base_url,
                turns=turns,
                error=redact_sensitive_text(str(exc)),
            )
            path = snapshot_path_for(scenario, config.output_dir)
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            snapshot_path = str(path)
        status = _classify_live_error_status(exc, events=events)
        failure_category = classify_live_failure_category(exc=exc, events=events)
        failure_details = _failure_details_from_category(
            category=failure_category,
            error=str(exc),
        )
        acceptance_gate = build_error_acceptance_gate_result(
            scenario=scenario,
            error=redact_sensitive_text(str(exc)),
            snapshot_path=snapshot_path,
            status=status,
        )
        acceptance_gate["failure_category"] = failure_category
        return LiveScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=False,
            normalized_score=None,
            grade=None,
            snapshot_path=snapshot_path,
            elapsed_seconds=round(elapsed_seconds, 2),
            status=str(acceptance_gate["status"]),
            runtime_metrics=partial_runtime_metrics,
            first_token_seconds=(
                float(partial_runtime_metrics["first_token_seconds"])
                if isinstance(
                    _as_dict(partial_runtime_metrics).get("first_token_seconds"),
                    (int, float),
                )
                else None
            ),
            tool_call_count=(
                int(partial_runtime_metrics["tool_call_count"])
                if isinstance(
                    _as_dict(partial_runtime_metrics).get("tool_call_count"),
                    int,
                )
                else None
            ),
            evidence_closure=build_acceptance_evidence_closure(
                scenario=scenario,
                report_data=report_data,
                snapshot_path=snapshot_path,
            ),
            acceptance_gate=acceptance_gate,
            failure_category=failure_category,
            failure_details=failure_details,
            error=redact_sensitive_text(str(exc)),
        )
