"""High-level structured report builder."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.reports.render_markdown import render_report_markdown
from app.reports.validators import ReportValidationResult, validate_report_data


@dataclass(frozen=True)
class ReportBundle:
    """A validated structured report and its Markdown rendering."""

    report_data: dict[str, Any]
    markdown: str
    validation: ReportValidationResult


def build_report_bundle(report_data: dict[str, Any]) -> ReportBundle:
    """Validate report_data and render Markdown from the same source payload."""

    validation = validate_report_data(report_data)
    markdown = render_report_markdown(report_data) if validation.ok else ""
    return ReportBundle(
        report_data=report_data,
        markdown=markdown,
        validation=validation,
    )
