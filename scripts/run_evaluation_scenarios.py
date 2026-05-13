"""Run fixed evaluation scenarios against the live local API."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import sys
import time
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
    build_acceptance_evidence_closure,
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


def _optional_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return float(value)


def _result_failure_category(result: dict[str, Any]) -> str | None:
    category = result.get("failure_category")
    if isinstance(category, str) and category:
        return category

    gate = result.get("acceptance_gate") if isinstance(result.get("acceptance_gate"), dict) else {}
    failures = gate.get("failures") if isinstance(gate, dict) else []
    dimensions = {
        str(failure.get("dimension"))
        for failure in failures
        if isinstance(failure, dict) and failure.get("dimension")
    }
    if "runtime_budget" in dimensions or "runtime_quality" in dimensions:
        return "runtime_budget"

    closure = result.get("evidence_closure")
    if isinstance(closure, dict) and closure.get("passed") is False:
        return "evidence_closure"

    error = str(result.get("error") or "").lower()
    if "session_busy" in error or "conversation is busy" in error or "busy" in error:
        return "conversation_busy"
    if "timeout" in error or "timed out" in error:
        return "timeout"
    if result.get("passed") is False:
        return "acceptance_gate"
    return None


def _failure_classification_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if not isinstance(result, dict) or result.get("passed") is True:
            continue
        category = _result_failure_category(result) or "unknown"
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _enrich_run_summary(
    summary: dict[str, Any],
    *,
    results: list[dict[str, Any]],
    scenarios: list[Any],
    partial_reason: str | None = None,
) -> dict[str, Any]:
    selected_ids = [str(scenario.id) for scenario in scenarios]
    completed_ids = [str(result.get("scenario_id")) for result in results if result.get("scenario_id")]
    pending_ids = [scenario_id for scenario_id in selected_ids if scenario_id not in set(completed_ids)]
    run_context = {
        "version": "acceptance_run_context.v1",
        "partial": bool(partial_reason or pending_ids),
        "partial_reason": partial_reason,
        "completed_scenario_ids": completed_ids,
        "pending_scenario_ids": pending_ids,
        "failure_classification_counts": _failure_classification_counts(results),
    }
    summary["run_context"] = run_context
    return _redact_cli_payload(summary)


def _build_live_error_result(
    scenario: Any,
    *,
    error: str,
    failure_category: str,
    status: str = "failed",
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    redacted_error = redact_sensitive_text(error)
    gate_status = status if status in {"failed", "blocked", "skipped"} else "failed"
    acceptance_gate = build_error_acceptance_gate_result(
        scenario=scenario,
        error=redacted_error,
        status=gate_status,
    )
    acceptance_gate["failure_category"] = failure_category
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "status": gate_status,
        "passed": False,
        "normalized_score": None,
        "grade": None,
        "snapshot_path": None,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "agent_score": None,
        "runtime_budget_passed": None,
        "runtime_findings": [],
        "runtime_metrics": None,
        "tool_counts": None,
        "evidence_closure": build_acceptance_evidence_closure(
            scenario=scenario,
            report_data=None,
            snapshot_path=None,
        ),
        "acceptance_gate": acceptance_gate,
        "failure_category": failure_category,
        "failure_details": [redacted_error],
        "error": redacted_error,
    }


def _build_and_optionally_write_summary(
    *,
    results: list[dict[str, Any]],
    scenarios: list[Any],
    base_url: str,
    output_dir: Path,
    preflight: dict[str, Any] | None,
    write_files: bool,
    prefix: str,
    partial_reason: str | None = None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    summary = build_acceptance_run_summary(
        results=results,
        scenarios=scenarios,
        base_url=base_url,
        output_dir=output_dir,
        preflight=preflight,
    )
    summary = _enrich_run_summary(
        summary,
        results=results,
        scenarios=scenarios,
        partial_reason=partial_reason,
    )
    summary_paths = (
        write_acceptance_summary_files(summary, output_dir, prefix=prefix)
        if write_files
        else None
    )
    return summary, summary_paths


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
                "details": check.get("details") or {},
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
        "failure_classification_counts": _failure_classification_counts(results),
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
        if result.get("failure_category"):
            print(f"  category={result['failure_category']}")
        for detail in result.get("failure_details") or []:
            print(f"  detail={detail}")
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
        "--scenario-timeout",
        type=float,
        default=_optional_float_env("ZHIXING_EVAL_SCENARIO_TIMEOUT"),
        help=(
            "Wall-clock timeout seconds for one scenario. "
            "Defaults to --timeout when omitted."
        ),
    )
    parser.add_argument(
        "--global-timeout",
        type=float,
        default=_optional_float_env("ZHIXING_EVAL_GLOBAL_TIMEOUT"),
        help="Wall-clock timeout seconds for the whole selected scenario run.",
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
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.scenario_timeout is not None and args.scenario_timeout <= 0:
        parser.error("--scenario-timeout must be positive")
    if args.global_timeout is not None and args.global_timeout <= 0:
        parser.error("--global-timeout must be positive")

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
        scenario_timeout_seconds=args.scenario_timeout or args.timeout,
        conversation_title_prefix=args.title_prefix,
        runtime_budget=runtime_budget_from_dict(runtime_budget_overrides or None),
        enable_llm_judge=args.llm_judge,
        llm_judge_threshold=args.llm_judge_threshold,
    )
    results = []
    continue_on_error = args.continue_on_error or args.acceptance_core or args.acceptance_smoke
    summary = None
    summary_paths = None
    summary_output_dir = args.summary_dir or args.output_dir
    run_started_at = time.perf_counter()
    run_interrupted = False
    partial_reason: str | None = None
    active_scenario = None

    try:
        for scenario in scenarios:
            active_scenario = scenario
            global_remaining = (
                args.global_timeout - (time.perf_counter() - run_started_at)
                if args.global_timeout is not None
                else None
            )
            if global_remaining is not None and global_remaining <= 0:
                error = (
                    "Global timeout budget exhausted before scenario "
                    f"{scenario.id} could start"
                )
                results.append(
                    _build_live_error_result(
                        scenario,
                        error=error,
                        failure_category="global_timeout",
                    )
                )
                partial_reason = "global_timeout"
                break

            scenario_timeout = config.scenario_timeout_seconds
            if global_remaining is not None:
                scenario_timeout = (
                    min(scenario_timeout, global_remaining)
                    if scenario_timeout is not None
                    else global_remaining
                )
            scenario_config = replace(
                config,
                scenario_timeout_seconds=scenario_timeout,
            )
            result = run_live_scenario(scenario, scenario_config)
            result_payload = result.to_dict()
            if (
                result.failure_category == "timeout"
                and args.global_timeout is not None
                and time.perf_counter() - run_started_at >= args.global_timeout
            ):
                result_payload["failure_category"] = "global_timeout"
                if isinstance(result_payload.get("acceptance_gate"), dict):
                    result_payload["acceptance_gate"]["failure_category"] = "global_timeout"
                partial_reason = "global_timeout"
            results.append(result_payload)
            active_scenario = None
            if not args.no_summary:
                summary, summary_paths = _build_and_optionally_write_summary(
                    results=results,
                    scenarios=scenarios,
                    base_url=args.base_url,
                    output_dir=summary_output_dir,
                    preflight=preflight,
                    write_files=True,
                    prefix=args.summary_prefix,
                    partial_reason=partial_reason or "in_progress",
                )
            if not result.passed and not continue_on_error:
                partial_reason = partial_reason or "stopped_after_failure"
                break
            if partial_reason == "global_timeout":
                break
    except KeyboardInterrupt:
        run_interrupted = True
        partial_reason = "interrupted"
        if active_scenario is not None and active_scenario.id not in {
            str(result.get("scenario_id")) for result in results
        }:
            elapsed_seconds = time.perf_counter() - run_started_at
            results.append(
                _build_live_error_result(
                    active_scenario,
                    error=(
                        "Evaluation run interrupted before this scenario completed. "
                        "Partial results were preserved."
                    ),
                    failure_category="interrupted",
                    elapsed_seconds=elapsed_seconds,
                )
            )

    if (not args.no_summary) or run_interrupted or partial_reason:
        summary, summary_paths = _build_and_optionally_write_summary(
            results=results,
            scenarios=scenarios,
            base_url=args.base_url,
            output_dir=summary_output_dir,
            preflight=preflight,
            write_files=not args.no_summary,
            prefix=args.summary_prefix,
            partial_reason=partial_reason,
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

    if run_interrupted:
        return 130

    passed = bool(summary["passed"]) if isinstance(summary, dict) else bool(results and all(result["passed"] for result in results))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
