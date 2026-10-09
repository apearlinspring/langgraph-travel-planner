from pathlib import Path

from scripts import check_public_release_boundary as boundary


def test_public_release_boundary_flags_forbidden_paths_without_scanning_content(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("DASHSCOPE_API_KEY=real-looking-secret-value", encoding="utf-8")

    report = boundary.build_public_release_boundary_report(
        repo_root=tmp_path,
        candidate_paths=[Path(".env")],
    )

    assert report["status"] == "blocked"
    assert report["forbidden_paths"] == [".env"]
    assert report["content_findings"] == []
    assert ".env" in report["skipped_content_paths"]


def test_public_release_boundary_flags_real_secret_assignments(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text(
        'DASHSCOPE_API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"\n',
        encoding="utf-8",
    )

    report = boundary.build_public_release_boundary_report(
        repo_root=tmp_path,
        candidate_paths=[Path("app.py")],
    )

    assert report["status"] == "blocked"
    assert report["content_findings"][0]["kind"] == "secret_assignment"
    assert report["content_findings"][0]["key"] == "DASHSCOPE_API_KEY"


def test_public_release_boundary_allows_placeholders_and_runtime_references(tmp_path: Path):
    source = tmp_path / "settings.py"
    source.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=change-me",
                "JWT_SECRET_KEY=<real-secret>",
                "SECRET_KEY = settings.jwt_secret_key",
                "AMAP_API_KEY=${AMAP_API_KEY:-}",
            ]
        ),
        encoding="utf-8",
    )

    report = boundary.build_public_release_boundary_report(
        repo_root=tmp_path,
        candidate_paths=[Path("settings.py")],
    )

    assert report["status"] == "passed"
    assert report["content_findings"] == []


def test_public_release_boundary_skips_test_content_by_default(tmp_path: Path):
    test_file = tmp_path / "tests" / "test_fake_secret.py"
    test_file.parent.mkdir()
    test_file.write_text(
        'def test_fake():\n    assert "Bearer abcdefghijklmnopqrstuvwxyz123456"\n',
        encoding="utf-8",
    )

    report = boundary.build_public_release_boundary_report(
        repo_root=tmp_path,
        candidate_paths=[Path("tests/test_fake_secret.py")],
    )

    assert report["status"] == "passed"
    assert report["content_findings"] == []
    assert "tests/test_fake_secret.py" in report["skipped_content_paths"]
