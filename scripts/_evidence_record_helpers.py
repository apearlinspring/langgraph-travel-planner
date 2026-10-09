"""Shared primitives for private evidence-record checker scripts."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
from pathlib import Path
from typing import Any


READY_VALUES = frozenset(
    {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
)
PLACEHOLDER_VALUES = frozenset({"", "unknown", "tbd", "null", "none", "n/a", "na"})


def make_path_arg(project_root: Path) -> Callable[[str], Path]:
    def path_arg(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else project_root / path

    return path_arg


def make_json_object_reader(
    *,
    object_error: str,
    read_error: str | None = None,
    encoding: str = "utf-8-sig",
) -> Callable[[Path], dict[str, Any]]:
    def read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding=encoding))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if read_error is None:
                raise
            raise ValueError(read_error.format(path=path)) from exc
        if not isinstance(payload, dict):
            raise ValueError(object_error)
        return payload

    return read_json


def read_optional_json_object(
    path: Path | None,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, {
            "key": f"missing_{label}",
            "finding": f"{label} JSON path is required.",
            "path_echoed": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {
            "key": f"unreadable_{label}",
            "finding": f"{label} JSON could not be read.",
            "path_echoed": False,
        }
    if not isinstance(payload, dict):
        return None, {
            "key": f"invalid_{label}",
            "finding": f"{label} JSON must be an object.",
            "path_echoed": False,
        }
    return payload, None


def has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def make_placeholder_checker(
    *,
    prefixes: Iterable[str],
    fragments: Iterable[str],
) -> Callable[[Any], bool]:
    prefix_values = tuple(prefixes)
    fragment_values = tuple(fragments)

    def looks_placeholder(value: Any) -> bool:
        lowered = str(value or "").strip().strip("'\"").lower()
        return (
            lowered in PLACEHOLDER_VALUES
            or any(lowered.startswith(prefix) for prefix in prefix_values)
            or any(fragment in lowered for fragment in fragment_values)
        )

    return looks_placeholder


def make_final_text_checker(looks_placeholder: Callable[[Any], bool]) -> Callable[[Any], bool]:
    def has_final_text(value: Any) -> bool:
        return has_text(value) and not looks_placeholder(value)

    return has_final_text


def is_ready(value: Any) -> bool:
    return str(value or "").strip().lower() in READY_VALUES


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def blocker(check: str, field: str, finding: str) -> dict[str, str]:
    return {"check": check, "field": field, "finding": finding}


def status_from_checks(
    checks: Mapping[str, Mapping[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    blockers = []
    for name, check in checks.items():
        if check.get("status") != "blocked":
            continue
        for item in check.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                blockers.append({"check": name, **dict(item)})
        if not check.get("blocked_reasons"):
            blockers.append({"check": name, "finding": check.get("finding") or "blocked"})
    return ("blocked" if blockers else "passed", blockers)
