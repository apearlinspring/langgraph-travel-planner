"""Prepare a private M1 execution workspace outside Git."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_external_dependency_resilience_record import (  # noqa: E402
    _template_record as build_external_dependency_template,
)
from scripts.check_m1_execution_input_gap import (  # noqa: E402
    build_m1_execution_input_gap_report,
)
from scripts.check_m1_launch_inputs import build_m1_launch_inputs_template  # noqa: E402
from scripts.check_m1_operations_review_record import (  # noqa: E402
    _template_record as build_operations_review_template,
)
from scripts.check_m1_rollout_execution_record import (  # noqa: E402
    _template_record as build_rollout_execution_template,
)


M1_PRIVATE_EXECUTION_WORKSPACE_VERSION = "m1_private_execution_workspace.v1"
PRIVATE_WORKDIR_PLACEHOLDER = "<private-workdir>"
FORBIDDEN_PATH_PARTS = {
    ".env",
    ".runtime",
    ".venv",
    "logs",
    "vectorstore",
    "vectorstore_internal",
}


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_forbidden_path(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_PATH_PARTS)


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _private_readme_text() -> str:
    return "\n".join(
        [
            "# M1 Private Execution Workspace",
            "",
            "This directory is private and must stay outside Git.",
            "",
            "Fill non-secret status fields first:",
            "",
            "```powershell",
            "uv run python scripts\\check_m1_launch_inputs.py --input-json <private-workdir>\\m1-launch-inputs.local.json --json --output <private-workdir>\\m1-launch-inputs-report.json",
            "uv run python scripts\\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\\m1-launch-inputs.local.json --markdown",
            "```",
            "",
            "Do not paste API keys, passwords, tokens, cookies, raw logs, database dumps, vector stores, private URLs or server IPs into public docs or Git.",
            "M1 keeps real payment, booking, inventory lock, ticketing and fulfillment disabled.",
            "",
        ]
    )


def _private_gitignore_text() -> str:
    return "\n".join(
        [
            "# Private M1 execution evidence stays outside Git.",
            "*",
            "!.gitignore",
            "!README.md",
            "",
        ]
    )


def _missing_groups(gap_report: Mapping[str, Any] | None) -> dict[str, list[Mapping[str, Any]]]:
    if not isinstance(gap_report, Mapping):
        return {}
    missing = gap_report.get("missing_for_user")
    if not isinstance(missing, Mapping):
        return {}
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for group, items in missing.items():
        if not isinstance(items, list):
            continue
        grouped[str(group)] = [item for item in items if isinstance(item, Mapping)]
    return grouped


def _missing_label(item: Mapping[str, Any]) -> str:
    return str(item.get("env_var") or item.get("key") or item.get("label") or "-")


def _missing_finding(item: Mapping[str, Any]) -> str:
    return str(item.get("finding") or item.get("reason") or "Missing or blocked.")


def _private_input_todo_markdown(gap_report: Mapping[str, Any] | None) -> str:
    grouped = _missing_groups(gap_report)
    lines = [
        "# M1 Private Input TODO",
        "",
        "This file is generated from the current input-gap report and contains no secret values.",
        "Fill the real values in the private JSON or local shell environment, then regenerate the reports.",
        "",
        "| Group | Item | Fill Location | Finding |",
        "|---|---|---|---|",
    ]
    wrote = False
    fill_locations = {
        "m1_launch_inputs": "m1-launch-inputs.local.json",
        "private_live_inputs": "m1-live-inputs.local.ps1 or current shell env",
        "private_record_inputs": "matching private record JSON",
    }
    for group, items in grouped.items():
        for item in items:
            wrote = True
            label = _missing_label(item).replace("|", "\\|")
            finding = _missing_finding(item).replace("|", "\\|")
            location = fill_locations.get(group, "private workdir").replace("|", "\\|")
            lines.append(f"| `{group}` | `{label}` | `{location}` | {finding} |")
    if not wrote:
        lines.append("| - | - | - | No missing private inputs recorded. |")
    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "# Optional: fill and dot-source the generated live input file before live probes.",
            "# . <private-workdir>\\m1-live-inputs.local.ps1",
            "uv run python scripts\\check_m1_launch_inputs.py --input-json <private-workdir>\\m1-launch-inputs.local.json --json --output <private-workdir>\\m1-launch-inputs-report.json",
            "uv run python scripts\\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\\m1-launch-inputs.local.json --markdown --output <private-workdir>\\m1-execution-input-gap.md",
            "```",
            "",
            "## Boundary",
            "",
            "- Do not put API keys, passwords, bearer tokens, cookies, private keys, raw logs, database dumps or vector stores into Git.",
            "- Keep real server coordinates, backup paths, owner names and probe credentials in the private workspace or a controlled shell only.",
            "- Filling this TODO does not prove deployment, backup restore, live chat, rate limit, rollback or production readiness.",
            "",
        ]
    )
    return "\n".join(lines)


def _private_live_inputs_ps1(gap_report: Mapping[str, Any] | None) -> str:
    grouped = _missing_groups(gap_report)
    live_items = grouped.get("private_live_inputs", [])
    launch_items = grouped.get("m1_launch_inputs", [])
    lines = [
        "# M1 private live input starter.",
        "# Fill real values, uncomment the needed assignments, then dot-source this file.",
        "# This file is private evidence input and must stay outside Git.",
        "",
    ]
    if launch_items:
        lines.extend(
            [
                "# Launch JSON still needs these non-secret declarations in m1-launch-inputs.local.json:",
                *[f"# - {_missing_label(item)}" for item in launch_items],
                "",
            ]
        )
    if live_items:
        lines.append("# Live probe inputs:")
        for item in live_items:
            label = _missing_label(item)
            if "ZHIXING_PROBE_ACCESS_TOKEN" in label:
                lines.extend(
                    [
                        "# Choose one probe auth strategy:",
                        '# $env:ZHIXING_PROBE_ACCESS_TOKEN = "<fill-probe-bearer-token>"',
                        "# or:",
                        '# $env:ZHIXING_PROBE_USERNAME = "<fill-probe-username>"',
                        '# $env:ZHIXING_PROBE_PASSWORD = "<fill-probe-password>"',
                    ]
                )
            elif "ZHIXING_BACKUP_DIR" in label:
                lines.append('# $env:ZHIXING_BACKUP_DIR = "<fill-absolute-backup-dir-outside-git>"')
            else:
                safe_label = label.replace('"', "")
                lines.append(f'# $env:{safe_label} = "<fill-value>"')
    else:
        lines.append("# No missing live probe environment inputs were recorded.")
    lines.extend(
        [
            "",
            "# Recheck after filling:",
            "# uv run python scripts\\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\\m1-launch-inputs.local.json --markdown",
            "",
        ]
    )
    return "\n".join(lines)


def _todo_file_plan(*, execute: bool) -> list[dict[str, Any]]:
    action = "would_write" if not execute else "written"
    return [
        {
            "key": "m1_private_input_todo",
            "filename": "m1-private-inputs.todo.md",
            "description": "Generated private checklist for remaining launch/live inputs.",
            "exists": False,
            "action": action,
            "path_echoed": False,
        },
        {
            "key": "m1_live_inputs_starter",
            "filename": "m1-live-inputs.local.ps1",
            "description": "Commented private PowerShell starter for live probe env vars.",
            "exists": False,
            "action": action,
            "path_echoed": False,
        },
    ]


def _write_todo_files(*, private_workdir: Path, gap_report: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    outputs = [
        (
            "m1_private_input_todo",
            "m1-private-inputs.todo.md",
            "Generated private checklist for remaining launch/live inputs.",
            _private_input_todo_markdown(gap_report),
        ),
        (
            "m1_live_inputs_starter",
            "m1-live-inputs.local.ps1",
            "Commented private PowerShell starter for live probe env vars.",
            _private_live_inputs_ps1(gap_report),
        ),
    ]
    results: list[dict[str, Any]] = []
    for key, filename, description, text in outputs:
        target = private_workdir / filename
        existed = target.exists()
        target.write_text(text.rstrip() + "\n", encoding="utf-8")
        results.append(
            {
                "key": key,
                "filename": filename,
                "description": description,
                "exists": True,
                "action": "updated" if existed else "written",
                "path_echoed": False,
            }
        )
    return results


def _template_specs() -> list[dict[str, Any]]:
    return [
        {
            "key": "m1_launch_inputs",
            "filename": "m1-launch-inputs.local.json",
            "kind": "json",
            "builder": build_m1_launch_inputs_template,
            "description": "Non-secret launch input declarations.",
        },
        {
            "key": "external_dependency_resilience_record",
            "filename": "external-dependency-resilience-record.local.json",
            "kind": "json",
            "builder": build_external_dependency_template,
            "description": "External API, cost, timeout/retry and degradation record.",
        },
        {
            "key": "m1_rollout_execution_record",
            "filename": "m1-rollout-execution-record.local.json",
            "kind": "json",
            "builder": build_rollout_execution_template,
            "description": "Rollout execution, release artifact, backup point and rollback readiness record.",
        },
        {
            "key": "m1_operations_review_record",
            "filename": "m1-operations-review-record.local.json",
            "kind": "json",
            "builder": build_operations_review_template,
            "description": "Post-rollout operations review and follow-up record.",
        },
        {
            "key": "private_workspace_readme",
            "filename": "README.md",
            "kind": "markdown",
            "builder": _private_readme_text,
            "description": "Private workspace usage notes.",
        },
        {
            "key": "private_workspace_gitignore",
            "filename": ".gitignore",
            "kind": "text",
            "builder": _private_gitignore_text,
            "description": "Defense-in-depth ignore rules for private evidence files.",
        },
    ]


def _render_template(builder: Callable[[], Any], kind: str) -> str:
    payload = builder()
    if kind == "json":
        if not isinstance(payload, Mapping):
            raise TypeError("JSON template builder must return a mapping.")
        return _json_text(payload)
    return str(payload).rstrip() + "\n"


def _workdir_check(private_workdir: Path | None) -> dict[str, Any]:
    if private_workdir is None:
        return {
            "status": "blocked",
            "finding": "Private workdir is required.",
            "path_echoed": False,
        }
    inside_project = _is_relative_to(private_workdir, PROJECT_ROOT)
    forbidden = _is_forbidden_path(private_workdir)
    if inside_project:
        status = "blocked_sensitive_boundary"
        finding = "Private workdir must stay outside the Git workspace."
    elif forbidden:
        status = "blocked_sensitive_boundary"
        finding = "Private workdir points to a forbidden runtime or secret-like location."
    else:
        status = "passed"
        finding = "Private workdir can be used for private M1 templates."
    return {
        "status": status,
        "finding": finding,
        "exists": private_workdir.exists(),
        "inside_project": inside_project,
        "forbidden_path": forbidden,
        "path_echoed": False,
    }


def _file_plan(
    *,
    private_workdir: Path | None,
    execute: bool,
    overwrite: bool,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec in _template_specs():
        target = private_workdir / spec["filename"] if private_workdir is not None else None
        exists = target.exists() if target is not None else False
        action = "would_write"
        if exists and not overwrite:
            action = "skip_existing"
        elif exists and overwrite:
            action = "would_overwrite"
        if execute:
            if exists and not overwrite:
                action = "skipped_existing"
            elif exists and overwrite:
                action = "overwritten"
            else:
                action = "written"
        entries.append(
            {
                "key": spec["key"],
                "filename": spec["filename"],
                "description": spec["description"],
                "exists": exists,
                "action": action,
                "path_echoed": False,
            }
        )
    workflow_dir_exists = (private_workdir / "m1-live-evidence-workflow").exists() if private_workdir is not None else False
    entries.append(
        {
            "key": "m1_live_evidence_workflow_dir",
            "filename": "m1-live-evidence-workflow/",
            "description": "Private live evidence workflow output directory.",
            "exists": workflow_dir_exists,
            "action": "would_create_dir" if not execute else "created_or_exists",
            "path_echoed": False,
        }
    )
    return entries


def _write_templates(*, private_workdir: Path, overwrite: bool) -> list[dict[str, Any]]:
    private_workdir.mkdir(parents=True, exist_ok=True)
    (private_workdir / "m1-live-evidence-workflow").mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for spec in _template_specs():
        target = private_workdir / spec["filename"]
        exists_before = target.exists()
        if exists_before and not overwrite:
            results.append(
                {
                    "key": spec["key"],
                    "filename": spec["filename"],
                    "description": spec["description"],
                    "exists": True,
                    "action": "skipped_existing",
                    "path_echoed": False,
                }
            )
            continue
        target.write_text(_render_template(spec["builder"], spec["kind"]), encoding="utf-8")
        results.append(
            {
                "key": spec["key"],
                "filename": spec["filename"],
                "description": spec["description"],
                "exists": True,
                "action": "overwritten" if exists_before else "written",
                "path_echoed": False,
            }
        )
    results.append(
        {
            "key": "m1_live_evidence_workflow_dir",
            "filename": "m1-live-evidence-workflow/",
            "description": "Private live evidence workflow output directory.",
            "exists": True,
            "action": "created_or_exists",
            "path_echoed": False,
        }
    )
    return results


def _status_from(
    *,
    workdir: Mapping[str, Any],
    file_results: list[Mapping[str, Any]],
    execute: bool,
) -> str:
    if workdir.get("status") == "blocked_sensitive_boundary":
        return "blocked_sensitive_boundary"
    if workdir.get("status") == "blocked":
        return "blocked_missing_private_workdir"
    if not execute:
        return "ready_to_prepare"
    if any(item.get("action") == "error" for item in file_results):
        return "blocked_write_failed"
    return "workspace_prepared"


def build_m1_private_execution_workspace_report(
    *,
    private_workdir: Path | None,
    execute: bool = False,
    overwrite: bool = False,
    environ: Mapping[str, str] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build or execute a private M1 workspace preparation plan."""

    now = generated_at or datetime.now(UTC)
    env = environ if environ is not None else os.environ
    workdir = _workdir_check(private_workdir)
    file_results: list[dict[str, Any]]
    if execute and workdir.get("status") == "passed" and private_workdir is not None:
        try:
            file_results = _write_templates(private_workdir=private_workdir, overwrite=overwrite)
        except OSError as exc:
            file_results = [
                {
                    "key": "write_templates",
                    "filename": "-",
                    "description": "Write private M1 templates.",
                    "exists": False,
                    "action": "error",
                    "finding": exc.__class__.__name__,
                    "path_echoed": False,
                }
            ]
    else:
        file_results = _file_plan(private_workdir=private_workdir, execute=execute, overwrite=overwrite)

    gap_report = None
    if private_workdir is not None and workdir.get("status") == "passed":
        gap_report = build_m1_execution_input_gap_report(
            environ=env,
            private_workdir=private_workdir,
            m1_input_json=private_workdir / "m1-launch-inputs.local.json",
            generated_at=now,
        )
        if execute:
            try:
                file_results.extend(_write_todo_files(private_workdir=private_workdir, gap_report=gap_report))
            except OSError as exc:
                file_results.append(
                    {
                        "key": "m1_private_input_todo",
                        "filename": "-",
                        "description": "Write generated private input TODO files.",
                        "exists": False,
                        "action": "error",
                        "finding": exc.__class__.__name__,
                        "path_echoed": False,
                    }
                )
        else:
            file_results.extend(_todo_file_plan(execute=False))

    return {
        "version": M1_PRIVATE_EXECUTION_WORKSPACE_VERSION,
        "status": _status_from(workdir=workdir, file_results=file_results, execute=execute),
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "runs_live_probes": False,
            "connects_ssh": False,
            "starts_services": False,
            "deploys_code": False,
            "deletes_files": False,
            "writes_files": execute,
            "overwrites_existing_files": execute and overwrite,
            "records_public_url": False,
            "records_server_ip": False,
            "records_credentials": False,
            "path_echoed": False,
        },
        "target": {
            "private_workdir": PRIVATE_WORKDIR_PLACEHOLDER if private_workdir is not None else None,
            "private_workdir_present": private_workdir is not None,
            "private_workdir_echoed": False,
        },
        "workdir_check": workdir,
        "files": file_results,
        "post_prepare_gap_status": gap_report.get("status") if isinstance(gap_report, Mapping) else None,
        "post_prepare_missing_for_user": gap_report.get("missing_for_user") if isinstance(gap_report, Mapping) else None,
        "next_commands": [
            "uv run python scripts\\check_m1_launch_inputs.py --input-json <private-workdir>\\m1-launch-inputs.local.json --json --output <private-workdir>\\m1-launch-inputs-report.json",
            "uv run python scripts\\check_m1_execution_input_gap.py --private-workdir <private-workdir> --m1-input-json <private-workdir>\\m1-launch-inputs.local.json --markdown",
            "uv run python scripts\\run_m1_private_live_evidence_workflow.py --markdown --output-dir <private-workdir>\\m1-live-evidence-workflow --include-standard-live-probes --include-external-dependency-resilience-record --external-dependency-record-json <private-workdir>\\external-dependency-resilience-record.local.json --include-m1-rollout-execution-record --m1-rollout-record-json <private-workdir>\\m1-rollout-execution-record.local.json --include-m1-operations-review-record --m1-operations-review-json <private-workdir>\\m1-operations-review-record.local.json",
        ],
        "not_proven_by_this_preparation": [
            "Filled private inputs are complete.",
            "Real secrets are present and valid.",
            "The target server is reachable.",
            "Live probes, deployment, backup, restore, rollout, operations review or signoff have run.",
            "M1 is ready beyond controlled-trial scope.",
        ],
    }


def build_m1_private_execution_workspace_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M1 Private Execution Workspace",
        "",
        f"- Status: `{report.get('status')}`",
        "- Policy: does not read `.env`, does not run live probes, does not echo private paths.",
        "",
        "## Files",
        "",
        "| File | Action | Description |",
        "|---|---|---|",
    ]
    for item in report.get("files") or []:
        if not isinstance(item, Mapping):
            continue
        filename = str(item.get("filename") or "-").replace("|", "\\|")
        action = str(item.get("action") or "-").replace("|", "\\|")
        description = str(item.get("description") or "-").replace("|", "\\|")
        lines.append(f"| `{filename}` | `{action}` | {description} |")
    lines.extend(
        [
            "",
            "## Post-Prepare Gap",
            "",
            f"- Status: `{report.get('post_prepare_gap_status') or 'not_checked'}`",
            "",
            "## Next Commands",
            "",
        ]
    )
    for command in report.get("next_commands") or []:
        lines.extend(["```powershell", str(command), "```", ""])
    lines.extend(["## Not Proven", ""])
    for item in report.get("not_proven_by_this_preparation") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-workdir", type=_path_arg, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_private_execution_workspace_report(
        private_workdir=args.private_workdir,
        execute=args.execute,
        overwrite=args.overwrite,
    )
    output_text = (
        build_m1_private_execution_workspace_markdown(report)
        if args.markdown and not args.json
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    )
    if args.output:
        if _is_forbidden_path(args.output):
            print("Refusing to write private workspace report to a forbidden path.", file=sys.stderr)
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output.name}")
    else:
        print(output_text)
    return 0 if report["status"] in {"ready_to_prepare", "workspace_prepared"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
