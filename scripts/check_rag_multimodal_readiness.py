"""Check RAG multimodal extraction readiness."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

if "--json" in sys.argv:
    os.environ.setdefault("ZHIXING_SUPPRESS_CONSOLE_LOGS", "1")
if "--no-dotenv" in sys.argv:
    os.environ.setdefault("ZHIXING_DISABLE_DOTENV", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import has_real_env_value, settings  # noqa: E402
from app.rag.multimodal_extractor import (  # noqa: E402
    find_ffmpeg,
    multimodal_auto_extract_enabled,
    resolve_multimodal_cache_path,
    resolve_transcript_command_template,
)
from app.utils.llm_factory import resolve_model_name  # noqa: E402
from scripts.rag_transcribe_whisper import (  # noqa: E402
    default_transcription_config,
    faster_whisper_available,
)


RAG_MULTIMODAL_READINESS_VERSION = "rag_multimodal_readiness.v1"


def _status(value: bool) -> str:
    return "configured" if value else "not_configured"


def _redact_local_path(value: str | Path | None) -> str:
    """Return a path suitable for public readiness output."""

    if not value:
        return ""
    path = Path(str(value))
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT.resolve())
        display = str(relative).replace("\\", "/")
    except (OSError, ValueError):
        return "<external path redacted>"

    if display == ".runtime" or display.startswith(".runtime/"):
        return ".runtime/<redacted>"
    if display == ".venv" or display.startswith(".venv/"):
        return ".venv/<redacted>"
    if display == "data/vectorstore" or display.startswith("data/vectorstore/"):
        return "data/vectorstore/<redacted>"
    if display == "data/vectorstore_internal" or display.startswith(
        "data/vectorstore_internal/"
    ):
        return "data/vectorstore_internal/<redacted>"
    return display


def _summarize_e2e_acceptance(result: dict[str, object]) -> dict[str, object]:
    query_results = []
    for item in result.get("query_results") or []:
        if not isinstance(item, dict):
            continue
        hits = item.get("hits") or []
        first_hit = hits[0] if isinstance(hits, list) and hits else {}
        query_results.append(
            {
                "id": item.get("id"),
                "passed": item.get("passed"),
                "expected_hit_rank": item.get("expected_hit_rank"),
                "expected_hit_extraction_method": item.get("expected_hit_extraction_method"),
                "first_source": (first_hit or {}).get("source") if isinstance(first_hit, dict) else "",
                "latency_ms": ((item.get("trace") or {}).get("latency_ms") if isinstance(item.get("trace"), dict) else None),
            }
        )
    return {
        "status": result.get("status"),
        "passed": result.get("passed"),
        "loaded_from_disk": result.get("loaded_from_disk"),
        "document_count": result.get("document_count"),
        "parent_count": result.get("parent_count"),
        "child_count": result.get("child_count"),
        "root": _redact_local_path(str(result.get("root") or "")),
        "result_path": _redact_local_path(
            Path(str(result.get("root") or "")) / "acceptance_result.json"
        )
        if result.get("root")
        else "",
        "query_results": query_results,
    }


def _run_e2e_acceptance_check() -> dict[str, object]:
    from scripts.accept_rag_multimodal_e2e import (
        DEFAULT_ROOT,
        DEFAULT_SOURCE_DIR,
        AcceptanceBlocked,
        run_multimodal_e2e_acceptance,
    )

    root = PROJECT_ROOT / DEFAULT_ROOT
    source_dir = PROJECT_ROOT / DEFAULT_SOURCE_DIR
    try:
        result = run_multimodal_e2e_acceptance(root=root, source_dir=source_dir)
    except AcceptanceBlocked as exc:
        return {
            "status": "blocked",
            "passed": False,
            "root": _redact_local_path(root),
            "result_path": _redact_local_path(root / "acceptance_result.json"),
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "passed": False,
            "root": _redact_local_path(root),
            "result_path": _redact_local_path(root / "acceptance_result.json"),
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
    return _summarize_e2e_acceptance(result)


def build_rag_multimodal_readiness_report(*, check_e2e: bool = False) -> dict[str, object]:
    """Return a redacted readiness report for multimodal RAG extraction."""

    if check_e2e:
        from scripts.accept_rag_multimodal_e2e import DEFAULT_ROOT, configure_acceptance_environment

        configure_acceptance_environment(root=PROJECT_ROOT / DEFAULT_ROOT)

    ffmpeg = find_ffmpeg()
    transcript_command = resolve_transcript_command_template()
    whisper_config = default_transcription_config()
    report = {
        "version": RAG_MULTIMODAL_READINESS_VERSION,
        "enabled": multimodal_auto_extract_enabled(),
        "cache_path": _redact_local_path(resolve_multimodal_cache_path()),
        "vision": {
            "status": _status(has_real_env_value(settings.dashscope_api_key)),
            "model": resolve_model_name(profile="vision"),
            "env_vars": ["DASHSCOPE_API_KEY", "QWEN_VISION_MODEL_NAME"],
        },
        "ffmpeg": {
            "status": _status(bool(ffmpeg)),
            "path": _redact_local_path(ffmpeg),
            "env_vars": ["RAG_FFMPEG_PATH", "PATH"],
        },
        "transcript_command": {
            "status": _status(bool(transcript_command)),
            "has_input_placeholder": "{input}" in transcript_command,
            "env_vars": ["RAG_MULTIMODAL_TRANSCRIPT_COMMAND"],
        },
        "asr": {
            "status": _status(faster_whisper_available()),
            "engine": "faster-whisper",
            "model_size": whisper_config.model_size,
            "device": whisper_config.device,
            "compute_type": whisper_config.compute_type,
            "model_cache": _redact_local_path(whisper_config.model_cache),
            "env_vars": [
                "RAG_WHISPER_MODEL_SIZE",
                "RAG_WHISPER_MODEL_CACHE",
                "RAG_WHISPER_DEVICE",
                "RAG_WHISPER_COMPUTE_TYPE",
                "RAG_WHISPER_LANGUAGE",
            ],
        },
        "commands": {
            "sidecar_smoke": (
                "uv run python scripts\\rag_transcribe_sidecar.py "
                "data\\documents\\destinations\\example.mp3"
            ),
            "whisper_asr": (
                "uv run python scripts\\rag_transcribe_whisper.py "
                "data\\documents\\destinations\\example.mp3"
            ),
            "enable_auto_extract": (
                "$env:RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT='true'; "
                "$env:RAG_MULTIMODAL_TRANSCRIPT_COMMAND="
                "'uv run python scripts\\rag_transcribe_whisper.py {input}'"
            ),
            "e2e_acceptance": "uv run python scripts\\accept_rag_multimodal_e2e.py --json",
            "readiness_with_e2e": (
                "uv run python scripts\\check_rag_multimodal_readiness.py "
                "--json --check-e2e"
            ),
        },
        "e2e_acceptance": {
            "status": "not_checked",
            "command": "uv run python scripts\\accept_rag_multimodal_e2e.py --json",
        },
    }

    findings = []
    if not report["enabled"]:
        findings.append("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT is disabled.")
    if not ffmpeg:
        findings.append(
            "ffmpeg is not available; video keyframe extraction will use sidecar/transcript fallback."
        )
    if not transcript_command:
        findings.append(
            "RAG_MULTIMODAL_TRANSCRIPT_COMMAND is empty; audio/video auto transcription will be empty."
        )
    elif "{input}" not in transcript_command:
        findings.append(
            "RAG_MULTIMODAL_TRANSCRIPT_COMMAND should include {input} as the media file placeholder."
        )
    elif "rag_transcribe_whisper.py" in transcript_command and not faster_whisper_available():
        findings.append("faster-whisper is missing; real ASR transcript command cannot run.")
    if not has_real_env_value(settings.dashscope_api_key):
        findings.append("DASHSCOPE_API_KEY is missing or placeholder-like; image vision extraction will fail.")

    if check_e2e:
        e2e_result = _run_e2e_acceptance_check()
        report["e2e_acceptance"] = e2e_result
        if not e2e_result.get("passed"):
            findings.append(
                "RAG multimodal e2e acceptance did not pass: "
                f"{e2e_result.get('status')}"
            )

    report["findings"] = findings
    report["status"] = "passed" if not findings else "degraded"
    return report


def _render_human(report: dict[str, object]) -> str:
    lines = [
        "# RAG Multimodal Readiness",
        f"- status: {report['status']}",
        f"- enabled: {report['enabled']}",
        f"- cache_path: {report['cache_path']}",
        f"- vision: {(report['vision'] or {}).get('status')}",
        f"- ffmpeg: {(report['ffmpeg'] or {}).get('status')}",
        f"- transcript_command: {(report['transcript_command'] or {}).get('status')}",
        f"- asr: {(report['asr'] or {}).get('status')}",
        f"- e2e_acceptance: {(report['e2e_acceptance'] or {}).get('status')}",
    ]
    findings = report.get("findings") or []
    if findings:
        lines.append("- findings: " + " | ".join(str(item) for item in findings))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Do not load the local .env file; useful for public, redacted readiness checks.",
    )
    parser.add_argument(
        "--check-e2e",
        action="store_true",
        help="Also run the live multimodal vector-store acceptance check under .runtime.",
    )
    args = parser.parse_args()
    report = build_rag_multimodal_readiness_report(check_e2e=args.check_e2e)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report), end="")
    if args.check_e2e and not (report.get("e2e_acceptance") or {}).get("passed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
