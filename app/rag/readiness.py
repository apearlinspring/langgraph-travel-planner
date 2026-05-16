"""RAG vector store readiness checks shared by init scripts and preflight."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.rag.contracts import (
    CONTRACT_VERSION,
    INTERNAL_KNOWLEDGE_BASE,
    PUBLIC_KNOWLEDGE_BASE,
)


PUBLIC_VECTORSTORE_CONTRACT = {
    "label": "Public RAG vector store",
    "default_path": "data/vectorstore",
    "default_collection": "travel_guides",
    "knowledge_base": PUBLIC_KNOWLEDGE_BASE,
    "visibility": "public",
    "required_metadata": (
        "contract_version",
        "knowledge_base",
        "source",
        "source_type",
        "category",
        "visibility",
        "evidence_level",
        "applicable_modes",
        "constraints",
        "last_reviewed",
    ),
    "retrieval_probes": (
        {
            "name": "destination_guide",
            "metadata": {"category": "destinations", "visibility": "public"},
            "terms_any": ("西安", "兵马俑", "destination_guide"),
        },
        {
            "name": "food_recommendations",
            "metadata": {"category": "destinations", "visibility": "public"},
            "terms_any": ("美食", "肉夹馍", "回民街"),
        },
    ),
}

INTERNAL_VECTORSTORE_CONTRACT = {
    "label": "Internal RAG vector store",
    "default_path": "data/vectorstore_internal",
    "default_collection": INTERNAL_KNOWLEDGE_BASE,
    "knowledge_base": INTERNAL_KNOWLEDGE_BASE,
    "visibility": "internal",
    "required_metadata": (
        "contract_version",
        "knowledge_base",
        "source",
        "source_type",
        "category",
        "visibility",
        "evidence_level",
        "applicable_modes",
        "constraints",
        "last_reviewed",
        "freshness_status",
        "requires_verification",
    ),
    "category_required_metadata": {
        "products": (
            "product_id",
            "destination",
            "theme",
            "duration",
            "audience",
            "service_level",
            "price_band",
            "evidence_type",
        ),
    },
    "retrieval_probes": (
        {
            "name": "agency_products",
            "metadata": {"category": "products", "visibility": "internal"},
            "terms_any": ("product_id", "路线", "产品", "适合人群", "服务边界"),
        },
        {
            "name": "agency_sop",
            "metadata": {"category": "sop", "visibility": "internal"},
            "terms_any": ("服务", "顾问", "流程"),
        },
        {
            "name": "agency_pricing",
            "metadata": {"category": "pricing", "visibility": "internal"},
            "terms_any": ("报价", "预算", "待核验"),
        },
        {
            "name": "agency_risk",
            "metadata": {"category": "risk", "visibility": "internal"},
            "terms_any": ("风险", "避坑", "Plan B"),
        },
        {
            "name": "agency_report",
            "metadata": {"category": "report", "visibility": "internal"},
            "terms_any": ("报告", "交付", "章节"),
        },
    ),
}


@dataclass(frozen=True)
class ChromaCollectionReadiness:
    """Readiness result for one Chroma collection."""

    finding: str | None
    details: dict[str, Any]

    @property
    def ready(self) -> bool:
        return self.finding is None


class RagReadinessError(RuntimeError):
    """Raised when runtime code tries to use a non-ready RAG collection."""

    def __init__(self, finding: str, details: Mapping[str, Any]):
        super().__init__(finding)
        self.finding = finding
        self.details = dict(details)
        self.finding_code = str(self.details.get("finding_code") or "rag_not_ready")


def rag_vectorstore_contract_details() -> dict[str, Any]:
    """Return the public/internal vector store contract without secret values."""

    return {
        "public": dict(PUBLIC_VECTORSTORE_CONTRACT),
        "internal": dict(INTERNAL_VECTORSTORE_CONTRACT),
    }


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _metadata_values_for_embedding(
    connection: sqlite3.Connection,
    embedding_id: object,
) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT key, string_value, int_value, float_value, bool_value
        FROM embedding_metadata
        WHERE id = ?
        """,
        (embedding_id,),
    ).fetchall()
    metadata: dict[str, str] = {}
    for key, string_value, int_value, float_value, bool_value in rows:
        value = string_value
        if value is None:
            value = int_value if int_value is not None else float_value
        if value is None:
            value = bool_value
        if value is not None:
            metadata[str(key)] = str(value)
    return metadata


def _metadata_rows_for_embeddings(
    connection: sqlite3.Connection,
    embedding_ids: Iterable[object],
) -> list[dict[str, str]]:
    return [
        _metadata_values_for_embedding(connection, embedding_id)
        for embedding_id in embedding_ids
    ]


def _document_text(metadata: Mapping[str, str]) -> str:
    return " ".join(
        str(value or "")
        for key, value in metadata.items()
        if key in {"chroma:document", "document", "source", "title", "category"}
    )


def _probe_matches(metadata: Mapping[str, str], probe: Mapping[str, Any]) -> bool:
    expected_metadata = probe.get("metadata") or {}
    for key, expected in expected_metadata.items():
        if metadata.get(str(key)) != str(expected):
            return False

    terms = tuple(str(term) for term in probe.get("terms_any") or () if str(term))
    if not terms:
        return True
    haystack = _document_text(metadata)
    return any(term.lower() in haystack.lower() for term in terms)


def _find_retrieval_probe_gap(
    metadata_rows: Iterable[Mapping[str, str]],
    retrieval_probes: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any] | None:
    rows = list(metadata_rows)
    for probe in retrieval_probes or ():
        if not any(_probe_matches(row, probe) for row in rows):
            return {
                "probe": dict(probe),
                "available_categories": sorted(
                    {row.get("category", "") for row in rows if row.get("category")}
                ),
                "available_visibilities": sorted(
                    {row.get("visibility", "") for row in rows if row.get("visibility")}
                ),
            }
    return None


def _embedding_ids_for_collection(
    connection: sqlite3.Connection,
    collection_id: object,
    *,
    sample_size: int,
) -> tuple[int, list[object]]:
    embedding_columns = _table_columns(connection, "embeddings")
    if "collection_id" in embedding_columns:
        count = connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE collection_id = ?",
            (collection_id,),
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT id FROM embeddings WHERE collection_id = ? LIMIT ?",
            (collection_id, sample_size),
        ).fetchall()
        return int(count), [row[0] for row in rows]

    if "collection" in embedding_columns:
        count = connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE collection = ?",
            (collection_id,),
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT id FROM embeddings WHERE collection = ? LIMIT ?",
            (collection_id, sample_size),
        ).fetchall()
        return int(count), [row[0] for row in rows]

    if "segment_id" in embedding_columns and _has_table(connection, "segments"):
        segment_columns = _table_columns(connection, "segments")
        collection_column = (
            "collection"
            if "collection" in segment_columns
            else "collection_id"
            if "collection_id" in segment_columns
            else None
        )
        if collection_column:
            count = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM embeddings e
                JOIN segments s ON e.segment_id = s.id
                WHERE s.{collection_column} = ?
                """,
                (collection_id,),
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT e.id
                FROM embeddings e
                JOIN segments s ON e.segment_id = s.id
                WHERE s.{collection_column} = ?
                LIMIT ?
                """,
                (collection_id, sample_size),
            ).fetchall()
            return int(count), [row[0] for row in rows]

    raise sqlite3.DatabaseError(
        "cannot map embeddings table rows back to a collection"
    )


def _all_embedding_ids_for_collection(
    connection: sqlite3.Connection,
    collection_id: object,
) -> list[object]:
    _count, embedding_ids = _embedding_ids_for_collection(
        connection,
        collection_id,
        sample_size=2_000_000,
    )
    return embedding_ids


def check_chroma_collection_readiness(
    *,
    configured_path: str,
    collection_name: str,
    label: str,
    expected_metadata: Mapping[str, str],
    required_metadata: Iterable[str],
    category_required_metadata: Mapping[str, Iterable[str]] | None = None,
    project_root: Path | None = None,
    sample_size: int = 5,
    retrieval_probes: Iterable[Mapping[str, Any]] | None = None,
) -> ChromaCollectionReadiness:
    """Validate one persisted Chroma collection and its evidence metadata."""

    vectorstore_path = Path(configured_path)
    if not vectorstore_path.is_absolute() and project_root is not None:
        vectorstore_path = project_root / vectorstore_path
    details: dict[str, Any] = {
        "path": str(vectorstore_path),
        "collection_name": collection_name,
        "required_metadata": list(required_metadata),
        "category_required_metadata": {
            str(category): list(fields)
            for category, fields in (category_required_metadata or {}).items()
        },
        "expected_metadata": dict(expected_metadata),
    }

    if not vectorstore_path.exists():
        details["finding_code"] = "vectorstore_missing"
        return ChromaCollectionReadiness(
            f"{label} directory does not exist.",
            details,
        )
    if not vectorstore_path.is_dir():
        details["finding_code"] = "vectorstore_path_not_directory"
        return ChromaCollectionReadiness(
            f"{label} path is not a directory.",
            details,
        )

    metadata_path = vectorstore_path / "chroma.sqlite3"
    details["metadata_path"] = str(metadata_path)
    if not metadata_path.exists():
        details["finding_code"] = "vectorstore_missing"
        return ChromaCollectionReadiness(
            f"{label} metadata file chroma.sqlite3 is missing.",
            details,
        )

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{metadata_path.as_posix()}?mode=ro", uri=True)
        if not _has_table(connection, "collections"):
            details["finding_code"] = "metadata_schema_missing"
            return ChromaCollectionReadiness(
                f"{label} metadata has no collections table.",
                details,
            )
        collection = connection.execute(
            "SELECT id FROM collections WHERE name = ? LIMIT 1",
            (collection_name,),
        ).fetchone()
        if collection is None:
            details["finding_code"] = "collection_missing"
            return ChromaCollectionReadiness(
                f"{label} collection {collection_name!r} is missing.",
                details,
            )

        collection_id = collection[0]
        details["collection_id"] = str(collection_id)
        for table_name in ("embeddings", "embedding_metadata"):
            if not _has_table(connection, table_name):
                details["finding_code"] = "metadata_schema_missing"
                return ChromaCollectionReadiness(
                    f"{label} metadata has no {table_name} table.",
                    details,
                )

        embedding_count, sample_embedding_ids = _embedding_ids_for_collection(
            connection,
            collection_id,
            sample_size=sample_size,
        )
        details["embedding_count"] = embedding_count
        details["metadata_sample_size"] = len(sample_embedding_ids)
        if embedding_count <= 0:
            details["finding_code"] = "retrieval_no_hit"
            return ChromaCollectionReadiness(
                f"{label} collection {collection_name!r} has no embeddings.",
                details,
            )

        required_keys = tuple(required_metadata)
        for embedding_id in sample_embedding_ids:
            metadata = _metadata_values_for_embedding(connection, embedding_id)
            category_specific_keys = tuple(
                (category_required_metadata or {}).get(metadata.get("category", ""), ())
            )
            required_for_row = tuple(dict.fromkeys((*required_keys, *category_specific_keys)))
            missing_keys = [key for key in required_for_row if key not in metadata]
            if missing_keys:
                details["bad_embedding_id"] = str(embedding_id)
                details["missing_metadata"] = missing_keys
                details["finding_code"] = "metadata_missing"
                return ChromaCollectionReadiness(
                    f"{label} collection {collection_name!r} has documents missing metadata: "
                    + ", ".join(missing_keys),
                    details,
                )
            for key, expected in expected_metadata.items():
                actual = metadata.get(key)
                if actual != expected:
                    details["bad_embedding_id"] = str(embedding_id)
                    details["metadata_mismatch"] = {
                        "key": key,
                        "expected": expected,
                        "actual": actual,
                    }
                    details["finding_code"] = "metadata_mismatch"
                    return ChromaCollectionReadiness(
                        f"{label} collection {collection_name!r} has invalid metadata "
                        f"{key}={actual!r}; expected {expected!r}.",
                        details,
                    )
        all_embedding_ids = _all_embedding_ids_for_collection(connection, collection_id)
        probes = tuple(retrieval_probes or ())
        details["retrieval_probe_count"] = len(probes)
        probe_gap = _find_retrieval_probe_gap(
            _metadata_rows_for_embeddings(connection, all_embedding_ids),
            probes,
        )
        if probe_gap:
            details["finding_code"] = "retrieval_no_hit"
            details["retrieval_probe_gap"] = probe_gap
            probe_name = (probe_gap.get("probe") or {}).get("name") or "unknown"
            return ChromaCollectionReadiness(
                f"{label} collection {collection_name!r} has no runtime retrieval hit "
                f"for probe {probe_name!r}.",
                details,
            )
    except sqlite3.Error as exc:
        details["error_type"] = exc.__class__.__name__
        details["finding_code"] = "metadata_unreadable"
        return ChromaCollectionReadiness(
            f"{label} metadata is not readable: {exc}",
            details,
        )
    finally:
        if connection is not None:
            connection.close()

    details["contract_version"] = CONTRACT_VERSION
    return ChromaCollectionReadiness(None, details)
