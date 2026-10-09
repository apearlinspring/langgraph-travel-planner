from pathlib import Path

from scripts import check_production_image_build_policy as policy


def _write(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def test_production_image_build_policy_passes_default_repo_contract():
    report = policy.build_production_image_build_policy_report()

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["runs_docker"] is False
    assert report["summary"]["uses_remote_background_build"] is True


def test_production_image_build_policy_blocks_secret_like_mirror_policy():
    record = policy.build_policy_template()
    record["package_mirror"][
        "pip_index_url_source"
    ] = "https://user:secret@example.invalid/simple"

    report = policy.build_production_image_build_policy_report(policy_record=record)

    assert report["status"] == "blocked"
    assert any(
        item["section"] == "package_mirror"
        and item["key"] == "pip_index_url_source"
        for item in report["blocked_reasons"]
    )


def test_production_image_build_policy_requires_remote_background_mode():
    record = policy.build_policy_template()
    record["remote_build"]["mode"] = "foreground"

    report = policy.build_production_image_build_policy_report(policy_record=record)

    assert report["status"] == "blocked"
    assert any(
        item["section"] == "remote_build" and item["key"] == "mode"
        for item in report["blocked_reasons"]
    )


def test_production_image_build_policy_blocks_full_requirements_dockerfile(tmp_path: Path):
    update_script = _write(
        tmp_path / "update-runtime-image.sh",
        """
        PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
        PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.org}"
        ZHIXING_MIN_FREE_DISK_MB="${ZHIXING_MIN_FREE_DISK_MB:-2048}"
        COMPOSE_PROJECT_NAME="${ZHIXING_COMPOSE_PROJECT_NAME:-langgraph-travel-planner}"
        docker build .
        docker compose up -d --no-build backend caddy
        """,
    )
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM python:3.12-slim
        COPY requirements.txt /tmp/requirements.txt
        RUN pip install -r /tmp/requirements.txt
        """,
    )
    requirements = _write(tmp_path / "requirements.runtime.txt", "fastapi==0.124.4")

    report = policy.build_production_image_build_policy_report(
        update_script_path=update_script,
        dockerfile_path=dockerfile,
        runtime_requirements_path=requirements,
    )

    assert report["status"] == "blocked"
    assert any(
        item["section"] == "repo_dockerfile"
        and item["key"] == "runtime_requirements_input"
        for item in report["blocked_reasons"]
    )


def test_production_image_build_policy_requires_compose_project_pin(tmp_path: Path):
    update_script = _write(
        tmp_path / "update-runtime-image.sh",
        """
        PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
        PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.org}"
        ZHIXING_MIN_FREE_DISK_MB="${ZHIXING_MIN_FREE_DISK_MB:-2048}"
        docker build .
        docker compose up -d --no-build backend caddy
        """,
    )
    dockerfile = _write(
        tmp_path / "Dockerfile",
        """
        FROM python:3.12-slim
        COPY requirements.runtime.txt /tmp/requirements.runtime.txt
        RUN pip install -r /tmp/requirements.runtime.txt
        """,
    )
    requirements = _write(tmp_path / "requirements.runtime.txt", "fastapi==0.124.4")

    report = policy.build_production_image_build_policy_report(
        update_script_path=update_script,
        dockerfile_path=dockerfile,
        runtime_requirements_path=requirements,
    )

    assert report["status"] == "blocked"
    assert any(
        item["section"] == "repo_update_script"
        and item["key"] == "compose_project_pin"
        for item in report["blocked_reasons"]
    )
