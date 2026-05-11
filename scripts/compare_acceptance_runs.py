"""Compare two acceptance summary JSON files for offline Shadow / A-B review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.experiment import (  # noqa: E402
    ExperimentDefinition,
    build_experiment_definition,
    compare_acceptance_summaries,
    experiment_definition_from_dict,
    render_comparison_markdown,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_acceptance_summary(path: Path) -> dict[str, Any]:
    """Load a direct summary or the wrapper emitted by run_evaluation_scenarios --json."""

    payload = _load_json(path)
    if isinstance(payload.get("acceptance_summary"), dict):
        return payload["acceptance_summary"]
    return payload


def _scenario_ids_from_summary(summary: dict[str, Any]) -> list[str]:
    selected = summary.get("selected_scenarios")
    if isinstance(selected, list) and selected:
        return [
            str(item.get("id"))
            for item in selected
            if isinstance(item, dict) and item.get("id")
        ]
    return [
        str(item.get("scenario_id"))
        for item in summary.get("results", [])
        if isinstance(item, dict) and item.get("scenario_id")
    ]


def _default_experiment(args: argparse.Namespace, baseline: dict[str, Any]) -> ExperimentDefinition:
    scenario_set_id = args.scenario_set or str(baseline.get("core_tag") or "acceptance-summary")
    return build_experiment_definition(
        experiment_id=args.experiment_id,
        mode=args.mode,
        scenario_set_id=scenario_set_id,
        scenario_ids=_scenario_ids_from_summary(baseline),
        baseline_variant_id=args.baseline_variant,
        candidate_variant_id=args.candidate_variant,
        description=args.description,
    )


def _load_experiment(args: argparse.Namespace, baseline: dict[str, Any]) -> ExperimentDefinition:
    if args.experiment_file:
        return experiment_definition_from_dict(_load_json(args.experiment_file))
    return _default_experiment(args, baseline)


def _write_outputs(
    comparison: dict[str, Any],
    *,
    output_json: Path | None,
    output_md: Path | None,
) -> None:
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    if output_md:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_comparison_markdown(comparison), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_summary", type=Path, help="Baseline acceptance summary JSON")
    parser.add_argument("candidate_summary", type=Path, help="Candidate acceptance summary JSON")
    parser.add_argument(
        "--experiment-file",
        type=Path,
        default=None,
        help="Optional experiment definition JSON",
    )
    parser.add_argument(
        "--experiment-id",
        default="ad-hoc-shadow-ab",
        help="Experiment id used when --experiment-file is omitted",
    )
    parser.add_argument(
        "--mode",
        choices=["shadow-only", "offline-ab"],
        default="shadow-only",
        help="Offline comparison mode",
    )
    parser.add_argument(
        "--scenario-set",
        default=None,
        help="Scenario set id used when --experiment-file is omitted",
    )
    parser.add_argument(
        "--baseline-variant",
        default="baseline",
        help="Baseline variant id used when --experiment-file is omitted",
    )
    parser.add_argument(
        "--candidate-variant",
        default="candidate",
        help="Candidate variant id used when --experiment-file is omitted",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Optional comparison description",
    )
    parser.add_argument("--output-json", type=Path, default=None, help="Write JSON comparison")
    parser.add_argument("--output-md", type=Path, default=None, help="Write Markdown comparison")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Return exit code 2 when the candidate regresses or is blocked",
    )
    args = parser.parse_args(argv)

    baseline = load_acceptance_summary(args.baseline_summary)
    candidate = load_acceptance_summary(args.candidate_summary)
    experiment = _load_experiment(args, baseline)
    comparison = compare_acceptance_summaries(
        baseline,
        candidate,
        experiment=experiment,
    )
    _write_outputs(
        comparison,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    if args.json:
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
    else:
        print(render_comparison_markdown(comparison))
    if args.fail_on_regression and comparison.get("verdict") in {"blocked", "regressed"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

