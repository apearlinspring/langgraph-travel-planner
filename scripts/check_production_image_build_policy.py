"""Check production image build policy without running Docker or reading secrets."""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import re
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_IMAGE_BUILD_POLICY_VERSION = "production_image_build_policy.v1"
RECORD_VERSION = "production_image_build_policy_record.v1"
PLACEHOLDER_PREFIXES = ("todo", "tbd", "your-", "example", "change-me", "placeholder", "<", "${")
SECRETISH_PATTERN = re.compile(
    r"(?i)(://[^/\s]+:[^@\s]+@|api[_-]?key\s*=|token\s*=|password\s*=|secret\s*=|bearer\s+)"
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def build_policy_template() -> dict[str, Any]:
    """Return the safe public baseline for M1 production image builds."""

    return {
        "record_version": RECORD_VERSION,
        "package_mirror": {
            "pip_index_url_source": "PIP_INDEX_URL environment variable or default official PyPI",
            "pip_trusted_host_source": "PIP_TRUSTED_HOST environment variable only when the mirror requires it",
            "secret_values_in_url": False,
            "mirror_failure_policy": "retry the configured mirror first; fallback requires an operator note",
        },
        "remote_build": {
            "mode": "remote_background",
            "wrapper": "nohup or systemd-run",
            "timeout_seconds": 1800,
            "log_retention_days": 7,
            "records_pid": True,
            "records_log_path": True,
        },
        "safety": {
            "disk_guard_required": True,
            "minimum_free_disk_mb": 2048,
            "no_system_prune": True,
            "no_volume_delete": True,
            "no_env_delete": True,
            "no_vectorstore_delete": True,
            "current_release_unchanged_until_success": True,
            "rollback_command_recorded": True,
        },
        "evidence": {
            "record_start_end": True,
            "record_build_duration": True,
            "record_image_id_before_after": True,
            "record_image_size": True,
            "record_compose_ps": True,
            "record_health_ready_after": True,
            "values_echoed": False,
        },
    }


def _read_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return None, _finding(
            section="policy_record",
            key="policy_json_readable",
            status="blocked",
            finding=f"Cannot read policy JSON: {exc.__class__.__name__}",
        )
    except json.JSONDecodeError as exc:
        return None, _finding(
            section="policy_record",
            key="policy_json_valid",
            status="blocked",
            finding=f"Policy JSON is invalid: {exc.msg}",
        )
    if not isinstance(payload, dict):
        return None, _finding(
            section="policy_record",
            key="policy_json_object",
            status="blocked",
            finding="Policy JSON must be an object.",
        )
    return payload, None


def _looks_placeholder(value: Any) -> bool:
    lowered = str(value or "").strip().strip("'\"").lower()
    if lowered in {"", "unknown", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _contains_secretish_value(value: Any) -> bool:
    return bool(SECRETISH_PATTERN.search(str(value or "")))


def _finding(*, section: str, key: str, status: str, finding: str) -> dict[str, Any]:
    return {
        "section": section,
        "key": key,
        "status": status,
        "finding": finding,
        "value_echoed": False,
    }


def _require_text(
    checks: list[dict[str, Any]],
    section: str,
    payload: Mapping[str, Any],
    key: str,
    *,
    must_contain: tuple[str, ...] = (),
) -> None:
    value = payload.get(key)
    if _looks_placeholder(value):
        checks.append(
            _finding(
                section=section,
                key=key,
                status="blocked",
                finding="Required policy text is missing or still looks like a placeholder.",
            )
        )
        return
    if _contains_secretish_value(value):
        checks.append(
            _finding(
                section=section,
                key=key,
                status="blocked",
                finding="Policy text appears to contain a secret-like value.",
            )
        )
        return
    lowered = str(value).lower()
    for needle in must_contain:
        if needle.lower() not in lowered:
            checks.append(
                _finding(
                    section=section,
                    key=key,
                    status="blocked",
                    finding=f"Policy text must mention {needle}.",
                )
            )
            return
    checks.append(
        _finding(section=section, key=key, status="passed", finding="Declared.")
    )


def _require_bool(
    checks: list[dict[str, Any]],
    section: str,
    payload: Mapping[str, Any],
    key: str,
    expected: bool,
) -> None:
    value = payload.get(key)
    checks.append(
        _finding(
            section=section,
            key=key,
            status="passed" if value is expected else "blocked",
            finding="Declared." if value is expected else f"Expected {expected}.",
        )
    )


def _require_min_number(
    checks: list[dict[str, Any]],
    section: str,
    payload: Mapping[str, Any],
    key: str,
    minimum: int,
) -> None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        status = "blocked"
        finding = f"Expected a numeric value >= {minimum}."
    elif value < minimum:
        status = "blocked"
        finding = f"Value must be >= {minimum}."
    else:
        status = "passed"
        finding = "Declared."
    checks.append(_finding(section=section, key=key, status=status, finding=finding))


def _section(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = payload.get(name)
    return section if isinstance(section, Mapping) else {}


def _policy_checks(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if record.get("record_version") != RECORD_VERSION:
        checks.append(
            _finding(
                section="policy_record",
                key="record_version",
                status="blocked",
                finding=f"Expected record_version {RECORD_VERSION}.",
            )
        )
    else:
        checks.append(
            _finding(
                section="policy_record",
                key="record_version",
                status="passed",
                finding="Record version is supported.",
            )
        )

    package_mirror = _section(record, "package_mirror")
    _require_text(checks, "package_mirror", package_mirror, "pip_index_url_source", must_contain=("PIP_INDEX_URL",))
    _require_text(
        checks,
        "package_mirror",
        package_mirror,
        "pip_trusted_host_source",
        must_contain=("PIP_TRUSTED_HOST",),
    )
    _require_bool(checks, "package_mirror", package_mirror, "secret_values_in_url", False)
    _require_text(checks, "package_mirror", package_mirror, "mirror_failure_policy", must_contain=("retry",))

    remote_build = _section(record, "remote_build")
    mode = str(remote_build.get("mode") or "").strip().lower()
    checks.append(
        _finding(
            section="remote_build",
            key="mode",
            status="passed" if mode == "remote_background" else "blocked",
            finding="Remote background build is required for long server builds.",
        )
    )
    _require_text(checks, "remote_build", remote_build, "wrapper")
    wrapper = str(remote_build.get("wrapper") or "").lower()
    if wrapper and not any(token in wrapper for token in ("nohup", "systemd", "tmux")):
        checks.append(
            _finding(
                section="remote_build",
                key="wrapper_kind",
                status="blocked",
                finding="Background wrapper must mention nohup, systemd-run, or tmux.",
            )
        )
    else:
        checks.append(
            _finding(
                section="remote_build",
                key="wrapper_kind",
                status="passed",
                finding="Background wrapper kind is acceptable.",
            )
        )
    _require_min_number(checks, "remote_build", remote_build, "timeout_seconds", 900)
    _require_min_number(checks, "remote_build", remote_build, "log_retention_days", 3)
    _require_bool(checks, "remote_build", remote_build, "records_pid", True)
    _require_bool(checks, "remote_build", remote_build, "records_log_path", True)

    safety = _section(record, "safety")
    for key in (
        "disk_guard_required",
        "no_system_prune",
        "no_volume_delete",
        "no_env_delete",
        "no_vectorstore_delete",
        "current_release_unchanged_until_success",
        "rollback_command_recorded",
    ):
        _require_bool(checks, "safety", safety, key, True)
    _require_min_number(checks, "safety", safety, "minimum_free_disk_mb", 2048)

    evidence = _section(record, "evidence")
    for key in (
        "record_start_end",
        "record_build_duration",
        "record_image_id_before_after",
        "record_image_size",
        "record_compose_ps",
        "record_health_ready_after",
    ):
        _require_bool(checks, "evidence", evidence, key, True)
    _require_bool(checks, "evidence", evidence, "values_echoed", False)
    return checks


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _repo_checks(
    *,
    update_script_path: Path,
    dockerfile_path: Path,
    runtime_requirements_path: Path,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    update_script = _read_text(update_script_path)
    dockerfile = _read_text(dockerfile_path)
    runtime_requirements = _read_text(runtime_requirements_path)

    script_expectations = {
        "pip_index_url_arg": "PIP_INDEX_URL",
        "pip_trusted_host_arg": "PIP_TRUSTED_HOST",
        "disk_guard": "ZHIXING_MIN_FREE_DISK_MB",
        "compose_project_pin": "COMPOSE_PROJECT_NAME",
        "docker_build": "docker build",
        "compose_refresh": "docker compose up -d --no-build backend caddy",
    }
    for key, needle in script_expectations.items():
        checks.append(
            _finding(
                section="repo_update_script",
                key=key,
                status="passed" if needle in update_script else "blocked",
                finding="Expected update-runtime-image.sh contract is present."
                if needle in update_script
                else "update-runtime-image.sh is missing an expected production build contract.",
            )
        )

    checks.append(
        _finding(
            section="repo_dockerfile",
            key="runtime_requirements_input",
            status="passed" if "requirements.runtime.txt" in dockerfile else "blocked",
            finding="Dockerfile uses runtime-only requirements."
            if "requirements.runtime.txt" in dockerfile
            else "Dockerfile must use requirements.runtime.txt for the default API image.",
        )
    )
    checks.append(
        _finding(
            section="repo_runtime_requirements",
            key="runtime_requirements_exists",
            status="passed" if runtime_requirements.strip() else "blocked",
            finding="runtime requirements file exists."
            if runtime_requirements.strip()
            else "requirements.runtime.txt is missing or empty.",
        )
    )
    return checks


def _status(checks: list[Mapping[str, Any]]) -> str:
    return "blocked" if any(item.get("status") == "blocked" for item in checks) else "passed"


def build_production_image_build_policy_report(
    *,
    policy_record: Mapping[str, Any] | None = None,
    update_script_path: Path | None = None,
    dockerfile_path: Path | None = None,
    runtime_requirements_path: Path | None = None,
) -> dict[str, Any]:
    record = dict(policy_record or build_policy_template())
    checks = [
        *_policy_checks(record),
        *_repo_checks(
            update_script_path=update_script_path or PROJECT_ROOT / "deploy" / "update-runtime-image.sh",
            dockerfile_path=dockerfile_path or PROJECT_ROOT / "Dockerfile",
            runtime_requirements_path=runtime_requirements_path or PROJECT_ROOT / "requirements.runtime.txt",
        ),
    ]
    blocked_reasons = [item for item in checks if item.get("status") == "blocked"]
    return {
        "version": PRODUCTION_IMAGE_BUILD_POLICY_VERSION,
        "status": _status(checks),
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "runs_docker": False,
            "starts_services": False,
            "deletes_docker_resources": False,
            "reads_runtime_dirs": False,
            "secret_values_echoed": False,
        },
        "summary": {
            "policy_record_version": record.get("record_version"),
            "uses_remote_background_build": _section(record, "remote_build").get("mode") == "remote_background",
            "requires_disk_guard": _section(record, "safety").get("disk_guard_required") is True,
            "requires_runtime_requirements": True,
        },
        "checks": checks,
        "blocked_reasons": blocked_reasons,
        "not_proven_by_this_check": [
            "This check does not build an image or measure image size.",
            "It does not connect to the server, start services, delete Docker resources or read .env.",
            "It does not prove that a specific remote build has completed; that requires a private execution record.",
        ],
    }


def build_production_image_build_policy_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Production Image Build Policy",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- This report does not run Docker, connect SSH, read `.env` or echo private values.",
        "",
        "| Section | Key | Status | Finding |",
        "|---|---|---|---|",
    ]
    for item in report.get("checks") or []:
        if isinstance(item, Mapping):
            lines.append(
                "| `{}` | `{}` | `{}` | {} |".format(
                    item.get("section"),
                    item.get("key"),
                    item.get("status"),
                    str(item.get("finding") or "-").replace("|", "\\|"),
                )
            )
    blockers = report.get("blocked_reasons") or []
    if blockers:
        lines.extend(["", "## Blocked Reasons", ""])
        for item in blockers:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_check") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-json", type=_path_arg)
    parser.add_argument("--update-script", type=_path_arg, default=PROJECT_ROOT / "deploy" / "update-runtime-image.sh")
    parser.add_argument("--dockerfile", type=_path_arg, default=PROJECT_ROOT / "Dockerfile")
    parser.add_argument("--runtime-requirements", type=_path_arg, default=PROJECT_ROOT / "requirements.runtime.txt")
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        output = json.dumps(build_policy_template(), ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return 0

    policy_record: dict[str, Any] | None = None
    if args.policy_json:
        policy_record, read_error = _read_json(args.policy_json)
        if read_error is not None:
            report = {
                "version": PRODUCTION_IMAGE_BUILD_POLICY_VERSION,
                "status": "blocked",
                "policy": {
                    "reads_dotenv": False,
                    "connects_ssh": False,
                    "runs_docker": False,
                    "secret_values_echoed": False,
                },
                "checks": [read_error],
                "blocked_reasons": [read_error],
                "not_proven_by_this_check": [],
            }
        else:
            report = build_production_image_build_policy_report(
                policy_record=policy_record,
                update_script_path=args.update_script,
                dockerfile_path=args.dockerfile,
                runtime_requirements_path=args.runtime_requirements,
            )
    else:
        report = build_production_image_build_policy_report(
            update_script_path=args.update_script,
            dockerfile_path=args.dockerfile,
            runtime_requirements_path=args.runtime_requirements,
        )

    output = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_production_image_build_policy_markdown(report)
    )
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="" if output.endswith("\n") else "\n")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
