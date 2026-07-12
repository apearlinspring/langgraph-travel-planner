"""Knowledge document extraction helpers for text and multimodal files."""
from __future__ import annotations

import csv
import html
import json
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    import yaml
except Exception:  # pragma: no cover - minimal dependency shells
    yaml = None


TEXT_DOCUMENT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".json",
    ".csv",
    ".html",
    ".htm",
    ".docx",
    ".pdf",
}
IMAGE_DOCUMENT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
AUDIO_DOCUMENT_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_DOCUMENT_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MULTIMODAL_DOCUMENT_EXTENSIONS = (
    IMAGE_DOCUMENT_EXTENSIONS | AUDIO_DOCUMENT_EXTENSIONS | VIDEO_DOCUMENT_EXTENSIONS
)
SUPPORTED_KNOWLEDGE_EXTENSIONS = TEXT_DOCUMENT_EXTENSIONS | MULTIMODAL_DOCUMENT_EXTENSIONS
SIDECAR_EXTENSIONS = {".md", ".txt", ".json", ".srt", ".vtt", ".lrc"}


@dataclass(frozen=True)
class ExtractedKnowledgeDocument:
    """Text representation and metadata extracted from one knowledge file."""

    text: str
    metadata: dict[str, Any]
    modality: str
    source_format: str
    extraction_method: str
    sidecar_source: str | None = None


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def text(self) -> str:
        return "\n".join(self._parts)


def is_supported_knowledge_file(path: Path) -> bool:
    """Return whether a file can be represented for RAG indexing."""

    return path.is_file() and path.suffix.lower() in SUPPORTED_KNOWLEDGE_EXTENSIONS


def is_sidecar_document(path: Path) -> bool:
    """Return True for files such as photo.jpg.md that describe another asset."""

    if path.suffix.lower() not in SIDECAR_EXTENSIONS:
        return False
    return Path(path.stem).suffix.lower() in SUPPORTED_KNOWLEDGE_EXTENSIONS


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.lstrip("\ufeff")
    lines = normalized.splitlines(keepends=True)
    if lines and lines[0].strip() == "u---":
        lines[0] = lines[0].replace("u---", "---", 1)
        normalized = "".join(lines)
    if not normalized.startswith("---"):
        return {}, normalized

    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, normalized

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return {}, normalized

    raw_metadata = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :]).lstrip()
    if yaml is not None:
        loaded = yaml.safe_load(raw_metadata) or {}
        metadata = loaded if isinstance(loaded, dict) else {}
    else:
        metadata = {}
        for line in raw_metadata.splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("'\"")
    return dict(metadata), body


def _json_to_text(value: Any, *, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if key in {"metadata", "front_matter"}:
                continue
            next_prefix = f"{prefix}{key}: " if not prefix else f"{prefix}.{key}: "
            lines.extend(_json_to_text(item, prefix=next_prefix))
        return lines
    if isinstance(value, list):
        lines: list[str] = []
        for index, item in enumerate(value, start=1):
            lines.extend(_json_to_text(item, prefix=f"{prefix}{index}. "))
        return lines
    text = str(value or "").strip()
    return [f"{prefix}{text}".strip()] if text else []


def _extract_json(path: Path) -> tuple[dict[str, Any], str]:
    payload = json.loads(_read_text(path))
    if isinstance(payload, dict):
        metadata = payload.get("metadata") or payload.get("front_matter") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        content = (
            payload.get("content")
            or payload.get("body")
            or payload.get("text")
            or payload.get("description")
            or payload.get("transcript")
        )
        if content is not None:
            return dict(metadata), str(content)
        return dict(metadata), "\n".join(_json_to_text(payload))
    return {}, "\n".join(_json_to_text(payload))


def _extract_csv(path: Path) -> str:
    text = _read_text(path)
    rows = csv.reader(text.splitlines())
    lines = []
    for row in rows:
        values = [cell.strip() for cell in row if cell.strip()]
        if values:
            lines.append(" | ".join(values))
    return "\n".join(lines)


def _extract_html(path: Path) -> str:
    parser = _HTMLTextParser()
    parser.feed(_read_text(path))
    return html.unescape(parser.text())


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            raw_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return ""
    root = ElementTree.fromstring(raw_xml)
    paragraphs: list[str] = []
    current: list[str] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t" and node.text:
            current.append(node.text)
        elif tag == "p" and current:
            paragraphs.append("".join(current).strip())
            current = []
    if current:
        paragraphs.append("".join(current).strip())
    return "\n".join(item for item in paragraphs if item)


def _extract_pdf(path: Path) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        fitz = None
    if fitz is not None:
        try:
            with fitz.open(path) as document:
                return "\n".join(page.get_text("text") for page in document)
        except Exception:
            return ""

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _sidecar_candidates(path: Path) -> list[Path]:
    names = [
        path.with_name(path.name + ".md"),
        path.with_name(path.name + ".txt"),
        path.with_name(path.name + ".json"),
        path.with_name(path.name + ".srt"),
        path.with_name(path.name + ".vtt"),
        path.with_name(path.name + ".lrc"),
        path.with_suffix(".md"),
        path.with_suffix(".txt"),
        path.with_suffix(".json"),
        path.with_suffix(".srt"),
        path.with_suffix(".vtt"),
        path.with_suffix(".lrc"),
    ]
    unique: list[Path] = []
    for candidate in names:
        if candidate == path or candidate in unique:
            continue
        unique.append(candidate)
    return unique


def _load_sidecar(path: Path) -> tuple[str, dict[str, Any], Path | None]:
    for candidate in _sidecar_candidates(path):
        if not candidate.exists() or not candidate.is_file():
            continue
        suffix = candidate.suffix.lower()
        if suffix == ".json":
            metadata, text = _extract_json(candidate)
            return text, metadata, candidate
        metadata, body = _parse_front_matter(_read_text(candidate))
        return body, metadata, candidate
    return "", {}, None


def _modality_for_suffix(suffix: str) -> str:
    if suffix in IMAGE_DOCUMENT_EXTENSIONS:
        return "image"
    if suffix in AUDIO_DOCUMENT_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_DOCUMENT_EXTENSIONS:
        return "video"
    return "text"


def _multimodal_placeholder(path: Path, modality: str, text: str, metadata: dict[str, Any]) -> str:
    title = str(metadata.get("title") or path.stem).strip()
    media_label = {"image": "图片", "audio": "音频", "video": "视频"}.get(modality, "多模态")
    parts = [
        f"# {title}",
        f"文件类型：{media_label}",
        f"文件名：{path.name}",
    ]
    if text.strip():
        parts.extend(["", text.strip()])
    else:
        parts.extend(
            [
                "",
                "该多模态文件尚未提供可检索说明、字幕、转写或图像描述；当前仅按文件名和元数据参与召回。",
            ]
        )
    return "\n".join(parts)


def extract_knowledge_document(
    path: Path,
    *,
    auto_extract: bool = True,
) -> ExtractedKnowledgeDocument:
    """Extract a text representation from one supported knowledge file."""

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise ValueError(f"Unsupported knowledge document format: {path.suffix}")

    metadata: dict[str, Any] = {}
    sidecar_source: Path | None = None
    extraction_method = "plain_text"

    if suffix in {".md", ".markdown", ".txt", ".text", ".rst"}:
        metadata, text = _parse_front_matter(_read_text(path))
        extraction_method = "front_matter_text" if metadata else "plain_text"
    elif suffix == ".json":
        metadata, text = _extract_json(path)
        extraction_method = "json_text"
    elif suffix == ".csv":
        text = _extract_csv(path)
        extraction_method = "csv_text"
    elif suffix in {".html", ".htm"}:
        metadata, text = _parse_front_matter(_extract_html(path))
        extraction_method = "html_text"
    elif suffix == ".docx":
        text = _extract_docx(path)
        metadata, sidecar_metadata, sidecar_source = {}, {}, None
        sidecar_text, sidecar_metadata, sidecar_source = _load_sidecar(path)
        metadata.update(sidecar_metadata)
        if sidecar_text:
            text = f"{text}\n\n{sidecar_text}".strip()
        extraction_method = "docx_text"
    elif suffix == ".pdf":
        pdf_text = _extract_pdf(path)
        text = pdf_text
        sidecar_text, sidecar_metadata, sidecar_source = _load_sidecar(path)
        metadata.update(sidecar_metadata)
        if sidecar_text:
            text = f"{text}\n\n{sidecar_text}".strip()
        extraction_method = "pdf_text" if pdf_text.strip() else "pdf_sidecar"
    else:
        modality = _modality_for_suffix(suffix)
        sidecar_text, metadata, sidecar_source = _load_sidecar(path)
        auto_result = None
        if auto_extract:
            try:
                from app.rag.multimodal_extractor import extract_multimodal_text

                auto_result = extract_multimodal_text(path)
            except Exception:
                auto_result = None

        sections: list[str] = []
        if sidecar_text.strip():
            sections.append("## 人工说明或转写\n" + sidecar_text.strip())
        if auto_result is not None:
            metadata.update(auto_result.metadata)
            metadata["auto_extraction_method"] = auto_result.extraction_method
            if auto_result.text.strip():
                sections.append("## 自动多模态抽取\n" + auto_result.text.strip())

        text = _multimodal_placeholder(path, modality, "\n\n".join(sections), metadata)
        extraction_method = (
            auto_result.extraction_method
            if auto_result is not None and auto_result.ok
            else f"{modality}_sidecar" if sidecar_source else f"{modality}_metadata"
        )

    if suffix in MULTIMODAL_DOCUMENT_EXTENSIONS:
        modality = _modality_for_suffix(suffix)
    else:
        modality = "text"

    normalized_text = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    return ExtractedKnowledgeDocument(
        text=normalized_text,
        metadata=metadata,
        modality=modality,
        source_format=suffix.lstrip("."),
        extraction_method=extraction_method,
        sidecar_source=str(sidecar_source) if sidecar_source else None,
    )
