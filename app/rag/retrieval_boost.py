"""Query-aware ranking boosts for RAG retrieval candidates."""
from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any, Mapping


_CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]{4,}")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")
_DESTINATION_VALUE_SPLIT_RE = re.compile(r"[|,，、;/；]+")
_DESTINATION_TITLE_RE = re.compile(
    r"^\s*(?P<destination>[\u4e00-\u9fff]{2,16}?)"
    r"(?:公开)?(?:目的地(?:知识)?(?:样例|指南)|(?:旅游|旅行|自由行)攻略)\s*$"
)
_DESTINATION_HEADING_RE = re.compile(
    r"(?m)^\s*#{1,3}\s*(?P<destination>[\u4e00-\u9fff]{2,16}?)"
    r"(?:旅游|旅行|自由行)?攻略(?:\s*[（(].*)?\s*$"
)
_ADMINISTRATIVE_SUFFIXES = (
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "特别行政区",
    "自治区",
    "省",
    "市",
)

_FORMAT_MODALITY = {
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "webp": "image",
    "gif": "image",
    "bmp": "image",
    "tif": "image",
    "tiff": "image",
    "mp3": "audio",
    "wav": "audio",
    "m4a": "audio",
    "aac": "audio",
    "flac": "audio",
    "ogg": "audio",
    "mp4": "video",
    "mov": "video",
    "avi": "video",
    "mkv": "video",
    "webm": "video",
}

_MODALITY_HINTS = {
    "image": (
        "图片",
        "照片",
        "图像",
        "配图",
        "地图",
        "截图",
        "示意图",
        "看图",
        "ocr",
        "image",
        "photo",
        "jpg",
        "jpeg",
        "png",
        "webp",
    ),
    "audio": (
        "音频",
        "录音",
        "语音",
        "转写",
        "导览音频",
        "讲解音频",
        "audio",
        "mp3",
        "wav",
        "ogg",
    ),
    "video": (
        "视频",
        "短片",
        "录像",
        "字幕",
        "抽帧",
        "画面",
        "video",
        "mp4",
        "webm",
        "vtt",
        "srt",
    ),
}


def infer_query_modalities(query: str) -> set[str]:
    """Infer explicit media modalities requested by a query."""

    normalized = str(query or "").lower()
    return {
        modality
        for modality, hints in _MODALITY_HINTS.items()
        if any(hint in normalized for hint in hints)
    }


def document_modality(metadata: Mapping[str, Any]) -> str:
    """Return a normalized modality for a knowledge document."""

    declared = str(metadata.get("content_modality") or "").strip().lower()
    if declared:
        return declared
    source_format = str(metadata.get("source_format") or "").strip().lower()
    return _FORMAT_MODALITY.get(source_format, "text")


def _destination_aliases(value: object) -> set[str]:
    normalized = "".join(str(value or "").strip().lower().split())
    normalized = normalized.strip("#：:，,。；;、（）()[]【】")
    if len(normalized) < 2:
        return set()

    aliases = {normalized}
    for suffix in _ADMINISTRATIVE_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
            aliases.add(normalized[: -len(suffix)])
            break
    return aliases


def document_destination_aliases(
    metadata: Mapping[str, Any],
    page_content: str,
) -> set[str]:
    """Extract normalized destination labels declared by one document."""

    aliases: set[str] = set()
    raw_destination = metadata.get("destination")
    values: Iterable[object]
    if isinstance(raw_destination, (list, tuple, set)):
        values = raw_destination
    else:
        values = _DESTINATION_VALUE_SPLIT_RE.split(str(raw_destination or ""))
    for value in values:
        aliases.update(_destination_aliases(value))

    title_match = _DESTINATION_TITLE_RE.match(str(metadata.get("title") or ""))
    if title_match:
        aliases.update(_destination_aliases(title_match.group("destination")))

    is_destination_guide = (
        str(metadata.get("category") or "") == "destinations"
        or str(metadata.get("source_type") or "") == "destination_guide"
    )
    if is_destination_guide:
        heading_match = _DESTINATION_HEADING_RE.search(str(page_content or "")[:500])
        if heading_match:
            aliases.update(_destination_aliases(heading_match.group("destination")))
    return aliases


def explicit_query_destinations(
    query: str,
    documents: Iterable[tuple[Mapping[str, Any], str]],
) -> set[str]:
    """Find destination labels explicitly named by a query in this corpus."""

    normalized_query = "".join(str(query or "").lower().split())
    known_aliases = {
        alias
        for metadata, page_content in documents
        for alias in document_destination_aliases(metadata, page_content)
    }
    return {alias for alias in known_aliases if alias in normalized_query}


def destination_match_priority(
    query_destinations: set[str],
    *,
    metadata: Mapping[str, Any],
    page_content: str,
) -> int:
    """Rank exact destination hits before generic and cross-city candidates."""

    if not query_destinations:
        return 1
    document_destinations = document_destination_aliases(metadata, page_content)
    if document_destinations & query_destinations:
        return 0
    return 2 if document_destinations else 1


def _query_phrases(query: str) -> set[str]:
    normalized = str(query or "").lower()
    phrases = set(_ASCII_TOKEN_RE.findall(normalized))
    for match in _CHINESE_RUN_RE.finditer(normalized):
        run = match.group(0)
        max_size = min(len(run), 8)
        for size in range(4, max_size + 1):
            for index in range(0, len(run) - size + 1):
                phrases.add(run[index : index + size])
    return phrases


def query_document_boost(
    query: str,
    *,
    metadata: Mapping[str, Any],
    page_content: str,
) -> float:
    """Return a small normalized relevance boost for candidate ordering."""

    boost = 0.0
    modality_hints = infer_query_modalities(query)
    modality = document_modality(metadata)
    if modality in modality_hints:
        boost += 0.8

    source_format = str(metadata.get("source_format") or "").strip().lower()
    if source_format and source_format in str(query or "").lower():
        boost += 0.2

    normalized_query = "".join(str(query or "").lower().split())
    if any(
        destination in normalized_query
        for destination in document_destination_aliases(metadata, page_content)
    ):
        boost += 1.0

    haystack_parts = [
        str(page_content or ""),
        str(metadata.get("title") or ""),
        str(metadata.get("source") or ""),
        source_format,
        modality,
    ]
    haystack = "\n".join(haystack_parts).lower()
    phrase_hits = [phrase for phrase in _query_phrases(query) if phrase in haystack]
    if phrase_hits:
        boost += min(0.8, sum(min(len(phrase), 8) / 40 for phrase in phrase_hits))

    return boost
