"""Render a redacted M1 deployment resource request pack.

The pack is intended for collecting server, DNS/TLS, environment, data,
acceptance, backup, monitoring and incident-response inputs before a controlled
M1 trial. It does not read .env files and never asks operators to paste secret
values into Git, documents or chat.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_m1_launch_inputs import (  # noqa: E402
    M1_INPUT_SPECS,
    build_m1_launch_inputs_report,
)
from scripts.export_acceptance_evidence import redact_text  # noqa: E402


M1_RESOURCE_REQUEST_VERSION = "m1_resource_request.v1"


RESOURCE_GROUPS: tuple[dict[str, str], ...] = (
    {
        "key": "server_domain_tls",
        "label": "服务器、公网域名和 TLS",
        "request": "准备 2-4 vCPU、8-16 GB RAM、80-160 GB SSD 的 Linux 服务器，开放 80/443，完成 DNS 和 HTTPS。",
        "evidence": "服务器规格、域名解析状态、TLS 状态、反向代理状态和 health URL。",
    },
    {
        "key": "runtime_services",
        "label": "PostgreSQL、Redis 和部署目录",
        "request": "确认 PostgreSQL、Redis 采用 Compose 或托管服务，并准备部署目录、持久化卷和迁移窗口。",
        "evidence": "数据库/缓存模式、迁移结果、Docker Compose 状态和 readiness 摘要。",
    },
    {
        "key": "secret_store",
        "label": "密钥托管和轮换",
        "request": "把真实密钥放在服务器环境、CI secrets 或云密钥系统，不发到文档或聊天。",
        "evidence": "密钥托管方式、负责人、轮换周期和泄露响应负责人。",
    },
    {
        "key": "rag_data",
        "label": "RAG 数据和脱敏业务材料",
        "request": "准备公开资料、脱敏路线模板、风险 SOP 和报告字段要求；不提供真实客户资料或向量库文件。",
        "evidence": "数据来源、脱敏确认、RAG 初始化和召回评测摘要。",
    },
    {
        "key": "external_api",
        "label": "LLM、地图和可选外部 API",
        "request": "确认 DashScope、高德，以及 Tavily、航班、酒店等可选服务的启用状态、预算和降级策略。",
        "evidence": "服务状态、控制台负责人、配额预算、timeout/retry 和降级策略。",
    },
    {
        "key": "acceptance",
        "label": "验收账号、场景和时间窗口",
        "request": "准备验收账号、固定 smoke 场景、API 预算和验收时间窗口。",
        "evidence": "acceptance preflight、acceptance smoke 和 M1 go/no-go 脱敏摘要。",
    },
    {
        "key": "backup_restore",
        "label": "备份和恢复演练",
        "request": "准备 PostgreSQL 备份目录或对象存储，完成非生产恢复演练，明确可接受数据丢失窗口。",
        "evidence": "备份策略、最新 dump 元数据、pg_restore catalog 可读性和恢复演练声明。",
    },
    {
        "key": "monitoring_alerting",
        "label": "监控告警和成本预算",
        "request": "准备 health/readiness 告警、错误率、P95、工具失败、成本、备份和日志脱敏监控。",
        "evidence": "告警投递声明、指标监控状态、成本预算和日志脱敏抽样结果。",
    },
    {
        "key": "rollback_incident",
        "label": "回滚和事故响应",
        "request": "明确回滚负责人、事故负责人、回滚目标、回滚后 smoke 和事故复盘状态。",
        "evidence": "回滚演练、回滚后 health/gate/smoke、事故分级和沟通状态。",
    },
)

RUNTIME_CONFIG_VARS: tuple[dict[str, str], ...] = (
    {"env_var": "APP_ENV", "purpose": "环境标识，M1 建议 staging。", "secret": "false"},
    {"env_var": "POSTGRES_HOST", "purpose": "PostgreSQL 主机或服务名。", "secret": "false"},
    {"env_var": "POSTGRES_PORT", "purpose": "PostgreSQL 端口。", "secret": "false"},
    {"env_var": "POSTGRES_DB", "purpose": "PostgreSQL 数据库名。", "secret": "false"},
    {"env_var": "POSTGRES_USER", "purpose": "应用数据库账号名。", "secret": "false"},
    {"env_var": "REDIS_HOST", "purpose": "Redis 主机或服务名。", "secret": "false"},
    {"env_var": "REDIS_PORT", "purpose": "Redis 端口。", "secret": "false"},
    {"env_var": "RAG_VECTORSTORE_PATH", "purpose": "公开 RAG 向量库运行时路径。", "secret": "false"},
    {"env_var": "RAG_INTERNAL_VECTORSTORE_PATH", "purpose": "内部知识库向量库运行时路径。", "secret": "false"},
    {"env_var": "ZHIXING_SITE_ADDRESS", "purpose": "反向代理站点地址或域名。", "secret": "false"},
)

SECRET_INPUTS: tuple[dict[str, str], ...] = (
    {"env_var": "DASHSCOPE_API_KEY", "purpose": "LLM 调用密钥。", "required": "M1 required"},
    {"env_var": "JWT_SECRET_KEY", "purpose": "登录态签名密钥。", "required": "M1 required"},
    {"env_var": "POSTGRES_PASSWORD", "purpose": "应用数据库账号密码。", "required": "M1 required"},
    {"env_var": "REDIS_PASSWORD", "purpose": "Redis 访问口令。", "required": "M1 required if Redis auth is enabled"},
    {"env_var": "AMAP_API_KEY", "purpose": "高德地图后端 API key。", "required": "M1 required"},
    {"env_var": "AMAP_WEB_JS_KEY", "purpose": "浏览器端地图 key。", "required": "optional"},
    {"env_var": "TAVILY_API_KEY", "purpose": "联网搜索服务 key。", "required": "optional"},
    {"env_var": "VARIFLIGHT_API_KEY", "purpose": "航班查询服务 key。", "required": "optional"},
    {"env_var": "AIGOHOTEL_API_KEY", "purpose": "酒店服务 API key。", "required": "optional"},
    {"env_var": "AIGOHOTEL_SECRET_KEY", "purpose": "酒店服务签名密钥。", "required": "optional"},
    {"env_var": "LANGSMITH_API_KEY", "purpose": "LangSmith 观测 key。", "required": "optional"},
    {"env_var": "EVAL_USERNAME", "purpose": "验收账号用户名。", "required": "acceptance only"},
    {"env_var": "EVAL_PASSWORD", "purpose": "验收账号密码。", "required": "acceptance only"},
)

DATA_REQUESTS: tuple[dict[str, str], ...] = (
    {
        "key": "public_destination_docs",
        "need": "公开目的地资料、交通建议、季节风险和景点说明。",
        "forbidden": "不可复制的内部资料、真实客户行程和供应商私密底价。",
    },
    {
        "key": "desensitized_product_templates",
        "need": "脱敏后的路线结构、服务范围、可选升级项和报价区间。",
        "forbidden": "真实库存、真实联系人、合同、付款凭证或可识别客户资料。",
    },
    {
        "key": "report_contract_samples",
        "need": "脱敏报告样例、字段顺序、预算展示和待核验写法。",
        "forbidden": "真实订单、身份证、手机号、发票、合同或聊天全文。",
    },
)

COMMAND_PLAN: tuple[dict[str, str], ...] = (
    {
        "key": "render_request_pack",
        "command": "python scripts/render_m1_resource_request.py --markdown",
        "runs_when": "before collecting resources",
    },
    {
        "key": "render_non_secret_input_template",
        "command": "python scripts/check_m1_launch_inputs.py --template --output <private-workdir>/m1-launch-inputs.local.json",
        "runs_when": "before collecting non-secret server, network, backup, monitoring and ownership declarations",
    },
    {
        "key": "check_non_secret_input_file",
        "command": "python scripts/check_m1_launch_inputs.py --input-json <private-workdir>/m1-launch-inputs.local.json --json",
        "runs_when": "after the non-secret input template is filled outside Git",
    },
    {
        "key": "check_non_secret_inputs",
        "command": "python scripts/check_m1_launch_inputs.py --json",
        "runs_when": "after non-secret declarations are set in the target deployment environment",
    },
    {
        "key": "server_env_checklist",
        "command": "python scripts/render_server_env_checklist.py --markdown",
        "runs_when": "before creating <deploy-dir>/shared/.env on the server",
    },
    {
        "key": "server_env_file_check",
        "command": "python scripts/check_server_env_file.py --env-file <deploy-dir>/shared/.env --json",
        "runs_when": "after the server shared .env is created on the server or secret-safe shell",
    },
    {
        "key": "first_deploy_dry_run",
        "command": "python scripts/check_m1_first_deploy_dry_run.py --json",
        "runs_when": "after deploy target inputs and local release tools are ready",
    },
    {
        "key": "release_artifact_manifest",
        "command": "python scripts/build_release_artifact.py --execute --output-dir <release-output-dir> --json",
        "runs_when": "after local dry-run passes and the Git worktree is clean",
    },
    {
        "key": "server_first_deploy_script_dry_run",
        "command": "scp deploy/first-deploy.sh <ssh-user>@<server-host>:/tmp/zhixing-first-deploy.sh && ssh <ssh-user>@<server-host> \"sh /tmp/zhixing-first-deploy.sh --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>\"",
        "runs_when": "after release archive upload, before executing remote deploy",
    },
    {
        "key": "server_first_deploy_script_execute",
        "command": "ssh <ssh-user>@<server-host> \"sh /tmp/zhixing-first-deploy.sh --execute --start-services --archive /tmp/<release-archive> --archive-sha256 <archive-sha256> --deploy-dir <deploy-dir>\"",
        "runs_when": "after remote dry-run is reviewed and runtime .env is present on the server",
    },
    {
        "key": "deployment_gate",
        "command": "python scripts/check_m1_deployment_gate.py --json",
        "runs_when": "after server, env, backup, monitoring and security declarations are ready",
    },
    {
        "key": "final_go_no_go",
        "command": "python scripts/collect_m1_go_no_go_evidence.py --include-all-declared-evidence --include-server-preflight-evidence --check-server-docker --check-server-deploy-dir --check-server-disk --check-health-url --run-gate --run-acceptance-smoke --json",
        "runs_when": "after live target is deployed and API budget is approved",
    },
)


def _safe_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _non_secret_inputs_from_launch_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks = report.get("checks") or []
    by_env = {
        str(item.get("env_var")): item
        for item in checks
        if isinstance(item, Mapping)
    }
    inputs: list[dict[str, Any]] = []
    for spec in M1_INPUT_SPECS:
        check = by_env.get(spec.env_var, {})
        inputs.append(
            {
                "category": spec.category,
                "key": spec.key,
                "env_var": spec.env_var,
                "label": spec.label,
                "required": spec.required,
                "current_status": check.get("status", "not_checked"),
                "present": bool(check.get("present", False)),
                "value_echoed": False,
                "action": check.get("action")
                or f"Set {spec.env_var} in the deployment environment; do not send secret values.",
            }
        )
    return inputs


def build_m1_resource_request_report(
    *,
    environ: Mapping[str, str] | None = None,
    include_current_env_status: bool = True,
) -> dict[str, Any]:
    """Build a sendable M1 resource request without echoing values."""

    env = environ if environ is not None else os.environ
    launch_report = (
        build_m1_launch_inputs_report(environ=env)
        if include_current_env_status
        else {
            "status": "not_checked",
            "missing_or_blocked_env_vars": [],
            "category_statuses": {},
            "checks": [],
        }
    )
    report = {
        "version": M1_RESOURCE_REQUEST_VERSION,
        "status": "ready_to_collect_resources",
        "policy": {
            "reads_dotenv": False,
            "reads_current_process_environment": include_current_env_status,
            "does_not_echo_values": True,
            "requests_secret_values_in_chat_or_git": False,
            "safe_to_commit": True,
        },
        "current_env_summary": {
            "status": launch_report.get("status"),
            "missing_or_blocked_env_vars": launch_report.get("missing_or_blocked_env_vars") or [],
            "category_statuses": launch_report.get("category_statuses") or {},
            "value_echoed": False,
        },
        "resource_groups": list(RESOURCE_GROUPS),
        "non_secret_inputs": _non_secret_inputs_from_launch_report(launch_report),
        "runtime_config_vars": [
            {**item, "value_echoed": False, "delivery": "deployment environment only"}
            for item in RUNTIME_CONFIG_VARS
        ],
        "secret_inputs": [
            {
                **item,
                "value_echoed": False,
                "delivery": "secret manager, CI secrets, or server .env only; do not paste values here",
            }
            for item in SECRET_INPUTS
        ],
        "data_requests": list(DATA_REQUESTS),
        "command_plan": list(COMMAND_PLAN),
        "not_proven_by_this_request": [
            "The target server exists or is reachable.",
            "Real secret values are present or valid.",
            "PostgreSQL, Redis, RAG vector stores, LLM, map or optional providers are healthy.",
            "Backups, restore drills, alert delivery, rollback drills or acceptance smoke have run.",
            "The system can process real payment, booking, price lock, ticketing or fulfillment.",
        ],
    }
    return _safe_payload(report)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_m1_resource_request_markdown(report: Mapping[str, Any]) -> str:
    safe_report = _safe_payload(dict(report))
    if not isinstance(safe_report, Mapping):
        safe_report = {}
    policy = safe_report.get("policy") if isinstance(safe_report.get("policy"), Mapping) else {}
    current = (
        safe_report.get("current_env_summary")
        if isinstance(safe_report.get("current_env_summary"), Mapping)
        else {}
    )
    lines = [
        "# M1 Resource Request Pack（受控试运行资源申请包）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Reads `.env` | `{_markdown_cell(policy.get('reads_dotenv'))}` |",
        f"| Echoes values | `{_markdown_cell(not policy.get('does_not_echo_values'))}` |",
        f"| Requests secret values here | `{_markdown_cell(policy.get('requests_secret_values_in_chat_or_git'))}` |",
        f"| Current env status | `{_markdown_cell(current.get('status'))}` |",
        "",
        "## 资源组",
        "",
        "| Key | Label | Need | Evidence |",
        "|---|---|---|---|",
    ]
    for item in safe_report.get("resource_groups") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"{_markdown_cell(item.get('label'))} | "
            f"{_markdown_cell(item.get('request'))} | "
            f"{_markdown_cell(item.get('evidence'))} |"
        )

    lines.extend(["", "## 非密钥环境声明", "", "| Env Var | Category | Status | Action |", "|---|---|---|---|"])
    for item in safe_report.get("non_secret_inputs") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"{_markdown_cell(item.get('category'))} | "
            f"{_markdown_cell(item.get('current_status'))} | "
            f"{_markdown_cell(item.get('action'))} |"
        )

    lines.extend(["", "## 运行配置变量", "", "| Env Var | Purpose | Delivery |", "|---|---|---|"])
    for item in safe_report.get("runtime_config_vars") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"{_markdown_cell(item.get('purpose'))} | "
            f"{_markdown_cell(item.get('delivery'))} |"
        )

    lines.extend(
        [
            "",
            "## 密钥变量",
            "",
            "真实值只放到服务器环境、CI secrets 或云密钥系统；不要写入 Git、文档、聊天记录或工单正文。",
            "",
            "| Env Var | Required | Purpose | Delivery |",
            "|---|---|---|---|",
        ]
    )
    for item in safe_report.get("secret_inputs") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"{_markdown_cell(item.get('required'))} | "
            f"{_markdown_cell(item.get('purpose'))} | "
            f"{_markdown_cell(item.get('delivery'))} |"
        )

    lines.extend(["", "## 数据输入", "", "| Key | Need | Forbidden |", "|---|---|---|"])
    for item in safe_report.get("data_requests") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"{_markdown_cell(item.get('need'))} | "
            f"{_markdown_cell(item.get('forbidden'))} |"
        )

    lines.extend(["", "## 命令计划", "", "| Key | Command | Runs when |", "|---|---|---|"])
    for item in safe_report.get("command_plan") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"`{_markdown_cell(item.get('command'))}` | "
            f"{_markdown_cell(item.get('runs_when'))} |"
        )

    lines.extend(["", "## 边界", ""])
    for item in safe_report.get("not_proven_by_this_request") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    parser.add_argument(
        "--no-current-env-status",
        action="store_true",
        help="Do not include current process environment readiness status.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_m1_resource_request_report(
        include_current_env_status=not args.no_current_env_status,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_m1_resource_request_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
