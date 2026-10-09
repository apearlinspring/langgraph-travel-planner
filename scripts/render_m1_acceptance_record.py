"""Render a redacted M1 acceptance record from gate or go/no-go evidence."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_deployment_gate import (  # noqa: E402
    DEFAULT_BASE_URL,
    build_m1_deployment_gate_report,
)
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


M1_ACCEPTANCE_RECORD_VERSION = "m1_acceptance_record.v1"
MAX_BLOCKERS = 20
BLOCKING_SECTION_STATUSES = {"blocked", "failed", "unknown", "skipped", "not_checked", "missing"}


def _run_git(args: Sequence[str]) -> str:
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


def _load_gate_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read M1 gate JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"M1 gate JSON must be an object: {path}")
    redacted = redact_data(payload)
    return redacted if isinstance(redacted, dict) else {}


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read {label} JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    redacted = redact_data(payload)
    return redacted if isinstance(redacted, dict) else {}


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _short_reason(item: Mapping[str, Any]) -> str:
    reason = item.get("reason") or item.get("finding") or item.get("status") or "blocked"
    return _markdown_cell(reason)


def _section_statuses(gate_report: Mapping[str, Any]) -> dict[str, str]:
    raw = gate_report.get("section_statuses")
    if isinstance(raw, Mapping):
        return {str(key): str(value) for key, value in raw.items()}
    sections = gate_report.get("sections")
    if isinstance(sections, Mapping):
        return {
            str(key): str((value or {}).get("status") if isinstance(value, Mapping) else "unknown")
            for key, value in sections.items()
        }
    return {}


def _m1_input_statuses(gate_report: Mapping[str, Any]) -> dict[str, Any]:
    sections = gate_report.get("sections")
    if not isinstance(sections, Mapping):
        return {}
    inputs = sections.get("m1_launch_inputs")
    return inputs if isinstance(inputs, dict) else {}


def _runtime_statuses(gate_report: Mapping[str, Any]) -> dict[str, Any]:
    sections = gate_report.get("sections")
    if not isinstance(sections, Mapping):
        return {}
    runtime = sections.get("runtime_readiness")
    return runtime if isinstance(runtime, dict) else {}


def _status_counts_table(gate_report: Mapping[str, Any]) -> list[str]:
    rows = ["| Section | Status |", "|---|---|"]
    statuses = _section_statuses(gate_report)
    if not statuses:
        rows.append("| - | missing |")
        return rows
    for section, status in sorted(statuses.items()):
        rows.append(f"| {_markdown_cell(section)} | {_markdown_cell(status)} |")
    return rows


def _input_category_table(gate_report: Mapping[str, Any]) -> list[str]:
    inputs = _m1_input_statuses(gate_report)
    category_statuses = inputs.get("category_statuses")
    rows = ["| Category | Status |", "|---|---|"]
    if not isinstance(category_statuses, Mapping):
        rows.append("| - | not_available |")
        return rows
    for category, status in sorted(category_statuses.items()):
        rows.append(f"| {_markdown_cell(category)} | {_markdown_cell(status)} |")
    return rows


def _runtime_table(gate_report: Mapping[str, Any]) -> list[str]:
    runtime = _runtime_statuses(gate_report)
    target_statuses = runtime.get("target_statuses")
    rows = ["| Target | Status |", "|---|---|"]
    if not isinstance(target_statuses, Mapping):
        status = runtime.get("status") or "not_available"
        rows.append(f"| runtime_readiness | {_markdown_cell(status)} |")
        return rows
    for target, status in sorted(target_statuses.items()):
        rows.append(f"| {_markdown_cell(target)} | {_markdown_cell(status)} |")
    return rows


def _blocker_table(gate_report: Mapping[str, Any]) -> list[str]:
    blockers = gate_report.get("blocked_reasons")
    rows = ["| Section | Key / Env Var | Reason |", "|---|---|---|"]
    if not isinstance(blockers, list) or not blockers:
        rows.append("| - | - | - |")
        return rows
    for item in blockers[:MAX_BLOCKERS]:
        if not isinstance(item, Mapping):
            continue
        section = item.get("section") or item.get("target") or "-"
        key = item.get("env_var") or item.get("key") or item.get("label") or "-"
        rows.append(
            "| "
            f"{_markdown_cell(section)} | "
            f"{_markdown_cell(key)} | "
            f"{_short_reason(item)} |"
        )
    if len(blockers) > MAX_BLOCKERS:
        rows.append(f"| more | {len(blockers) - MAX_BLOCKERS} omitted | See gate JSON summary |")
    return rows


def _reason_table(report: Mapping[str, Any], key: str, *, empty_label: str) -> list[str]:
    rows = ["| Section | Key / Target | Reason |", "|---|---|---|"]
    items = report.get(key)
    if not isinstance(items, list) or not items:
        if key == "blocked_reasons":
            bad_sections = [
                (section, status)
                for section, status in sorted(_section_statuses(report).items())
                if status in BLOCKING_SECTION_STATUSES
            ]
            if bad_sections:
                for section, status in bad_sections[:MAX_BLOCKERS]:
                    rows.append(
                        "| "
                        f"{_markdown_cell(section)} | "
                        f"{_markdown_cell(section)} | "
                        f"Section status is {_markdown_cell(status)}. |"
                    )
                if len(bad_sections) > MAX_BLOCKERS:
                    rows.append(f"| more | {len(bad_sections) - MAX_BLOCKERS} omitted | See source JSON summary |")
                return rows
        rows.append(f"| - | - | {_markdown_cell(empty_label)} |")
        return rows
    for item in items[:MAX_BLOCKERS]:
        if not isinstance(item, Mapping):
            continue
        section = item.get("section") or item.get("target") or "-"
        reason_key = item.get("env_var") or item.get("key") or item.get("target") or item.get("label") or "-"
        rows.append(
            "| "
            f"{_markdown_cell(section)} | "
            f"{_markdown_cell(reason_key)} | "
            f"{_short_reason(item)} |"
        )
    if len(items) > MAX_BLOCKERS:
        rows.append(f"| more | {len(items) - MAX_BLOCKERS} omitted | See source JSON summary |")
    return rows


def _final_status(gate_report: Mapping[str, Any]) -> str:
    status = str(gate_report.get("status") or "not_run")
    if status == "passed":
        return "passed"
    if status == "degraded":
        return "degraded"
    return "blocked"


def _trial_status_from_go_no_go(report: Mapping[str, Any]) -> str:
    status = str(report.get("status") or "not_run")
    decision = str(report.get("decision") or "")
    if status == "passed":
        return "passed"
    if status == "degraded" or decision == "conditional_go":
        return "degraded"
    return "blocked"


def build_m1_go_no_go_acceptance_record_markdown(
    go_no_go_report: Mapping[str, Any],
    *,
    record_id: str | None = None,
    environment: str = "staging",
    generated_at: datetime | None = None,
    source: str = "go_no_go_json",
) -> str:
    """Build a redacted Markdown record from M1 go/no-go evidence."""

    safe_report = redact_data(dict(go_no_go_report))
    if not isinstance(safe_report, dict):
        safe_report = {}
    now = generated_at or datetime.now(UTC)
    resolved_record_id = record_id or f"m1-{now.strftime('%Y%m%d%H%M%S')}"
    release_commit = _run_git(["rev-parse", "--short", "HEAD"])
    final_status = _trial_status_from_go_no_go(safe_report)

    lines = [
        "# M1 Acceptance Record（受控试运行验收记录）",
        "",
        "## 1. 基本信息",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Record version | `{M1_ACCEPTANCE_RECORD_VERSION}` |",
        f"| Record ID | `{_markdown_cell(resolved_record_id)}` |",
        f"| Generated at | `{_markdown_cell(now.isoformat())}` |",
        f"| Source | `{_markdown_cell(source)}` |",
        f"| Environment | `{_markdown_cell(environment)}` |",
        f"| Release commit | `{_markdown_cell(release_commit)}` |",
        f"| Evidence status | `{_markdown_cell(safe_report.get('status') or 'missing')}` |",
        f"| Go/no-go decision | `{_markdown_cell(safe_report.get('decision') or 'missing')}` |",
        f"| M1 trial status | `{_markdown_cell(final_status)}` |",
        "| Can claim production-ready | `no` |",
        "",
        "## 2. Evidence Section 状态",
        "",
        *_status_counts_table(safe_report),
        "",
        "## 3. 阻塞项摘要",
        "",
        *_reason_table(safe_report, "blocked_reasons", empty_label="No blocker recorded."),
        "",
        "## 4. 条件放行 / 降级项",
        "",
        *_reason_table(safe_report, "degraded_reasons", empty_label="No degraded item recorded."),
        "",
        "## 5. 本记录不能证明的事项",
        "",
    ]
    not_proven = (
        safe_report.get("not_proven_by_this_run")
        or safe_report.get("not_proven_by_this_report")
        or safe_report.get("not_proven_by_this_gate")
    )
    if isinstance(not_proven, list) and not_proven:
        lines.extend(f"- {_markdown_cell(item)}" for item in not_proven)
    else:
        lines.extend(
            [
                "- 这是 M1 受控试运行验收记录，不等价于完整生产高可用认证。",
                "- 不证明 PostgreSQL/Redis 已具备多节点 HA、自动故障切换或跨可用区容灾。",
                "- 不证明真实支付、真实预订、锁价、出票或履约已经开放。",
                "- 不证明长期压测、容量模型、SLO 和 on-call 体系已经完成。",
            ]
        )
    lines.extend(
        [
            "",
            "## 6. 脱敏边界",
            "",
            "- 本记录只保留状态、section、阻塞原因、降级原因和下一步方向。",
            "- 不写 `.env`、真实密钥、账号口令、连接串、日志原文、数据库备份、向量库文件或客户资料。",
            "- 若 evidence status 是 `degraded`，M1 结论只能写条件放行，不能写完整生产可用。",
            "",
        ]
    )
    return redact_text("\n".join(lines))


def _acceptance_exit_code(status: Any) -> int:
    return 0 if str(status) in {"passed", "degraded"} else 2


def build_m1_acceptance_record_markdown(
    gate_report: Mapping[str, Any],
    *,
    record_id: str | None = None,
    environment: str = "staging",
    generated_at: datetime | None = None,
    source: str = "live_gate",
) -> str:
    """Build a redacted Markdown record from an M1 deployment gate report."""

    safe_gate = redact_data(dict(gate_report))
    if not isinstance(safe_gate, dict):
        safe_gate = {}
    now = generated_at or datetime.now(UTC)
    resolved_record_id = record_id or f"m1-{now.strftime('%Y%m%d%H%M%S')}"
    release_commit = _run_git(["rev-parse", "--short", "HEAD"])
    section_statuses = _section_statuses(safe_gate)
    inputs = _m1_input_statuses(safe_gate)
    runtime = _runtime_statuses(safe_gate)
    final_status = _final_status(safe_gate)

    lines = [
        "# M1 Acceptance Record（受控试运行验收记录）",
        "",
        "## 1. 基本信息",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Record version | `{M1_ACCEPTANCE_RECORD_VERSION}` |",
        f"| Record ID | `{_markdown_cell(resolved_record_id)}` |",
        f"| Generated at | `{_markdown_cell(now.isoformat())}` |",
        f"| Source | `{_markdown_cell(source)}` |",
        f"| Environment | `{_markdown_cell(environment)}` |",
        f"| Release commit | `{_markdown_cell(release_commit)}` |",
        f"| Gate status | `{_markdown_cell(safe_gate.get('status') or 'missing')}` |",
        f"| M1 trial status | `{_markdown_cell(final_status)}` |",
        "| Can claim production-ready | `no` |",
        "",
        "## 2. Section 状态",
        "",
        *_status_counts_table(safe_gate),
        "",
        "## 3. M1 非密钥输入",
        "",
        f"- 输入项数量: {_markdown_cell(inputs.get('input_count'))}",
        f"- 通过数量: {_markdown_cell(inputs.get('passed_count'))}",
        f"- 阻塞数量: {_markdown_cell(inputs.get('blocked_count'))}",
        "",
        *_input_category_table(safe_gate),
        "",
        "## 4. Runtime readiness",
        "",
        f"- Runtime gate status: `{_markdown_cell(runtime.get('status') or 'not_available')}`",
        f"- `.env` loaded by M1 gate: `{_markdown_cell((safe_gate.get('policy') or {}).get('reads_dotenv'))}`",
        "",
        *_runtime_table(safe_gate),
        "",
        "## 5. 阻塞项摘要",
        "",
        *_blocker_table(safe_gate),
        "",
        "## 6. 本记录不能证明的事项",
        "",
    ]
    not_proven = safe_gate.get("not_proven_by_this_gate")
    if isinstance(not_proven, list) and not_proven:
        lines.extend(f"- {_markdown_cell(item)}" for item in not_proven)
    else:
        lines.extend(
            [
                "- 真实服务器已经部署当前 release。",
                "- 真实密钥在供应商侧可用。",
                "- PostgreSQL 备份和恢复演练已经执行。",
                "- acceptance smoke 已经对目标 URL 通过。",
                "- 可以开放真实支付、预订、锁价、出票或履约。",
            ]
        )
    lines.extend(
        [
            "",
            "## 7. 脱敏边界",
            "",
            "- 本记录只保留状态、变量名、section、阻塞原因和下一步方向。",
            "- 不写 `.env`、真实密钥、账号口令、连接串、日志原文、数据库备份、向量库文件或客户资料。",
            "- 若 gate status 不是 `passed`，M1 结论只能写 `blocked` 或 `degraded`，不能写生产可用。",
            "",
        ]
    )
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-json", type=_path_arg, default=None, help="Optional existing M1 deployment gate JSON.")
    parser.add_argument("--go-no-go-json", type=_path_arg, default=None, help="Optional existing M1 go/no-go JSON.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional Markdown output path. Defaults to stdout.")
    parser.add_argument("--record-id", default=None, help="Optional record id.")
    parser.add_argument("--environment", default="staging", help="Environment label for the record.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL when running the gate.")
    parser.add_argument("--include-acceptance", action="store_true", help="Include acceptance preflight when running the gate.")
    parser.add_argument("--check-backend", action="store_true", help="Probe backend readiness when running the gate.")
    parser.add_argument("--skip-rag-mixed-corpus-safety", action="store_true", help="Skip mixed-corpus safety in runtime readiness.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.gate_json is not None and args.go_no_go_json is not None:
        raise ValueError("Use only one of --gate-json or --go-no-go-json.")
    if args.go_no_go_json is not None:
        go_no_go_report = _load_json_object(args.go_no_go_json, label="M1 go/no-go")
        source = f"go_no_go_json:{args.go_no_go_json.name}"
        markdown = build_m1_go_no_go_acceptance_record_markdown(
            go_no_go_report,
            record_id=args.record_id,
            environment=args.environment,
            source=source,
        )
        status = go_no_go_report.get("status")
    elif args.gate_json is not None:
        gate_report = _load_gate_json(args.gate_json)
        source = f"gate_json:{args.gate_json.name}"
        markdown = build_m1_acceptance_record_markdown(
            gate_report,
            record_id=args.record_id,
            environment=args.environment,
            source=source,
        )
        status = gate_report.get("status")
    else:
        gate_report = build_m1_deployment_gate_report(
            base_url=args.base_url,
            include_acceptance=args.include_acceptance,
            check_backend=args.check_backend,
            check_rag_mixed_corpus_safety=not args.skip_rag_mixed_corpus_safety,
        )
        source = "live_gate"
        markdown = build_m1_acceptance_record_markdown(
            gate_report,
            record_id=args.record_id,
            environment=args.environment,
            source=source,
        )
        status = gate_report.get("status")
    if args.output is None:
        print(markdown)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.output}")
    return _acceptance_exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
