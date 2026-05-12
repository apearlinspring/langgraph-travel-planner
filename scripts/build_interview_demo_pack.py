"""Build a sanitized interview demo pack for the ZhiXing project."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


PACK_VERSION = "interview_demo_pack.v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".runtime" / "interview-demo-pack"

SOURCE_DOCUMENTS = (
    Path("docs/interview-demo-pack.md"),
    Path("docs/interview-answer-map.md"),
    Path("docs/demo-script.md"),
)

GENERATED_FILENAMES = (
    "README.md",
    "commands.ps1",
    "manifest.json",
    "redaction-check.txt",
    *(path.name for path in SOURCE_DOCUMENTS),
)

DEMO_PATHS = (
    {
        "id": "local-briefing",
        "name": "本地纯讲解路径",
        "requires_real_secrets": False,
        "entry": "docs/interview-demo-pack.md#本地纯讲解路径",
        "commands": [
            r".\.venv\Scripts\python scripts\build_interview_demo_pack.py",
            r".\.venv\Scripts\python -m pytest tests\test_interview_demo_pack.py -q",
        ],
    },
    {
        "id": "acceptance-smoke",
        "name": "acceptance-smoke 验收烟测路径",
        "requires_real_secrets": True,
        "entry": "docs/demo-script.md#路径二acceptance-smoke-真实链路",
        "commands": [
            r".\.venv\Scripts\python main.py",
            (
                r".\.venv\Scripts\python scripts\run_evaluation_scenarios.py "
                r"--acceptance-smoke --base-url http://127.0.0.1:8000 "
                r"--json --summary-dir .runtime\acceptance-smoke"
            ),
        ],
    },
    {
        "id": "frontend-report",
        "name": "前端报告路径",
        "requires_real_secrets": "backend_report_data",
        "entry": "docs/demo-script.md#路径三前端报告可视化",
        "commands": [
            r".\.venv\Scripts\python main.py",
            "打开 frontend\\zhixing.html，使用同一会话查看 report_data 报告卡片和导出结果。",
        ],
    },
)


@dataclass(frozen=True)
class SensitivePattern:
    name: str
    pattern: re.Pattern[str]


SENSITIVE_PATTERNS = (
    SensitivePattern(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    SensitivePattern(
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}\b"),
    ),
    SensitivePattern(
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password|authorization)\b"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{16,}"
        ),
    ),
    SensitivePattern(
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    SensitivePattern(
        "mainland_china_phone",
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ),
)


def scan_sensitive_text(text: str) -> list[str]:
    """Return sensitive pattern names found in text."""

    return [item.name for item in SENSITIVE_PATTERNS if item.pattern.search(text)]


def repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _run_git_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _require_source_documents(repo_root: Path) -> list[Path]:
    paths = [repo_root / path for path in SOURCE_DOCUMENTS]
    missing = [repo_relative(path, repo_root) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing interview demo source documents: " + ", ".join(missing)
        )
    return paths


def _assert_safe_source_path(path: Path, repo_root: Path) -> None:
    relative = Path(repo_relative(path, repo_root))
    parts = set(relative.parts)
    if ".runtime" in parts or any(part.startswith(".env") for part in relative.parts):
        raise ValueError(f"Refusing to copy runtime or environment file: {relative}")


def _read_safe_text(path: Path, repo_root: Path) -> str:
    _assert_safe_source_path(path, repo_root)
    text = path.read_text(encoding="utf-8")
    findings = scan_sensitive_text(text)
    if findings:
        raise ValueError(
            f"Sensitive content detected in {repo_relative(path, repo_root)}: "
            + ", ".join(sorted(findings))
        )
    return text


def _prepare_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in GENERATED_FILENAMES:
        target = output_dir / filename
        if target.exists():
            target.unlink()


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _render_index(manifest: dict[str, object]) -> str:
    demo_lines = []
    for item in DEMO_PATHS:
        requires = "需要真实环境" if item["requires_real_secrets"] else "不需要真实密钥"
        demo_lines.append(f"- `{item['id']}`：{item['name']}，{requires}。")

    sources = "\n".join(
        f"- `{item['path']}`：{item['purpose']}"
        for item in manifest["source_documents"]  # type: ignore[index]
    )
    demos = "\n".join(demo_lines)

    return fr"""# Interview Demo Pack（面试演示包）

本目录由 `scripts/build_interview_demo_pack.py` 生成，用于把知行项目整理成可讲述、可复跑、可审计的 AI-Agent（人工智能智能体）面试材料。

## 使用方式

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null
.\.venv\Scripts\python scripts\build_interview_demo_pack.py
```

## 三条演示路径

{demos}

## 文件说明

- `interview-demo-pack.md`：能力总览、演示路径和安全边界。
- `interview-answer-map.md`：面试问题、架构回答、代码定位和可运行命令。
- `demo-script.md`：按时间顺序讲解的演示脚本。
- `commands.ps1`：复跑演示包、专项测试和验收入口的命令清单。
- `manifest.json`：机器可读清单，记录来源、生成文件和安全策略。
- `redaction-check.txt`：本次生成的脱敏扫描结果。

## 来源文档

{sources}

## 安全边界

生成器只复制上述三份已脱敏文档，并生成命令与清单；它不读取 `.env`，不复制 `.runtime` 原始快照，不保存手机号、邮箱、JWT（JSON Web Token，令牌认证）或真实 API（应用程序接口）密钥。
"""


def _render_commands() -> str:
    return r"""# Interview Demo Pack commands
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null

# 1. Rebuild the sanitized demo pack.
.\.venv\Scripts\python scripts\build_interview_demo_pack.py --output .runtime\interview-demo-pack

# 2. Validate this module locally.
.\.venv\Scripts\python -m compileall app tests scripts
.\.venv\Scripts\python -m pytest tests\test_interview_demo_pack.py -q

# 3. Optional full default regression.
.\.venv\Scripts\python -m pytest -q

# 4. Real acceptance smoke path, only after the backend and real environment are ready.
.\.venv\Scripts\python main.py
.\.venv\Scripts\python scripts\run_evaluation_scenarios.py --acceptance-smoke --base-url http://127.0.0.1:8000 --json --summary-dir .runtime\acceptance-smoke
"""


def _source_document_metadata(paths: Iterable[Path], repo_root: Path) -> list[dict[str, str]]:
    purposes = {
        "interview-demo-pack.md": "面试演示包主入口",
        "interview-answer-map.md": "AI-Agent 能力面试答题地图",
        "demo-script.md": "三条演示路径的讲述脚本",
    }
    return [
        {
            "path": repo_relative(path, repo_root),
            "purpose": purposes.get(path.name, "interview demo source"),
        }
        for path in paths
    ]


def _scan_generated_files(output_dir: Path) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".env"):
            findings[str(path)] = ["env_file"]
            continue
        text = path.read_text(encoding="utf-8")
        sensitive = scan_sensitive_text(text)
        if sensitive:
            findings[str(path)] = sorted(sensitive)
    return findings


def build_demo_pack(
    output_dir: str | Path | None = None,
    *,
    repo_root: str | Path = PROJECT_ROOT,
) -> dict[str, object]:
    """Build the interview demo pack and return its manifest."""

    root = Path(repo_root).resolve()
    out = Path(output_dir or root / ".runtime" / "interview-demo-pack").resolve()
    source_paths = _require_source_documents(root)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    _prepare_output_dir(out)

    copied_files: list[str] = []
    for source_path in source_paths:
        text = _read_safe_text(source_path, root)
        target = out / source_path.name
        _write_text(target, text)
        copied_files.append(repo_relative(target, root))

    manifest: dict[str, object] = {
        "version": PACK_VERSION,
        "generated_at": now,
        "source_commit": _run_git_commit(root),
        "output_dir": repo_relative(out, root),
        "output_policy": {
            "reads_env_files": False,
            "copies_runtime_snapshots": False,
            "stores_real_secrets_or_pii": False,
            "source_files_are_allowlisted": True,
        },
        "demo_paths": list(DEMO_PATHS),
        "source_documents": _source_document_metadata(source_paths, root),
        "generated_files": [],
    }

    generated_index = _render_index(manifest)
    generated_commands = _render_commands()
    for filename, text in {
        "README.md": generated_index,
        "commands.ps1": generated_commands,
    }.items():
        target = out / filename
        findings = scan_sensitive_text(text)
        if findings:
            raise ValueError(f"Sensitive content detected in generated {filename}: {findings}")
        _write_text(target, text)

    redaction_findings = _scan_generated_files(out)
    if redaction_findings:
        raise ValueError("Sensitive content detected in generated pack: " + json.dumps(redaction_findings))

    generated_files = sorted(repo_relative(path, root) for path in out.iterdir() if path.is_file())
    manifest["generated_files"] = generated_files

    manifest_path = out / "manifest.json"
    _write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    final_findings = _scan_generated_files(out)
    if final_findings:
        raise ValueError("Sensitive content detected after manifest write: " + json.dumps(final_findings))

    _write_text(
        out / "redaction-check.txt",
        "NO_SENSITIVE_FINDINGS\n"
        "Checked generated Markdown, PowerShell and JSON files for common email, phone, JWT, "
        "bearer token and assigned secret patterns.\n",
    )

    manifest["generated_files"] = sorted(
        repo_relative(path, root) for path in out.iterdir() if path.is_file()
    )
    _write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a sanitized interview demo pack without copying secrets or runtime snapshots."
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory. Defaults to .runtime/interview-demo-pack.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = build_demo_pack(args.output)
    print(
        json.dumps(
            {
                "status": "built",
                "version": manifest["version"],
                "output_dir": manifest["output_dir"],
                "generated_files": manifest["generated_files"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
