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

_JSON_MODE_REQUESTED = "--json" in sys.argv
_ORIGINAL_STDOUT = sys.stdout
if _JSON_MODE_REQUESTED:
    sys.stdout = sys.stderr

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
    build_error_acceptance_gate_result,
    build_skipped_acceptance_gate_result,
    write_acceptance_summary_files,
)
from app.evaluation.preflight import run_acceptance_preflight  # noqa: E402
from app.evaluation.runtime_metrics import runtime_budget_from_dict  # noqa: E402
from app.evaluation.scenarios import (  # noqa: E402
    acceptance_core_scenarios,
    acceptance_smoke_scenarios,
    load_scenarios,
)
from app.utils.security import redact_sensitive_text  # noqa: E402


RUNTIME_ARTIFACT_ROOT = PROJECT_ROOT / ".runtime"


def _redact_cli_payload(value: Any, *, max_depth: int = 12) -> Any:
    if max_depth < 0:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            key: _redact_cli_payload(item, max_depth=max_depth - 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_cli_payload(item, max_depth=max_depth - 1)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _redact_cli_payload(item, max_depth=max_depth - 1)
            for item in value
        )
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _require_runtime_artifact_dir(path: Path, *, flag_name: str) -> Path:
    resolved_path = (PROJECT_ROOT / path if not path.is_absolute() else path).resolve()
    runtime_root = RUNTIME_ARTIFACT_ROOT.resolve()
    if resolved_path != runtime_root and runtime_root not in resolved_path.parents:
        raise ValueError(
            f"{flag_name} must point inside {RUNTIME_ARTIFACT_ROOT} for live acceptance artifacts"
        )
    return path


def _preflight_health_checks(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    checks = preflight.get("checks") or []
    return [
        check
        for check in checks
        if isinstance(check, dict)
        and (
            str(check.get("key") or "").startswith("backend_")
            or "health" in str(check.get("label") or "").lower()
        )
    ]


def _preflight_blocking_reasons(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    checks = preflight.get("checks") or []
    reasons = []
    for check in checks:
        if not isinstance(check, dict) or check.get("status") not in {"blocked", "skipped"}:
            continue
        reasons.append(
            {
                "key": check.get("key"),
                "label": check.get("label"),
                "status": check.get("status"),
                "required": check.get("required"),
                "env_vars": check.get("env_vars") or [],
                "findings": check.get("findings") or [],
                "suggestion": check.get("suggestion") or "",
            }
        )
    return reasons


def _status_from_results(
    results: list[dict[str, Any]],
    *,
    preflight: dict[str, Any] | None = None,
) -> str:
    preflight_status = str((preflight or {}).get("status") or "")
    if preflight_status == "blocked":
        return "blocked"
    if preflight_status == "skipped":
        return "skipped"

    statuses = [
        str(
            result.get("status")
            or (result.get("acceptance_gate") or {}).get("status")
            or ("passed" if result.get("passed") else "failed")
        )
        for result in results
    ]
    if not statuses:
        return "skipped"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    if "degraded" in statuses:
        return "degraded"
    if preflight_status == "degraded":
        return "degraded"
    if all(status == "passed" for status in statuses):
        return "passed"
    return "skipped"


def _status_with_preflight_guard(
    status: str,
    *,
    preflight: dict[str, Any] | None,
) -> str:
    """Keep machine JSON from ever reporting passed when preflight says otherwise."""

    preflight_status = str((preflight or {}).get("status") or "")
    if preflight_status == "blocked":
        return "blocked"
    if preflight_status == "skipped":
        return "skipped"
    if preflight_status == "degraded" and status == "passed":
        return "degraded"
    return status


def build_cli_json_payload(
    *,
    results: list[dict[str, Any]],
    acceptance_summary: dict[str, Any] | None,
    summary_paths: dict[str, str] | None,
    preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_status = (
        str(acceptance_summary.get("status"))
        if isinstance(acceptance_summary, dict) and acceptance_summary.get("status")
        else _status_from_results(results, preflight=preflight)
    )
    status = _status_with_preflight_guard(raw_status, preflight=preflight)
    payload = {
        "status": status,
        "passed": status == "passed",
        "preflight": preflight,
        "missing_required": (preflight or {}).get("missing_required") or [],
        "degraded_optional": (preflight or {}).get("degraded_optional") or [],
        "health_checks": _preflight_health_checks(preflight or {}),
        "blocking_reasons": _preflight_blocking_reasons(preflight or {}),
        "results": results,
        "acceptance_summary": acceptance_summary,
        "summary_paths": summary_paths,
    }
    return _redact_cli_payload(payload)


def _print_plan(scenarios: list[Any]) -> None:
    print("# Evaluation Scenario Plan")
    print()
    for scenario in scenarios:
        print(f"- {scenario.id}: {scenario.expected_mode}, min_score={scenario.min_score}")
        requirements = scenario.requirements or {}
        print(
            "  requirements: "
            f"real_llm={requirements.get('real_llm', True)}, "
            f"real_mcp={requirements.get('real_mcp', False)}, "
            f"mcp_servers={requirements.get('mcp_servers', [])}, "
            f"external_apis={requirements.get('external_apis', [])}"
        )
        for index, message in enumerate(scenario_message_sequence(scenario), start=1):
            print(f"  turn {index}: {message}")


def _print_results(results: list[dict[str, Any]]) -> None:
    print("# Evaluation Scenario Results")
    print()
    for result in results:
        status = str(result.get("status") or ("passed" if result["passed"] else "failed")).upper()
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
        supplements = gate.get("supplemental_dimensions") or {}
        llm_judge = supplements.get("llm_judge") or {}
        if llm_judge:
            print(
                "  llm_judge="
                f"{llm_judge.get('status')}, score={llm_judge.get('score')}"
            )
        for failure in (gate.get("failures") or [])[:3]:
            print(
                "  gate="
                f"{failure.get('dimension_label')}: "
                f"{'; '.join(str(item) for item in (failure.get('findings') or [])[:2])}"
            )
            print(f"  next={failure.get('suggestion')}")


def _print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if _JSON_MODE_REQUESTED:
        _ORIGINAL_STDOUT.write(text)
        _ORIGINAL_STDOUT.write("\n")
        _ORIGINAL_STDOUT.flush()
    else:
        print(text)


def _preflight_skip_reason(preflight: dict[str, Any]) -> str:
    status = str(preflight.get("status") or "")
    if status == "passed":
        return "Preflight-only passed; live scenarios were intentionally not run."
    if status == "degraded":
        degraded = preflight.get("degraded_optional") or []
        detail = ", ".join(str(item) for item in degraded) if degraded else "optional checks degraded"
        return "Preflight-only degraded; live scenarios were intentionally not run: " + detail

    missing = preflight.get("missing_required") or []
    checks = preflight.get("checks") or []
    findings = [
        f"{check.get('label')}: {'; '.join(str(item) for item in (check.get('findings') or []))}"
        for check in checks
        if isinstance(check, dict) and check.get("status") in {"blocked", "skipped"}
    ]
    if findings:
        return "Preflight blocked live acceptance: " + " | ".join(findings[:5])
    return "Preflight blocked live acceptance; missing required checks: " + ", ".join(missing)


def _preflight_only_exit_code(preflight: dict[str, Any]) -> int:
    return 0 if preflight.get("status") in {"passed", "degraded"} else 2


def _build_skipped_results(scenarios: list[Any], preflight: dict[str, Any]) -> list[dict[str, Any]]:
    reason = _preflight_skip_reason(preflight)
    result_status = "blocked" if preflight.get("status") == "blocked" else "skipped"
    return [
        {
            "scenario_id": scenario.id,
            "scenario_name": scenario.name,
            "status": result_status,
            "passed": False,
            "normalized_score": None,
            "grade": None,
            "snapshot_path": None,
            "elapsed_seconds": 0.0,
            "agent_score": None,
            "runtime_budget_passed": None,
            "runtime_findings": [],
            "acceptance_gate": (
                build_error_acceptance_gate_result(
                    scenario=scenario,
                    error=reason,
                    status="blocked",
                )
                if result_status == "blocked"
                else build_skipped_acceptance_gate_result(
                    scenario=scenario,
                    reason=reason,
                )
            ),
            "error": reason,
        }
        for scenario in scenarios
    ]


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
        "--acceptance-smoke",
        action="store_true",
        help="Run the minimal live acceptance smoke scenario set tagged acceptance-smoke.",
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
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run acceptance preflight and write blocked/degraded summary without live scenario calls.",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Run optional LLM-as-Judge supplemental review after deterministic scoring.",
    )
    parser.add_argument(
        "--llm-judge-threshold",
        type=float,
        default=80.0,
        help="Supplemental LLM judge pass threshold. Does not override deterministic gates.",
    )
    args = parser.parse_args()
    if args.acceptance_core and args.acceptance_smoke:
        parser.error("--acceptance-core and --acceptance-smoke are mutually exclusive")

    try:
        args.output_dir = _require_runtime_artifact_dir(
            args.output_dir,
            flag_name="--output-dir",
        )
        if args.summary_dir is not None:
            args.summary_dir = _require_runtime_artifact_dir(
                args.summary_dir,
                flag_name="--summary-dir",
            )
    except ValueError as exc:
        parser.error(str(exc))

    catalog = load_scenarios(args.scenarios_file)
    if args.acceptance_core and not args.scenario:
        scenarios = acceptance_core_scenarios(catalog)
    elif args.acceptance_smoke and not args.scenario:
        scenarios = acceptance_smoke_scenarios(catalog)
    else:
        scenarios = select_scenarios(catalog, args.scenario)
    if args.dry_run:
        _print_plan(scenarios)
        return 0

    preflight = run_acceptance_preflight(
        scenarios,
        base_url=args.base_url,
        check_backend=True,
        require_llm_judge=args.llm_judge,
    ).to_dict()

    if preflight["status"] in {"blocked", "skipped"} or args.preflight_only:
        results = _build_skipped_results(scenarios, preflight)
        summary_output_dir = args.summary_dir or args.output_dir
        summary = build_acceptance_run_summary(
            results=results,
            scenarios=scenarios,
            base_url=args.base_url,
            output_dir=summary_output_dir,
            preflight=preflight,
        )
        summary_paths = None if args.no_summary else write_acceptance_summary_files(
            summary,
            summary_output_dir,
            prefix=args.summary_prefix,
        )
        if args.json:
            _print_json(
                build_cli_json_payload(
                    results=results,
                    acceptance_summary=summary,
                    summary_paths=summary_paths,
                    preflight=preflight,
                )
            )
        else:
            _print_results(results)
            if summary_paths:
                print()
                print("# Acceptance Summary Artifacts")
                print(f"- JSON: {summary_paths['json']}")
                print(f"- Markdown: {summary_paths['markdown']}")
        if args.preflight_only:
            return _preflight_only_exit_code(preflight)
        return 0 if summary["status"] == "passed" else 2

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
        enable_llm_judge=args.llm_judge,
        llm_judge_threshold=args.llm_judge_threshold,
    )
    results = []
    continue_on_error = args.continue_on_error or args.acceptance_core or args.acceptance_smoke
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
            preflight=preflight,
        )
        summary_paths = write_acceptance_summary_files(
            summary,
            summary_output_dir,
            prefix=args.summary_prefix,
        )

    if args.json:
        _print_json(
            build_cli_json_payload(
                results=results,
                acceptance_summary=summary,
                summary_paths=summary_paths,
                preflight=preflight,
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
