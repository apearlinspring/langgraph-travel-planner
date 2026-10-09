"""Shared primitives for deterministic evaluation scoring and value coercion."""

from __future__ import annotations

from typing import Any


def grade(normalized_score: float) -> str:
    """Convert a normalized score to the project's common letter grade."""
    if normalized_score >= 90:
        return "A"
    if normalized_score >= 80:
        return "B"
    if normalized_score >= 70:
        return "C"
    if normalized_score >= 60:
        return "D"
    return "F"


def score(
    condition: bool,
    points: float,
    findings: list[str],
    message: str,
) -> float:
    """Award points when a condition passes, otherwise record its finding."""
    if condition:
        return points
    findings.append(message)
    return 0.0


def as_float(value: Any) -> float | None:
    """Return a real numeric value as ``float`` while rejecting booleans."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def as_int(value: Any) -> int | None:
    """Return an integer value while rejecting booleans."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def as_dict(value: Any) -> dict[str, Any]:
    """Return dictionaries unchanged and coerce other values to an empty mapping."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Return lists unchanged and coerce other values to an empty list."""
    return value if isinstance(value, list) else []


def has_text(value: Any) -> bool:
    """Return whether a value is a non-blank string."""
    return isinstance(value, str) and bool(value.strip())
