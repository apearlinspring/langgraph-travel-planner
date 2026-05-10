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
from app.evaluation.acceptance_gate import (  # noqa: E402
    build_acceptance_run_summary,
    write_acceptance_summary_files,
)
from app.evaluation.runtime_metrics import runtime_budget_from_dict  # noqa: E402
from app.evaluation.scenarios import acceptance_core_scenarios, load_scenarios  # noqa: E402


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
        runtime_budget_passed = result.get("runtime_budget_passed")
        runtime_budget_text = (
            f", runtime_budget={'PASS' if runtime_budget_passed else 'FAIL'}"
            if runtime_budget_passed is not None
            else ""
        )
        print(
            f"- {status} {result['scenario_id']}: "
            f"score={score}{agent_score_text}{runtime_budget_text}, elapsed={result['elapsed_seconds']}s"
        )
        for finding in result.get("runtime_findings") or []:
            print(f"  runtime={finding}")
        if result.get("snapshot_path"):
            print(f"  snapshot={result['snapshot_path']}")
        if result.get("error"):
            print(f"  error={result['error']}")
        gate = result.get("acceptance_gate") or {}
        for failure in (gate.get("failures") or [])[:3]:
            print(
                "  gate="
                f"{failure.get('dimension_label')}: "
                f"{'; '.join(str(item) for item in (failure.get('findings') or [])[:2])}"
            )
            print(f"  next={failure.get('suggestion')}")


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
        "--acceptance-core",
        action="store_true",
        help="Run the first-stage core acceptance scenario set tagged acceptance-core.",
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
    parser.add_argument(
        "--summary-dir",
        type=Path,
        default=None,
        help="Directory for JSON and Markdown acceptance summaries. Defaults to output-dir.",
    )
    parser.add_argument(
        "--summary-prefix",
        default="acceptance-summary",
        help="Filename prefix for generated acceptance summary artifacts.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Do not write run-level JSON and Markdown acceptance summaries.",
    )
    args = parser.parse_args()

    catalog = load_scenarios(args.scenarios_file)
    scenarios = (
        acceptance_core_scenarios(catalog)
        if args.acceptance_core and not args.scenario
        else select_scenarios(catalog, args.scenario)
    )
    if args.dry_run:
        _print_plan(scenarios)
        return 0

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
    config = LiveRunConfig(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout,
        conversation_title_prefix=args.title_prefix,
        runtime_budget=runtime_budget_from_dict(runtime_budget_overrides or None),
    )
    results = []
    continue_on_error = args.continue_on_error or args.acceptance_core
    for scenario in scenarios:
        result = run_live_scenario(scenario, config)
        results.append(result.to_dict())
        if not result.passed and not continue_on_error:
            break

    summary = None
    summary_paths = None
    if not args.no_summary:
        summary_output_dir = args.summary_dir or args.output_dir
        summary = build_acceptance_run_summary(
            results=results,
            scenarios=scenarios,
            base_url=args.base_url,
            output_dir=summary_output_dir,
        )
        summary_paths = write_acceptance_summary_files(
            summary,
            summary_output_dir,
            prefix=args.summary_prefix,
        )

    if args.json:
        print(
            json.dumps(
                {
                    "results": results,
                    "acceptance_summary": summary,
                    "summary_paths": summary_paths,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_results(results)
        if summary_paths:
            print()
            print("# Acceptance Summary Artifacts")
            print(f"- JSON: {summary_paths['json']}")
            print(f"- Markdown: {summary_paths['markdown']}")

    passed = bool(summary["passed"]) if isinstance(summary, dict) else bool(results and all(result["passed"] for result in results))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
