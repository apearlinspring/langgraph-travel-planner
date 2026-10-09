"""Run an end-to-end RAG multimodal acceptance check.

This script builds a temporary knowledge base under .runtime, indexes image,
audio, and video samples into a temporary Chroma vector store, reloads that
store from disk, and verifies that AdvancedRAGPipeline retrieves each modality
as rank 1 evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

if "--json" in sys.argv:
    os.environ.setdefault("ZHIXING_SUPPRESS_CONSOLE_LOGS", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import has_real_env_value, settings  # noqa: E402
from app.rag.document_loader import DocumentManager  # noqa: E402
from app.rag.pipeline import AdvancedRAGPipeline  # noqa: E402
from app.rag.text_splitter import AdvancedParentDocumentSplitter  # noqa: E402
from app.rag.vectorstore import VectorStoreManager  # noqa: E402
from scripts.rag_transcribe_whisper import faster_whisper_available  # noqa: E402


RAG_MULTIMODAL_E2E_ACCEPTANCE_VERSION = "rag_multimodal_e2e_acceptance.v1"
DEFAULT_ROOT = ".runtime/rag_e2e_acceptance"
DEFAULT_SOURCE_DIR = ".runtime/rag_web_acceptance/documents/destinations"
DEFAULT_COLLECTION_NAME = "rag_e2e_multimodal_acceptance"


def project_display_path(value: str | Path) -> str:
    """Return a project-relative display path when possible."""

    if not str(value).strip():
        return ""
    path = Path(value)
    try:
        display = path.resolve().relative_to(PROJECT_ROOT.resolve())
        return str(display).replace("\\", "/")
    except (OSError, ValueError):
        return str(value).replace("\\", "/")


@dataclass(frozen=True)
class AcceptanceAsset:
    """One sample file copied into the temporary acceptance knowledge base."""

    name: str
    required: bool = True


@dataclass(frozen=True)
class AcceptanceQuery:
    """One labeled query and expected modality hit."""

    id: str
    query: str
    expected_source_contains: str
    expected_modality: str
    expected_terms: tuple[str, ...]


DEFAULT_ASSETS = (
    AcceptanceAsset("samplelib-city-park.jpg"),
    AcceptanceAsset("samplelib-city-park.jpg.md"),
    AcceptanceAsset("openai-whisper-jfk.flac"),
    AcceptanceAsset("samplelib-city-road.mp4"),
    AcceptanceAsset("samplelib-city-road.mp4.vtt"),
)

DEFAULT_QUERIES = (
    AcceptanceQuery(
        id="image_city_park",
        query="城市公园图片里适合老人低强度路线的步道和绿色空间",
        expected_source_contains="samplelib-city-park.jpg",
        expected_modality="image",
        expected_terms=("城市公园", "老人低强度路线"),
    ),
    AcceptanceQuery(
        id="audio_jfk_whisper",
        query="ask not what your country can do for you 这段音频转写",
        expected_source_contains="openai-whisper-jfk.flac",
        expected_modality="audio",
        expected_terms=("ask not what your country can do for you",),
    ),
    AcceptanceQuery(
        id="video_city_road",
        query="城市道路视频样例 交通动线 步行换乘",
        expected_source_contains="samplelib-city-road.mp4",
        expected_modality="video",
        expected_terms=("交通动线", "步行换乘"),
    ),
)


class AcceptanceBlocked(RuntimeError):
    """Raised when the local environment cannot run live acceptance."""


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _assert_runtime_child(path: Path) -> Path:
    resolved = path.resolve()
    runtime_root = (PROJECT_ROOT / ".runtime").resolve()
    if resolved == runtime_root or runtime_root not in resolved.parents:
        raise AcceptanceBlocked(f"Output path must be inside .runtime: {resolved}")
    return resolved


def _copy_assets(source_dir: Path, destination_dir: Path) -> list[str]:
    missing = [
        asset.name
        for asset in DEFAULT_ASSETS
        if asset.required and not (source_dir / asset.name).exists()
    ]
    if missing:
        raise AcceptanceBlocked(
            "Missing multimodal acceptance assets: "
            + ", ".join(missing)
            + f". Expected under {project_display_path(source_dir)}."
        )
    copied: list[str] = []
    destination_dir.mkdir(parents=True, exist_ok=True)
    for asset in DEFAULT_ASSETS:
        source = source_dir / asset.name
        if not source.exists():
            continue
        shutil.copy2(source, destination_dir / asset.name)
        copied.append(asset.name)
    return copied


def _default_transcript_command(root: Path) -> str:
    model_cache = root / "whisper_models"
    return (
        "uv run python scripts/rag_transcribe_whisper.py {input} "
        "--model-size tiny --device cpu --compute-type int8 "
        f'--model-cache "{model_cache}"'
    )


def configure_acceptance_environment(
    *,
    root: Path,
    transcript_command: str | None = None,
) -> dict[str, str]:
    """Set process-local env vars required by multimodal extraction."""

    resolved_command = transcript_command or _default_transcript_command(root)
    updates = {
        "RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT": "true",
        "RAG_MULTIMODAL_VIDEO_FRAME_COUNT": "1",
        "RAG_MULTIMODAL_CACHE_PATH": str(root / "multimodal_cache"),
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND": resolved_command,
        "RAG_WHISPER_MODEL_SIZE": "tiny",
        "RAG_WHISPER_MODEL_CACHE": str(root / "whisper_models"),
        "RAG_WHISPER_DEVICE": "cpu",
        "RAG_WHISPER_COMPUTE_TYPE": "int8",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
    }
    os.environ.update(updates)
    return updates


def _preflight(source_dir: Path) -> list[str]:
    findings: list[str] = []
    if not has_real_env_value(settings.dashscope_api_key):
        findings.append("DASHSCOPE_API_KEY is missing or placeholder-like.")
    if not faster_whisper_available():
        findings.append("faster-whisper is not installed.")
    missing = [
        asset.name
        for asset in DEFAULT_ASSETS
        if asset.required and not (source_dir / asset.name).exists()
    ]
    if missing:
        findings.append("Missing assets: " + ", ".join(missing))
    return findings


def _document_summary(documents: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "source": project_display_path(str(doc.metadata.get("source") or "")),
            "modality": doc.metadata.get("content_modality"),
            "format": doc.metadata.get("source_format"),
            "extraction_method": doc.metadata.get("extraction_method"),
            "auto_status": doc.metadata.get("multimodal_auto_extract_status"),
            "sidecar_source": project_display_path(str(doc.metadata.get("sidecar_source") or "")),
            "text_len": len(doc.page_content or ""),
        }
        for doc in documents
    ]


def _render_hits(hits: Sequence[Any]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for rank, doc in enumerate(hits, start=1):
        metadata = dict(doc.metadata or {})
        text = str(doc.page_content or "")
        rendered.append(
            {
                "rank": rank,
                "source": project_display_path(str(metadata.get("source") or "")),
                "content_modality": metadata.get("content_modality"),
                "source_format": metadata.get("source_format"),
                "extraction_method": metadata.get("extraction_method"),
                "auto_status": metadata.get("multimodal_auto_extract_status"),
                "text_len": len(text),
                "preview": text[:240],
                "_full_text": text,
            }
        )
    return rendered


def _query_passed(query: AcceptanceQuery, hits: list[dict[str, Any]]) -> tuple[bool, dict[str, Any] | None]:
    expected_hit = next(
        (
            hit
            for hit in hits
            if query.expected_source_contains in str(hit.get("source") or "")
            and hit.get("content_modality") == query.expected_modality
        ),
        None,
    )
    if expected_hit is None:
        return False, None
    expected_text = str(expected_hit.get("_full_text") or "").lower()
    return all(term.lower() in expected_text for term in query.expected_terms), expected_hit


def _write_result_json(root: Path, result: dict[str, Any]) -> Path:
    safe_root = _assert_runtime_child(root)
    safe_root.mkdir(parents=True, exist_ok=True)
    result_path = safe_root / "acceptance_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result_path


def run_multimodal_e2e_acceptance(
    *,
    root: Path,
    source_dir: Path,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    top_k: int = 2,
    transcript_command: str | None = None,
) -> dict[str, Any]:
    """Build a temporary vector store and verify multimodal rank-1 retrieval."""

    root = _assert_runtime_child(root)
    source_dir = _resolve_project_path(source_dir)
    preflight_findings = _preflight(source_dir)
    if preflight_findings:
        raise AcceptanceBlocked(" | ".join(preflight_findings))

    if root.exists():
        shutil.rmtree(root)
    destination_dir = root / "documents" / "destinations"
    copied_assets = _copy_assets(source_dir, destination_dir)
    env_updates = configure_acceptance_environment(
        root=root,
        transcript_command=transcript_command,
    )

    manager = DocumentManager(str(root / "documents"))
    documents = manager.load_destination_documents()
    splitter = AdvancedParentDocumentSplitter(
        parent_chunk_size=1200,
        parent_chunk_overlap=100,
        child_chunk_size=260,
        child_chunk_overlap=40,
    )
    parent_docs, child_docs = splitter.split_documents(documents)

    vectorstore_path = root / "vectorstore"
    creator = VectorStoreManager(
        persist_directory=str(vectorstore_path),
        collection_name=collection_name,
    )
    creator.create_vectorstore(child_docs)
    loader = VectorStoreManager(
        persist_directory=str(vectorstore_path),
        collection_name=collection_name,
    )
    loaded_vectorstore = loader.load_vectorstore()

    pipeline = AdvancedRAGPipeline(
        vectorstore=loaded_vectorstore,
        all_documents=child_docs,
        parent_splitter=splitter,
        query_strategy="local_multi_query",
        use_llm_reranker=False,
        top_k=top_k,
        enable_cache=False,
    )

    query_results: list[dict[str, Any]] = []
    for query in DEFAULT_QUERIES:
        hits = pipeline.retrieve(
            query.query,
            metadata_filter={"visibility": "public"},
        )
        rendered_hits = _render_hits(hits)
        passed, expected_hit = _query_passed(query, rendered_hits)
        query_results.append(
            {
                "id": query.id,
                "query": query.query,
                "passed": passed,
                "expected_hit_rank": expected_hit.get("rank") if expected_hit else None,
                "expected_hit_extraction_method": (
                    expected_hit.get("extraction_method") if expected_hit else None
                ),
                "hits": [
                    {key: value for key, value in hit.items() if key != "_full_text"}
                    for hit in rendered_hits
                ],
                "trace": pipeline.last_trace,
            }
        )

    result = {
        "version": RAG_MULTIMODAL_E2E_ACCEPTANCE_VERSION,
        "status": "passed",
        "passed": all(
            item["passed"] and item["expected_hit_rank"] == 1
            for item in query_results
        ),
        "root": project_display_path(root),
        "source_dir": project_display_path(source_dir),
        "copied_assets": copied_assets,
        "collection_name": collection_name,
        "loaded_from_disk": True,
        "document_count": len(documents),
        "parent_count": len(parent_docs),
        "child_count": len(child_docs),
        "metadata_summary": _document_summary(documents),
        "query_results": query_results,
        "environment": {
            "rag_multimodal_video_frame_count": env_updates["RAG_MULTIMODAL_VIDEO_FRAME_COUNT"],
            "rag_multimodal_cache_path": project_display_path(
                env_updates["RAG_MULTIMODAL_CACHE_PATH"]
            ),
            "rag_whisper_model_cache": project_display_path(
                env_updates["RAG_WHISPER_MODEL_CACHE"]
            ),
            "transcript_command_kind": (
                "whisper"
                if "rag_transcribe_whisper.py" in env_updates["RAG_MULTIMODAL_TRANSCRIPT_COMMAND"]
                else "custom"
            ),
        },
    }
    if not result["passed"]:
        result["status"] = "failed"
    _write_result_json(root, result)
    return result


def _blocked_result(error: Exception, *, root: Path, source_dir: Path) -> dict[str, Any]:
    return {
        "version": RAG_MULTIMODAL_E2E_ACCEPTANCE_VERSION,
        "status": "blocked",
        "passed": False,
        "root": project_display_path(root),
        "source_dir": project_display_path(source_dir),
        "error_type": error.__class__.__name__,
        "error": str(error),
    }


def render_human(result: dict[str, Any]) -> str:
    """Render a compact human-readable report."""

    lines = [
        "# RAG Multimodal E2E Acceptance",
        f"- status: {result.get('status')}",
        f"- passed: {result.get('passed')}",
        f"- loaded_from_disk: {result.get('loaded_from_disk')}",
        f"- documents: {result.get('document_count')}",
        f"- child_chunks: {result.get('child_count')}",
    ]
    if result.get("error"):
        lines.append(f"- error: {result.get('error')}")
    for item in result.get("query_results") or []:
        first = (item.get("hits") or [{}])[0]
        lines.append(
            "- "
            f"{item.get('id')}: passed={item.get('passed')} "
            f"rank={item.get('expected_hit_rank')} "
            f"method={item.get('expected_hit_extraction_method')} "
            f"source={Path(str(first.get('source') or '')).name}"
        )
    return "\n".join(lines) + "\n"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(DEFAULT_ROOT),
        help="Temporary runtime directory for copied samples, cache, vector store, and result JSON.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(DEFAULT_SOURCE_DIR),
        help="Directory containing the prepared image/audio/video sample assets.",
    )
    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION_NAME,
        help="Temporary Chroma collection name.",
    )
    parser.add_argument("--top-k", type=int, default=2, help="Final retrieval top_k.")
    parser.add_argument(
        "--transcript-command",
        default=None,
        help="Override RAG_MULTIMODAL_TRANSCRIPT_COMMAND for this process.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = _resolve_project_path(args.root)
    source_dir = _resolve_project_path(args.source_dir)
    try:
        result = run_multimodal_e2e_acceptance(
            root=root,
            source_dir=source_dir,
            collection_name=args.collection_name,
            top_k=args.top_k,
            transcript_command=args.transcript_command,
        )
    except AcceptanceBlocked as exc:
        result = _blocked_result(exc, root=root, source_dir=source_dir)
        try:
            _write_result_json(root, result)
        except AcceptanceBlocked:
            pass
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_human(result), end="")
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
