from pathlib import Path

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.rag import vectorstore as vectorstore_module
from scripts import init_rag


class _DeterministicEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.0, 1.0] for index, _text in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 1.0]


def test_init_rag_blocks_without_real_dashscope_key(monkeypatch):
    class FakeSettings:
        dashscope_api_key = ""

    monkeypatch.setattr(init_rag, "settings", FakeSettings())
    monkeypatch.setattr(init_rag, "has_real_env_value", lambda value: bool(value))

    with pytest.raises(init_rag.RagInitializationError) as exc_info:
        init_rag._ensure_model_credentials()

    message = str(exc_info.value)
    assert message.startswith("blocked:")
    assert "DASHSCOPE_API_KEY" in message
    assert "text-embedding-v2" in message
    assert "scripts.init_rag" in message


def test_replace_vectorstore_directory_preserves_previous_store(tmp_path):
    target_dir = tmp_path / "vectorstore"
    target_dir.mkdir()
    (target_dir / "chroma.sqlite3").write_text("old", encoding="utf-8")

    build_dir = init_rag._new_refresh_auxiliary_path(target_dir, "build")
    build_dir.mkdir(parents=True)
    (build_dir / "chroma.sqlite3").write_text("new", encoding="utf-8")

    backup_dir = init_rag._replace_vectorstore_directory(
        target_dir=target_dir,
        build_dir=build_dir,
        label="测试 RAG",
    )

    assert backup_dir is not None
    assert target_dir.exists()
    assert not build_dir.exists()
    assert (target_dir / "chroma.sqlite3").read_text(encoding="utf-8") == "new"
    assert (backup_dir / "chroma.sqlite3").read_text(encoding="utf-8") == "old"
    assert backup_dir.parent.name == ".rag-vectorstore-backups"


def test_replace_vectorstore_directory_restores_backup_if_promotion_fails(
    monkeypatch,
    tmp_path,
):
    target_dir = tmp_path / "vectorstore"
    target_dir.mkdir()
    (target_dir / "chroma.sqlite3").write_text("old", encoding="utf-8")
    build_dir = init_rag._new_refresh_auxiliary_path(target_dir, "build")
    build_dir.mkdir(parents=True)
    (build_dir / "chroma.sqlite3").write_text("new", encoding="utf-8")

    original_replace = Path.replace

    def fail_build_promotion(path, target):
        if path == build_dir:
            raise PermissionError("simulated locked HNSW file")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_build_promotion)

    with pytest.raises(PermissionError, match="locked HNSW"):
        init_rag._replace_vectorstore_directory(
            target_dir=target_dir,
            build_dir=build_dir,
            label="测试 RAG",
        )

    assert (target_dir / "chroma.sqlite3").read_text(encoding="utf-8") == "old"
    assert (build_dir / "chroma.sqlite3").read_text(encoding="utf-8") == "new"


def test_rollback_vectorstore_replacement_restores_backup(tmp_path):
    target_dir = tmp_path / "vectorstore"
    target_dir.mkdir()
    (target_dir / "chroma.sqlite3").write_text("new-broken", encoding="utf-8")

    backup_dir = init_rag._new_refresh_auxiliary_path(target_dir, "backup")
    backup_dir.mkdir(parents=True)
    (backup_dir / "chroma.sqlite3").write_text("old-good", encoding="utf-8")

    init_rag._rollback_vectorstore_replacement(
        target_dir=target_dir,
        backup_dir=backup_dir,
        label="测试 RAG",
    )

    assert target_dir.exists()
    assert (target_dir / "chroma.sqlite3").read_text(encoding="utf-8") == "old-good"
    assert not backup_dir.exists()
    failed_root = target_dir.parent / ".rag-vectorstore-faileds"
    failed_paths = list(failed_root.glob("vectorstore-*"))
    assert len(failed_paths) == 1
    assert (failed_paths[0] / "chroma.sqlite3").read_text(encoding="utf-8") == "new-broken"


def test_cleanup_refresh_build_refuses_non_build_directory(tmp_path):
    unsafe_dir = tmp_path / "vectorstore"
    unsafe_dir.mkdir()

    with pytest.raises(init_rag.RagInitializationError, match="non-build"):
        init_rag._cleanup_refresh_build(unsafe_dir)


def test_build_vectorstore_releases_chroma_before_promotion(monkeypatch, tmp_path):
    monkeypatch.setattr(
        vectorstore_module,
        "DashScopeEmbeddings",
        lambda **_kwargs: _DeterministicEmbeddings(),
    )

    class PassthroughSplitter:
        def split_documents(self, documents):
            return documents, documents

    monkeypatch.setattr(init_rag, "AdvancedParentDocumentSplitter", PassthroughSplitter)
    target_dir = tmp_path / "vectorstore"
    build_dir = init_rag._build_vectorstore(
        documents=[Document(page_content="Windows HNSW lock regression")],
        persist_directory=str(target_dir),
        collection_name="close_regression",
        label="测试 RAG",
    )

    assert list(build_dir.rglob("data_level0.bin"))
    init_rag._replace_vectorstore_directory(
        target_dir=target_dir,
        build_dir=build_dir,
        label="测试 RAG",
    )
    assert list(target_dir.rglob("data_level0.bin"))


def test_build_vectorstore_closes_manager_before_failure_cleanup(monkeypatch, tmp_path):
    events: list[str] = []

    class FakeSplitter:
        def split_documents(self, documents):
            return documents, documents

    class FakeManager:
        def __init__(self, *, persist_directory, collection_name):
            self.persist_directory = Path(persist_directory)
            self.persist_directory.mkdir(parents=True)

        def create_vectorstore(self, documents):
            events.append("create")
            raise RuntimeError("build failed")

        def close(self):
            events.append("close")

    def fake_cleanup(build_dir):
        events.append("cleanup")

    monkeypatch.setattr(init_rag, "AdvancedParentDocumentSplitter", FakeSplitter)
    monkeypatch.setattr(init_rag, "VectorStoreManager", FakeManager)
    monkeypatch.setattr(init_rag, "_cleanup_refresh_build", fake_cleanup)

    with pytest.raises(RuntimeError, match="build failed"):
        init_rag._build_vectorstore(
            documents=[object()],
            persist_directory=str(tmp_path / "vectorstore"),
            collection_name="test_collection",
            label="测试 RAG",
        )

    assert events == ["create", "close", "cleanup"]
