"""Evaluate structured report data from a saved real-chain JSON snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.live_runner import build_quality_summary  # noqa: E402
from app.evaluation.report_quality import evaluate_report_quality  # noqa: E402
from app.evaluation.runtime_metrics import runtime_budget_from_dict  # noqa: E402
from app.evaluation.scenarios import EvaluationScenario, get_scenario, load_scenarios  # noqa: E402


def _extract_latest_report_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    if isinstance(snapshot.get("report_data"), dict):
        return snapshot["report_data"]
    if isinstance(snapshot.get("latest_report"), dict):
        return snapshot["latest_report"]
    if isinstance(snapshot.get("summary"), dict) and isinstance(
        snapshot["summary"].get("latest_report"),
        dict,
    ):
        return snapshot["summary"]["latest_report"]

    history = snapshot.get("history") or {}
    messages = history.get("messages") or []
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        extra_info = message.get("extra_info") or {}
        report_data = extra_info.get("report_data")
        if isinstance(report_data, dict):
            return report_data
        additional_kwargs = message.get("additional_kwargs") or {}
        report_data = additional_kwargs.get("report_data")
        if isinstance(report_data, dict):
            return report_data
    raise ValueError("No structured report_data found in snapshot")


def _print_markdown(result: dict[str, Any]) -> None:
    scenario = result.get("scenario")
    print(f"# Report Evaluation: {result['normalized_score']} / 100 ({result['grade']})")
    print()
    if scenario:
        print(f"- Scenario: {scenario['id']} ({scenario['name']})")
        print(f"- Expected mode: {scenario['expected_mode']}")
        print(f"- Scenario minimum score: {scenario['min_score']}")
    print(f"- Passed: {result['passed']}")
    print(f"- Raw score: {result['total_score']} / {result['max_score']}")
    print()
    print("## Criteria")
    for criterion in result["criteria"]:
        ratio = round(criterion["ratio"] * 100, 1)
        print(
            f"- {criterion['name']}: "
            f"{criterion['score']} / {criterion['max_score']} "
            f"({ratio}%)"
        )
        for finding in criterion["findings"]:
            print(f"  - {finding}")
    print()
    print("## Summary")
    for item in result["summary"]:
        print(f"- {item}")
    quality_summary = result.get("quality_summary")
    if isinstance(quality_summary, dict):
        aggregate = quality_summary.get("aggregate") or {}
        print()
        print("## Agent Run Quality")
        print(f"- Aggregate: {aggregate.get('normalized_score')} / 100")
        print(f"- Passed: {aggregate.get('passed')}")
        for key in ("rag_quality", "tool_quality", "runtime_quality"):
            item = quality_summary.get(key) or {}
            print(f"- {key}: {item.get('normalized_score')} / 100 ({item.get('grade')})")
        runtime_quality = quality_summary.get("runtime_quality") or {}
        budget_gate = runtime_quality.get("budget_gate") or {}
        print(f"- runtime_budget: {'PASS' if budget_gate.get('passed') else 'FAIL'}")
        runtime_governance = quality_summary.get("runtime_governance") or {}
        for section_key in ("slow_path", "cost_risk", "tool_usage", "errors"):
            section = runtime_governance.get(section_key) or {}
            for finding in (section.get("findings") or [])[:3]:
                print(f"  - {section_key}: {finding}")


def _scenario_for_snapshot(
    *,
    scenario: EvaluationScenario | None,
    report_data: dict[str, Any],
    expected_mode: str | None,
    min_score: float,
) -> EvaluationScenario:
    if scenario is not None:
        return scenario
    agency_context = report_data.get("agency_context") if isinstance(report_data, dict) else {}
    mode = expected_mode or (
        agency_context.get("mode") if isinstance(agency_context, dict) else None
    )
    if mode not in {"agency_plan", "free_planning"}:
        mode = "agency_plan"
    return EvaluationScenario(
        id="adhoc_snapshot",
        name="Ad hoc snapshot",
        category="snapshot",
        prompt="",
        expected_mode=mode,
        min_score=min_score,
        focus=["snapshot"],
        tags=["snapshot"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, nargs="?", help="Path to a saved JSON snapshot")
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario id from the evaluation catalog",
    )
    parser.add_argument(
        "--scenarios-file",
        type=Path,
        default=None,
        help="Optional scenario catalog JSON path",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenario ids and exit",
    )
    parser.add_argument(
        "--expected-mode",
        choices=["agency_plan", "free_planning"],
        default=None,
        help="Expected agency_context.mode for this scenario",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit with code 2 if normalized score is below this value",
    )
    parser.add_argument(
        "--enforce-runtime-budget",
        action="store_true",
        help="Exit with code 2 if the runtime budget gate fails",
    )
    parser.add_argument(
        "--enforce-agent-gate",
        action="store_true",
        help="Exit with code 2 if the combined Agent quality gate fails",
    )
    parser.add_argument(
        "--max-total-seconds",
        type=float,
        default=None,
        help="Override runtime budget for total elapsed seconds",
    )
    parser.add_argument(
        "--max-first-token-seconds",
        type=float,
        default=None,
        help="Override runtime budget for first token latency",
    )
    parser.add_argument(
        "--max-tool-calls",
        type=int,
        default=None,
        help="Override runtime budget for tool-call count",
    )
    parser.add_argument(
        "--max-estimated-tokens",
        type=int,
        default=None,
        help="Override runtime budget for estimated total tokens",
    )
    parser.add_argument(
        "--max-error-events",
        type=int,
        default=None,
        help="Override runtime budget for SSE error events",
    )
    args = parser.parse_args()

    if args.list_scenarios:
        for scenario in load_scenarios(args.scenarios_file):
            print(f"{scenario.id}\t{scenario.expected_mode}\t{scenario.min_score}\t{scenario.name}")
        return 0

    if args.snapshot is None:
        parser.error("snapshot is required unless --list-scenarios is used")

    scenario = get_scenario(args.scenario, args.scenarios_file) if args.scenario else None
    expected_mode = args.expected_mode or (scenario.expected_mode if scenario else None)
    fail_under = args.fail_under
    if fail_under is None and scenario:
        fail_under = scenario.min_score

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    report_data = _extract_latest_report_data(snapshot)
    result = evaluate_report_quality(
        report_data,
        expected_mode=expected_mode,
    ).to_dict()
    if scenario:
        result["scenario"] = scenario.to_dict()

    quality_scenario = _scenario_for_snapshot(
        scenario=scenario,
        report_data=report_data,
        expected_mode=expected_mode,
        min_score=fail_under or 80.0,
    )
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    events = snapshot.get("events") if isinstance(snapshot.get("events"), list) else []
    turns = snapshot.get("turns") if isinstance(snapshot.get("turns"), list) else []
    assistant_text = snapshot.get("assistant_text") if isinstance(snapshot.get("assistant_text"), str) else ""
    elapsed_seconds = summary.get("elapsed_seconds") if isinstance(summary.get("elapsed_seconds"), (int, float)) else 0
    report_evaluation = dict(result)
    runtime_budget_overrides = {
        key: value
        for key, value in {
            "max_total_elapsed_seconds": args.max_total_seconds,
            "max_first_token_seconds": args.max_first_token_seconds,
            "max_tool_call_count": args.max_tool_calls,
            "max_estimated_total_tokens": args.max_estimated_tokens,
            "max_error_event_count": args.max_error_events,
        }.items()
        if value is not None
    }
    result["quality_summary"] = build_quality_summary(
        scenario=quality_scenario,
        events=events,
        turns=turns,
        assistant_text=assistant_text,
        report_data=report_data,
        report_evaluation=report_evaluation,
        elapsed_seconds=float(elapsed_seconds),
        timeout_seconds=900.0,
        runtime_budget=(
            runtime_budget_from_dict(runtime_budget_overrides)
            if runtime_budget_overrides
            else None
        ),
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_markdown(result)

    runtime_quality = result["quality_summary"].get("runtime_quality") or {}
    runtime_budget_failed = (
        args.enforce_runtime_budget
        and not bool((runtime_quality.get("budget_gate") or {}).get("passed"))
    )
    agent_gate_failed = (
        args.enforce_agent_gate
        and not bool((result["quality_summary"].get("aggregate") or {}).get("passed"))
    )
    report_failed = fail_under is not None and (
        result["normalized_score"] < fail_under or not result["passed"]
    )
    if report_failed or runtime_budget_failed or agent_gate_failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
