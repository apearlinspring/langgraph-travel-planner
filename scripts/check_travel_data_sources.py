"""Check travel RAG data-source governance before release.

This script does not download data, call external APIs, read `.env`, build a
vector store, or write files. It validates the source registry and public
destination Markdown metadata so public RAG data can be traced to an approved
source and a conservative usage boundary.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.contracts import parse_markdown_metadata  # noqa: E402


TRAVEL_DATA_SOURCE_READINESS_VERSION = "travel_data_source_readiness.v1"
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "data" / "documents" / "source_registry.json"
DEFAULT_DESTINATIONS_DIR = PROJECT_ROOT / "data" / "documents" / "destinations"
REQUIRED_SOURCE_FIELDS = {
    "key",
    "name",
    "license",
    "attribution",
    "attribution_required",
    "origin_type",
    "content_types",
    "enabled_for_m1",
    "m1_usage",
    "ingestion_boundary",
    "raw_cache_policy",
}
REQUIRED_DESTINATION_FIELDS = {
    "title",
    "category",
    "source_type",
    "visibility",
    "applicable_modes",
    "evidence_level",
    "last_reviewed",
    "source_key",
    "source_name",
    "license",
    "attribution",
    "data_origin",
    "content_boundary",
}
FORBIDDEN_SOURCE_HINTS = {
    "xiaohongshu",
    "小红书",
    "ctrip",
    "携程",
    "mafengwo",
    "马蜂窝",
    "wechat",
    "公众号",
    "dianping",
    "大众点评",
}


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _load_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read source registry: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Source registry must be a JSON object.")
    return payload


def _finding(*, target: str, key: str, finding: str, severity: str = "blocked") -> dict[str, str]:
    return {
        "severity": severity,
        "target": target,
        "key": key,
        "finding": finding,
    }


def _validate_registry(registry: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        return {}, [_finding(target="source_registry", key="sources", finding="Registry must define at least one source.")]
    source_map: dict[str, Mapping[str, Any]] = {}
    keys = []
    for index, source in enumerate(sources):
        target = f"sources[{index}]"
        if not isinstance(source, Mapping):
            findings.append(_finding(target=target, key="source_shape", finding="Source entry must be an object."))
            continue
        source_key = str(source.get("key") or "").strip()
        keys.append(source_key)
        for field in sorted(REQUIRED_SOURCE_FIELDS):
            if _is_blank(source.get(field)):
                findings.append(_finding(target=source_key or target, key=field, finding="Required source field is missing."))
        normalized_source_text = " ".join(str(source.get(field) or "") for field in ("key", "name", "url")).lower()
        if any(hint in normalized_source_text for hint in FORBIDDEN_SOURCE_HINTS):
            findings.append(
                _finding(
                    target=source_key or target,
                    key="forbidden_source",
                    finding="Source has unclear public-reuse rights and must not be enabled for public RAG data.",
                )
            )
        origin_type = str(source.get("origin_type") or "").strip()
        if origin_type.startswith("external") and _is_blank(source.get("url")):
            findings.append(_finding(target=source_key or target, key="url", finding="External source must declare a public URL."))
        content_types = source.get("content_types")
        if not isinstance(content_types, list) or not all(str(item).strip() for item in content_types):
            findings.append(_finding(target=source_key or target, key="content_types", finding="content_types must be a non-empty string list."))
        if source_key:
            source_map[source_key] = source
    for key, count in Counter(keys).items():
        if key and count > 1:
            findings.append(_finding(target=key, key="duplicate_source_key", finding="Source key must be unique."))
    return source_map, findings


def _document_needs_boundary(body: str) -> bool:
    prefix = body[:1200]
    return "不代表真实库存" in prefix and ("实时价格" in prefix or "锁价" in prefix)


def _validate_destination_document(
    path: Path,
    *,
    source_map: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    try:
        parsed = parse_markdown_metadata(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        return [_finding(target=path.name, key="read_error", finding=f"Cannot read document: {exc.__class__.__name__}")]
    metadata = parsed.metadata
    target = path.name
    for field in sorted(REQUIRED_DESTINATION_FIELDS):
        if _is_blank(metadata.get(field)):
            findings.append(_finding(target=target, key=field, finding="Required destination metadata field is missing."))
    if str(metadata.get("category") or "").strip() != "destinations":
        findings.append(_finding(target=target, key="category", finding="Destination document must use category=destinations."))
    if str(metadata.get("visibility") or "").strip() != "public":
        findings.append(_finding(target=target, key="visibility", finding="Destination document must be public data."))
    source_key = str(metadata.get("source_key") or "").strip()
    source = source_map.get(source_key)
    if not source:
        findings.append(_finding(target=target, key="source_key", finding="source_key is not present in source_registry.json."))
    else:
        origin_type = str(source.get("origin_type") or "").strip()
        if origin_type.startswith("external"):
            for field in ("source_url", "retrieved_at"):
                if _is_blank(metadata.get(field)):
                    findings.append(_finding(target=target, key=field, finding="External-source document must record source_url and retrieved_at."))
        source_license = str(source.get("license") or "").strip().lower()
        doc_license = str(metadata.get("license") or "").strip().lower()
        if source_license and doc_license and source_license not in doc_license and doc_license not in source_license:
            findings.append(_finding(target=target, key="license", finding="Document license does not match the declared source license."))
    if not _document_needs_boundary(parsed.body):
        findings.append(
            _finding(
                target=target,
                key="content_boundary",
                finding="Destination document must state it does not represent real inventory or realtime pricing.",
            )
        )
    return findings


def build_travel_data_source_readiness_report(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    destinations_dir: Path = DEFAULT_DESTINATIONS_DIR,
) -> dict[str, Any]:
    """Validate public travel data-source governance."""

    report: dict[str, Any] = {
        "version": TRAVEL_DATA_SOURCE_READINESS_VERSION,
        "status": "blocked",
        "policy": {
            "reads_dotenv": False,
            "downloads_data": False,
            "calls_external_apis": False,
            "builds_vectorstore": False,
            "writes_files": False,
            "allows_unclear_platform_content": False,
        },
        "target": {
            "registry_path": registry_path.name,
            "destinations_dir": destinations_dir.name,
            "paths_are_redacted": True,
        },
    }
    try:
        registry = _load_registry(registry_path)
    except ValueError as exc:
        report["blockers"] = [_finding(target="source_registry", key="load", finding=str(exc))]
        return report
    source_map, findings = _validate_registry(registry)
    destination_paths = sorted(destinations_dir.glob("*.md")) if destinations_dir.exists() else []
    if not destination_paths:
        findings.append(_finding(target="destinations", key="documents", finding="No destination Markdown documents found."))
    for path in destination_paths:
        findings.extend(_validate_destination_document(path, source_map=source_map))
    enabled_sources = [
        key
        for key, source in source_map.items()
        if bool(source.get("enabled_for_m1"))
    ]
    report.update(
        {
            "registry_version": registry.get("version"),
            "source_count": len(source_map),
            "enabled_for_m1_count": len(enabled_sources),
            "destination_document_count": len(destination_paths),
            "enabled_source_keys": sorted(enabled_sources),
            "not_proven_by_this_check": [
                "This check does not download Wikivoyage, OpenStreetMap, Wikimedia Commons, Natural Earth or GeoNames data.",
                "It does not prove that destination facts are fresh, complete or suitable for fulfillment.",
                "It does not prove image copyrights beyond the recorded metadata; per-file review is still required.",
                "It does not prove live vector-store ingestion or retrieval quality.",
            ],
        }
    )
    if findings:
        report["status"] = "blocked"
        report["blockers"] = findings
    else:
        report["status"] = "passed"
        report["blockers"] = []
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-path", type=_path_arg, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--destinations-dir", type=_path_arg, default=DEFAULT_DESTINATIONS_DIR)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_travel_data_source_readiness_report(
        registry_path=args.registry_path,
        destinations_dir=args.destinations_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
