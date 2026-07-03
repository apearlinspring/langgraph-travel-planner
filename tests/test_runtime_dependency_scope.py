import json
from pathlib import Path

from scripts import check_runtime_dependency_scope as scope


def _write(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def test_runtime_dependency_scope_passes_clean_runtime_inputs(tmp_path: Path):
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "example"
        dependencies = [
          "fastapi==0.124.4",
          "redis==5.0.0",
          "dashscope==1.25.4",
          "langchain-chroma>=0.1.4",
        ]
        """,
    )
    requirements = _write(
        tmp_path / "requirements.runtime.txt",
        """
        fastapi==0.124.4
        redis==5.0.0
        dashscope==1.25.4
        langchain-chroma==1.0.0
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

    report = scope.build_runtime_dependency_scope_report(
        pyproject_path=pyproject,
        requirements_path=requirements,
        dockerfile_path=dockerfile,
    )

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    assert report["sections"]["dockerfile"]["installed_requirement_inputs"] == [
        "/tmp/requirements.runtime.txt"
    ]


def test_runtime_dependency_scope_blocks_test_and_heavy_runtime_inputs(tmp_path: Path):
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "example"
        dependencies = [
          "fastapi==0.124.4",
          "pytest~=9.0.2",
          "pytest-asyncio~=1.3.0",
          "sentence-transformers==3.3.0",
          "faster-whisper>=1.2.1",
          "imageio-ffmpeg>=0.6.0",
        ]
        """,
    )
    requirements = _write(
        tmp_path / "requirements.txt",
        """
        av==17.1.0 \\
            --hash=sha256:example
        faster-whisper==1.2.1
        nvidia-cublas==13.1.0.3 ; sys_platform == 'linux'
        pytest==9.0.3
        pytest-asyncio==1.3.0
        sentence-transformers==3.3.0
        torch==2.11.0
        triton==3.6.0 ; sys_platform == 'linux'
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

    report = scope.build_runtime_dependency_scope_report(
        pyproject_path=pyproject,
        requirements_path=requirements,
        dockerfile_path=dockerfile,
    )

    blocked_packages = {
        item["package"]
        for item in report["blocked_reasons"]
        if item.get("package")
    }
    assert report["status"] == "blocked"
    assert {
        "pytest",
        "pytest-asyncio",
        "sentence-transformers",
        "faster-whisper",
        "imageio-ffmpeg",
        "av",
        "nvidia-cublas",
        "torch",
        "triton",
    }.issubset(blocked_packages)
    assert report["sections"]["dockerfile"]["installs_default_requirements_txt"] is True
    assert any(item.get("section") == "production_image_input" for item in report["blocked_reasons"])


def test_runtime_dependency_scope_cli_json_passes_current_repo(capsys):
    exit_code = scope.main(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["version"] == scope.RUNTIME_DEPENDENCY_SCOPE_VERSION
    assert payload["status"] == "passed"
    assert payload["policy"]["reads_dotenv"] is False
    assert payload["sections"]["dockerfile"]["installed_requirement_inputs"] == [
        "/tmp/requirements.runtime.txt"
    ]
