import pytest

from scripts import init_rag


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
