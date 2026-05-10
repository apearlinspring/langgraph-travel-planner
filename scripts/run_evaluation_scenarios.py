"""Run fixed evaluation scenarios against the live local API."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.live_runner import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_OUTPUT_DIR,
    LiveRunConfig,
    run_live_scenario,
    scenario_message_sequence,
    select_scenarios,
)
from app.evaluation.scenarios import load_scenarios  # noqa: E402


def _print_plan(scenarios: list[Any]) -> None:
    print("# Evaluation Scenario Plan")
    print()
    for scenario in scenarios:
        print(f"- {scenario.id}: {scenario.expected_mode}, min_score={scenario.min_score}")
        for index, message in enumerate(scenario_message_sequence(scenario), start=1):
            print(f"  turn {index}: {message}")


def _print_results(results: list[dict[str, Any]]) -> None:
    print("# Evaluation Scenario Results")
    print()
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        score = result["normalized_score"] if result["normalized_score"] is not None else "-"
        agent_score = result.get("agent_score")
        agent_score_text = f", agent_score={agent_score}" if agent_score is not None else ""
        print(
            f"- {status} {result['scenario_id']}: "
            f"score={score}{agent_score_text}, elapsed={result['elapsed_seconds']}s"
        )
        if result.get("snapshot_path"):
            print(f"  snapshot={result['snapshot_path']}")
        if result.get("error"):
            print(f"  error={result['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="Scenario id to run. Can be repeated. Defaults to all scenarios.",
    )
    parser.add_argument(
        "--scenarios-file",
        type=Path,
        default=None,
        help="Optional scenario catalog JSON path",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("ZHIXING_EVAL_BASE_URL", DEFAULT_BASE_URL),
        help="Backend base URL",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("ZHIXING_EVAL_USERNAME", "test"),
        help="Evaluation account username",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ZHIXING_EVAL_PASSWORD", "000000"),
        help="Evaluation account password",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for live run snapshots",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("ZHIXING_EVAL_TIMEOUT", "900")),
        help="HTTP timeout seconds per request",
    )
    parser.add_argument(
        "--title-prefix",
        default="eval",
        help="Conversation title prefix",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected scenarios without calling the backend",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue running remaining scenarios after a failed scenario",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary",
    )
    args = parser.parse_args()

    scenarios = select_scenarios(load_scenarios(args.scenarios_file), args.scenario)
    if args.dry_run:
        _print_plan(scenarios)
        return 0

    config = LiveRunConfig(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout,
        conversation_title_prefix=args.title_prefix,
    )
    results = []
    for scenario in scenarios:
        result = run_live_scenario(scenario, config)
        results.append(result.to_dict())
        if not result.passed and not args.continue_on_error:
            break

    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        _print_results(results)

    return 0 if results and all(result["passed"] for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
