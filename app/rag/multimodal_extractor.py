"""Optional multimodal extraction for RAG knowledge assets."""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from app.config import PROJECT_ROOT, has_real_env_value, settings
from app.rag.document_formats import (
    AUDIO_DOCUMENT_EXTENSIONS,
    IMAGE_DOCUMENT_EXTENSIONS,
    VIDEO_DOCUMENT_EXTENSIONS,
)
from app.utils.llm_factory import build_chat_model, resolve_model_name
from app.utils.logger import app_logger


MULTIMODAL_EXTRACTION_VERSION = "rag.multimodal_extraction.v1"


@dataclass(frozen=True)
class MultimodalExtractionResult:
    """Text and diagnostics produced from a non-text knowledge asset."""

    text: str
    extraction_method: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def multimodal_auto_extract_enabled() -> bool:
    """Return whether automatic multimodal extraction should run."""

    return _env_bool(
        "RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT",
        bool(getattr(settings, "rag_enable_multimodal_auto_extract", False)),
    )


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _cache_dir() -> Path:
    path = resolve_multimodal_cache_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_multimodal_cache_path() -> Path:
    """Return the configured multimodal cache path without creating it."""

    configured = os.getenv(
        "RAG_MULTIMODAL_CACHE_PATH",
        getattr(settings, "rag_multimodal_cache_path", ".runtime/rag_multimodal_cache"),
    )
    return _resolve_project_path(configured)


def resolve_transcript_command_template() -> str:
    """Return the trusted transcript command template, if configured."""

    return os.getenv(
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
        getattr(settings, "rag_multimodal_transcript_command", ""),
    ).strip()


def find_ffmpeg() -> str | None:
    """Find an ffmpeg executable from explicit config, PATH, or local tool folders."""

    configured = os.getenv(
        "RAG_FFMPEG_PATH",
        getattr(settings, "rag_ffmpeg_path", ""),
    ).strip()
    candidates: list[str] = []
    if configured:
        candidates.append(str(_resolve_project_path(configured)))

    path_match = shutil.which("ffmpeg")
    if path_match:
        candidates.append(path_match)

    local_names = [
        ".runtime/tools/ffmpeg/ffmpeg.exe",
        ".runtime/tools/ffmpeg/bin/ffmpeg.exe",
        ".runtime/bin/ffmpeg.exe",
        "tools/ffmpeg/ffmpeg.exe",
        "tools/ffmpeg/bin/ffmpeg.exe",
    ]
    candidates.extend(str(PROJECT_ROOT / name) for name in local_names)

    try:
        import imageio_ffmpeg  # type: ignore
    except Exception:
        imageio_ffmpeg = None
    if imageio_ffmpeg is not None:
        try:
            candidates.append(str(imageio_ffmpeg.get_ffmpeg_exe()))
        except Exception:
            pass

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_key(path: Path, *, method: str) -> str:
    model = resolve_model_name(profile="vision")
    payload = {
        "version": MULTIMODAL_EXTRACTION_VERSION,
        "method": method,
        "model": model,
        "source": path.name,
        "digest": _file_digest(path),
    }
    if method in {"audio_transcript_command", "video_keyframe_vision"}:
        command_digest = hashlib.sha256(
            resolve_transcript_command_template().encode("utf-8", errors="ignore")
        ).hexdigest()
        payload["transcript_command_digest"] = command_digest
    if method == "video_keyframe_vision":
        payload["video_frame_count"] = os.getenv(
            "RAG_MULTIMODAL_VIDEO_FRAME_COUNT",
            str(getattr(settings, "rag_multimodal_video_frame_count", 3)),
        )
        payload["video_frame_width"] = os.getenv(
            "RAG_MULTIMODAL_VIDEO_FRAME_WIDTH",
            str(getattr(settings, "rag_multimodal_video_frame_width", 640)),
        )
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _read_cache(path: Path, *, method: str) -> MultimodalExtractionResult | None:
    cache_path = _cache_dir() / f"{_cache_key(path, method=method)}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return MultimodalExtractionResult(
            text=str(payload.get("text") or ""),
            extraction_method=str(payload.get("extraction_method") or method),
            metadata=dict(payload.get("metadata") or {}),
        )
    except Exception as exc:
        app_logger.warning(f"多模态抽取缓存读取失败: {cache_path} {exc}")
        return None


def _write_cache(path: Path, *, result: MultimodalExtractionResult) -> None:
    cache_path = _cache_dir() / f"{_cache_key(path, method=result.extraction_method)}.json"
    payload = {
        "version": MULTIMODAL_EXTRACTION_VERSION,
        "text": result.text,
        "extraction_method": result.extraction_method,
        "metadata": result.metadata,
    }
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _describe_image_with_vision(path: Path) -> str:
    if not has_real_env_value(settings.dashscope_api_key):
        raise RuntimeError("DASHSCOPE_API_KEY is not configured for vision extraction")

    max_bytes = int(
        os.getenv(
            "RAG_MULTIMODAL_MAX_IMAGE_BYTES",
            str(getattr(settings, "rag_multimodal_max_image_bytes", 6_000_000)),
        )
    )
    if path.stat().st_size > max_bytes:
        raise RuntimeError(
            f"image is larger than RAG_MULTIMODAL_MAX_IMAGE_BYTES={max_bytes}"
        )

    model = build_chat_model(profile="vision", temperature=0, max_tokens=900)
    prompt = (
        "你是旅游知识库的多模态资料整理员。请阅读这张图片，输出适合 RAG 检索的中文资料。"
        "要求包含：1) 图片整体描述；2) 可见文字/OCR；3) 目的地、景点、交通、酒店、餐饮、"
        "预算、风险等可用于旅行规划的事实；4) 不确定内容标注为待核验。不要编造看不见的信息。"
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _image_data_url(path)}},
        ]
    )
    response = model.invoke([message])
    return str(response.content or "").strip()


def extract_image_text(path: Path) -> MultimodalExtractionResult:
    """Describe one image using the configured vision model."""

    cached = _read_cache(path, method="image_vision")
    if cached is not None:
        metadata = dict(cached.metadata)
        metadata["multimodal_cache_hit"] = "true"
        return MultimodalExtractionResult(
            text=cached.text,
            extraction_method=cached.extraction_method,
            metadata=metadata,
        )

    try:
        text = _describe_image_with_vision(path)
    except Exception as exc:
        return MultimodalExtractionResult(
            text="",
            extraction_method="image_vision",
            metadata={
                "multimodal_auto_extract_status": "failed",
                "multimodal_auto_extract_error": exc.__class__.__name__,
            },
        )

    result = MultimodalExtractionResult(
        text=text,
        extraction_method="image_vision",
        metadata={
            "multimodal_auto_extract_status": "success",
            "multimodal_cache_hit": "false",
            "vision_model": resolve_model_name(profile="vision"),
        },
    )
    _write_cache(path, result=result)
    return result


def _extract_video_keyframes(path: Path) -> list[Path]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not available for video keyframe extraction")

    frame_count = int(
        os.getenv(
            "RAG_MULTIMODAL_VIDEO_FRAME_COUNT",
            str(getattr(settings, "rag_multimodal_video_frame_count", 3)),
        )
    )
    frame_width = int(
        os.getenv(
            "RAG_MULTIMODAL_VIDEO_FRAME_WIDTH",
            str(getattr(settings, "rag_multimodal_video_frame_width", 640)),
        )
    )
    frame_count = max(1, min(frame_count, 8))
    frame_dir = _cache_dir() / "video_frames" / _file_digest(path)[:16]
    frame_dir.mkdir(parents=True, exist_ok=True)
    pattern = frame_dir / "frame_%03d.jpg"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-vf",
        f"thumbnail,scale={frame_width}:-1",
        "-frames:v",
        str(frame_count),
        str(pattern),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {completed.stderr[-300:]}")
    return sorted(frame_dir.glob("frame_*.jpg"))


def extract_video_text(path: Path) -> MultimodalExtractionResult:
    """Extract video keyframes and describe them with the vision model."""

    cached = _read_cache(path, method="video_keyframe_vision")
    if cached is not None:
        metadata = dict(cached.metadata)
        metadata["multimodal_cache_hit"] = "true"
        return MultimodalExtractionResult(
            text=cached.text,
            extraction_method=cached.extraction_method,
            metadata=metadata,
        )

    frame_texts: list[str] = []
    frame_error: str | None = None
    transcript = ""
    transcript_error: str | None = None

    try:
        frame_paths = _extract_video_keyframes(path)
        for index, frame_path in enumerate(frame_paths, start=1):
            frame_result = extract_image_text(frame_path)
            if frame_result.ok:
                frame_texts.append(f"关键帧 {index}：\n{frame_result.text}")
    except Exception as exc:
        frame_error = exc.__class__.__name__

    try:
        transcript = _run_transcript_command(path)
    except Exception as exc:
        transcript_error = exc.__class__.__name__

    parts = []
    if frame_texts:
        parts.append("## 视频关键帧自动描述\n" + "\n\n".join(frame_texts))
    if transcript:
        parts.append("## 视频转写文本\n" + transcript)
    text = "\n\n".join(parts).strip()
    status = "success" if text else "empty"
    if not text and (frame_error or transcript_error):
        status = "failed"
    metadata = {
        "multimodal_auto_extract_status": status,
        "multimodal_cache_hit": "false",
        "transcript_command_configured": "true"
        if resolve_transcript_command_template()
        else "false",
        "video_keyframe_count": str(len(frame_texts)),
        "vision_model": resolve_model_name(profile="vision"),
    }
    if frame_error:
        metadata["video_keyframe_error"] = frame_error
    if transcript_error:
        metadata["multimodal_transcript_error"] = transcript_error

    result = MultimodalExtractionResult(
        text=text,
        extraction_method="video_keyframe_vision",
        metadata=metadata,
    )
    if text:
        _write_cache(path, result=result)
    return result


def _run_transcript_command(path: Path) -> str:
    """Run an operator-configured trusted transcript command for audio or video."""

    template = resolve_transcript_command_template()
    if not template:
        return ""

    def _clean_part(value: str) -> str:
        stripped = value.strip()
        if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
            return stripped[1:-1]
        return stripped

    command = [
        _clean_part(part.replace("{input}", str(path)))
        for part in shlex.split(template, posix=os.name != "nt")
    ]
    if not command:
        return ""
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"transcript command failed: {completed.stderr[-300:]}")
    return completed.stdout.strip()


def extract_audio_text(path: Path) -> MultimodalExtractionResult:
    """Transcribe audio with an operator-configured trusted command."""

    cached = _read_cache(path, method="audio_transcript_command")
    if cached is not None:
        metadata = dict(cached.metadata)
        metadata["multimodal_cache_hit"] = "true"
        return MultimodalExtractionResult(
            text=cached.text,
            extraction_method=cached.extraction_method,
            metadata=metadata,
        )

    try:
        transcript = _run_transcript_command(path)
    except Exception as exc:
        return MultimodalExtractionResult(
            text="",
            extraction_method="audio_transcript_command",
            metadata={
                "multimodal_auto_extract_status": "failed",
                "multimodal_auto_extract_error": exc.__class__.__name__,
            },
        )
    result = MultimodalExtractionResult(
        text=transcript,
        extraction_method="audio_transcript_command",
        metadata={
            "multimodal_auto_extract_status": "success" if transcript else "empty",
            "multimodal_cache_hit": "false",
        },
    )
    if transcript:
        _write_cache(path, result=result)
    return result


def extract_multimodal_text(path: Path) -> MultimodalExtractionResult:
    """Extract searchable text from an image, audio, or video file when enabled."""

    if not multimodal_auto_extract_enabled():
        return MultimodalExtractionResult(
            text="",
            extraction_method="multimodal_disabled",
            metadata={"multimodal_auto_extract_status": "disabled"},
        )

    suffix = path.suffix.lower()
    if suffix in IMAGE_DOCUMENT_EXTENSIONS:
        return extract_image_text(path)
    if suffix in VIDEO_DOCUMENT_EXTENSIONS:
        return extract_video_text(path)
    if suffix in AUDIO_DOCUMENT_EXTENSIONS:
        return extract_audio_text(path)
    return MultimodalExtractionResult(
        text="",
        extraction_method="unsupported_multimodal",
        metadata={"multimodal_auto_extract_status": "unsupported"},
    )
