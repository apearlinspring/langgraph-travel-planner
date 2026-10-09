"""Check production runtime dependency scope.

This check is intentionally static. It reads only dependency declaration files,
the runtime-only requirements input, and Dockerfile text, never `.env`, runtime
directories, logs, vector stores, or installed package metadata. Its purpose is
to stop a production image from silently installing test frameworks, multimodal
deep-gate tooling, or large GPU/training dependency stacks.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_REQUIREMENTS = PROJECT_ROOT / "requirements.runtime.txt"
RUNTIME_DEPENDENCY_SCOPE_VERSION = "runtime_dependency_scope.v1"

PACKAGE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:\[.*?\])?\s*(?:[<>=!~]=?|;|\\|$)")
REQUIREMENTS_FILE_PATTERN = re.compile(r"(?:COPY|ADD)\s+(\S*requirements\S*)\s+", re.IGNORECASE)
REQUIREMENTS_INSTALL_PATTERN = re.compile(r"(?:^|\s)-r\s+([^\s;&]+requirements[^\s;&]+)", re.IGNORECASE)


@dataclass(frozen=True)
class DependencyRule:
    package: str
    severity: str
    category: str
    reason: str
    expected_scope: str


DIRECT_DEPENDENCY_RULES: tuple[DependencyRule, ...] = (
    DependencyRule(
        "pytest",
        "blocked",
        "dev_test",
        "pytest is a test framework and should not be installed by the production image.",
        "dev/test dependency group",
    ),
    DependencyRule(
        "pytest-asyncio",
        "blocked",
        "dev_test",
        "pytest-asyncio is a test framework plugin and should not be installed by the production image.",
        "dev/test dependency group",
    ),
    DependencyRule(
        "faster-whisper",
        "blocked",
        "multimodal_deep_gate",
        "faster-whisper is an ASR deep-gate dependency; keep it in an optional profile or worker image.",
        "optional multimodal or offline worker profile",
    ),
    DependencyRule(
        "imageio-ffmpeg",
        "blocked",
        "multimodal_deep_gate",
        "imageio-ffmpeg is only needed for multimedia extraction fallback, not the default API runtime.",
        "optional multimodal or offline worker profile",
    ),
    DependencyRule(
        "sentence-transformers",
        "blocked",
        "local_embedding_stack",
        "The deployed RAG path uses DashScope embeddings; local embedding models should not be in the default API image.",
        "optional local-embedding build profile",
    ),
)

LOCKED_REQUIREMENTS_RULES: tuple[DependencyRule, ...] = (
    *DIRECT_DEPENDENCY_RULES,
    DependencyRule(
        "torch",
        "blocked",
        "gpu_training_stack",
        "torch pulls large CPU/GPU wheels and is not required by the default API runtime.",
        "optional model, ASR, or local-embedding profile",
    ),
    DependencyRule(
        "triton",
        "blocked",
        "gpu_training_stack",
        "triton is pulled by GPU/model stacks and should not enter the default production image.",
        "optional model, ASR, or local-embedding profile",
    ),
    DependencyRule(
        "av",
        "blocked",
        "multimodal_deep_gate",
        "av is pulled by media/ASR tooling and should not enter the default API runtime.",
        "optional multimodal or offline worker profile",
    ),
)

NVIDIA_RULE = DependencyRule(
    "nvidia-*",
    "blocked",
    "gpu_training_stack",
    "nvidia-* CUDA wheels are GPU runtime dependencies and make the API image heavy and slow to build.",
    "optional GPU/model profile",
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _normalize_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value or "").strip().lower())


def _rule_map(rules: Sequence[DependencyRule]) -> dict[str, DependencyRule]:
    return {_normalize_package_name(rule.package): rule for rule in rules}


def _status_from_findings(findings: Sequence[Mapping[str, Any]]) -> str:
    if any(item.get("severity") == "blocked" for item in findings):
        return "blocked"
    if findings:
        return "degraded"
    return "passed"


def _read_text(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        return path.read_text(encoding="utf-8-sig"), {"status": "passed", "path_echoed": False}
    except OSError as exc:
        return "", {
            "status": "blocked",
            "path_echoed": False,
            "finding": f"Cannot read file: {exc.__class__.__name__}",
        }


def _dependency_name_from_pep508(value: str) -> str:
    match = PACKAGE_PATTERN.match(value)
    return _normalize_package_name(match.group(1)) if match else ""


def _parse_pyproject_dependencies(pyproject_path: Path) -> dict[str, Any]:
    text, read_status = _read_text(pyproject_path)
    if read_status.get("status") != "passed":
        return {
            "status": "blocked",
            "path_echoed": False,
            "dependencies": [],
            "blocked_reasons": [read_status],
        }
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return {
            "status": "blocked",
            "path_echoed": False,
            "dependencies": [],
            "blocked_reasons": [{"finding": f"pyproject.toml is not valid TOML: {exc}"}],
        }
    dependencies = payload.get("project", {}).get("dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []
    package_names = sorted(
        {name for name in (_dependency_name_from_pep508(str(item)) for item in dependencies) if name}
    )
    findings = _find_rule_violations(package_names, DIRECT_DEPENDENCY_RULES, source="pyproject.project.dependencies")
    return {
        "status": _status_from_findings(findings),
        "path_echoed": False,
        "dependency_count": len(package_names),
        "dependencies": package_names,
        "findings": findings,
        "blocked_reasons": [item for item in findings if item.get("severity") == "blocked"],
    }


def _parse_requirements_packages(requirements_path: Path) -> dict[str, Any]:
    text, read_status = _read_text(requirements_path)
    if read_status.get("status") != "passed":
        return {
            "status": "blocked",
            "path_echoed": False,
            "packages": [],
            "blocked_reasons": [read_status],
        }
    package_names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("--hash="):
            continue
        if stripped.startswith(("-r", "--requirement", "--index-url", "--extra-index-url", "--trusted-host")):
            continue
        name = _dependency_name_from_pep508(stripped)
        if name:
            package_names.add(name)
    packages = sorted(package_names)
    findings = _find_rule_violations(packages, LOCKED_REQUIREMENTS_RULES, source="requirements.lock")
    for package in packages:
        if package.startswith("nvidia-"):
            findings.append(_finding_from_rule(NVIDIA_RULE, package=package, source="requirements.lock"))
    findings = sorted(findings, key=lambda item: (str(item.get("category")), str(item.get("package"))))
    return {
        "status": _status_from_findings(findings),
        "path_echoed": False,
        "package_count": len(packages),
        "packages": packages,
        "findings": findings,
        "blocked_reasons": [item for item in findings if item.get("severity") == "blocked"],
    }


def _finding_from_rule(rule: DependencyRule, *, package: str, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "package": package,
        "severity": rule.severity,
        "category": rule.category,
        "reason": rule.reason,
        "expected_scope": rule.expected_scope,
    }


def _find_rule_violations(
    package_names: Sequence[str],
    rules: Sequence[DependencyRule],
    *,
    source: str,
) -> list[dict[str, Any]]:
    rule_by_package = _rule_map(rules)
    findings: list[dict[str, Any]] = []
    for package in package_names:
        rule = rule_by_package.get(package)
        if rule is None:
            continue
        findings.append(_finding_from_rule(rule, package=package, source=source))
    return findings


def _dockerfile_report(dockerfile_path: Path) -> dict[str, Any]:
    text, read_status = _read_text(dockerfile_path)
    if read_status.get("status") != "passed":
        return {
            "status": "not_checked",
            "path_echoed": False,
            "finding": "Dockerfile was not found or could not be read.",
        }
    copied_requirement_inputs = [
        match.group(1).strip('"').strip("'")
        for match in REQUIREMENTS_FILE_PATTERN.finditer(text)
    ]
    installed_requirement_inputs = [
        match.group(1).strip('"').strip("'")
        for match in REQUIREMENTS_INSTALL_PATTERN.finditer(text)
    ]
    uses_default_requirements = any(
        Path(value.replace("\\", "/")).name == "requirements.txt"
        for value in copied_requirement_inputs
    )
    installs_default_requirements = any(
        Path(value.replace("\\", "/")).name == "requirements.txt"
        for value in installed_requirement_inputs
    )
    installs_requirements = bool(installed_requirement_inputs)
    status = "blocked" if uses_default_requirements and installs_default_requirements else "passed"
    return {
        "status": status,
        "path_echoed": False,
        "copied_requirement_inputs": copied_requirement_inputs,
        "installed_requirement_inputs": installed_requirement_inputs,
        "uses_default_requirements_txt": uses_default_requirements,
        "installs_requirements_file": installs_requirements,
        "installs_default_requirements_txt": installs_default_requirements,
        "finding": (
            "Dockerfile installs the full locked requirements.txt into the production image."
            if status == "blocked"
            else "Dockerfile does not obviously install the full default requirements.txt."
        ),
    }


def build_runtime_dependency_scope_report(
    *,
    pyproject_path: Path | None = None,
    requirements_path: Path | None = None,
    dockerfile_path: Path | None = None,
) -> dict[str, Any]:
    """Build a static production dependency-scope report."""

    pyproject = _parse_pyproject_dependencies(pyproject_path or PROJECT_ROOT / "pyproject.toml")
    requirements = _parse_requirements_packages(requirements_path or DEFAULT_RUNTIME_REQUIREMENTS)
    dockerfile = _dockerfile_report(dockerfile_path or PROJECT_ROOT / "Dockerfile")

    blocked_reasons: list[dict[str, Any]] = []
    for section_name, section in (
        ("pyproject", pyproject),
        ("requirements", requirements),
        ("dockerfile", dockerfile),
    ):
        if section.get("status") != "blocked":
            continue
        section_blockers = section.get("blocked_reasons")
        if section_blockers:
            for item in section_blockers:
                payload = dict(item)
                payload.setdefault("section", section_name)
                blocked_reasons.append(payload)
        else:
            blocked_reasons.append(
                {
                    "section": section_name,
                    "severity": "blocked",
                    "reason": section.get("finding") or "Section is blocked.",
                }
            )

    if requirements.get("status") == "blocked" and dockerfile.get("status") == "blocked":
        blocked_reasons.append(
            {
                "section": "production_image_input",
                "severity": "blocked",
                "reason": "The production Dockerfile currently installs requirements.txt, so locked heavy packages enter the image.",
                "expected_scope": "Use a runtime-only requirements file or explicit build profile.",
            }
        )

    status = "blocked" if blocked_reasons else "passed"
    return {
        "version": RUNTIME_DEPENDENCY_SCOPE_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "reads_runtime_dirs": False,
            "installs_packages": False,
            "runs_docker": False,
            "path_values_echoed": False,
        },
        "sections": {
            "pyproject": pyproject,
            "requirements": requirements,
            "dockerfile": dockerfile,
        },
        "blocked_reasons": blocked_reasons,
        "repair_suggestions": [
            {
                "action": "Move pytest and pytest-asyncio out of project.dependencies into a dev/test dependency group.",
                "command": "uv lock && uv export --frozen --no-dev --no-hashes -o requirements.runtime.txt",
            },
            {
                "action": "Move faster-whisper, imageio-ffmpeg, sentence-transformers and their torch/GPU transitive stack behind optional multimodal or local-embedding profiles.",
                "command": "Create a runtime-only Docker build input before the next M1 execute.",
            },
            {
                "action": "Point the production Dockerfile at the runtime-only requirements file after import coverage is verified.",
                "command": "uv run python scripts\\check_runtime_dependency_scope.py --json",
            },
        ],
        "not_proven_by_this_check": [
            "This static check does not build the image or measure image size.",
            "It does not prove every runtime import is covered by a future runtime-only requirements file.",
            "It does not validate GPU, ASR, or local embedding optional worker images.",
            "It does not change the live server or currently running containers.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_runtime_dependency_scope_markdown(report: Mapping[str, Any]) -> str:
    sections = report.get("sections") if isinstance(report.get("sections"), Mapping) else {}
    lines = [
        "# Runtime Dependency Scope",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: file paths, .env values and installed package metadata are not echoed.",
        "",
        "| Section | Status | Evidence |",
        "|---|---|---|",
    ]
    for name in ("pyproject", "requirements", "dockerfile"):
        section = sections.get(name) if isinstance(sections.get(name), Mapping) else {}
        if name == "pyproject":
            evidence = f"dependencies={section.get('dependency_count', 0)}, findings={len(section.get('findings') or [])}"
        elif name == "requirements":
            evidence = f"packages={section.get('package_count', 0)}, findings={len(section.get('findings') or [])}"
        else:
            evidence = section.get("finding") or "-"
        lines.append(f"| `{name}` | `{section.get('status')}` | {_markdown_cell(evidence)} |")
    blockers = report.get("blocked_reasons") or []
    if blockers:
        lines.extend(["", "## Blocked Reasons", ""])
        for item in blockers:
            if isinstance(item, Mapping):
                package = f" `{item.get('package')}`" if item.get("package") else ""
                lines.append(f"- `{item.get('section') or item.get('source')}`{package}: {item.get('reason')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_check") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", type=_path_arg, default=PROJECT_ROOT / "pyproject.toml")
    parser.add_argument("--requirements", type=_path_arg, default=DEFAULT_RUNTIME_REQUIREMENTS)
    parser.add_argument("--dockerfile", type=_path_arg, default=PROJECT_ROOT / "Dockerfile")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_runtime_dependency_scope_report(
        pyproject_path=args.pyproject,
        requirements_path=args.requirements,
        dockerfile_path=args.dockerfile,
    )
    output = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_runtime_dependency_scope_markdown(report)
    )
    print(output, end="" if output.endswith("\n") else "\n")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
