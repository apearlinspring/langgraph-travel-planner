"""Validate internal RAG knowledge metadata for CI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.contracts import (
    INTERNAL_REVIEW_MAX_AGE_DAYS,
    validate_internal_knowledge_base,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate internal travel-agency RAG knowledge metadata.",
    )
    parser.add_argument(
        "--internal-dir",
        default=str(PROJECT_ROOT / "data" / "documents" / "internal"),
        help="Internal knowledge directory to validate.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=INTERNAL_REVIEW_MAX_AGE_DAYS,
        help="Maximum allowed days since last_reviewed.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_internal_knowledge_base(
        args.internal_dir,
        max_age_days=args.max_age_days,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report.passed else "FAIL"
        print(
            f"[{status}] checked={report.checked_files} "
            f"errors={len(report.errors)} warnings={len(report.warnings)} "
            f"max_age_days={report.max_age_days}"
        )
        for finding in report.findings:
            print(
                f"- {finding.severity.upper()} "
                f"{finding.path} {finding.field}: {finding.message}"
            )

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
