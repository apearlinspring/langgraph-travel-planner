"""Report contract, validation, and rendering helpers."""
from app.reports.builder import ReportBundle, build_report_bundle
from app.reports.contracts import (
    REPORT_SECTION_IDS,
    REPORT_SECTIONS,
    REPORT_VERSION,
    REQUIRED_REPORT_SECTION_IDS,
    REQUIRED_REPORT_TOP_LEVEL_KEYS,
    report_sections,
)
from app.reports.render_markdown import render_report_markdown
from app.reports.validators import ReportValidationResult, validate_report_data

__all__ = [
    "REPORT_SECTION_IDS",
    "REPORT_SECTIONS",
    "REPORT_VERSION",
    "REQUIRED_REPORT_SECTION_IDS",
    "REQUIRED_REPORT_TOP_LEVEL_KEYS",
    "ReportBundle",
    "ReportValidationResult",
    "build_report_bundle",
    "render_report_markdown",
    "report_sections",
    "validate_report_data",
]
