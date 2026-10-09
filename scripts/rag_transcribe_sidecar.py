"""Print transcript text from a media file sidecar.

This script is a deterministic smoke-test transcript command for RAG multimodal
ingestion. It does not perform speech recognition; production ASR can replace
it as long as the command prints transcript text to stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SIDECAR_EXTENSIONS = (".md", ".txt", ".json", ".srt", ".vtt", ".lrc")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sidecar_candidates(path: Path) -> list[Path]:
    candidates = []
    for suffix in SIDECAR_EXTENSIONS:
        candidates.append(path.with_name(path.name + suffix))
    for suffix in SIDECAR_EXTENSIONS:
        candidates.append(path.with_suffix(suffix))

    unique: list[Path] = []
    for candidate in candidates:
        if candidate != path and candidate not in unique:
            unique.append(candidate)
    return unique


def _strip_front_matter(text: str) -> str:
    normalized = text.lstrip("\ufeff")
    if not normalized.startswith("---"):
        return normalized
    lines = normalized.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip()
    return normalized


def _json_to_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        preferred = (
            value.get("transcript")
            or value.get("text")
            or value.get("content")
            or value.get("body")
            or value.get("description")
        )
        if preferred is not None:
            return [str(preferred)]
        lines: list[str] = []
        for key, item in value.items():
            if key in {"metadata", "front_matter"}:
                continue
            lines.extend(_json_to_text(item))
        return lines
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_json_to_text(item))
        return lines
    text = str(value or "").strip()
    return [text] if text else []


def _parse_json(text: str) -> str:
    payload = json.loads(text)
    return "\n".join(item for item in _json_to_text(payload) if item.strip())


def _strip_timed_text(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.upper() == "WEBVTT":
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _strip_lrc(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\[[0-9:.]+\]", "", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def extract_sidecar_transcript(path: Path) -> tuple[Path | None, str]:
    """Return the sidecar path and transcript text for a media file."""

    for candidate in _sidecar_candidates(path):
        if not candidate.exists() or not candidate.is_file():
            continue
        suffix = candidate.suffix.lower()
        text = _read_text(candidate)
        if suffix == ".json":
            return candidate, _parse_json(text)
        if suffix in {".srt", ".vtt"}:
            return candidate, _strip_timed_text(text)
        if suffix == ".lrc":
            return candidate, _strip_lrc(text)
        return candidate, _strip_front_matter(text).strip()
    return None, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Media file path.")
    parser.add_argument(
        "--show-source",
        action="store_true",
        help="Prefix output with the sidecar file path for manual debugging.",
    )
    args = parser.parse_args()

    sidecar, transcript = extract_sidecar_transcript(args.input)
    if args.show_source and sidecar is not None:
        print(f"source: {sidecar}")
    if transcript:
        print(transcript)
    return 0


if __name__ == "__main__":
    sys.exit(main())
