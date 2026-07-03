"""Collect a redacted Docker image cleanup plan over SSH without deleting anything."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


DOCKER_DISK_CLEANUP_PLAN_VERSION = "docker_disk_cleanup_plan.v1"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
DISK_WARN_USED_PERCENT = 90
DISK_FAIL_USED_PERCENT = 98


REMOTE_PLAN_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

disk_line() {
  target="$1"
  if df -Pm "$target" >/dev/null 2>&1; then
    df -Pm "$target" 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $2 "|" $4 "|" $5 "|" $6}'
  fi
}

emit root_disk "$(disk_line /)"
if [ -n "$DEPLOY_DIR" ] && [ -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present true
  emit deploy_disk "$(disk_line "$DEPLOY_DIR")"
else
  emit deploy_dir_present false
  emit deploy_disk ""
fi

if ! command -v docker >/dev/null 2>&1; then
  emit docker_available false
  exit 0
fi

emit docker_available true
emit docker_version "$(timeout 5 docker --version 2>/dev/null || true)"
emit docker_system_df "$(timeout 20 docker system df 2>/dev/null | tr '\n' ';' || true)"

if timeout 10 docker ps -q >/tmp/zhixing-running-containers.$$ 2>/dev/null; then
  while IFS= read -r container_id; do
    [ -n "$container_id" ] || continue
    image_id="$(timeout 5 docker inspect -f '{{.Image}}' "$container_id" 2>/dev/null || true)"
    name="$(timeout 5 docker inspect -f '{{.Name}}' "$container_id" 2>/dev/null | sed 's#^/##' || true)"
    [ -n "$image_id" ] && emit running_image "$image_id|$name"
  done </tmp/zhixing-running-containers.$$
fi
rm -f /tmp/zhixing-running-containers.$$

if timeout 10 docker ps -aq >/tmp/zhixing-all-containers.$$ 2>/dev/null; then
  while IFS= read -r container_id; do
    [ -n "$container_id" ] || continue
    image_id="$(timeout 5 docker inspect -f '{{.Image}}' "$container_id" 2>/dev/null || true)"
    name="$(timeout 5 docker inspect -f '{{.Name}}' "$container_id" 2>/dev/null | sed 's#^/##' || true)"
    state="$(timeout 5 docker inspect -f '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
    [ -n "$image_id" ] && emit container_image "$image_id|$name|$state"
  done </tmp/zhixing-all-containers.$$
fi
rm -f /tmp/zhixing-all-containers.$$

if timeout 20 docker image ls -aq --no-trunc >/tmp/zhixing-images.$$ 2>/dev/null; then
  sort -u /tmp/zhixing-images.$$ | while IFS= read -r image_id; do
    [ -n "$image_id" ] || continue
    row="$(
      timeout 10 docker image inspect \
        -f '{{.Id}}|{{json .RepoTags}}|{{json .RepoDigests}}|{{.Created}}|{{.Size}}' \
        "$image_id" 2>/dev/null || true
    )"
    [ -n "$row" ] && emit image "$row"
  done
fi
rm -f /tmp/zhixing-images.$$
"""


def _run_command(
    args: Sequence[str],
    *,
    input_text: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    normalized_input = str(input_text).replace("\r\n", "\n").replace("\r", "\n")
    completed = subprocess.run(
        list(args),
        input=normalized_input.encode("utf-8"),
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


def _parse_probe_lines(stdout: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for raw_line in str(stdout or "").splitlines():
        if "\t" not in raw_line:
            continue
        key, value = raw_line.split("\t", 1)
        parsed.setdefault(key.strip(), []).append(value.strip())
    return parsed


def _first(values: Mapping[str, list[str]], key: str, default: str = "") -> str:
    items = values.get(key) or []
    return str(items[0]) if items else default


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _parse_disk_line(value: str, *, label: str) -> dict[str, Any]:
    parts = str(value or "").split("|")
    if len(parts) < 4:
        return {
            "status": "not_checked",
            "label": label,
            "summary_present": False,
            "value_echoed": False,
            "finding": "Disk summary is not available.",
        }
    total_mb, free_mb, used_percent, mount = parts[:4]
    try:
        total = int(total_mb)
        free = int(free_mb)
        used = int(used_percent)
    except ValueError:
        return {
            "status": "degraded",
            "label": label,
            "summary_present": True,
            "value_echoed": False,
            "finding": "Disk summary could not be parsed.",
        }
    status = "passed"
    finding = "Disk usage is below the cleanup warning threshold."
    if used >= DISK_FAIL_USED_PERCENT:
        status = "blocked"
        finding = "Disk usage is at or above the cleanup fail threshold."
    elif used >= DISK_WARN_USED_PERCENT:
        status = "degraded"
        finding = "Disk usage is above the cleanup warning threshold."
    return {
        "status": status,
        "label": label,
        "total_mb": total,
        "free_mb": free,
        "used_percent": used,
        "mount_present": bool(mount),
        "warn_used_percent": DISK_WARN_USED_PERCENT,
        "fail_used_percent": DISK_FAIL_USED_PERCENT,
        "value_echoed": False,
        "finding": finding,
    }


def _image_id_short(image_id: str) -> str:
    text = str(image_id or "")
    return text.replace("sha256:", "")[:12]


def _repo_tags(value: str) -> list[str]:
    payload = _safe_json_loads(value)
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if item]


def _parse_image_row(row: str) -> dict[str, Any] | None:
    parts = str(row or "").split("|", 4)
    if len(parts) != 5:
        return None
    image_id, repo_tags_raw, repo_digests_raw, created, size_text = parts
    try:
        size_bytes = int(size_text)
    except ValueError:
        size_bytes = 0
    repo_tags = _repo_tags(repo_tags_raw)
    repo_digests = _repo_tags(repo_digests_raw)
    return {
        "image_id": image_id,
        "image_id_prefix": _image_id_short(image_id),
        "repo_tags_count": len(repo_tags),
        "repo_tags_redacted": True,
        "repo_digests_count": len(repo_digests),
        "created": created,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 1) if size_bytes else 0,
        "repo_tags_echoed": False,
    }


def _container_image_map(rows: Sequence[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for row in rows:
        image_id, _, name = str(row or "").partition("|")
        if not image_id:
            continue
        mapping.setdefault(image_id, [])
        if name:
            mapping[image_id].append(name)
    return mapping


def build_docker_disk_cleanup_plan_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    max_candidates: int = 20,
    timeout_seconds: float = 90,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a read-only Docker image cleanup plan."""

    report: dict[str, Any] = {
        "version": DOCKER_DISK_CLEANUP_PLAN_VERSION,
        "status": "blocked",
        "policy": {
            "read_only": True,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_prune": False,
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "prints_secret_values": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "not_proven_by_this_plan": [
            "No Docker image has been deleted.",
            "Estimated image size can double-count shared layers.",
            "A cleanup candidate can still be operationally important; execution requires explicit approval.",
            "This plan does not inspect logs, .env files, database rows, Redis keys, volumes or vector store contents.",
        ],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [
            {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
        ]
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
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_PLAN_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_probe_timeout", "finding": "SSH read-only Docker disk plan timed out."}]
        return report
    if completed.returncode != 0:
        report["blocked_reasons"] = [{"key": "ssh_probe_failed", "finding": "SSH read-only Docker disk plan failed."}]
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        return report

    parsed = _parse_probe_lines(completed.stdout)
    root_disk = _parse_disk_line(_first(parsed, "root_disk"), label="root")
    deploy_disk = _parse_disk_line(_first(parsed, "deploy_disk"), label="deploy")
    running_images = _container_image_map(parsed.get("running_image") or [])
    container_images = _container_image_map(parsed.get("container_image") or parsed.get("running_image") or [])
    protected_image_ids = set(container_images)
    images = []
    for row in parsed.get("image") or []:
        image = _parse_image_row(row)
        if image is None:
            continue
        image_id = str(image["image_id"])
        protected = image_id in protected_image_ids
        image["protected"] = protected
        image["running_containers_count"] = len(running_images.get(image_id, []))
        image["container_references_count"] = len(container_images.get(image_id, []))
        image["cleanup_candidate"] = not protected
        if image["running_containers_count"]:
            image["reason"] = "running_container_image"
        elif protected:
            image["reason"] = "container_referenced_image"
        else:
            image["reason"] = "not_used_by_any_container"
        images.append(image)

    candidates = [image for image in images if image["cleanup_candidate"]]
    candidates.sort(key=lambda item: int(item.get("size_bytes") or 0), reverse=True)
    selected = candidates[: max(0, int(max_candidates))]
    selected_size = sum(int(item.get("size_bytes") or 0) for item in selected)
    total_candidate_size = sum(int(item.get("size_bytes") or 0) for item in candidates)
    disk_statuses = {root_disk["status"], deploy_disk["status"]}
    blocked = [status for status in disk_statuses if status == "blocked"]
    degraded = [status for status in disk_statuses if status == "degraded"]
    status = "blocked" if blocked else ("degraded" if degraded else "passed")
    risk_status = "blocked" if blocked else ("attention_required" if degraded else "ok")
    report.update(
        {
            "status": status,
            "risk_status": risk_status,
            "ssh": {
                "status": "passed",
                "docker_available": _first(parsed, "docker_available") == "true",
                "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
                "docker_version_present": bool(_first(parsed, "docker_version")),
                "docker_system_df_available": bool(_first(parsed, "docker_system_df")),
                "docker_system_df_echoed": False,
            },
            "disk": {
                "root": root_disk,
                "deploy": deploy_disk,
            },
            "images": {
                "total_count": len(images),
                "protected_count": len(images) - len(candidates),
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "estimated_candidate_size_bytes": total_candidate_size,
                "estimated_selected_size_bytes": selected_size,
                "estimated_selected_size_mb": round(selected_size / (1024 * 1024), 1) if selected_size else 0,
                "virtual_size_note": "Docker image sizes can double-count shared layers; verify disk after any approved deletion.",
            },
            "selected_candidates": selected,
            "blocked_reasons": [],
            "degraded_reasons": [],
            "approval_required": {
                "required_for_execution": True,
                "suggested_scope": f"Review selected_candidates and approve at most {len(selected)} image deletions.",
                "destructive_action_in_this_plan": False,
            },
        }
    )
    if not report["ssh"]["docker_available"]:
        report["status"] = "blocked"
        report["risk_status"] = "blocked"
        report["blocked_reasons"].append({"key": "docker_unavailable", "finding": "Docker CLI is not available on the target."})
    if root_disk["status"] == "blocked" or deploy_disk["status"] == "blocked":
        report["blocked_reasons"].append({"key": "disk_usage_fail_threshold", "finding": "Disk usage is at or above fail threshold."})
    elif root_disk["status"] == "degraded" or deploy_disk["status"] == "degraded":
        report["degraded_reasons"].append({"key": "disk_usage_warning_threshold", "finding": "Disk usage is above warning threshold."})
    return report


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("|", "\\|")
    return text or "-"


def build_docker_disk_cleanup_plan_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Docker Disk Cleanup Plan",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Risk: `{report.get('risk_status')}`",
        "- Policy: read-only, no image/container/volume deletion, no prune.",
        "",
        "## Disk",
        "",
        "| Target | Status | Used | Free MB | Finding |",
        "|---|---|---:|---:|---|",
    ]
    for key, item in (report.get("disk") or {}).items():
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(key)} | "
            f"{_markdown_cell(item.get('status'))} | "
            f"{_markdown_cell(item.get('used_percent'))}% | "
            f"{_markdown_cell(item.get('free_mb'))} | "
            f"{_markdown_cell(item.get('finding'))} |"
        )
    images = report.get("images") or {}
    lines.extend(
        [
            "",
            "## Image Candidates",
            "",
            f"- Total images: `{images.get('total_count', 0)}`",
            f"- Protected container images: `{images.get('protected_count', 0)}`",
            f"- Cleanup candidates: `{images.get('candidate_count', 0)}`",
            f"- Selected candidates: `{images.get('selected_count', 0)}`",
            f"- Estimated selected size: `{images.get('estimated_selected_size_mb', 0)} MB`",
            "",
            "| Image | Size MB | Repo Tags | Reason |",
            "|---|---:|---|---|",
        ]
    )
    for item in report.get("selected_candidates") or []:
        if not isinstance(item, Mapping):
            continue
        tag_count = item.get("repo_tags_count", 0)
        tags = f"<redacted:{tag_count}>"
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('image_id_prefix'))}` | "
            f"{_markdown_cell(item.get('size_mb'))} | "
            f"{_markdown_cell(tags)} | "
            f"{_markdown_cell(item.get('reason'))} |"
        )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_plan") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target, e.g. user@host. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    args = parser.parse_args(argv)

    report = build_docker_disk_cleanup_plan_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        max_candidates=args.max_candidates,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_docker_disk_cleanup_plan_markdown(report)
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
