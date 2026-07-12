from pathlib import Path

import pytest

from scripts import accept_rag_multimodal_e2e as acceptance


def test_multimodal_acceptance_script_imports_cleanly():
    assert acceptance.RAG_MULTIMODAL_E2E_ACCEPTANCE_VERSION.endswith(".v1")
    assert callable(acceptance.run_multimodal_e2e_acceptance)
    assert callable(acceptance.main)


def test_multimodal_acceptance_rejects_output_outside_runtime():
    with pytest.raises(acceptance.AcceptanceBlocked, match="inside .runtime"):
        acceptance._assert_runtime_child(acceptance.PROJECT_ROOT)


def test_multimodal_acceptance_main_does_not_write_blocked_result_outside_runtime(
    tmp_path: Path,
    capsys,
):
    unsafe_root = tmp_path / "outside-runtime"
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    exit_code = acceptance.main(
        [
            "--root",
            str(unsafe_root),
            "--source-dir",
            str(source_dir),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"status": "blocked"' in captured.out
    assert not unsafe_root.exists()


def test_multimodal_acceptance_reports_missing_assets(tmp_path: Path):
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "destination"
    source_dir.mkdir()

    with pytest.raises(acceptance.AcceptanceBlocked) as exc_info:
        acceptance._copy_assets(source_dir, destination_dir)

    message = str(exc_info.value)
    assert "Missing multimodal acceptance assets" in message
    assert "openai-whisper-jfk.flac" in message


def test_multimodal_acceptance_configures_whisper_cache(tmp_path: Path):
    root = tmp_path / ".runtime" / "rag_e2e_acceptance"

    updates = acceptance.configure_acceptance_environment(root=root)

    assert updates["RAG_WHISPER_MODEL_SIZE"] == "tiny"
    assert updates["RAG_WHISPER_DEVICE"] == "cpu"
    assert updates["RAG_WHISPER_COMPUTE_TYPE"] == "int8"
    assert updates["RAG_WHISPER_MODEL_CACHE"] == str(root / "whisper_models")
    assert "{input}" in updates["RAG_MULTIMODAL_TRANSCRIPT_COMMAND"]
    assert "scripts/rag_transcribe_whisper.py" in updates["RAG_MULTIMODAL_TRANSCRIPT_COMMAND"]
    assert f'"{root / "whisper_models"}"' in updates["RAG_MULTIMODAL_TRANSCRIPT_COMMAND"]


def test_multimodal_acceptance_human_renderer_summarizes_ranked_hits():
    report = {
        "status": "passed",
        "passed": True,
        "loaded_from_disk": True,
        "document_count": 3,
        "child_count": 5,
        "query_results": [
            {
                "id": "audio_jfk_whisper",
                "passed": True,
                "expected_hit_rank": 1,
                "expected_hit_extraction_method": "audio_transcript_command",
                "hits": [{"source": "D:/tmp/openai-whisper-jfk.flac"}],
            }
        ],
    }

    rendered = acceptance.render_human(report)

    assert "status: passed" in rendered
    assert "audio_jfk_whisper" in rendered
    assert "rank=1" in rendered
    assert "openai-whisper-jfk.flac" in rendered
