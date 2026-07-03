import subprocess

from scripts import check_rate_limit_release_scope as scope


def _runner(*, status_output: str = "## main\n", head_paths=None, returncode: int = 0):
    head_text = "\n".join(head_paths or []) + ("\n" if head_paths else "")

    def run(args, *, repo_root, timeout_seconds=30):
        command = " ".join(args)
        if returncode != 0:
            return subprocess.CompletedProcess(list(args), returncode, stdout="", stderr="fatal: git failed")
        if " status " in f" {command} ":
            return subprocess.CompletedProcess(list(args), 0, stdout=status_output, stderr="")
        if " ls-tree " in f" {command} ":
            return subprocess.CompletedProcess(list(args), 0, stdout=head_text, stderr="")
        return subprocess.CompletedProcess(list(args), 0, stdout="", stderr="")

    return run


def _write_required_files(root, *, omit_marker=False):
    marker_text = {
        ".env.example": "API_RATE_LIMIT_ENABLED=false\nAPI_RATE_LIMIT_BACKEND=redis\n",
        "app/api/v1/mock_checkout.py": "mock_checkout\n",
        "app/config.py": (
            "API_RATE_LIMIT_ENABLED\nAPI_RATE_LIMIT_BACKEND\nAPI_RATE_LIMIT_LOCAL_FALLBACK\n"
            "api_rate_limit_protected_prefixes\n"
        ),
        "app/core/rate_limit.py": (
            "ApiRateLimitMiddleware\nRedisFixedWindowRateLimitStore\nredis_unavailable\n"
            "Retry-After\nX-RateLimit-Limit\n"
        ),
        "app/main.py": (
            "ApiRateLimitMiddleware\nsettings.api_rate_limit_enabled\n"
            "settings.api_rate_limit_local_fallback\n"
        ),
        "docker-compose.yml": (
            "API_RATE_LIMIT_ENABLED: ${API_RATE_LIMIT_ENABLED:-true}\n"
            "API_RATE_LIMIT_BACKEND: ${API_RATE_LIMIT_BACKEND:-redis}\n"
            "API_RATE_LIMIT_LOCAL_FALLBACK: ${API_RATE_LIMIT_LOCAL_FALLBACK:-false}\n"
        ),
        "docs/部署与运行/deployment-readiness.md": "collect_rate_limit_live_probe.py\nRetry-After\n",
        "docs/部署与运行/postgres-redis-ops-runbook.md": (
            "API_RATE_LIMIT_BACKEND=redis\nAPI_RATE_LIMIT_LOCAL_FALLBACK=false\n"
        ),
        "scripts/check_rate_limit_release_scope.py": "RATE_LIMIT_RELEASE_SCOPE_VERSION\n",
        "scripts/collect_m1_go_no_go_evidence.py": (
            "include_rate_limit_live_probe\nbuild_rate_limit_live_probe_report\n"
            "runs_rate_limit_live_probe\n"
        ),
        "scripts/collect_rate_limit_live_probe.py": (
            "RATE_LIMIT_LIVE_PROBE_VERSION\nreads_response_body\nmissing_429\n"
            "missing_limit_header\n"
        ),
        "tests/test_api_rate_limit_middleware.py": "test\n",
        "tests/test_m1_go_no_go_evidence.py": "test\n",
        "tests/test_mock_checkout.py": "test\n",
        "tests/test_rate_limit_live_probe.py": "test\n",
        "tests/test_rate_limit_release_scope.py": "test\n",
        "tests/test_script_entrypoints.py": "test\n",
    }
    if omit_marker:
        marker_text["app/core/rate_limit.py"] = "ApiRateLimitMiddleware\n"
    for path, text in marker_text.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_rate_limit_release_scope_passes_when_clean_head_contains_contract(tmp_path):
    _write_required_files(tmp_path)

    report = scope.build_rate_limit_release_scope_report(
        repo_root=tmp_path,
        command_runner=_runner(head_paths=scope.REQUIRED_RELEASE_FILES),
    )

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["uses_git_head_as_release_source"] is True


def test_rate_limit_release_scope_blocks_untracked_and_dirty_required_files(tmp_path):
    _write_required_files(tmp_path)
    head_paths = [path for path in scope.REQUIRED_RELEASE_FILES if path != "app/core/rate_limit.py"]

    report = scope.build_rate_limit_release_scope_report(
        repo_root=tmp_path,
        command_runner=_runner(
            status_output="## main\n?? app/core/rate_limit.py\n M app/main.py\n",
            head_paths=head_paths,
        ),
    )

    assert report["status"] == "blocked"
    assert any(item.get("key") == "not_in_git_head" for item in report["blocked_reasons"])
    assert any(item.get("key") == "dirty_required_file" for item in report["blocked_reasons"])
    rate_file = next(item for item in report["required_files"] if item["path"] == "app/core/rate_limit.py")
    main_file = next(item for item in report["required_files"] if item["path"] == "app/main.py")
    assert rate_file["in_git_head"] is False
    assert rate_file["worktree_status"] == "??"
    assert main_file["worktree_status"] == "M"


def test_rate_limit_release_scope_blocks_missing_contract_marker(tmp_path):
    _write_required_files(tmp_path, omit_marker=True)

    report = scope.build_rate_limit_release_scope_report(
        repo_root=tmp_path,
        command_runner=_runner(head_paths=scope.REQUIRED_RELEASE_FILES),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "missing_contract_marker" for item in report["contract_marker_findings"])


def test_rate_limit_release_scope_blocks_git_failure(tmp_path):
    _write_required_files(tmp_path)

    report = scope.build_rate_limit_release_scope_report(
        repo_root=tmp_path,
        command_runner=_runner(returncode=128),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "git_status" for item in report["blocked_reasons"])
    assert any(item["key"] == "git_head" for item in report["blocked_reasons"])


def test_rate_limit_release_scope_markdown_includes_required_actions(tmp_path):
    _write_required_files(tmp_path)
    report = scope.build_rate_limit_release_scope_report(
        repo_root=tmp_path,
        command_runner=_runner(
            status_output="## main\n?? app/core/rate_limit.py\n",
            head_paths=[path for path in scope.REQUIRED_RELEASE_FILES if path != "app/core/rate_limit.py"],
        ),
    )

    markdown = scope.build_rate_limit_release_scope_markdown(report)

    assert "API Rate Limit Release Scope" in markdown
    assert "not_in_git_head" in markdown
    assert "Stage and commit" in markdown
