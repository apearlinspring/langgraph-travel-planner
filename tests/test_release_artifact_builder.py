import json
import subprocess

from scripts import build_release_artifact as artifact


def _boundary(status: str = "passed"):
    return {
        "version": "public_release_boundary.v1",
        "status": status,
        "candidate_count": 3,
        "scanned_count": 3,
        "forbidden_paths": [],
        "content_findings": [],
        "skipped_content_paths": [],
    }


def _clean_git_runner(args, *, timeout_seconds=30):
    command = list(args)
    if command == ["git", "status", "--short", "--branch"]:
        return subprocess.CompletedProcess(command, 0, stdout="## main...origin/main\n", stderr="")
    if command == ["git", "rev-parse", "HEAD"]:
        return subprocess.CompletedProcess(command, 0, stdout="abcdef1234567890abcdef1234567890abcdef12\n", stderr="")
    if command == ["git", "rev-parse", "--short", "HEAD"]:
        return subprocess.CompletedProcess(command, 0, stdout="abcdef1\n", stderr="")
    if command == ["git", "rev-parse", "HEAD^{tree}"]:
        return subprocess.CompletedProcess(command, 0, stdout="tree123\n", stderr="")
    if command == ["git", "branch", "--show-current"]:
        return subprocess.CompletedProcess(command, 0, stdout="main\n", stderr="")
    if command == ["git", "ls-tree", "-r", "--name-only", "HEAD"]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="app/main.py\ndocker-compose.yml\ndeploy/first-deploy.sh\n",
            stderr="",
        )
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _dirty_git_runner(args, *, timeout_seconds=30):
    command = list(args)
    if command == ["git", "status", "--short", "--branch"]:
        return subprocess.CompletedProcess(command, 0, stdout="## main...origin/main\n M app/main.py\n", stderr="")
    return _clean_git_runner(args, timeout_seconds=timeout_seconds)


def test_release_artifact_dry_run_does_not_write_files(tmp_path):
    report = artifact.build_release_artifact_report(
        execute=False,
        output_dir=tmp_path,
        command_runner=_clean_git_runner,
        boundary_builder=lambda: _boundary("passed"),
    )

    assert report["status"] == "ready_to_build"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["writes_files_by_default"] is False
    assert report["artifact"]["archive_written"] is False
    assert report["artifact"]["manifest_written"] is False
    assert list(tmp_path.iterdir()) == []


def test_release_artifact_blocks_dirty_worktree(tmp_path):
    report = artifact.build_release_artifact_report(
        execute=True,
        output_dir=tmp_path,
        command_runner=_dirty_git_runner,
        boundary_builder=lambda: _boundary("passed"),
    )

    assert report["status"] == "blocked"
    assert report["section_statuses"]["git_worktree"] == "blocked"
    assert report["section_statuses"]["artifact_write"] == "blocked"
    assert report["artifact"]["archive_written"] is False
    assert list(tmp_path.iterdir()) == []


def test_release_artifact_execute_writes_archive_and_manifest(tmp_path):
    def runner(args, *, timeout_seconds=30):
        command = list(args)
        if command[:4] == ["git", "archive", "--format=tar", "-o"]:
            archive_path = command[4]
            with open(archive_path, "wb") as handle:
                handle.write(b"fake-tar-content")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return _clean_git_runner(command, timeout_seconds=timeout_seconds)

    report = artifact.build_release_artifact_report(
        execute=True,
        output_dir=tmp_path,
        release_id="m1_test_release",
        command_runner=runner,
        boundary_builder=lambda: _boundary("passed"),
    )

    archive_path = tmp_path / "m1_test_release.tar"
    manifest_path = tmp_path / "m1_test_release.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert report["status"] == "passed"
    assert archive_path.exists()
    assert manifest_path.exists()
    assert report["artifact"]["archive_sha256"]
    assert report["artifact"]["archive_size_bytes"] == len(b"fake-tar-content")
    assert manifest["artifact"]["manifest_written"] is True
    assert manifest["artifact"]["archive_path_echoed"] is False
    assert manifest["sections"]["git_identity"]["tracked_file_count"] == 3


def test_release_artifact_markdown_contains_boundaries():
    report = artifact.build_release_artifact_report(
        execute=False,
        command_runner=_clean_git_runner,
        boundary_builder=lambda: _boundary("passed"),
    )

    markdown = artifact.build_release_artifact_markdown(report)

    assert "Release Artifact Manifest" in markdown
    assert "ready_to_build" in markdown
    assert "SSH authentication works" in markdown
    assert "--archive-sha256" in markdown
    assert "--execute --start-services" in markdown
