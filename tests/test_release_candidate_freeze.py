import subprocess

from scripts import check_release_candidate_freeze as freeze


def _runner_with_status(output: str, returncode: int = 0):
    def runner(args, *, timeout_seconds=30):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=output if returncode == 0 else "",
            stderr="" if returncode == 0 else output,
        )

    return runner


def test_release_candidate_freeze_passes_clean_worktree():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("## main...origin/main\n")
    )

    assert report["status"] == "passed"
    assert report["freeze_state"] == "frozen"
    assert report["dirty_count"] == 0
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["reads_file_contents"] is False
    assert report["policy"]["starts_services"] is False


def test_release_candidate_freeze_groups_dirty_paths_by_workstream():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status(
            "\n".join(
                [
                    "## main...origin/main",
                    " M deploy/first-deploy.sh",
                    " M app/rag/retriever.py",
                    " M app/main.py",
                    " M frontend/report-renderer.js",
                    "?? docs/项目总览/agent-ai-app-improvement-roadmap.md",
                    "?? scratch/local-note.md",
                ]
            )
            + "\n"
        )
    )

    counts = {
        item["key"]: item["changed_count"]
        for item in report["workstreams"]
    }

    assert report["status"] == "blocked"
    assert report["freeze_state"] == "not_frozen"
    assert report["dirty_count"] == 6
    assert counts["deployment_runtime"] == 1
    assert counts["rag_evaluation"] == 1
    assert counts["business_api_runtime"] == 1
    assert counts["report_frontend"] == 1
    assert counts["project_docs"] == 1
    assert report["unknown_paths"] == ["scratch/local-note.md"]
    assert any(item["key"] == "unknown_path_review" for item in report["blocked_reasons"])


def test_release_candidate_freeze_flags_forbidden_paths_without_reading_content():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("## main\n?? .env\n?? .runtime/state.json\n")
    )

    assert report["status"] == "blocked"
    assert report["forbidden_paths"] == [".env", ".runtime/state.json"]
    assert any(item["key"] == "forbidden_release_path" for item in report["blocked_reasons"])


def test_release_candidate_freeze_allows_env_example():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("## main\n M .env.example\n")
    )

    assert report["status"] == "blocked"
    assert report["forbidden_paths"] == []
    assert not any(item["key"] == "forbidden_release_path" for item in report["blocked_reasons"])


def test_release_candidate_freeze_can_include_public_closure_check():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("## main...origin/main\n"),
        check_public_closure=True,
        public_closure_builder=lambda: {
            "version": "m1_public_release_closure.v1",
            "status": "passed",
            "section_statuses": {"public_coordinate_scan": "passed"},
        },
    )

    assert report["status"] == "passed"
    assert report["public_release_closure"]["status"] == "passed"
    assert report["policy"]["reads_file_contents"] is True
    assert report["policy"]["uses_git_status_only"] is False
    assert report["policy"]["checks_public_release_closure"] is True


def test_release_candidate_freeze_blocks_failed_public_closure_check():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("## main...origin/main\n"),
        check_public_closure=True,
        public_closure_builder=lambda: {
            "version": "m1_public_release_closure.v1",
            "status": "blocked",
            "section_statuses": {"public_coordinate_scan": "blocked"},
        },
    )

    assert report["status"] == "blocked"
    assert report["freeze_state"] == "not_frozen"
    assert any(item["key"] == "public_release_closure" for item in report["blocked_reasons"])


def test_release_candidate_freeze_blocks_git_status_failure():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("fatal: not a git repository", returncode=128)
    )

    assert report["status"] == "blocked"
    assert report["freeze_state"] == "unknown"
    assert report["dirty_count"] is None
    assert report["blocked_reasons"][0]["key"] == "git_status"


def test_release_candidate_freeze_markdown_includes_blockers_and_commands():
    report = freeze.build_release_candidate_freeze_report(
        command_runner=_runner_with_status("## main\n M app/rag/retriever.py\n")
    )

    markdown = freeze.build_release_candidate_freeze_markdown(report)

    assert "Release Candidate Freeze" in markdown
    assert "release_candidate_not_frozen" in markdown
    assert "check_release_candidate_freeze.py --check-public-closure --json" in markdown
    assert "build_release_artifact.py --json" in markdown
