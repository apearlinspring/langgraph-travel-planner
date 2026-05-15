import json
from pathlib import Path

import pytest

from scripts import build_project_demo_pack as demo_pack


SAFE_DOC_TEXT = """# Demo Source

AI-Agent（人工智能智能体）演示材料。

- RAG（检索增强生成）
- MCP（模型上下文协议）
- HITL（人类在环）
- CI/CD（持续集成/持续交付）
"""


def _write_required_sources(repo_root: Path, *, extra_text: str = "") -> None:
    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for relative_path in demo_pack.SOURCE_DOCUMENTS:
        (repo_root / relative_path).write_text(SAFE_DOC_TEXT + extra_text, encoding="utf-8")


def test_build_demo_pack_creates_sanitized_manifest(tmp_path: Path):
    _write_required_sources(tmp_path)

    manifest = demo_pack.build_demo_pack(tmp_path / ".runtime" / "project-demo-pack", repo_root=tmp_path)

    output_dir = tmp_path / ".runtime" / "project-demo-pack"
    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == demo_pack.PACK_VERSION
    assert saved_manifest["output_policy"]["reads_env_files"] is False
    assert saved_manifest["output_policy"]["copies_runtime_snapshots"] is False
    assert {item["id"] for item in saved_manifest["demo_paths"]} == {
        "local-briefing",
        "acceptance-smoke",
        "frontend-report",
    }
    assert (output_dir / "commands.ps1").exists()
    assert "NO_SENSITIVE_FINDINGS" in (output_dir / "redaction-check.txt").read_text(
        encoding="utf-8"
    )


def test_demo_pack_does_not_copy_env_or_runtime_sources(tmp_path: Path):
    _write_required_sources(tmp_path)
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=real-looking-secret-value", encoding="utf-8")
    runtime_dir = tmp_path / ".runtime" / "evaluations"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "snapshot.json").write_text(
        '{"authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456"}',
        encoding="utf-8",
    )

    demo_pack.build_demo_pack(tmp_path / "pack", repo_root=tmp_path)

    generated_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "pack").iterdir() if path.is_file()
    )
    assert "real-looking-secret-value" not in generated_text
    assert "abcdefghijklmnopqrstuvwxyz123456" not in generated_text
    assert ".env" not in [path.name for path in (tmp_path / "pack").iterdir()]

    manifest = json.loads((tmp_path / "pack" / "manifest.json").read_text(encoding="utf-8"))
    assert all(".runtime/evaluations" not in item["path"] for item in manifest["source_documents"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bearer abcdefghijklmnopqrstuvwxyz123456", "bearer_token"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "jwt",
        ),
        ("请联系 13800138000", "mainland_china_phone"),
        ("邮箱 test.person@example.com", "email"),
        ("api_key = sk-abcdefghijklmnopqrstuvwxyz123456", "assigned_secret"),
    ],
)
def test_sensitive_scanner_flags_common_secret_shapes(text: str, expected: str):
    assert expected in demo_pack.scan_sensitive_text(text)


def test_build_demo_pack_rejects_sensitive_source_document(tmp_path: Path):
    _write_required_sources(tmp_path, extra_text="\nBearer abcdefghijklmnopqrstuvwxyz123456\n")

    with pytest.raises(ValueError, match="Sensitive content detected"):
        demo_pack.build_demo_pack(tmp_path / "pack", repo_root=tmp_path)


def test_build_demo_pack_requires_all_source_documents(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Missing project demo source documents"):
        demo_pack.build_demo_pack(tmp_path / "pack", repo_root=tmp_path)


def test_committed_project_docs_build_without_sensitive_content(tmp_path: Path):
    manifest = demo_pack.build_demo_pack(tmp_path / "pack", repo_root=Path.cwd())

    assert manifest["output_policy"]["reads_env_files"] is False
    assert manifest["output_policy"]["copies_runtime_snapshots"] is False
    assert (tmp_path / "pack" / "manifest.json").exists()
    assert "NO_SENSITIVE_FINDINGS" in (tmp_path / "pack" / "redaction-check.txt").read_text(
        encoding="utf-8"
    )


def test_project_docs_cover_required_capabilities_and_demo_paths():
    combined = "\n".join(
        [
            Path("docs/project-demo-pack.md").read_text(encoding="utf-8"),
            Path("docs/project-capability-map.md").read_text(encoding="utf-8"),
            Path("docs/demo-script.md").read_text(encoding="utf-8"),
            Path("README.md").read_text(encoding="utf-8"),
        ]
    )

    for phrase in [
        "多智能体编排",
        "状态机",
        "工具调用",
        "RAG（检索增强生成）",
        "MCP（模型上下文协议）",
        "HITL（人类在环）",
        "治理",
        "可观测性",
        "验收门禁",
        "CI/CD（持续集成/持续交付）",
        "本地纯讲解路径",
        "acceptance-smoke",
        "前端报告路径",
        "report_data",
    ]:
        assert phrase in combined
