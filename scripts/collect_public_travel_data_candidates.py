"""Collect reviewed public travel-data candidates into a private workdir.

Default mode is plan-only: no network calls and no file writes. With
``--execute``, the script fetches small candidate summaries from approved public
sources and writes redacted review artifacts outside the Git workspace. It does
not download media files, read `.env`, build vector stores, or commit data.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_travel_data_sources import DEFAULT_REGISTRY_PATH  # noqa: E402


PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION = "public_travel_data_candidates.v1"
PRIVATE_OUTPUT_PLACEHOLDER = "<private-workdir>"
DEFAULT_RADIUS_METERS = 5000
DEFAULT_MAX_POIS = 8
DEFAULT_MAX_IMAGES = 6
REQUIRED_SOURCE_KEYS = ("wikivoyage", "openstreetmap", "wikimedia_commons")


@dataclass(frozen=True)
class CitySpec:
    key: str
    display_name: str
    wikivoyage_title: str
    commons_category: str
    latitude: float
    longitude: float


DEFAULT_CITY_SPECS: dict[str, CitySpec] = {
    "xian": CitySpec("xian", "西安", "Xi'an", "Xi'an", 34.3416, 108.9398),
    "hangzhou": CitySpec("hangzhou", "杭州", "Hangzhou", "Hangzhou", 30.2741, 120.1551),
    "guilin": CitySpec("guilin", "桂林", "Guilin", "Guilin", 25.2345, 110.1799),
    "xiamen": CitySpec("xiamen", "厦门", "Xiamen", "Xiamen", 24.4798, 118.0894),
}


JsonFetcher = Callable[[str, Mapping[str, str] | None, float], Mapping[str, Any]]


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _utc_now() -> str:
    return datetime.now(UTC).date().isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _load_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read source registry: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Source registry must be a JSON object.")
    return payload


def _source_map(registry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    sources = registry.get("sources")
    if not isinstance(sources, list):
        return {}
    return {
        str(source.get("key")): source
        for source in sources
        if isinstance(source, Mapping) and str(source.get("key") or "").strip()
    }


def _finding(key: str, finding: str, *, target: str = "public_travel_data_candidates") -> dict[str, str]:
    return {"key": key, "target": target, "finding": finding}


def _http_get_json(url: str, params: Mapping[str, str] | None, timeout_seconds: float) -> Mapping[str, Any]:
    query = f"?{urlencode(dict(params or {}))}" if params else ""
    request = Request(
        f"{url}{query}",
        method="GET",
        headers={"User-Agent": "zhixing-public-travel-data-candidate-collector/1.0"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("JSON response is not an object")
    return payload


def _http_post_json(url: str, params: Mapping[str, str] | None, timeout_seconds: float) -> Mapping[str, Any]:
    body = urlencode(dict(params or {})).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "zhixing-public-travel-data-candidate-collector/1.0",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("JSON response is not an object")
    return payload


def _source_metadata(source: Mapping[str, Any], *, retrieved_at: str) -> dict[str, Any]:
    return {
        "source_key": source.get("key"),
        "source_name": source.get("name"),
        "license": source.get("license"),
        "attribution": source.get("attribution"),
        "retrieved_at": retrieved_at,
    }


def _trim_text(value: Any, *, limit: int = 900) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _collect_wikivoyage_candidate(
    city: CitySpec,
    source: Mapping[str, Any],
    *,
    fetched_at: str,
    timeout_seconds: float,
    get_json: JsonFetcher,
) -> dict[str, Any]:
    payload = get_json(
        f"https://en.wikivoyage.org/api/rest_v1/page/summary/{quote(city.wikivoyage_title, safe='')}",
        None,
        timeout_seconds,
    )
    source_url = (
        ((payload.get("content_urls") or {}).get("desktop") or {}).get("page")
        if isinstance(payload.get("content_urls"), Mapping)
        else None
    ) or f"https://en.wikivoyage.org/wiki/{quote(city.wikivoyage_title.replace(' ', '_'), safe='_')}"
    return {
        **_source_metadata(source, retrieved_at=fetched_at),
        "city_key": city.key,
        "city_name": city.display_name,
        "candidate_id": f"{city.key}:wikivoyage:summary",
        "candidate_type": "destination_text_summary",
        "title": payload.get("title") or city.wikivoyage_title,
        "source_url": source_url,
        "summary": _trim_text(payload.get("extract")),
        "review_required": True,
        "commit_ready": False,
        "content_boundary": "reference_only_no_inventory_or_price_lock",
    }


def _overpass_query(city: CitySpec, *, radius_meters: int, max_pois: int) -> str:
    radius = max(100, int(radius_meters))
    limit = max(1, int(max_pois))
    lat = round(float(city.latitude), 6)
    lon = round(float(city.longitude), 6)
    return (
        "[out:json][timeout:25];"
        "("
        f'node["tourism"](around:{radius},{lat},{lon});'
        f'way["tourism"](around:{radius},{lat},{lon});'
        f'relation["tourism"](around:{radius},{lat},{lon});'
        ");"
        f"out body center {limit};"
    )


def _collect_osm_candidates(
    city: CitySpec,
    source: Mapping[str, Any],
    *,
    fetched_at: str,
    radius_meters: int,
    max_pois: int,
    timeout_seconds: float,
    post_json: JsonFetcher,
) -> list[dict[str, Any]]:
    payload = post_json(
        "https://overpass-api.de/api/interpreter",
        {"data": _overpass_query(city, radius_meters=radius_meters, max_pois=max_pois)},
        timeout_seconds,
    )
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []
    candidates: list[dict[str, Any]] = []
    for item in elements[:max_pois]:
        if not isinstance(item, Mapping):
            continue
        tags = item.get("tags") if isinstance(item.get("tags"), Mapping) else {}
        center = item.get("center") if isinstance(item.get("center"), Mapping) else {}
        lat = item.get("lat") or center.get("lat")
        lon = item.get("lon") or center.get("lon")
        candidates.append(
            {
                **_source_metadata(source, retrieved_at=fetched_at),
                "city_key": city.key,
                "city_name": city.display_name,
                "candidate_id": f"{city.key}:openstreetmap:{item.get('type')}:{item.get('id')}",
                "candidate_type": "poi_metadata",
                "name": tags.get("name") or tags.get("name:zh") or tags.get("name:en") or "",
                "tourism": tags.get("tourism") or "",
                "osm_type": item.get("type"),
                "osm_id": item.get("id"),
                "latitude": round(float(lat), 6) if isinstance(lat, (int, float)) else None,
                "longitude": round(float(lon), 6) if isinstance(lon, (int, float)) else None,
                "source_url": source.get("url"),
                "review_required": True,
                "commit_ready": False,
                "content_boundary": "metadata_only_no_inventory_or_price_lock",
            }
        )
    return candidates


def _commons_params(city: CitySpec, *, max_images: int) -> dict[str, str]:
    return {
        "action": "query",
        "format": "json",
        "generator": "categorymembers",
        "gcmtitle": f"Category:{city.commons_category}",
        "gcmtype": "file",
        "gcmlimit": str(max(1, int(max_images))),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime",
        "iiurlwidth": "320",
    }


def _collect_commons_candidates(
    city: CitySpec,
    source: Mapping[str, Any],
    *,
    fetched_at: str,
    max_images: int,
    timeout_seconds: float,
    get_json: JsonFetcher,
) -> list[dict[str, Any]]:
    payload = get_json(
        "https://commons.wikimedia.org/w/api.php",
        _commons_params(city, max_images=max_images),
        timeout_seconds,
    )
    pages = ((payload.get("query") or {}).get("pages") if isinstance(payload.get("query"), Mapping) else None)
    if not isinstance(pages, Mapping):
        return []
    candidates: list[dict[str, Any]] = []
    for page in list(pages.values())[:max_images]:
        if not isinstance(page, Mapping):
            continue
        imageinfo = page.get("imageinfo")
        first_info = imageinfo[0] if isinstance(imageinfo, list) and imageinfo else {}
        if not isinstance(first_info, Mapping):
            first_info = {}
        ext = first_info.get("extmetadata") if isinstance(first_info.get("extmetadata"), Mapping) else {}

        def ext_value(name: str) -> str:
            value = ext.get(name)
            if isinstance(value, Mapping):
                return _trim_text(value.get("value"), limit=300)
            return ""

        candidates.append(
            {
                **_source_metadata(source, retrieved_at=fetched_at),
                "city_key": city.key,
                "city_name": city.display_name,
                "candidate_id": f"{city.key}:wikimedia_commons:{page.get('pageid') or page.get('title')}",
                "candidate_type": "image_metadata",
                "title": page.get("title") or "",
                "source_url": first_info.get("descriptionurl") or source.get("url"),
                "thumbnail_url": first_info.get("thumburl") or "",
                "mime": first_info.get("mime") or "",
                "author": ext_value("Artist"),
                "usage_terms": ext_value("UsageTerms"),
                "license_short_name": ext_value("LicenseShortName"),
                "review_required": True,
                "commit_ready": False,
                "content_boundary": "metadata_only_no_media_download",
            }
        )
    return candidates


def _resolve_cities(city_keys: Sequence[str]) -> tuple[list[CitySpec], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    specs: list[CitySpec] = []
    selected = city_keys or ("xian",)
    for key in selected:
        normalized = str(key or "").strip().lower()
        if normalized not in DEFAULT_CITY_SPECS:
            findings.append(_finding("unknown_city", f"Unsupported city key: {key}", target="city"))
        else:
            specs.append(DEFAULT_CITY_SPECS[normalized])
    return specs, findings


def _selected_sources(
    source_map: Mapping[str, Mapping[str, Any]],
    source_keys: Sequence[str],
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    selected: dict[str, Mapping[str, Any]] = {}
    for key in source_keys:
        source = source_map.get(key)
        if not source:
            findings.append(_finding("missing_source", f"Missing source_registry entry: {key}", target=key))
            continue
        if not bool(source.get("enabled_for_m1")):
            findings.append(_finding("source_not_enabled", f"Source is not enabled for M1: {key}", target=key))
            continue
        selected[key] = source
    return selected, findings


def _readme(candidates: Mapping[str, Any]) -> str:
    return (
        "# Public Travel Data Candidate Review\n\n"
        "This private folder contains small public-data candidates for human review before any RAG ingestion.\n\n"
        "## Boundary\n\n"
        "- Candidates are not committed by this script.\n"
        "- Media files are not downloaded.\n"
        "- Raw API responses are not stored.\n"
        "- Every candidate remains `commit_ready=false` until a human verifies license, attribution and content quality.\n"
        "- Candidate data cannot be used to claim real inventory, price lock, booking, ticketing or fulfillment.\n\n"
        f"Candidate count: `{candidates.get('candidate_count')}`\n"
    )


def build_public_travel_data_candidates_report(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    city_keys: Sequence[str] = ("xian",),
    include_wikivoyage: bool = True,
    include_osm: bool = True,
    include_commons: bool = True,
    execute: bool = False,
    output_dir: Path | None = None,
    allow_project_output: bool = False,
    radius_meters: int = DEFAULT_RADIUS_METERS,
    max_pois: int = DEFAULT_MAX_POIS,
    max_images: int = DEFAULT_MAX_IMAGES,
    timeout_seconds: float = 20.0,
    get_json: JsonFetcher = _http_get_json,
    post_json: JsonFetcher = _http_post_json,
) -> dict[str, Any]:
    """Build a plan or execute a small public-data candidate collection."""

    try:
        registry = _load_registry(registry_path)
    except ValueError as exc:
        return {
            "version": PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION,
            "status": "blocked",
            "blockers": [_finding("registry_load", str(exc), target="source_registry")],
        }
    source_map = _source_map(registry)
    requested_source_keys = []
    if include_wikivoyage:
        requested_source_keys.append("wikivoyage")
    if include_osm:
        requested_source_keys.append("openstreetmap")
    if include_commons:
        requested_source_keys.append("wikimedia_commons")
    cities, city_findings = _resolve_cities(city_keys)
    selected_sources, source_findings = _selected_sources(source_map, requested_source_keys)
    blockers = [*city_findings, *source_findings]
    inside_project = bool(output_dir and _is_relative_to(output_dir, PROJECT_ROOT))
    report: dict[str, Any] = {
        "version": PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION,
        "status": "not_checked",
        "policy": {
            "reads_dotenv": False,
            "downloads_media": False,
            "stores_raw_api_responses": False,
            "builds_vectorstore": False,
            "writes_files": execute,
            "calls_external_apis": execute,
            "output_should_remain_private": True,
        },
        "target": {
            "registry_path": registry_path.name,
            "output_dir": PRIVATE_OUTPUT_PLACEHOLDER if output_dir else "",
            "output_dir_inside_project": inside_project,
            "allow_project_output": allow_project_output,
            "city_keys": [city.key for city in cities],
            "source_keys": requested_source_keys,
        },
        "execution_plan": {
            "execute_required_for_network": True,
            "candidate_output": "public-travel-data-candidates.json",
            "review_readme": "README.md",
            "review_required_before_ingestion": True,
        },
        "not_proven_by_this_report": [
            "Plan-only mode does not fetch or validate live public data.",
            "Collected candidates are not proof of data freshness, opening hours, ticket prices, inventory or fulfillment.",
            "Collected image metadata is not proof that a media file can be reused until per-file license review is complete.",
        ],
    }
    if blockers:
        report["status"] = "blocked"
        report["blockers"] = blockers
        return report
    if not execute:
        report["planned_city_count"] = len(cities)
        report["planned_source_count"] = len(requested_source_keys)
        return report
    if output_dir is None:
        report["status"] = "blocked"
        report["blockers"] = [_finding("missing_output_dir", "Execution requires --output-dir outside the Git workspace.")]
        return report
    if inside_project and not allow_project_output:
        report["status"] = "blocked"
        report["blockers"] = [
            _finding("project_output_not_allowed", "Use a private output directory outside the Git workspace or pass --allow-project-output.")
        ]
        return report
    if timeout_seconds <= 0:
        report["status"] = "blocked"
        report["blockers"] = [_finding("invalid_timeout", "timeout_seconds must be positive.")]
        return report

    fetched_at = _utc_now()
    candidates: list[dict[str, Any]] = []
    degraded: list[dict[str, str]] = []
    for city in cities:
        if "wikivoyage" in selected_sources:
            try:
                candidates.append(
                    _collect_wikivoyage_candidate(
                        city,
                        selected_sources["wikivoyage"],
                        fetched_at=fetched_at,
                        timeout_seconds=timeout_seconds,
                        get_json=get_json,
                    )
                )
            except (HTTPError, TimeoutError, URLError, OSError, RuntimeError, ValueError, KeyError) as exc:
                degraded.append(_finding("wikivoyage_fetch_failed", exc.__class__.__name__, target=city.key))
        if "openstreetmap" in selected_sources:
            try:
                candidates.extend(
                    _collect_osm_candidates(
                        city,
                        selected_sources["openstreetmap"],
                        fetched_at=fetched_at,
                        radius_meters=radius_meters,
                        max_pois=max_pois,
                        timeout_seconds=timeout_seconds,
                        post_json=post_json,
                    )
                )
            except (HTTPError, TimeoutError, URLError, OSError, RuntimeError, ValueError, KeyError) as exc:
                degraded.append(_finding("osm_fetch_failed", exc.__class__.__name__, target=city.key))
        if "wikimedia_commons" in selected_sources:
            try:
                candidates.extend(
                    _collect_commons_candidates(
                        city,
                        selected_sources["wikimedia_commons"],
                        fetched_at=fetched_at,
                        max_images=max_images,
                        timeout_seconds=timeout_seconds,
                        get_json=get_json,
                    )
                )
            except (HTTPError, TimeoutError, URLError, OSError, RuntimeError, ValueError, KeyError) as exc:
                degraded.append(_finding("commons_fetch_failed", exc.__class__.__name__, target=city.key))

    payload = {
        "version": PUBLIC_TRAVEL_DATA_CANDIDATES_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "review_status": "human_review_required",
        "commit_ready_count": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "public-travel-data-candidates.json"
    readme_path = output_dir / "README.md"
    candidate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readme_path.write_text(_readme(payload), encoding="utf-8")
    report.update(
        {
            "status": "degraded" if degraded else "passed",
            "candidate_count": len(candidates),
            "artifact_paths": [
                {"role": "candidate_json", "path": candidate_path.name},
                {"role": "review_readme", "path": readme_path.name},
            ],
            "review_status": "human_review_required",
            "commit_ready_count": 0,
        }
    )
    if degraded:
        report["degraded_reasons"] = degraded
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-path", type=_path_arg, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--city", dest="cities", action="append", default=[], choices=sorted(DEFAULT_CITY_SPECS))
    parser.add_argument("--output-dir", type=_path_arg, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-project-output", action="store_true")
    parser.add_argument("--no-wikivoyage", action="store_true")
    parser.add_argument("--no-osm", action="store_true")
    parser.add_argument("--no-commons", action="store_true")
    parser.add_argument("--radius-meters", type=int, default=DEFAULT_RADIUS_METERS)
    parser.add_argument("--max-pois", type=int, default=DEFAULT_MAX_POIS)
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_public_travel_data_candidates_report(
        registry_path=args.registry_path,
        city_keys=args.cities or ("xian",),
        include_wikivoyage=not args.no_wikivoyage,
        include_osm=not args.no_osm,
        include_commons=not args.no_commons,
        execute=args.execute,
        output_dir=args.output_dir,
        allow_project_output=args.allow_project_output,
        radius_meters=args.radius_meters,
        max_pois=args.max_pois,
        max_images=args.max_images,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
