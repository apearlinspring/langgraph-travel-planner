"""Prepare or start a production image build as a remote background job.

Dry-run mode is the default and does not connect SSH or run Docker. Real
execution requires ``--execute`` and an explicit approval token. Starting a
background job is not treated as build success; fill and validate a private
``check_production_image_build_execution_record.py`` record after completion.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._remote_probe_helpers import (  # noqa: E402
    first_value as _first,
    parse_tabbed_probe_lines as _parse_probe_lines,
)


PRODUCTION_IMAGE_BUILD_EXECUTION_PREP_VERSION = "production_image_build_execution_prep.v1"
APPROVAL_TOKEN = "APPROVE_PRODUCTION_IMAGE_BUILD_EXECUTION"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
PRIVATE_PATH_PLACEHOLDER = "<private-server-build-record-path>"
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{6,96}$")


REMOTE_START_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"
BUILD_ID="$2"
RELEASE_LABEL="$3"
BUILD_TIMEOUT_SECONDS="$4"

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

if [ ! -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present false
  exit 0
fi
emit deploy_dir_present true

if [ ! -d "$DEPLOY_DIR/current" ]; then
  emit current_release_present false
  exit 0
fi
emit current_release_present true

if [ ! -f "$DEPLOY_DIR/current/deploy/update-runtime-image.sh" ]; then
  emit update_script_present false
  exit 0
fi
emit update_script_present true

if [ ! -f "$DEPLOY_DIR/current/requirements.runtime.txt" ]; then
  emit runtime_requirements_present false
  exit 0
fi
emit runtime_requirements_present true

if ! command -v docker >/dev/null 2>&1; then
  emit docker_available false
  exit 0
fi
emit docker_available true

mkdir -p "$DEPLOY_DIR/shared/build-records"
BUILD_DIR="$DEPLOY_DIR/shared/build-records/$BUILD_ID"
if [ -e "$BUILD_DIR" ]; then
  emit build_dir_available false
  exit 0
fi
mkdir -p "$BUILD_DIR"
chmod 700 "$BUILD_DIR" 2>/dev/null || true
LOG_FILE="$BUILD_DIR/build.log"
RECORD_FILE="$BUILD_DIR/execution.tsv"

(
  emit build_id "$BUILD_ID"
  emit release_label_present "$( [ -n "$RELEASE_LABEL" ] && echo true || echo false )"
  emit started_at "$(date -Iseconds 2>/dev/null || date)"
  emit wrapper nohup
  emit timeout_seconds "$BUILD_TIMEOUT_SECONDS"
  emit pip_index_url_configured "$( [ -n "${PIP_INDEX_URL:-}" ] && echo true || echo default )"
  emit pip_trusted_host_configured "$( [ -n "${PIP_TRUSTED_HOST:-}" ] && echo true || echo default )"
  cd "$DEPLOY_DIR/current"
  emit runtime_dependency_scope_start true
  if python scripts/check_runtime_dependency_scope.py --json >/dev/null 2>&1; then
    emit runtime_dependency_scope_passed true
  else
    emit runtime_dependency_scope_passed false
  fi
  image_before="$(docker image inspect -f '{{.Id}}' langgraph-travel-planner-backend:latest 2>/dev/null || true)"
  size_before="$(docker image inspect -f '{{.Size}}' langgraph-travel-planner-backend:latest 2>/dev/null || true)"
  emit image_id_before_present "$( [ -n "$image_before" ] && echo true || echo false )"
  emit image_size_before_present "$( [ -n "$size_before" ] && echo true || echo false )"
  start_epoch="$(date +%s)"
  if timeout "$BUILD_TIMEOUT_SECONDS" sh deploy/update-runtime-image.sh >>"$LOG_FILE" 2>&1; then
    emit build_result passed
    exit_code=0
  else
    exit_code="$?"
    emit build_result failed
  fi
  end_epoch="$(date +%s)"
  emit exit_code "$exit_code"
  emit ended_at "$(date -Iseconds 2>/dev/null || date)"
  emit duration_seconds "$((end_epoch - start_epoch))"
  image_after="$(docker image inspect -f '{{.Id}}' langgraph-travel-planner-backend:latest 2>/dev/null || true)"
  size_after="$(docker image inspect -f '{{.Size}}' langgraph-travel-planner-backend:latest 2>/dev/null || true)"
  emit image_id_after_present "$( [ -n "$image_after" ] && echo true || echo false )"
  emit image_changed "$( [ -n "$image_before" ] && [ -n "$image_after" ] && [ "$image_before" != "$image_after" ] && echo true || echo false )"
  emit image_size_after_present "$( [ -n "$size_after" ] && echo true || echo false )"
  emit image_size_after_bytes "$size_after"
  if docker compose ps >/dev/null 2>&1; then
    emit compose_ps_status passed
  else
    emit compose_ps_status blocked
  fi
  if curl -fsS --max-time 10 http://localhost:${APP_PORT:-8000}/health/live >/dev/null 2>&1; then
    emit health_live_status passed
  else
    emit health_live_status blocked
  fi
  if curl -fsS --max-time 15 http://localhost:${APP_PORT:-8000}/health/ready >/dev/null 2>&1; then
    emit health_ready_status passed
  else
    emit health_ready_status blocked
  fi
  emit log_file_recorded true
  emit record_file_recorded true
) >"$RECORD_FILE" 2>&1 &
pid="$!"

emit background_job_started true
emit pid_recorded true
emit log_file_recorded true
emit record_file_recorded true
emit record_path "$RECORD_FILE"
emit log_path "$LOG_FILE"
emit pid "$pid"
"""


def _run_command(
    args: Sequence[str],
    *,
    input_text: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        input=str(input_text).encode("utf-8"),
        capture_output=True,
        text=False,
        timeout=timeout_seconds,
        check=False,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        stdout=completed.stdout.decode("utf-8", "replace"),
        stderr=completed.stderr.decode("utf-8", "replace"),
    )


def _default_build_id() -> str:
    return "zhixing-image-build-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _target_summary(ssh_target: str, deploy_dir: str) -> dict[str, str]:
    return {
        "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
        "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
    }


def build_production_image_build_execution_prep_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    build_id: str | None = None,
    release_label: str = "",
    build_timeout_seconds: int = 1800,
    execute: bool = False,
    approval_token: str = "",
    timeout_seconds: float = 60,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a dry-run plan or start a remote background image build."""

    normalized_build_id = build_id or _default_build_id()
    report: dict[str, Any] = {
        "version": PRODUCTION_IMAGE_BUILD_EXECUTION_PREP_VERSION,
        "status": "blocked",
        "mode": "execute" if execute else "dry_run",
        "target": _target_summary(ssh_target, deploy_dir),
        "build": {
            "build_id_present": bool(normalized_build_id),
            "release_label_present": bool(str(release_label or "").strip()),
            "build_timeout_seconds": build_timeout_seconds,
        },
        "policy": {
            "reads_dotenv": False,
            "prints_secret_values": False,
            "connects_ssh": bool(execute),
            "runs_docker": bool(execute),
            "starts_services": bool(execute),
            "deletes_docker_resources": False,
            "runs_system_prune": False,
            "reads_runtime_dirs": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "private_paths_echoed": False,
            "requires_execute_flag": True,
            "requires_approval_token": True,
        },
        "approval": {
            "execute_requested": bool(execute),
            "approval_token_accepted": bool(execute and approval_token == APPROVAL_TOKEN),
            "approval_token_echoed": False,
        },
        "execution_record": {
            "required_validator": "scripts/check_production_image_build_execution_record.py",
            "record_path": PRIVATE_PATH_PLACEHOLDER,
            "log_path": PRIVATE_PATH_PLACEHOLDER,
            "record_path_echoed": False,
            "log_path_echoed": False,
        },
        "not_proven_by_this_report": [
            "Dry-run mode does not connect SSH, run Docker, start services or build an image.",
            "Execute mode only starts a background build job; it does not prove the build completed.",
            "A private execution record must still be filled and validated after the background job finishes.",
            "This report does not prove vulnerability status, long-duration stability, real payment, booking, inventory lock or fulfillment.",
        ],
    }

    blocked: list[dict[str, Any]] = []
    if not ssh_target or not deploy_dir:
        blocked.append({"key": "missing_target", "finding": "SSH target and deploy directory are required."})
    if not SAFE_ID_PATTERN.match(normalized_build_id):
        blocked.append({"key": "invalid_build_id", "finding": "Build id must be 6-96 safe filename characters."})
    if build_timeout_seconds < 900:
        blocked.append({"key": "timeout_too_short", "finding": "Remote build timeout must be at least 900 seconds."})
    if execute and approval_token != APPROVAL_TOKEN:
        blocked.append({"key": "missing_approval", "finding": "Execution requires the explicit production image build approval token."})
    if blocked:
        report["blocked_reasons"] = blocked
        return report

    if not execute:
        report.update(
            {
                "status": "ready_for_explicit_approval",
                "blocked_reasons": [],
                "plan": {
                    "uses_remote_background_wrapper": True,
                    "wrapper": "nohup",
                    "runs_update_runtime_image_script": True,
                    "runs_runtime_dependency_scope_gate_first": True,
                    "records_pid": True,
                    "records_redacted_log_path": True,
                    "records_private_execution_tsv": True,
                    "checks_compose_ps": True,
                    "checks_health_live": True,
                    "checks_health_ready": True,
                },
            }
        )
        return report

    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        ssh_target,
        "bash",
        "-s",
        "--",
        deploy_dir,
        normalized_build_id,
        release_label,
        str(build_timeout_seconds),
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_START_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_start_timeout", "finding": "SSH background build start timed out."}]
        return report
    if completed.returncode != 0:
        report["blocked_reasons"] = [{"key": "ssh_start_failed", "finding": "SSH background build start failed."}]
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line_present": bool(str(completed.stderr or "").splitlines()[:1]),
            "stderr_value_echoed": False,
        }
        return report

    parsed = _parse_probe_lines(completed.stdout)
    missing_remote = []
    for key in (
        "deploy_dir_present",
        "current_release_present",
        "update_script_present",
        "runtime_requirements_present",
        "docker_available",
    ):
        if _first(parsed, key) != "true":
            missing_remote.append(key)
    if _first(parsed, "build_dir_available", "true") == "false":
        missing_remote.append("build_dir_available")
    if _first(parsed, "background_job_started") != "true":
        missing_remote.append("background_job_started")
    if missing_remote:
        report["blocked_reasons"] = [
            {"key": "remote_precheck_failed", "finding": "Remote build precheck failed.", "missing": missing_remote}
        ]
        report["remote_precheck"] = {
            "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
            "current_release_present": _first(parsed, "current_release_present") == "true",
            "update_script_present": _first(parsed, "update_script_present") == "true",
            "runtime_requirements_present": _first(parsed, "runtime_requirements_present") == "true",
            "docker_available": _first(parsed, "docker_available") == "true",
        }
        return report

    report.update(
        {
            "status": "background_job_started",
            "blocked_reasons": [],
            "remote_precheck": {
                "deploy_dir_present": True,
                "current_release_present": True,
                "update_script_present": True,
                "runtime_requirements_present": True,
                "docker_available": True,
            },
            "background_job": {
                "started": True,
                "pid_recorded": _first(parsed, "pid_recorded") == "true",
                "log_file_recorded": _first(parsed, "log_file_recorded") == "true",
                "record_file_recorded": _first(parsed, "record_file_recorded") == "true",
                "pid_echoed": False,
                "log_path_echoed": False,
                "record_path_echoed": False,
            },
        }
    )
    return report


def build_production_image_build_execution_prep_markdown(report: Mapping[str, Any]) -> str:
    policy = report.get("policy") if isinstance(report.get("policy"), Mapping) else {}
    plan = report.get("plan") if isinstance(report.get("plan"), Mapping) else {}
    job = report.get("background_job") if isinstance(report.get("background_job"), Mapping) else {}
    lines = [
        "# Production Image Build Execution Prep",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Connects SSH: `{policy.get('connects_ssh')}`",
        f"- Runs Docker: `{policy.get('runs_docker')}`",
        f"- Starts services: `{policy.get('starts_services')}`",
        f"- Runs system prune: `{policy.get('runs_system_prune')}`",
        "",
        "## Plan",
        "",
        f"- Uses background wrapper: `{plan.get('uses_remote_background_wrapper', job.get('started'))}`",
        f"- Records PID: `{plan.get('records_pid', job.get('pid_recorded'))}`",
        f"- Records log path: `{plan.get('records_redacted_log_path', job.get('log_file_recorded'))}`",
        f"- Records execution TSV: `{plan.get('records_private_execution_tsv', job.get('record_file_recorded'))}`",
        f"- Health live check planned: `{plan.get('checks_health_live')}`",
        f"- Health ready check planned: `{plan.get('checks_health_ready')}`",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--build-id", default=None, help="Safe build id used for private remote record files.")
    parser.add_argument("--release-label", default="", help="Release label. Presence is recorded, value is redacted.")
    parser.add_argument("--build-timeout-seconds", type=int, default=1800)
    parser.add_argument("--execute", action="store_true", help="Start the remote background build job.")
    parser.add_argument("--approval-token", default="", help="Required with --execute. Value is never echoed.")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_production_image_build_execution_prep_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        build_id=args.build_id,
        release_label=args.release_label,
        build_timeout_seconds=args.build_timeout_seconds,
        execute=args.execute,
        approval_token=args.approval_token,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_production_image_build_execution_prep_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
