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
}


@dataclass(frozen=True)
class ChromaCollectionReadiness:
    """Readiness result for one Chroma collection."""

    finding: str | None
    details: dict[str, Any]

    @property
    def ready(self) -> bool:
        return self.finding is None


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


def check_chroma_collection_readiness(
    *,
    configured_path: str,
    collection_name: str,
    label: str,
    expected_metadata: Mapping[str, str],
    required_metadata: Iterable[str],
    project_root: Path | None = None,
    sample_size: int = 5,
) -> ChromaCollectionReadiness:
    """Validate one persisted Chroma collection and its evidence metadata."""

    vectorstore_path = Path(configured_path)
    if not vectorstore_path.is_absolute() and project_root is not None:
        vectorstore_path = project_root / vectorstore_path
    details: dict[str, Any] = {
        "path": str(vectorstore_path),
        "collection_name": collection_name,
        "required_metadata": list(required_metadata),
        "expected_metadata": dict(expected_metadata),
    }

    if not vectorstore_path.exists():
        return ChromaCollectionReadiness(
            f"{label} directory does not exist.",
            details,
        )
    if not vectorstore_path.is_dir():
        return ChromaCollectionReadiness(
            f"{label} path is not a directory.",
            details,
        )

    metadata_path = vectorstore_path / "chroma.sqlite3"
    details["metadata_path"] = str(metadata_path)
    if not metadata_path.exists():
        return ChromaCollectionReadiness(
            f"{label} metadata file chroma.sqlite3 is missing.",
            details,
        )

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{metadata_path.as_posix()}?mode=ro", uri=True)
        if not _has_table(connection, "collections"):
            return ChromaCollectionReadiness(
                f"{label} metadata has no collections table.",
                details,
            )
        collection = connection.execute(
            "SELECT id FROM collections WHERE name = ? LIMIT 1",
            (collection_name,),
        ).fetchone()
        if collection is None:
            return ChromaCollectionReadiness(
                f"{label} collection {collection_name!r} is missing.",
                details,
            )

        collection_id = collection[0]
        details["collection_id"] = str(collection_id)
        for table_name in ("embeddings", "embedding_metadata"):
            if not _has_table(connection, table_name):
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
            return ChromaCollectionReadiness(
                f"{label} collection {collection_name!r} has no embeddings.",
                details,
            )

        required_keys = tuple(required_metadata)
        for embedding_id in sample_embedding_ids:
            metadata = _metadata_values_for_embedding(connection, embedding_id)
            missing_keys = [key for key in required_keys if key not in metadata]
            if missing_keys:
                details["bad_embedding_id"] = str(embedding_id)
                details["missing_metadata"] = missing_keys
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
                    return ChromaCollectionReadiness(
                        f"{label} collection {collection_name!r} has invalid metadata "
                        f"{key}={actual!r}; expected {expected!r}.",
                        details,
                    )
    except sqlite3.Error as exc:
        details["error_type"] = exc.__class__.__name__
        return ChromaCollectionReadiness(
            f"{label} metadata is not readable: {exc}",
            details,
        )
    finally:
        if connection is not None:
            connection.close()

    details["contract_version"] = CONTRACT_VERSION
    return ChromaCollectionReadiness(None, details)
