"""Transcribe a media file with faster-whisper for RAG multimodal ingestion.

The script prints transcript text to stdout by default, matching the
RAG_MULTIMODAL_TRANSCRIPT_COMMAND contract. It keeps model files in .runtime by
default so downloaded ASR artifacts stay outside Git.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class WhisperTranscriptionConfig:
    """Runtime options for local ASR transcription."""

    model_size: str
    device: str
    compute_type: str
    model_cache: Path
    language: str | None
    beam_size: int
    vad_filter: bool
    local_files_only: bool


def faster_whisper_available() -> bool:
    """Return whether faster-whisper is importable in the current environment."""

    return importlib.util.find_spec("faster_whisper") is not None


def default_model_cache_path() -> Path:
    configured = os.getenv("RAG_WHISPER_MODEL_CACHE", ".runtime/rag_whisper_models")
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def default_transcription_config() -> WhisperTranscriptionConfig:
    language = os.getenv("RAG_WHISPER_LANGUAGE", "").strip() or None
    return WhisperTranscriptionConfig(
        model_size=os.getenv("RAG_WHISPER_MODEL_SIZE", "tiny").strip() or "tiny",
        device=os.getenv("RAG_WHISPER_DEVICE", "cpu").strip() or "cpu",
        compute_type=os.getenv("RAG_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
        model_cache=default_model_cache_path(),
        language=language,
        beam_size=int(os.getenv("RAG_WHISPER_BEAM_SIZE", "1")),
        vad_filter=os.getenv("RAG_WHISPER_VAD_FILTER", "").strip().lower()
        in {"1", "true", "yes", "on"},
        local_files_only=os.getenv("RAG_WHISPER_LOCAL_FILES_ONLY", "").strip().lower()
        in {"1", "true", "yes", "on"},
    )


def _coerce_segment(segment: Any) -> dict[str, Any]:
    return {
        "start": float(getattr(segment, "start", 0.0) or 0.0),
        "end": float(getattr(segment, "end", 0.0) or 0.0),
        "text": str(getattr(segment, "text", "") or "").strip(),
    }


def _info_payload(info: Any) -> dict[str, Any]:
    return {
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
    }


def transcribe_media(
    path: Path,
    config: WhisperTranscriptionConfig | None = None,
    *,
    model_factory: Callable[[WhisperTranscriptionConfig], Any] | None = None,
) -> dict[str, Any]:
    """Return transcript text and segment metadata for one audio or video file."""

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    config = config or default_transcription_config()
    config.model_cache.mkdir(parents=True, exist_ok=True)

    if model_factory is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed; run `uv sync` or install project dependencies."
            ) from exc

        model = WhisperModel(
            config.model_size,
            device=config.device,
            compute_type=config.compute_type,
            download_root=str(config.model_cache),
            local_files_only=config.local_files_only,
        )
    else:
        model = model_factory(config)

    segments_iter, info = model.transcribe(
        str(path),
        language=config.language,
        beam_size=config.beam_size,
        vad_filter=config.vad_filter,
    )
    segments = [
        segment
        for segment in (_coerce_segment(item) for item in segments_iter)
        if str(segment.get("text") or "").strip()
    ]
    text = "\n".join(str(segment["text"]).strip() for segment in segments).strip()
    return {
        "text": text,
        "segments": segments,
        "model": config.model_size,
        "device": config.device,
        "compute_type": config.compute_type,
        "model_cache": str(config.model_cache),
        "info": _info_payload(info),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Audio or video file path.")
    parser.add_argument(
        "--model-size",
        default=default_transcription_config().model_size,
        help="Whisper model size or local model path. Default: RAG_WHISPER_MODEL_SIZE or tiny.",
    )
    parser.add_argument(
        "--device",
        default=default_transcription_config().device,
        help="Inference device. Default: RAG_WHISPER_DEVICE or cpu.",
    )
    parser.add_argument(
        "--compute-type",
        default=default_transcription_config().compute_type,
        help="CTranslate2 compute type. Default: RAG_WHISPER_COMPUTE_TYPE or int8.",
    )
    parser.add_argument(
        "--model-cache",
        type=Path,
        default=default_model_cache_path(),
        help="Model download/cache directory. Default: RAG_WHISPER_MODEL_CACHE or .runtime/rag_whisper_models.",
    )
    parser.add_argument(
        "--language",
        default=default_transcription_config().language,
        help="Optional language code such as zh or en. Empty means auto-detect.",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=default_transcription_config().beam_size,
        help="Beam size for decoding. Default: RAG_WHISPER_BEAM_SIZE or 1.",
    )
    parser.add_argument(
        "--vad-filter",
        action="store_true",
        default=default_transcription_config().vad_filter,
        help="Enable voice activity detection before transcription.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        default=default_transcription_config().local_files_only,
        help="Do not download model files; use local cache only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print transcript, segments, model and language metadata as JSON.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    config = WhisperTranscriptionConfig(
        model_size=args.model_size,
        device=args.device,
        compute_type=args.compute_type,
        model_cache=args.model_cache if args.model_cache.is_absolute() else PROJECT_ROOT / args.model_cache,
        language=args.language.strip() if isinstance(args.language, str) and args.language.strip() else None,
        beam_size=max(1, args.beam_size),
        vad_filter=bool(args.vad_filter),
        local_files_only=bool(args.local_files_only),
    )

    try:
        result = transcribe_media(args.input, config)
    except Exception as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["text"]:
        print(result["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
