import json
import re
from datetime import UTC, datetime
from pathlib import Path

from scripts import prepare_m1_private_execution_workspace as prep


def test_private_execution_workspace_plan_does_not_write(tmp_path: Path):
    private_dir = tmp_path / "m1-private"

    report = prep.build_m1_private_execution_workspace_report(
        private_workdir=private_dir,
        execute=False,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "ready_to_prepare"
    assert report["policy"]["writes_files"] is False
    assert private_dir.exists() is False
    assert report["target"]["private_workdir"] == "<private-workdir>"
    assert str(private_dir) not in payload
    assert {item["action"] for item in report["files"]} >= {"would_write", "would_create_dir"}


def test_private_execution_workspace_execute_writes_templates(tmp_path: Path):
    private_dir = tmp_path / "m1-private"

    report = prep.build_m1_private_execution_workspace_report(
        private_workdir=private_dir,
        execute=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "workspace_prepared"
    assert report["policy"]["writes_files"] is True
    assert report["post_prepare_gap_status"] == "blocked_missing_private_input"
    assert (private_dir / "m1-launch-inputs.local.json").exists()
    assert (private_dir / "external-dependency-resilience-record.local.json").exists()
    assert (private_dir / "m1-rollout-execution-record.local.json").exists()
    assert (private_dir / "m1-operations-review-record.local.json").exists()
    assert (private_dir / "m1-live-evidence-workflow").is_dir()
    assert (private_dir / "m1-private-inputs.todo.md").exists()
    assert (private_dir / "m1-live-inputs.local.ps1").exists()
    assert (private_dir / "README.md").read_text(encoding="utf-8").startswith("# M1 Private Execution Workspace")
    assert (private_dir / ".gitignore").read_text(encoding="utf-8").startswith("# Private M1 execution evidence")
    live_inputs = (private_dir / "m1-live-inputs.local.ps1").read_text(encoding="utf-8")
    assert "# $env:ZHIXING_BACKUP_DIR" in live_inputs
    assert "# $env:ZHIXING_PROBE_ACCESS_TOKEN" in live_inputs
    assert re.search(r"(?m)^\s*\$env:ZHIXING_BACKUP_DIR\s*=", live_inputs) is None
    assert str(private_dir) not in payload


def test_private_execution_workspace_does_not_overwrite_existing_by_default(tmp_path: Path):
    private_dir = tmp_path / "m1-private"
    private_dir.mkdir()
    launch_path = private_dir / "m1-launch-inputs.local.json"
    launch_path.write_text("keep-me\n", encoding="utf-8")

    report = prep.build_m1_private_execution_workspace_report(
        private_workdir=private_dir,
        execute=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    assert report["status"] == "workspace_prepared"
    assert launch_path.read_text(encoding="utf-8") == "keep-me\n"
    launch_item = next(item for item in report["files"] if item["filename"] == "m1-launch-inputs.local.json")
    assert launch_item["action"] == "skipped_existing"
    assert (private_dir / "m1-private-inputs.todo.md").exists()
    assert (private_dir / "m1-live-inputs.local.ps1").exists()


def test_private_execution_workspace_overwrite_when_requested(tmp_path: Path):
    private_dir = tmp_path / "m1-private"
    private_dir.mkdir()
    launch_path = private_dir / "m1-launch-inputs.local.json"
    launch_path.write_text("replace-me\n", encoding="utf-8")

    report = prep.build_m1_private_execution_workspace_report(
        private_workdir=private_dir,
        execute=True,
        overwrite=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.loads(launch_path.read_text(encoding="utf-8"))

    assert report["status"] == "workspace_prepared"
    assert payload["version"] == "m1_launch_inputs_template.v1"
    launch_item = next(item for item in report["files"] if item["filename"] == "m1-launch-inputs.local.json")
    assert launch_item["action"] == "overwritten"


def test_private_execution_workspace_blocks_project_workdir():
    project_dir = prep.PROJECT_ROOT / "m1-private"

    report = prep.build_m1_private_execution_workspace_report(
        private_workdir=project_dir,
        execute=True,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    assert report["status"] == "blocked_sensitive_boundary"
    assert report["policy"]["writes_files"] is True
    assert report["workdir_check"]["inside_project"] is True
    assert project_dir.exists() is False


def test_private_execution_workspace_cli_execute_markdown_does_not_echo_path(
    tmp_path: Path,
    capsys,
):
    private_dir = tmp_path / "m1-private"

    code = prep.main(["--private-workdir", str(private_dir), "--execute", "--markdown"])
    output = capsys.readouterr().out

    assert code == 0
    assert "workspace_prepared" in output
    assert str(private_dir) not in output
    assert (private_dir / "m1-launch-inputs.local.json").exists()
