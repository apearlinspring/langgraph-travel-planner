"""Export a redacted, commit-safe acceptance-core evidence pack."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / ".runtime"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "docs" / "acceptance-core-report.md"
ACCEPTANCE_SUMMARY_VERSION = "acceptance_run_summary.v1"
REDACTED_VALUE = "[REDACTED]"

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.+-])",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
BEARER_PATTERN = re.compile(
    r"(?i)\b(?:bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}"
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"authorization|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"
)
API_KEY_PATTERN = re.compile(
    r"\b(?:sk|rk|pk|ak|dashscope|amap|tavily)[-_][A-Za-z0-9][A-Za-z0-9_-]{10,}\b",
    re.IGNORECASE,
)
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "email",
    "id_card",
    "identity",
    "mobile",
    "passport",
    "password",
    "phone",
    "secret",
    "token",
    "身份证",
    "手机号",
    "护照",
    "邮箱",
    "电话",
)

STATUS_LABELS = {
    "passed": "passed（通过）",
    "failed": "failed（失败）",
    "degraded": "degraded（降级）",
    "blocked": "blocked（环境阻塞）",
    "skipped": "skipped（跳过）",
    "pending": "pending（待运行）",
    "missing": "missing（缺失）",
    "missing_summary": "missing_summary（缺少摘要）",
}

EVIDENCE_CHECK_LABELS = {
    "snapshot": "快照",
    "report_data": "结构化报告",
    "budget": "预算",
    "budget_confidence": "预算置信度",
    "risk": "风险",
    "verification_items": "待核验项",
    "agency_business_evidence": "旅行社业务证据",
}


@dataclass(frozen=True)
class EvidenceExportResult:
    """Result metadata for one evidence-pack export."""

    output_path: Path
    summary_path: Path | None
    status: str
    missing_summary: bool


def redact_text(text: str) -> str:
    """Redact common credential and PII-shaped substrings from text."""

    redacted = str(text)
    redacted = SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED_VALUE}",
        redacted,
    )
    for pattern in (
        BEARER_PATTERN,
        JWT_PATTERN,
        API_KEY_PATTERN,
        EMAIL_PATTERN,
        PHONE_PATTERN,
    ):
        redacted = pattern.sub(REDACTED_VALUE, redacted)
    return redacted


def is_sensitive_key(key: object) -> bool:
    normalized = str(key or "").lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_data(value: Any, *, max_depth: int = 12) -> Any:
    """Recursively redact sensitive values while preserving useful metrics."""

    if max_depth < 0:
        return REDACTED_VALUE
    if isinstance(value, dict):
        return {
            str(key): (
                REDACTED_VALUE
                if is_sensitive_key(key) and isinstance(item, str)
                else redact_data(item, max_depth=max_depth - 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_data(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item, max_depth=max_depth - 1) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return int(value) if isinstance(value, int) else None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_acceptance_summary(payload: dict[str, Any]) -> bool:
    if payload.get("version") == ACCEPTANCE_SUMMARY_VERSION:
        return True
    return all(key in payload for key in ("selected_scenarios", "results", "status_counts"))


def find_latest_acceptance_summary(runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> Path | None:
    """Return the newest acceptance summary JSON under a runtime directory."""

    root = runtime_dir
    if not root.exists():
        return None
    candidates: list[tuple[float, str, Path]] = []
    for path in root.rglob("*.json"):
        payload = _read_json(path)
        if payload is None or not _is_acceptance_summary(payload):
            continue
        candidates.append((path.stat().st_mtime, path.name, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def load_acceptance_summary(path: Path) -> dict[str, Any]:
    """Load and redact one acceptance summary file."""

    payload = _read_json(path)
    if payload is None:
        raise ValueError(f"Cannot read acceptance summary JSON: {path}")
    if not _is_acceptance_summary(payload):
        raise ValueError(f"JSON file is not an acceptance summary: {path}")
    redacted = redact_data(payload)
    return redacted if isinstance(redacted, dict) else {}


def _status_label(status: Any) -> str:
    key = str(status or "missing").strip()
    return STATUS_LABELS.get(key, key)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _format_seconds(value: Any) -> str:
    number = _as_number(value)
    if number is None:
        return "-"
    return f"{number:.3f}s"


def _format_int(value: Any) -> str:
    number = _as_int(value)
    return str(number) if number is not None else "-"


def _format_bool_status(value: Any) -> str:
    if value is True:
        return STATUS_LABELS["passed"]
    if value is False:
        return STATUS_LABELS["failed"]
    return "-"


def _selected_scenario_records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    selected = [
        item
        for item in _as_list(summary.get("selected_scenarios"))
        if isinstance(item, dict)
    ]
    if selected:
        return selected
    return [
        {
            "id": result.get("scenario_id"),
            "name": result.get("scenario_name"),
            "expected_mode": _as_dict(result.get("acceptance_gate")).get("expected_mode"),
        }
        for result in _as_list(summary.get("results"))
        if isinstance(result, dict) and result.get("scenario_id")
    ]


def _result_by_scenario_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for result in _as_list(summary.get("results")):
        if not isinstance(result, dict):
            continue
        scenario_id = result.get("scenario_id")
        if isinstance(scenario_id, str) and scenario_id:
            results[scenario_id] = result
    return results


def _result_status(result: dict[str, Any] | None) -> str:
    if not result:
        return "pending"
    gate = _as_dict(result.get("acceptance_gate"))
    status = result.get("status") or gate.get("status")
    if status:
        return str(status)
    return "passed" if result.get("passed") is True else "failed"


def _runtime_metrics(result: dict[str, Any]) -> dict[str, Any]:
    metrics = _as_dict(result.get("runtime_metrics"))
    if metrics:
        return metrics
    quality_summary = _as_dict(result.get("quality_summary"))
    return _as_dict(quality_summary.get("runtime_metrics"))


def _first_token_seconds(result: dict[str, Any]) -> float | None:
    direct = _as_number(result.get("first_token_seconds"))
    if direct is not None:
        return direct
    return _as_number(_runtime_metrics(result).get("first_token_seconds"))


def _tool_call_count(result: dict[str, Any]) -> int | None:
    direct = _as_int(result.get("tool_call_count"))
    if direct is not None:
        return direct
    metrics_count = _as_int(_runtime_metrics(result).get("tool_call_count"))
    if metrics_count is not None:
        return metrics_count
    tool_counts = _as_dict(result.get("tool_counts"))
    counts = [_as_int(count) for count in tool_counts.values()]
    known_counts = [count for count in counts if count is not None]
    if known_counts:
        return sum(known_counts)
    return None


def _runtime_budget_status(result: dict[str, Any] | None) -> str:
    if not result:
        return STATUS_LABELS["pending"]
    if result.get("runtime_budget_passed") is not None:
        return _format_bool_status(result.get("runtime_budget_passed"))
    gate = _as_dict(result.get("acceptance_gate"))
    runtime_budget = _as_dict(_as_dict(gate.get("dimensions")).get("runtime_budget"))
    if runtime_budget.get("status"):
        return _status_label(runtime_budget.get("status"))
    runtime_quality = _as_dict(_as_dict(result.get("quality_summary")).get("runtime_quality"))
    budget_gate = _as_dict(runtime_quality.get("budget_gate"))
    if budget_gate.get("passed") is not None:
        return _format_bool_status(budget_gate.get("passed"))
    return "-"


def _evidence_closure_status(result: dict[str, Any] | None) -> str:
    if not result:
        return STATUS_LABELS["pending"]
    closure = _as_dict(result.get("evidence_closure"))
    if not closure:
        return STATUS_LABELS["missing"]
    missing = [str(item) for item in _as_list(closure.get("missing")) if str(item)]
    if closure.get("passed") is True:
        return STATUS_LABELS["passed"]
    if missing:
        return "missing: " + ", ".join(missing)
    return STATUS_LABELS["failed"]


def _scenario_table(summary: dict[str, Any]) -> list[str]:
    scenario_records = _selected_scenario_records(summary)
    results = _result_by_scenario_id(summary)
    seen: set[str] = set()
    rows = [
        "| 场景 | 模式 | 状态 | 首 token | 工具调用数 | 证据闭环 | 运行预算 |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for scenario in scenario_records:
        scenario_id = str(scenario.get("id") or "-")
        seen.add(scenario_id)
        result = results.get(scenario_id)
        rows.append(
            "| "
            f"{_markdown_cell(scenario_id)} | "
            f"{_markdown_cell(scenario.get('expected_mode') or '-')} | "
            f"{_markdown_cell(_status_label(_result_status(result)))} | "
            f"{_markdown_cell(_format_seconds(_first_token_seconds(result or {})))} | "
            f"{_markdown_cell(_format_int(_tool_call_count(result or {})))} | "
            f"{_markdown_cell(_evidence_closure_status(result))} | "
            f"{_markdown_cell(_runtime_budget_status(result))} |"
        )
    for scenario_id, result in sorted(results.items()):
        if scenario_id in seen:
            continue
        rows.append(
            "| "
            f"{_markdown_cell(scenario_id)} | "
            f"{_markdown_cell(_as_dict(result.get('acceptance_gate')).get('expected_mode') or '-')} | "
            f"{_markdown_cell(_status_label(_result_status(result)))} | "
            f"{_markdown_cell(_format_seconds(_first_token_seconds(result)))} | "
            f"{_markdown_cell(_format_int(_tool_call_count(result)))} | "
            f"{_markdown_cell(_evidence_closure_status(result))} | "
            f"{_markdown_cell(_runtime_budget_status(result))} |"
        )
    return rows


def _status_counts(summary: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    raw_counts = _as_dict(summary.get("status_counts"))
    for status in STATUS_LABELS:
        count = _as_int(raw_counts.get(status))
        if count is not None and count > 0:
            counts[status] = count
    selected_ids = {
        str(item.get("id"))
        for item in _selected_scenario_records(summary)
        if isinstance(item.get("id"), str)
    }
    result_ids = set(_result_by_scenario_id(summary))
    pending_count = len(selected_ids - result_ids)
    if pending_count:
        counts["pending"] = pending_count
    return counts


def _format_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "{}"
    return ", ".join(
        f"{key}={value}"
        for key, value in sorted(counts.items())
        if value not in (None, "", [])
    ) or "{}"


def _run_context_lines(summary: dict[str, Any]) -> list[str]:
    run_context = _as_dict(summary.get("run_context"))
    scenario_ids = [
        str(item.get("id"))
        for item in _selected_scenario_records(summary)
        if isinstance(item.get("id"), str)
    ]
    result_ids = list(_result_by_scenario_id(summary))
    pending = [
        scenario_id
        for scenario_id in scenario_ids
        if scenario_id not in set(result_ids)
    ]
    partial = bool(run_context.get("partial") or pending)
    lines = [
        f"- partial summary（部分摘要）: {'是' if partial else '否'}",
        f"- 部分原因: {_markdown_cell(run_context.get('partial_reason') or '-')}",
        f"- 已完成场景: {_markdown_cell(', '.join(result_ids) or '-')}",
        f"- 待运行场景: {_markdown_cell(', '.join(pending) or '-')}",
    ]
    classification_counts = _as_dict(
        run_context.get("failure_classification_counts")
        or summary.get("failure_classification_counts")
    )
    if classification_counts:
        lines.append(f"- 失败分类: {_markdown_cell(_format_counts(classification_counts))}")
    return lines


def _evidence_summary_lines(summary: dict[str, Any]) -> list[str]:
    closure = _as_dict(summary.get("evidence_closure"))
    counts = _as_dict(closure.get("counts"))
    lines = [
        f"- 结果数: {closure.get('result_count', 0)}",
        f"- 闭环通过: {closure.get('passed_count', 0)}",
    ]
    if counts:
        lines.extend(["", "| 检查项 | 通过场景数 |", "|---|---:|"])
        for key, value in counts.items():
            lines.append(
                "| "
                f"{_markdown_cell(EVIDENCE_CHECK_LABELS.get(str(key), str(key)))} | "
                f"{_markdown_cell(value)} |"
            )
    missing_by_scenario = _as_dict(closure.get("missing_by_scenario"))
    if missing_by_scenario:
        lines.extend(["", "缺口："])
        for scenario_id, missing in sorted(missing_by_scenario.items()):
            lines.append(
                "- "
                f"{_markdown_cell(scenario_id)}: "
                f"{_markdown_cell(', '.join(str(item) for item in _as_list(missing)) or '-')}"
            )
    return lines


def _runtime_budget_lines(summary: dict[str, Any]) -> list[str]:
    totals = _as_dict(summary.get("runtime_totals"))
    return [
        f"- 总耗时: {_markdown_cell(totals.get('elapsed_seconds', '-'))} 秒",
        f"- 平均耗时: {_markdown_cell(totals.get('average_elapsed_seconds', '-'))} 秒",
        f"- 工具调用: {_markdown_cell(totals.get('tool_call_count', '-'))} 次",
        f"- 工具失败: {_markdown_cell(totals.get('tool_failure_count', '-'))} 次",
        f"- fallback（兜底）: {_markdown_cell(totals.get('fallback_count', '-'))} 次",
        f"- 估算 token（文本令牌）: {_markdown_cell(totals.get('estimated_total_tokens', '-'))}",
        f"- 工具计数: {_markdown_cell(_format_counts(_as_dict(summary.get('tool_counts') or totals.get('tool_counts'))))}",
    ]


def _source_label(source_path: Path | None) -> str:
    if source_path is None:
        return "未找到 `.runtime` acceptance summary（验收摘要）"
    return (
        f"latest `.runtime` acceptance summary（验收摘要）: "
        f"`{_markdown_cell(source_path.name)}`"
    )


def build_missing_summary_markdown(
    *,
    runtime_dir: Path,
    required_scenario_count: int = 9,
) -> str:
    """Render a stable report for the missing-summary case."""

    lines = [
        "# Acceptance Core Evidence Pack（核心验收证据包）",
        "",
        "## 结论",
        "",
        "- 状态: missing_summary（缺少摘要）",
        f"- 场景: 0 / {required_scenario_count} 可判定",
        f"- 来源摘要: {_source_label(None)}",
        "- 原始产物: `.runtime/` 仅本地使用，不提交",
        "",
        "## 缺文件说明",
        "",
        (
            "- 未找到 `version=acceptance_run_summary.v1` 的 JSON（JavaScript 对象表示法）"
            f"摘要；已检查目录 `{_markdown_cell(runtime_dir)}`。"
        ),
        "- 该状态不能作为 acceptance-core（核心验收）通过证据，只能说明本地缺少可导出的真实跑批摘要。",
        "",
        "## 下一步",
        "",
        "1. 运行真实 acceptance-core（核心验收）跑批并把 summary 写入 `.runtime/`。",
        "2. 重新执行 `scripts/export_acceptance_evidence.py` 生成脱敏 Markdown（标记文本）证据包。",
        "",
    ]
    return "\n".join(lines)


def build_acceptance_evidence_markdown(
    summary: dict[str, Any],
    *,
    source_path: Path | None,
    required_scenario_count: int = 9,
) -> str:
    """Render a redacted, stable Markdown evidence pack from an acceptance summary."""

    summary = redact_data(summary)
    if not isinstance(summary, dict):
        summary = {}
    selected_count = _as_int(summary.get("selected_count"))
    if selected_count is None:
        selected_count = len(_selected_scenario_records(summary))
    result_count = _as_int(summary.get("result_count")) or len(_result_by_scenario_id(summary))
    status = str(summary.get("status") or "missing")
    status_counts = _status_counts(summary)
    created_at = summary.get("created_at")
    try:
        run_date = datetime.fromisoformat(str(created_at)).date().isoformat()
    except ValueError:
        run_date = "-"

    findings: list[str] = []
    if selected_count != required_scenario_count:
        findings.append(
            f"期望 {required_scenario_count} 个核心场景，摘要中 selected_count={selected_count}。"
        )
    if result_count < selected_count:
        findings.append(
            f"摘要为 partial summary（部分摘要）：已完成 {result_count} / {selected_count}。"
        )
    if status in {"failed", "degraded", "blocked", "skipped"}:
        findings.append(f"整批状态为 {_status_label(status)}，不能等同于 passed（通过）。")

    lines = [
        "# Acceptance Core Evidence Pack（核心验收证据包）",
        "",
        "## 结论",
        "",
        f"- 状态: {_status_label(status)}",
        f"- 场景: {summary.get('passed_count', 0)} / {selected_count} passed（通过）",
        f"- 状态统计: {_markdown_cell(_format_counts(status_counts))}",
        f"- 运行日期: {_markdown_cell(run_date)}",
        f"- 来源摘要: {_source_label(source_path)}",
        "- 原始产物: `.runtime/` 仅本地使用，不提交",
        "",
        "## 场景状态地图",
        "",
        *_scenario_table(summary),
        "",
        "## 证据闭环",
        "",
        *_evidence_summary_lines(summary),
        "",
        "## 运行预算",
        "",
        *_runtime_budget_lines(summary),
        "",
        "## 运行上下文",
        "",
        *_run_context_lines(summary),
        "",
        "## 状态说明",
        "",
        "- passed（通过）：预检通过且所有场景门禁通过。",
        "- degraded（降级）：存在非阻塞 warning（警告）或治理风险，不能等同于通过。",
        "- failed（失败）：至少一个场景或质量维度失败。",
        "- blocked（环境阻塞）：真实依赖不足，不能生成有效通过结论。",
        "- pending（待运行）：partial summary（部分摘要）中尚未完成的场景。",
        "",
        "## 脱敏与提交边界",
        "",
        "- 证据包只保留状态、计数、预算和闭环字段，不写入 `.env`、真实密钥、手机号、邮箱或 JWT（JSON Web Token，令牌认证）。",
        "- 源 JSON（JavaScript 对象表示法）快照和 summary 保持在 `.runtime/`，由 `.gitignore` 忽略，不进入提交。",
        "- 导出脚本仅读取 `.runtime` 摘要文件，不读取或写入 `.env`。",
        "",
    ]
    if findings:
        lines.extend(["## 注意事项", ""])
        lines.extend(f"- {_markdown_cell(item)}" for item in findings)
        lines.append("")
    return redact_text("\n".join(lines))


def export_acceptance_evidence(
    *,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    summary_path: Path | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    required_scenario_count: int = 9,
) -> EvidenceExportResult:
    """Write the commit-safe evidence pack and return export metadata."""

    resolved_summary_path = summary_path or find_latest_acceptance_summary(runtime_dir)
    if resolved_summary_path is None:
        markdown = build_missing_summary_markdown(
            runtime_dir=runtime_dir,
            required_scenario_count=required_scenario_count,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        return EvidenceExportResult(
            output_path=output_path,
            summary_path=None,
            status="missing_summary",
            missing_summary=True,
        )

    summary = load_acceptance_summary(resolved_summary_path)
    markdown = build_acceptance_evidence_markdown(
        summary,
        source_path=resolved_summary_path,
        required_scenario_count=required_scenario_count,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return EvidenceExportResult(
        output_path=output_path,
        summary_path=resolved_summary_path,
        status=str(summary.get("status") or "missing"),
        missing_summary=False,
    )


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir",
        type=_path_arg,
        default=DEFAULT_RUNTIME_DIR,
        help="Directory containing ignored runtime acceptance artifacts.",
    )
    parser.add_argument(
        "--summary",
        type=_path_arg,
        default=None,
        help="Optional explicit acceptance summary JSON path.",
    )
    parser.add_argument(
        "--output",
        type=_path_arg,
        default=DEFAULT_OUTPUT_PATH,
        help="Commit-safe Markdown evidence-pack output path.",
    )
    parser.add_argument(
        "--required-scenarios",
        type=int,
        default=9,
        help="Expected acceptance-core scenario count.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Return success even when no runtime summary exists.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = export_acceptance_evidence(
        runtime_dir=args.runtime_dir,
        summary_path=args.summary,
        output_path=args.output,
        required_scenario_count=args.required_scenarios,
    )
    print(f"wrote {result.output_path}")
    if result.summary_path is not None:
        print(f"source {result.summary_path}")
    if result.missing_summary and not args.allow_missing:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
