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

from app.evaluation.report_quality import evaluate_report_quality  # noqa: E402
from app.evaluation.scenarios import get_scenario, load_scenarios  # noqa: E402


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

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    report_data = _extract_latest_report_data(snapshot)
    result = evaluate_report_quality(
        report_data,
        expected_mode=expected_mode,
    ).to_dict()
    if scenario:
        result["scenario"] = scenario.to_dict()

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_markdown(result)

    if fail_under is not None and (
        result["normalized_score"] < fail_under or not result["passed"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
