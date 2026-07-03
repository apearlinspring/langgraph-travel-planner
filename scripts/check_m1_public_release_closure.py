"""Check the public M1 release closure boundary.

This checker is intentionally public-side only. It does not read `.env`, private
evidence directories, runtime folders, logs, backups or vector stores. Its job is
to verify that the repository contains the public deployment narrative, scripts
and over-claim guardrails needed before preparing a public release candidate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_public_release_boundary import (  # noqa: E402
    build_public_release_boundary_report,
    candidate_release_paths,
)


M1_PUBLIC_RELEASE_CLOSURE_VERSION = "m1_public_release_closure.v1"

REQUIRED_PUBLIC_DOCS = (
    "docs/部署与运行/deployment-readiness.md",
    "docs/部署与运行/m1-controlled-trial-status.md",
    "docs/部署与运行/m1-controlled-trial-runbook.md",
    "docs/部署与运行/m1-operations-evidence-playbook.md",
    "docs/部署与运行/m1-launch-checklist.md",
    "docs/部署与运行/m1-release-candidate-freeze.md",
    "docs/部署与运行/m1-acceptance-record-template.md",
    "docs/部署与运行/production-deployment-inputs.md",
    "docs/部署与运行/production-readiness-gap.md",
    "docs/部署与运行/postgres-redis-ops-runbook.md",
    "docs/部署与运行/backup-restore-runbook.md",
    "docs/部署与运行/monitoring-alerting-runbook.md",
    "docs/部署与运行/incident-response-rollback-runbook.md",
    "docs/部署与运行/security-release-key-rotation-runbook.md",
)

REQUIRED_PUBLIC_SCRIPTS = (
    "scripts/check_public_release_boundary.py",
    "scripts/check_m1_deployment_gate.py",
    "scripts/check_m1_first_deploy_dry_run.py",
    "scripts/build_release_artifact.py",
    "scripts/collect_m1_go_no_go_evidence.py",
    "scripts/run_m1_private_live_evidence_workflow.py",
    "scripts/check_m1_private_evidence_signoff.py",
    "scripts/render_m1_deployment_evidence_matrix.py",
    "scripts/render_m1_acceptance_record.py",
    "scripts/check_m1_rollout_execution_record.py",
    "scripts/check_m1_operations_review_record.py",
    "scripts/check_live_chat_probe_execution_approval.py",
    "scripts/collect_live_chat_probe.py",
    "scripts/check_live_chat_concurrency_probe_approval.py",
    "scripts/collect_live_chat_concurrency_probe.py",
    "scripts/collect_live_concurrency_probe.py",
    "scripts/collect_rate_limit_live_probe.py",
    "scripts/collect_server_capacity_snapshot.py",
    "scripts/collect_postgres_redis_live_probe.py",
    "scripts/collect_backup_schedule_live_probe.py",
    "scripts/collect_postgres_restore_drill_live_probe.py",
    "scripts/check_external_dependency_resilience_record.py",
    "scripts/check_security_release_readiness.py",
)

CLAIM_BOUNDARY_REQUIREMENTS = (
    {
        "key": "status_doc_boundary",
        "path": "docs/部署与运行/m1-controlled-trial-status.md",
        "phrases": (
            "不能声明为完整生产就绪",
            "不接真实支付",
            "chat 小流量并发采样",
            "独立补充 workflow/signoff",
        ),
    },
    {
        "key": "operations_playbook_boundary",
        "path": "docs/部署与运行/m1-operations-evidence-playbook.md",
        "phrases": (
            "不把项目包装成完整生产高可用系统",
            "不触发真实支付",
            "独立 workflow/signoff",
        ),
    },
    {
        "key": "deployment_template_private_boundary",
        "path": "docs/部署与运行/deployment-readiness.md",
        "phrases": (
            "Real production hostnames, IP addresses, SSH users, private keys, `.env` files and database contents must stay outside Git.",
            "check_public_release_boundary.py",
        ),
    },
    {
        "key": "security_key_boundary",
        "path": "docs/部署与运行/security-release-key-rotation-runbook.md",
        "phrases": (
            "不记录真实密钥",
            "check_public_release_boundary.py",
        ),
    },
)

PUBLIC_COORDINATE_PATTERNS = (
    ("real_domain", re.compile(r"\btravel\.403edr\.cn\b", re.IGNORECASE)),
    ("real_server_ip", re.compile(r"\b8\.145\.46\.253\b")),
    ("local_absolute_path", re.compile(r"D:\\Users\\Administrator", re.IGNORECASE)),
    ("private_evidence_dir", re.compile(r"m1-private-execution", re.IGNORECASE)),
    ("probe_identity_hint", re.compile(r"\bm1probe\b|ZhixingM1", re.IGNORECASE)),
)

PUBLIC_TEXT_EXTENSIONS = {".md", ".py", ".sh", ".yml", ".yaml", ".toml", ".txt", ".js"}


def _repo_path(path: str | Path) -> str:
    return Path(path).as_posix()


def _read_text(root: Path, relative_path: str) -> str | None:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
    except UnicodeDecodeError:
        return None


def _file_section(root: Path, paths: Sequence[str], *, label: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for relative_path in paths:
        path = root / relative_path
        exists = path.is_file()
        items.append(
            {
                "path": relative_path,
                "status": "passed" if exists else "blocked",
                "finding": f"{label} exists." if exists else f"{label} is missing.",
            }
        )
    missing = [item["path"] for item in items if item["status"] == "blocked"]
    return {
        "status": "blocked" if missing else "passed",
        "checked_count": len(items),
        "missing": missing,
        "items": items,
    }


def _claim_boundary_section(root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for requirement in CLAIM_BOUNDARY_REQUIREMENTS:
        relative_path = str(requirement["path"])
        text = _read_text(root, relative_path)
        missing_phrases = [
            phrase
            for phrase in requirement["phrases"]
            if text is None or phrase not in text
        ]
        items.append(
            {
                "key": requirement["key"],
                "path": relative_path,
                "status": "blocked" if missing_phrases else "passed",
                "missing_phrases": missing_phrases,
            }
        )
    blocked = [item for item in items if item["status"] == "blocked"]
    return {
        "status": "blocked" if blocked else "passed",
        "checked_count": len(items),
        "blocked_count": len(blocked),
        "items": items,
    }


def _public_text_paths(root: Path) -> list[Path]:
    ignored_parts = {
        ".git",
        ".runtime",
        ".venv",
        "__pycache__",
        "backups",
        "data",
        "logs",
        "node_modules",
        "tests",
    }
    paths: list[Path] = []
    for relative in candidate_release_paths(root):
        if any(part in ignored_parts for part in relative.parts):
            continue
        if relative == Path("scripts/check_m1_public_release_closure.py"):
            continue
        if relative.suffix.lower() in PUBLIC_TEXT_EXTENSIONS:
            paths.append(relative)
    return sorted(paths)


def _coordinate_section(root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for relative_path in _public_text_paths(root):
        text = _read_text(root, _repo_path(relative_path))
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in PUBLIC_COORDINATE_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {
                            "path": _repo_path(relative_path),
                            "line": line_number,
                            "kind": kind,
                        }
                    )
    return {
        "status": "blocked" if findings else "passed",
        "finding_count": len(findings),
        "findings": findings,
    }


def _build_section_statuses(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {key: str(value.get("status", "blocked")) for key, value in sections.items()}


def build_m1_public_release_closure_report(
    *,
    repo_root: str | Path = PROJECT_ROOT,
    public_boundary_builder: Callable[..., Mapping[str, Any]] = build_public_release_boundary_report,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    public_boundary = dict(public_boundary_builder(repo_root=root))
    sections: dict[str, Mapping[str, Any]] = {
        "public_release_boundary": public_boundary,
        "required_public_docs": _file_section(root, REQUIRED_PUBLIC_DOCS, label="Public M1 document"),
        "required_public_scripts": _file_section(root, REQUIRED_PUBLIC_SCRIPTS, label="Public M1 script"),
        "claim_boundary": _claim_boundary_section(root),
        "public_coordinate_scan": _coordinate_section(root),
    }
    section_statuses = _build_section_statuses(sections)
    blockers = [
        {"section": section, "status": status}
        for section, status in section_statuses.items()
        if status != "passed"
    ]
    return {
        "version": M1_PUBLIC_RELEASE_CLOSURE_VERSION,
        "status": "blocked" if blockers else "passed",
        "section_statuses": section_statuses,
        "blockers": blockers,
        "sections": sections,
        "policy": {
            "reads_dotenv": False,
            "reads_runtime_dirs": False,
            "reads_private_evidence_dirs": False,
            "connects_network": False,
            "connects_ssh": False,
            "starts_services": False,
            "deletes_files": False,
            "checks_public_docs_and_scripts": True,
            "checks_no_real_public_coordinates": True,
            "checks_no_full_production_overclaim": True,
        },
        "not_proven_by_this_report": [
            "This report does not prove that the server is currently healthy.",
            "This report does not prove that private M1 evidence exists or is signed.",
            "This report does not prove high-concurrency chat capacity, autoscaling, long-duration soak stability, real payment, booking, inventory lock, ticketing or fulfillment.",
            "A passed report means the public repository closure boundary is ready for release-candidate review.",
        ],
    }


def build_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 Public Release Closure Check",
        "",
        f"- status: `{report.get('status')}`",
        f"- version: `{report.get('version')}`",
        "",
        "## Section Statuses",
        "",
        "| Section | Status |",
        "|---|---|",
    ]
    for section, status in (report.get("section_statuses") or {}).items():
        lines.append(f"| {section} | `{status}` |")
    blockers = report.get("blockers") or []
    if blockers:
        lines.extend(["", "## Blockers", ""])
        for blocker in blockers:
            lines.append(f"- `{blocker.get('section')}` is `{blocker.get('status')}`.")
    lines.extend(["", "## Boundary", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. This is the default format.")
    parser.add_argument("--markdown", action="store_true", help="Print a Markdown summary.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_public_release_closure_report()
    if args.markdown:
        print(build_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
