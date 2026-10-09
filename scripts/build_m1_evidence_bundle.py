"""Build a private, redacted M1 deployment evidence bundle.

The bundle builder does not run probes, connect SSH, call live services, read
`.env` files, or start containers. It only reads an explicitly provided M1
go/no-go JSON report, redacts sensitive values, renders the live evidence
summary, and writes a small manifest when ``--execute`` is provided.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402
from scripts.render_m1_live_evidence_summary import (  # noqa: E402
    build_m1_live_evidence_summary_markdown,
)


M1_EVIDENCE_BUNDLE_VERSION = "m1_evidence_bundle.v1"
DEFAULT_BUNDLE_NAME = "m1-evidence-bundle"
URL_PATTERN = re.compile(r"https?://[^\s`'\"<>()\[\]{}|]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_redact_text(value: str) -> str:
    redacted = redact_text(value)
    redacted = URL_PATTERN.sub("[REDACTED_URL]", redacted)
    return IPV4_PATTERN.sub("[REDACTED_IP]", redacted)


def _bundle_redact_data(value: Any, *, max_depth: int = 12) -> Any:
    """Redact secrets, URLs and server addresses for portable evidence bundles."""

    value = redact_data(value, max_depth=max_depth)
    if max_depth < 0:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): _bundle_redact_data(item, max_depth=max_depth - 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_bundle_redact_data(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_bundle_redact_data(item, max_depth=max_depth - 1) for item in value)
    if isinstance(value, str):
        return _bundle_redact_text(value)
    return value


def _load_go_no_go_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read go/no-go JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("M1 go/no-go JSON must be an object.")
    redacted = _bundle_redact_data(payload)
    return redacted if isinstance(redacted, dict) else {}


def _summary_counts(report: Mapping[str, Any]) -> dict[str, Any]:
    sections = report.get("section_statuses")
    section_statuses = sections if isinstance(sections, Mapping) else {}
    blockers = report.get("blockers")
    degraded = report.get("degraded_reasons")
    return {
        "go_no_go_version": report.get("version"),
        "go_no_go_status": report.get("status"),
        "decision": report.get("decision"),
        "section_count": len(section_statuses),
        "section_statuses": dict(section_statuses),
        "blocker_count": len(blockers) if isinstance(blockers, list) else 0,
        "degraded_count": len(degraded) if isinstance(degraded, list) else 0,
    }


def _artifact_record(path: Path, *, output_dir: Path, role: str) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "role": role,
        "path": path.relative_to(output_dir).as_posix(),
        "bytes": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _build_readme(report: Mapping[str, Any], *, bundle_name: str, generated_at: datetime) -> str:
    summary = _summary_counts(report)
    lines = [
        "# M1 Evidence Bundle",
        "",
        "This private bundle contains redacted M1 deployment evidence for review and post-incident reconstruction.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Bundle | `{bundle_name}` |",
        f"| Generated at | `{generated_at.isoformat()}` |",
        f"| Decision | `{summary.get('decision')}` |",
        f"| Status | `{summary.get('go_no_go_status')}` |",
        f"| Section count | `{summary.get('section_count')}` |",
        f"| Blockers | `{summary.get('blocker_count')}` |",
        f"| Degraded reasons | `{summary.get('degraded_count')}` |",
        "",
        "## Files",
        "",
        "- `m1-go-no-go.redacted.json`: redacted source evidence used for this bundle.",
        "- `m1-live-evidence-summary.md`: human-readable deployment evidence summary.",
        "- `manifest.json`: artifact hashes, policy and decision metadata.",
        "",
        "## Boundaries",
        "",
        "- This bundle does not prove full production readiness by itself.",
        "- It does not contain `.env`, raw logs, vector stores, database dumps, real secrets or raw chat transcripts.",
        "- It does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
        "- Keep generated bundles in a private workdir unless every artifact has been manually reviewed for public release.",
        "",
    ]
    return _bundle_redact_text("\n".join(lines))


def build_m1_evidence_bundle_report(
    *,
    go_no_go_json: Path,
    output_dir: Path,
    bundle_name: str = DEFAULT_BUNDLE_NAME,
    execute: bool = False,
    allow_project_output: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build or plan a private redacted M1 evidence bundle."""

    now = generated_at or datetime.now(UTC)
    output_dir = output_dir.resolve()
    inside_project = _is_relative_to(output_dir, PROJECT_ROOT)
    report = _load_go_no_go_report(go_no_go_json)
    summary_markdown = _bundle_redact_text(
        build_m1_live_evidence_summary_markdown(
            report,
            generated_at=now,
            source_name=f"go_no_go_json:{go_no_go_json.name}",
        )
    )
    redacted_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    readme = _build_readme(report, bundle_name=bundle_name, generated_at=now)
    bundle_report: dict[str, Any] = {
        "version": M1_EVIDENCE_BUNDLE_VERSION,
        "status": "ready_to_write" if not execute else "passed",
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "runs_live_probes": False,
            "connects_ssh": False,
            "starts_services": False,
            "writes_files": execute,
            "records_source_path": False,
            "records_public_url": False,
            "records_server_ip": False,
            "records_credentials": False,
            "records_raw_logs": False,
            "records_raw_chat_transcripts": False,
            "output_should_remain_private": True,
        },
        "target": {
            "source_name": go_no_go_json.name,
            "source_path_echoed": False,
            "output_dir": "<private-workdir>",
            "output_dir_inside_project": inside_project,
            "allow_project_output": allow_project_output,
        },
        "git": {
            "commit": _run_git(["rev-parse", "HEAD"]),
            "short_commit": _run_git(["rev-parse", "--short", "HEAD"]),
            "branch": _run_git(["branch", "--show-current"]),
        },
        "go_no_go": _summary_counts(report),
        "planned_artifacts": [
            {"role": "redacted_go_no_go_json", "path": "m1-go-no-go.redacted.json"},
            {"role": "live_evidence_summary_markdown", "path": "m1-live-evidence-summary.md"},
            {"role": "bundle_readme", "path": "README.md"},
            {"role": "bundle_manifest", "path": "manifest.json"},
        ],
        "not_proven_by_this_bundle": [
            "Generating a bundle does not run health checks, live probes, SSH, deployment, rollback or chat.",
            "The bundle preserves only redacted evidence; raw operational evidence must stay in the private evidence store.",
            "The bundle does not prove full production-grade HA, autoscaling, high concurrency, real payment or fulfillment.",
        ],
    }
    if inside_project and not allow_project_output:
        bundle_report["status"] = "blocked"
        bundle_report["blocked_reasons"] = [
            {
                "key": "project_output_not_allowed",
                "finding": "Use a private output directory outside the Git workspace or pass --allow-project-output.",
            }
        ]
        return bundle_report
    if not execute:
        bundle_report["artifact_digests"] = [
            {
                "role": "redacted_go_no_go_json",
                "path": "m1-go-no-go.redacted.json",
                "sha256": _sha256_bytes(redacted_json.encode("utf-8")),
            },
            {
                "role": "live_evidence_summary_markdown",
                "path": "m1-live-evidence-summary.md",
                "sha256": _sha256_bytes(summary_markdown.encode("utf-8")),
            },
            {
                "role": "bundle_readme",
                "path": "README.md",
                "sha256": _sha256_bytes(readme.encode("utf-8")),
            },
        ]
        return bundle_report

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "m1-go-no-go.redacted.json"
    summary_path = output_dir / "m1-live-evidence-summary.md"
    readme_path = output_dir / "README.md"
    manifest_path = output_dir / "manifest.json"
    json_path.write_text(redacted_json, encoding="utf-8")
    summary_path.write_text(summary_markdown, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")
    artifacts = [
        _artifact_record(json_path, output_dir=output_dir, role="redacted_go_no_go_json"),
        _artifact_record(summary_path, output_dir=output_dir, role="live_evidence_summary_markdown"),
        _artifact_record(readme_path, output_dir=output_dir, role="bundle_readme"),
    ]
    manifest = dict(bundle_report)
    manifest["artifacts"] = artifacts
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifacts.append(_artifact_record(manifest_path, output_dir=output_dir, role="bundle_manifest"))
    bundle_report["artifacts"] = artifacts
    bundle_report["manifest_sha256"] = _sha256_file(manifest_path)
    return bundle_report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go-no-go-json", type=_path_arg, required=True, help="Private M1 go/no-go JSON path.")
    parser.add_argument("--output-dir", type=_path_arg, required=True, help="Private output directory for bundle files.")
    parser.add_argument("--bundle-name", default=DEFAULT_BUNDLE_NAME)
    parser.add_argument("--execute", action="store_true", help="Write the redacted bundle files.")
    parser.add_argument(
        "--allow-project-output",
        action="store_true",
        help="Allow writing into the Git workspace. Prefer a private directory outside the repo.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_m1_evidence_bundle_report(
            go_no_go_json=args.go_no_go_json,
            output_dir=args.output_dir,
            bundle_name=args.bundle_name,
            execute=args.execute,
            allow_project_output=args.allow_project_output,
        )
    except ValueError as exc:
        report = {
            "version": M1_EVIDENCE_BUNDLE_VERSION,
            "status": "blocked",
            "blocked_reasons": [{"key": "invalid_input", "finding": str(exc)}],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
