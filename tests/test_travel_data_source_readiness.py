import json
from pathlib import Path

from scripts.check_travel_data_sources import (
    TRAVEL_DATA_SOURCE_READINESS_VERSION,
    build_travel_data_source_readiness_report,
    main,
)
from app.rag.document_loader import DocumentManager


def _registry(path: Path, *, external: bool = False) -> None:
    source = {
        "key": "wikivoyage" if external else "zhixing_curated_sample",
        "name": "Wikivoyage" if external else "ZhiXing curated public destination sample",
        "url": "https://www.wikivoyage.org/" if external else "",
        "license": "CC BY-SA 4.0" if external else "Project demo sample",
        "attribution": "Wikivoyage contributors" if external else "ZhiXing demo dataset",
        "attribution_required": True,
        "origin_type": "external_public_license" if external else "curated_public_sample",
        "content_types": ["text"],
        "enabled_for_m1": True,
        "m1_usage": "Destination guide sample.",
        "ingestion_boundary": "Reference only; no realtime inventory or price lock.",
        "raw_cache_policy": "Raw cache stays outside Git.",
    }
    path.write_text(
        json.dumps(
            {
                "version": "travel_data_source_registry.v1",
                "sources": [source],
                "policy": {"forbidden_for_public_repo": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _document(path: Path, *, source_key: str = "zhixing_curated_sample", external: bool = False, include_source_url: bool = True) -> None:
    source_url = "source_url: https://en.wikivoyage.org/wiki/Xi%27an\nretrieved_at: 2026-06-24\n" if include_source_url else ""
    license_value = "CC BY-SA 4.0" if external else "Project demo sample"
    attribution = "Wikivoyage contributors" if external else "ZhiXing demo dataset"
    path.write_text(
        f"""---
title: 西安公开目的地知识样例
category: destinations
source_type: destination_guide
visibility: public
applicable_modes:
  - free_planning
  - agency_plan
evidence_level: guide
last_reviewed: 2026-06-24
source_key: {source_key}
source_name: test source
license: {license_value}
attribution: {attribution}
data_origin: curated_public_sample
content_boundary: reference_only_no_inventory_or_price_lock
{source_url}---

# 西安旅游攻略

> 本文是公开目的地知识样例，不代表真实库存、实时价格、供应商承诺或官方预约结果。
""",
        encoding="utf-8",
    )


def test_default_travel_data_source_readiness_passes():
    report = build_travel_data_source_readiness_report()

    assert report["version"] == TRAVEL_DATA_SOURCE_READINESS_VERSION
    assert report["status"] == "passed"
    assert report["destination_document_count"] >= 4
    assert "zhixing_curated_sample" in report["enabled_source_keys"]


def test_destination_source_metadata_is_preserved_for_rag():
    documents = DocumentManager().load_destination_documents()
    by_title = {doc.metadata.get("title"): doc for doc in documents}

    xian = by_title["西安公开目的地知识样例"]
    assert xian.metadata["source_key"] == "zhixing_curated_sample"
    assert xian.metadata["license"] == "Project demo sample"
    assert xian.metadata["attribution"] == "ZhiXing demo dataset"
    assert xian.metadata["content_boundary"] == "reference_only_no_inventory_or_price_lock"


def test_missing_destination_source_metadata_blocks(tmp_path: Path):
    registry = tmp_path / "source_registry.json"
    destinations = tmp_path / "destinations"
    destinations.mkdir()
    _registry(registry)
    (destinations / "xian.md").write_text(
        "# 西安旅游攻略\n\n> 本文不代表真实库存、实时价格、供应商承诺或官方预约结果。\n",
        encoding="utf-8",
    )

    report = build_travel_data_source_readiness_report(
        registry_path=registry,
        destinations_dir=destinations,
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "source_key" for item in report["blockers"])


def test_external_destination_requires_url_and_retrieved_at(tmp_path: Path):
    registry = tmp_path / "source_registry.json"
    destinations = tmp_path / "destinations"
    destinations.mkdir()
    _registry(registry, external=True)
    _document(
        destinations / "xian.md",
        source_key="wikivoyage",
        external=True,
        include_source_url=False,
    )

    report = build_travel_data_source_readiness_report(
        registry_path=registry,
        destinations_dir=destinations,
    )

    assert report["status"] == "blocked"
    assert {item["key"] for item in report["blockers"]} >= {"source_url", "retrieved_at"}


def test_travel_data_source_cli_returns_zero_for_valid_inputs(tmp_path: Path):
    registry = tmp_path / "source_registry.json"
    destinations = tmp_path / "destinations"
    destinations.mkdir()
    _registry(registry)
    _document(destinations / "xian.md")

    code = main(["--registry-path", str(registry), "--destinations-dir", str(destinations)])

    assert code == 0
