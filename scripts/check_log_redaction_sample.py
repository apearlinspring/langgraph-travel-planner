"""Check a log sample for unredacted credential or PII-shaped text.

The checker reports counts and categories only. It never prints raw log lines.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.security import redact_sensitive_text  # noqa: E402


LOG_REDACTION_SAMPLE_VERSION = "log_redaction_sample.v1"
SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "url_query_secret",
        re.compile(
            r"(?i)[?&](?:api[_-]?key|apikey|key|access[_-]?token|refresh[_-]?token|"
            r"token|secret|password|authorization)=[^&#\s]+"
        ),
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
            r"authorization|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"
        ),
    ),
    ("bearer_token", re.compile(r"(?i)\b(?:bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    (
        "api_key_shape",
        re.compile(r"\b(?:sk|rk|pk|ak|dashscope|amap|tavily)[-_][A-Za-z0-9][A-Za-z0-9_-]{10,}\b", re.IGNORECASE),
    ),
    (
        "email",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.+-])", re.IGNORECASE),
    ),
    ("phone", re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")),
    (
        "id_card",
        re.compile(
            r"(?<![0-9A-Za-z])\d{6}(?:18|19|20)\d{2}"
            r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]"
            r"(?![0-9A-Za-z])"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    category: str
    line_number: int


def _read_text(*, input_file: Path | None, use_stdin: bool) -> str:
    if input_file is not None:
        return input_file.read_text(encoding="utf-8", errors="replace")
    if use_stdin:
        return sys.stdin.read()
    return ""


def _scan_line(line: str, line_number: int) -> list[Finding]:
    findings: list[Finding] = []
    for category, pattern in SENSITIVE_PATTERNS:
        if pattern.search(line):
            findings.append(Finding(category=category, line_number=line_number))
    if redact_sensitive_text(line) != line and not findings:
        findings.append(Finding(category="redaction_delta", line_number=line_number))
    return findings


def build_log_redaction_sample_report(
    *,
    text: str,
    source_label: str = "log_sample",
    max_findings: int = 20,
) -> dict[str, Any]:
    """Return a redacted log redaction sample report."""

    lines = text.splitlines()
    findings: list[Finding] = []
    for line_number, line in enumerate(lines, start=1):
        findings.extend(_scan_line(line, line_number))

    category_counts: dict[str, int] = {}
    for finding in findings:
        category_counts[finding.category] = category_counts.get(finding.category, 0) + 1

    sampled = [
        {
            "category": finding.category,
            "line_number": finding.line_number,
            "raw_line_echoed": False,
        }
        for finding in findings[:max_findings]
    ]
    status = "blocked" if findings else "passed"
    return {
        "version": LOG_REDACTION_SAMPLE_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "raw_log_lines_echoed": False,
            "records_raw_log_text": False,
            "source_label_echoed": False,
        },
        "source": {
            "label": source_label,
            "label_echoed": False,
        },
        "line_count": len(lines),
        "finding_count": len(findings),
        "category_counts": dict(sorted(category_counts.items())),
        "sampled_findings": sampled,
        "declaration_statuses": {
            "ZHIXING_LOG_REDACTION_SAMPLE_STATUS": "passed" if status == "passed" else "blocked"
        },
        "blocked_reasons": sampled if status == "blocked" else [],
        "not_proven_by_this_report": [
            "This is a sampled log scan, not full log retention or SIEM coverage.",
            "The report does not print raw logs and does not prove logs are retained long term.",
            "A passed sample does not prove every future log path is safe.",
        ],
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=_path_arg, default=None, help="Optional UTF-8 log sample file.")
    parser.add_argument("--stdin", action="store_true", help="Read log sample from stdin.")
    parser.add_argument("--source-label", default="log_sample", help="Redacted source label for the report.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output file.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    text = _read_text(input_file=args.input, use_stdin=args.stdin)
    report = build_log_redaction_sample_report(
        text=text,
        source_label=args.source_label,
    )
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print("wrote output")
    else:
        print(output_text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
