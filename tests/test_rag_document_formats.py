from datetime import date
import json
from pathlib import Path
import subprocess
import sys

from app.rag.contracts import validate_internal_knowledge_base
from app.rag.document_formats import extract_knowledge_document
from app.rag.document_loader import DocumentManager
from scripts.check_rag_multimodal_readiness import build_rag_multimodal_readiness_report
from scripts.rag_transcribe_sidecar import extract_sidecar_transcript
from scripts.rag_transcribe_whisper import WhisperTranscriptionConfig, transcribe_media


def test_document_manager_loads_multiple_public_text_formats(tmp_path: Path):
    destinations = tmp_path / "destinations"
    destinations.mkdir()
    (destinations / "hangzhou.txt").write_text(
        """---
title: 杭州自由行攻略
---
# 杭州自由行
西湖、灵隐寺和河坊街适合第一次到访。
""",
        encoding="utf-8",
    )
    (destinations / "chengdu.json").write_text(
        """{
  "metadata": {"title": "成都美食攻略"},
  "content": "成都火锅、串串和宽窄巷子适合美食主题检索。"
}""",
        encoding="utf-8",
    )
    (destinations / "xian_food.csv").write_text(
        "name,area\n肉夹馍,回民街\nbiangbiang面,碑林\n",
        encoding="utf-8",
    )

    documents = DocumentManager(str(tmp_path)).load_destination_documents()
    by_format = {doc.metadata["source_format"]: doc for doc in documents}

    assert {"txt", "json", "csv"}.issubset(by_format)
    assert by_format["txt"].metadata["title"] == "杭州自由行攻略"
    assert "成都火锅" in by_format["json"].page_content
    assert "肉夹馍 | 回民街" in by_format["csv"].page_content
    assert all(doc.metadata["visibility"] == "public" for doc in documents)


def test_document_manager_loads_multimodal_file_with_sidecar(tmp_path: Path):
    destinations = tmp_path / "destinations"
    destinations.mkdir()
    image_path = destinations / "xian-map.png"
    image_path.write_bytes(b"not-a-real-image-fixture")
    (destinations / "xian-map.png.md").write_text(
        """---
title: 西安景区地图
---
图片说明：展示兵马俑、城墙和回民街的大致方位，适合路线规划时检索。
""",
        encoding="utf-8",
    )

    documents = DocumentManager(str(tmp_path)).load_destination_documents()
    image_doc = next(doc for doc in documents if doc.metadata["source_format"] == "png")

    assert image_doc.metadata["content_modality"] == "image"
    assert image_doc.metadata["extraction_method"] == "image_sidecar"
    assert image_doc.metadata["title"] == "西安景区地图"
    assert "兵马俑" in image_doc.page_content
    assert image_doc.metadata["sidecar_source"].endswith("xian-map.png.md")


def test_multimodal_file_without_sidecar_is_marked_as_metadata_only(tmp_path: Path):
    image_path = tmp_path / "unknown-map.png"
    image_path.write_bytes(b"not-a-real-image-fixture")

    extracted = extract_knowledge_document(image_path)

    assert extracted.extraction_method == "image_metadata"
    assert extracted.sidecar_source is None
    assert "仅按文件名和元数据参与召回" in extracted.text


def test_image_auto_extraction_adds_searchable_caption(tmp_path: Path, monkeypatch):
    from app.rag import multimodal_extractor

    image_path = tmp_path / "xian-map.png"
    image_path.write_bytes(b"not-a-real-image-fixture")
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv("RAG_MULTIMODAL_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setattr(
        multimodal_extractor,
        "_describe_image_with_vision",
        lambda path: "自动图像描述：画面包含西安城墙、兵马俑和回民街标注。",
    )

    extracted = extract_knowledge_document(image_path)

    assert extracted.extraction_method == "image_vision"
    assert extracted.metadata["multimodal_auto_extract_status"] == "success"
    assert "自动多模态抽取" in extracted.text
    assert "兵马俑" in extracted.text


def test_document_manager_preserves_multimodal_runtime_metadata(tmp_path: Path, monkeypatch):
    from app.rag import multimodal_extractor

    destinations = tmp_path / "destinations"
    destinations.mkdir()
    image_path = destinations / "xian-map.png"
    image_path.write_bytes(b"not-a-real-image-fixture")
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv("RAG_MULTIMODAL_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setattr(
        multimodal_extractor,
        "_describe_image_with_vision",
        lambda path: "自动图像描述：画面包含西安城墙、兵马俑和回民街标注。",
    )

    documents = DocumentManager(str(tmp_path)).load_destination_documents()
    image_doc = next(doc for doc in documents if doc.metadata["source_format"] == "png")

    assert image_doc.metadata["extraction_method"] == "image_vision"
    assert image_doc.metadata["auto_extraction_method"] == "image_vision"
    assert image_doc.metadata["multimodal_auto_extract_status"] == "success"
    assert image_doc.metadata["vision_model"]


def test_audio_auto_extraction_uses_trusted_transcript_hook(tmp_path: Path, monkeypatch):
    from app.rag import multimodal_extractor

    audio_path = tmp_path / "guide.mp3"
    audio_path.write_bytes(b"not-a-real-audio-fixture")
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv("RAG_MULTIMODAL_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setattr(
        multimodal_extractor,
        "_run_transcript_command",
        lambda path: "音频转写：导游介绍西安城墙夜游和本地小吃。",
    )

    extracted = extract_knowledge_document(audio_path)

    assert extracted.extraction_method == "audio_transcript_command"
    assert extracted.metadata["multimodal_auto_extract_status"] == "success"
    assert "音频转写" in extracted.text
    assert "本地小吃" in extracted.text


def test_sidecar_transcript_command_strips_vtt_timeline(tmp_path: Path):
    video_path = tmp_path / "city-road.mp4"
    video_path.write_bytes(b"not-a-real-video-fixture")
    (tmp_path / "city-road.mp4.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n城市道路视频样例。\n\n"
        "00:00:02.000 --> 00:00:04.000\n步行换乘和交通动线需要二次核验。\n",
        encoding="utf-8",
    )

    sidecar, transcript = extract_sidecar_transcript(video_path)

    assert sidecar and sidecar.name == "city-road.mp4.vtt"
    assert "WEBVTT" not in transcript
    assert "-->" not in transcript
    assert "城市道路视频样例" in transcript
    assert "交通动线" in transcript


def test_audio_auto_extraction_can_use_sidecar_transcript_command(tmp_path: Path, monkeypatch):
    audio_dir = tmp_path / "media files"
    audio_dir.mkdir()
    audio_path = audio_dir / "guide audio.mp3"
    audio_path.write_bytes(b"not-a-real-audio-fixture")
    (audio_dir / "guide audio.mp3.md").write_text(
        "音频转写：城市公园步道适合老人慢行路线。",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv("RAG_MULTIMODAL_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setenv(
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
        f"{sys.executable} scripts/rag_transcribe_sidecar.py {{input}}",
    )

    extracted = extract_knowledge_document(audio_path)

    assert extracted.extraction_method == "audio_transcript_command"
    assert extracted.metadata["multimodal_auto_extract_status"] == "success"
    assert "老人慢行路线" in extracted.text


def test_transcript_command_strips_wrapping_quotes_for_paths_with_spaces(
    tmp_path: Path,
    monkeypatch,
):
    from app.rag import multimodal_extractor

    media_dir = tmp_path / "media files"
    media_dir.mkdir()
    media_path = media_dir / "guide audio.mp3"
    media_path.write_bytes(b"fake")
    model_cache = tmp_path / "model cache"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="quoted path transcript\n", stderr="")

    monkeypatch.setenv(
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
        f'python scripts/rag_transcribe_whisper.py "{{input}}" --model-cache "{model_cache}"',
    )
    monkeypatch.setattr(multimodal_extractor.subprocess, "run", fake_run)

    transcript = multimodal_extractor._run_transcript_command(media_path)

    assert transcript == "quoted path transcript"
    assert str(media_path) in captured["command"]
    assert str(model_cache) in captured["command"]
    assert all(not str(part).startswith(("'", '"')) for part in captured["command"])
    assert all(not str(part).endswith(("'", '"')) for part in captured["command"])


def test_video_transcript_runs_even_when_ffmpeg_is_missing(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "city-road.mp4"
    video_path.write_bytes(b"not-a-real-video-fixture")
    (tmp_path / "city-road.mp4.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n城市道路视频样例，用于交通动线检索。\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv("RAG_MULTIMODAL_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setenv(
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
        f"{sys.executable} scripts/rag_transcribe_sidecar.py {{input}}",
    )
    monkeypatch.setattr("app.rag.multimodal_extractor.find_ffmpeg", lambda: None)

    extracted = extract_knowledge_document(video_path)

    assert extracted.extraction_method == "video_keyframe_vision"
    assert extracted.metadata["multimodal_auto_extract_status"] == "success"
    assert extracted.metadata["video_keyframe_error"] == "RuntimeError"
    assert extracted.metadata["transcript_command_configured"] == "true"
    assert "城市道路视频样例" in extracted.text


def test_multimodal_readiness_reports_transcript_fallback_without_ffmpeg(monkeypatch):
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv(
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
        "uv run python scripts/rag_transcribe_sidecar.py {input}",
    )
    monkeypatch.setattr("scripts.check_rag_multimodal_readiness.find_ffmpeg", lambda: None)

    report = build_rag_multimodal_readiness_report()

    assert report["enabled"] is True
    assert report["status"] == "degraded"
    assert report["ffmpeg"]["status"] == "not_configured"
    assert report["transcript_command"]["status"] == "configured"
    assert report["transcript_command"]["has_input_placeholder"] is True


def test_multimodal_readiness_redacts_local_runtime_paths(monkeypatch):
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv("RAG_MULTIMODAL_CACHE_PATH", ".runtime/rag_multimodal_cache")
    monkeypatch.setenv("RAG_WHISPER_MODEL_CACHE", ".runtime/rag_whisper_models")
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.find_ffmpeg",
        lambda: str(Path.cwd() / ".venv" / "Scripts" / "ffmpeg.exe"),
    )

    report = build_rag_multimodal_readiness_report()

    assert report["cache_path"] == ".runtime/<redacted>"
    assert report["ffmpeg"]["path"] == ".venv/<redacted>"
    assert report["asr"]["model_cache"] == ".runtime/<redacted>"
    rendered = json.dumps(report, ensure_ascii=False)
    assert str(Path.cwd()) not in rendered


def test_multimodal_readiness_can_use_imageio_ffmpeg(monkeypatch):
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")
    monkeypatch.setenv(
        "RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
        "uv run python scripts/rag_transcribe_sidecar.py {input}",
    )

    report = build_rag_multimodal_readiness_report()

    assert report["enabled"] is True
    assert report["ffmpeg"]["status"] == "configured"
    assert report["transcript_command"]["status"] == "configured"
    assert report["transcript_command"]["has_input_placeholder"] is True
    assert report["asr"]["engine"] == "faster-whisper"
    assert report["e2e_acceptance"]["status"] == "not_checked"


def test_multimodal_readiness_can_include_e2e_acceptance(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.has_real_env_value",
        lambda value: True,
    )
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.find_ffmpeg",
        lambda: "ffmpeg.exe",
    )
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.faster_whisper_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness._run_e2e_acceptance_check",
        lambda: {
            "status": "passed",
            "passed": True,
            "loaded_from_disk": True,
            "document_count": 3,
            "query_results": [
                {
                    "id": "audio_jfk_whisper",
                    "passed": True,
                    "expected_hit_rank": 1,
                }
            ],
        },
    )

    report = build_rag_multimodal_readiness_report(check_e2e=True)

    assert report["status"] == "passed"
    assert report["enabled"] is True
    assert report["transcript_command"]["status"] == "configured"
    assert report["e2e_acceptance"]["status"] == "passed"
    assert report["e2e_acceptance"]["passed"] is True


def test_multimodal_readiness_marks_e2e_failure_as_degraded(monkeypatch):
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.has_real_env_value",
        lambda value: True,
    )
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.find_ffmpeg",
        lambda: "ffmpeg.exe",
    )
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness.faster_whisper_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "scripts.check_rag_multimodal_readiness._run_e2e_acceptance_check",
        lambda: {"status": "failed", "passed": False, "error": "rank mismatch"},
    )

    report = build_rag_multimodal_readiness_report(check_e2e=True)

    assert report["status"] == "degraded"
    assert report["e2e_acceptance"]["status"] == "failed"
    assert any("e2e acceptance" in finding for finding in report["findings"])


def test_whisper_transcript_command_can_be_unit_tested_with_fake_model(tmp_path: Path):
    class FakeSegment:
        def __init__(self, start: float, end: float, text: str):
            self.start = start
            self.end = end
            self.text = text

    class FakeInfo:
        language = "zh"
        language_probability = 0.99
        duration = 2.5
        duration_after_vad = 2.0

    class FakeModel:
        def transcribe(self, path: str, **kwargs):
            assert kwargs["language"] == "zh"
            assert kwargs["beam_size"] == 1
            assert kwargs["vad_filter"] is False
            return [
                FakeSegment(0.0, 1.0, " 西安城墙适合夜游 "),
                FakeSegment(1.0, 2.0, ""),
                FakeSegment(2.0, 2.5, " 回民街适合安排小吃。"),
            ], FakeInfo()

    media_path = tmp_path / "guide.mp3"
    media_path.write_bytes(b"fake-audio")
    config = WhisperTranscriptionConfig(
        model_size="tiny",
        device="cpu",
        compute_type="int8",
        model_cache=tmp_path / "models",
        language="zh",
        beam_size=1,
        vad_filter=False,
        local_files_only=True,
    )

    result = transcribe_media(media_path, config, model_factory=lambda _: FakeModel())

    assert result["text"] == "西安城墙适合夜游\n回民街适合安排小吃。"
    assert result["segments"][0]["start"] == 0.0
    assert result["info"]["language"] == "zh"


def test_video_subtitle_sidecar_is_indexed_without_auto_extraction(tmp_path: Path):
    video_path = tmp_path / "xian-guide.mp4"
    video_path.write_bytes(b"not-a-real-video-fixture")
    (tmp_path / "xian-guide.mp4.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n西安城墙骑行和回民街美食适合夜间安排。\n",
        encoding="utf-8",
    )

    extracted = extract_knowledge_document(video_path)

    assert extracted.extraction_method == "video_sidecar"
    assert "西安城墙骑行" in extracted.text
    assert extracted.sidecar_source.endswith("xian-guide.mp4.vtt")


def test_internal_knowledge_validation_covers_non_markdown_formats(tmp_path: Path):
    internal = tmp_path / "internal" / "pricing"
    internal.mkdir(parents=True)
    (internal / "pricing_rules.txt").write_text(
        """---
source_type: agency_internal
category: pricing
visibility: internal
applicable_modes:
  - agency_plan
  - free_planning
evidence_level: rule
last_reviewed: "2026-05-11"
---
# 报价规则
费用包含、不含和待核验价格必须分开说明。
""",
        encoding="utf-8",
    )

    report = validate_internal_knowledge_base(
        tmp_path / "internal",
        today=date(2026, 5, 11),
    )

    assert report.passed is True
    assert report.checked_files == 1


def test_internal_knowledge_validation_does_not_run_multimodal_auto_extraction(
    tmp_path: Path,
    monkeypatch,
):
    from app.rag import multimodal_extractor

    internal = tmp_path / "internal" / "risk"
    internal.mkdir(parents=True)
    image_path = internal / "weather-risk.jpg"
    image_path.write_bytes(b"not-a-real-image-fixture")
    (internal / "weather-risk.jpg.md").write_text(
        """---
source_type: agency_internal
category: risk
visibility: internal
applicable_modes:
  - agency_plan
  - free_planning
evidence_level: warning
last_reviewed: "2026-05-11"
---
图片说明：暴雨天气下景区排队和交通延误需要 Plan B。
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT", "true")

    def fail_if_called(path):
        raise AssertionError("validation should not run multimodal extraction")

    monkeypatch.setattr(multimodal_extractor, "extract_multimodal_text", fail_if_called)

    report = validate_internal_knowledge_base(
        tmp_path / "internal",
        today=date(2026, 5, 11),
    )

    assert report.passed is True
    assert report.checked_files == 1
