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

from app.evaluation.report_quality import evaluate_report_quality
from app.evaluation.scenarios import EvaluationScenario


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
    conversation_title_prefix: str = "eval"


@dataclass
class LiveScenarioResult:
    scenario_id: str
    scenario_name: str
    passed: bool
    normalized_score: float | None
    grade: str | None
    snapshot_path: str | None
    elapsed_seconds: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON artifact saved after a live scenario run."""

    return {
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
            "evaluation": evaluation,
            "error": error,
        },
        "turns": turns or [],
        "assistant_text": assistant_text,
        "report_data": report_data,
        "events": events,
    }


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
    ) -> dict[str, Any]:
        request = self._request(path, payload, token=token)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def stream_json_events(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str,
    ) -> Iterable[dict[str, Any]]:
        request = self._request(path, payload, token=token)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
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


def _login(client: EvaluationApiClient, username: str, password: str) -> str:
    payload = client.post_json(
        "/api/v1/users/login",
        {"username": username, "password": password},
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
) -> dict[str, Any]:
    title = f"{title_prefix}: {scenario.id}"
    return client.post_json("/api/v1/conversations", {"title": title}, token=token)


def scenario_message_sequence(scenario: EvaluationScenario) -> list[str]:
    """Return the first prompt plus follow-up messages used to reach a report."""

    followups = scenario.followups or DEFAULT_FINALIZE_FOLLOWUPS
    return [scenario.prompt, *followups]


def run_live_scenario(
    scenario: EvaluationScenario,
    config: LiveRunConfig,
) -> LiveScenarioResult:
    """Run one scenario through the live API and save a scored snapshot."""

    started_at = time.perf_counter()
    client = EvaluationApiClient(config.base_url, timeout_seconds=config.timeout_seconds)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    assistant_parts: list[str] = []
    report_data: dict[str, Any] | None = None
    conversation: dict[str, Any] = {}

    try:
        token = _login(client, config.username, config.password)
        conversation = _create_conversation(
            client,
            token,
            scenario,
            config.conversation_title_prefix,
        )
        conversation_id = conversation.get("id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise RuntimeError("Conversation response did not contain id")

        for turn_index, user_message in enumerate(scenario_message_sequence(scenario), start=1):
            turn_started_at = time.perf_counter()
            turn_assistant_parts: list[str] = []
            turn_event_count_before = len(events)
            turn_error: str | None = None

            try:
                for event in client.stream_json_events(
                    f"/api/v1/chat/stream/{conversation_id}",
                    {"content": user_message},
                    token=token,
                ):
                    event_with_turn = {"turn_index": turn_index, **event}
                    events.append(event_with_turn)
                    event_type = event.get("type")
                    if event_type == "token":
                        content = event.get("content")
                        if isinstance(content, str):
                            assistant_parts.append(content)
                            turn_assistant_parts.append(content)
                    elif event_type == "report_data" and isinstance(event.get("report_data"), dict):
                        report_data = event["report_data"]
                    elif event_type == "error":
                        turn_error = str(event.get("message") or "SSE error event")
                        break
            except (urllib.error.URLError, OSError) as exc:
                turn_error = str(exc)

            turns.append(
                {
                    "turn_index": turn_index,
                    "user_message": user_message,
                    "assistant_chars": len("".join(turn_assistant_parts)),
                    "event_count": len(events) - turn_event_count_before,
                    "elapsed_seconds": round(time.perf_counter() - turn_started_at, 2),
                    "produced_report_data": report_data is not None,
                    "error": turn_error,
                }
            )
            if report_data is not None:
                break

        if report_data is None:
            last_error = next((turn.get("error") for turn in reversed(turns) if turn.get("error")), None)
            message = "Live scenario did not produce structured report_data"
            if last_error:
                message = f"{message}; last turn error: {last_error}"
            raise RuntimeError(message)

        evaluation = evaluate_report_quality(
            report_data,
            expected_mode=scenario.expected_mode,
            pass_threshold=scenario.min_score,
        ).to_dict()
        assistant_text = "".join(assistant_parts)
        elapsed_seconds = time.perf_counter() - started_at
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
        )
        path = snapshot_path_for(scenario, config.output_dir)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        return LiveScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=bool(evaluation["passed"]) and evaluation["normalized_score"] >= scenario.min_score,
            normalized_score=float(evaluation["normalized_score"]),
            grade=str(evaluation["grade"]),
            snapshot_path=str(path),
            elapsed_seconds=round(elapsed_seconds, 2),
        )
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        elapsed_seconds = time.perf_counter() - started_at
        snapshot_path: str | None = None
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
                error=str(exc),
            )
            path = snapshot_path_for(scenario, config.output_dir)
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            snapshot_path = str(path)
        return LiveScenarioResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            passed=False,
            normalized_score=None,
            grade=None,
            snapshot_path=snapshot_path,
            elapsed_seconds=round(elapsed_seconds, 2),
            error=str(exc),
        )
