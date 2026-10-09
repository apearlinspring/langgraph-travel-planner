"""Check security release readiness without reading .env files or secret values."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_public_release_boundary import build_public_release_boundary_report  # noqa: E402


SECURITY_RELEASE_READINESS_VERSION = "security_release_readiness.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
TRUTHY_DISABLED = {"1", "true", "yes", "y", "on", "disabled", "confirmed"}
FALSEY_ENABLED = {"0", "false", "no", "n", "off", "enabled"}
READY_WORDS = ("ready", "rotated", "managed", "confirmed")


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _base_check(
    *,
    category: str,
    key: str,
    env_var: str,
    label: str,
    status: str,
    finding: str,
) -> dict[str, Any]:
    return {
        "category": category,
        "key": key,
        "env_var": env_var,
        "label": label,
        "status": status,
        "finding": finding,
        "value_echoed": False,
    }


def _check_declared(
    *,
    category: str,
    key: str,
    env_var: str,
    value: str,
    label: str,
) -> dict[str, Any]:
    if not value:
        return _base_check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Missing required security release declaration.",
        )
    if _looks_placeholder(value):
        return _base_check(
            category=category,
            key=key,
            env_var=env_var,
            label=label,
            status="blocked",
            finding="Security release declaration still looks like a placeholder.",
        )
    return _base_check(
        category=category,
        key=key,
        env_var=env_var,
        label=label,
        status="passed",
        finding="Declared.",
    )


def _check_rotation_cadence(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="secrets",
        key="secret_rotation_cadence",
        env_var="ZHIXING_SECRET_ROTATION_CADENCE",
        value=value,
        label="Secret rotation cadence",
    )
    if item["status"] == "blocked":
        return item
    if not any(char.isdigit() for char in value):
        item["status"] = "blocked"
        item["finding"] = "Secret rotation cadence must include a numeric window."
    return item


def _check_ready_status(
    *,
    category: str,
    key: str,
    env_var: str,
    value: str,
    label: str,
) -> dict[str, Any]:
    item = _check_declared(
        category=category,
        key=key,
        env_var=env_var,
        value=value,
        label=label,
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if any(word in lowered for word in READY_WORDS):
        item["finding"] = "Ready or rotated status is declared."
        return item
    if any(word in lowered for word in ("blocked", "missing", "invalid", "leaked", "expired")):
        item["status"] = "blocked"
        item["finding"] = "Security credential status is not ready."
        return item
    item["status"] = "blocked"
    item["finding"] = "Expected ready/rotated/managed/confirmed status."
    return item


def _check_allowed_origins(value: str) -> dict[str, Any]:
    item = _check_declared(
        category="browser_keys",
        key="allowed_origins_status",
        env_var="ZHIXING_ALLOWED_ORIGINS_STATUS",
        value=value,
        label="Browser key allowed origins",
    )
    if item["status"] == "blocked":
        return item
    lowered = value.lower()
    if "*" in lowered or "any" in lowered or "unrestricted" in lowered or "all origins" in lowered:
        item["status"] = "blocked"
        item["finding"] = "Browser key origins must not be unrestricted."
    return item


def _check_high_risk_actions_disabled(value: str) -> dict[str, Any]:
    payload = {
        "category": "risk_boundary",
        "key": "real_payment_order_disabled",
        "env_var": "ZHIXING_REAL_PAYMENT_ORDER_DISABLED",
        "label": "Real payment/order disabled",
    }
    if not value:
        return _base_check(**payload, status="blocked", finding="Missing high-risk action disable flag.")
    lowered = value.lower()
    if lowered in TRUTHY_DISABLED:
        return _base_check(**payload, status="passed", finding="High-risk real-world actions are declared disabled.")
    if lowered in FALSEY_ENABLED or _looks_placeholder(value):
        return _base_check(
            **payload,
            status="blocked",
            finding="Real payment, booking, price lock, and ticketing must remain disabled for M1.",
        )
    return _base_check(
        **payload,
        status="blocked",
        finding="Expected explicit true/yes/disabled confirmation.",
    )


def _public_boundary_section(*, check: bool) -> dict[str, Any]:
    if not check:
        return {
            "status": "not_checked",
            "checked": False,
            "finding": "Public release boundary scan not requested.",
        }
    report = build_public_release_boundary_report()
    return {
        "status": report.get("status", "unknown"),
        "checked": True,
        "candidate_count": report.get("candidate_count"),
        "scanned_count": report.get("scanned_count"),
        "blocked_reasons": report.get("blocked_reasons") or [],
        "finding": "Public release boundary scan completed.",
    }


def build_security_release_readiness_report(
    *,
    environ: Mapping[str, str] | None = None,
    check_public_boundary: bool = False,
) -> dict[str, Any]:
    """Build a redacted security release readiness report."""

    env = environ if environ is not None else os.environ
    checks = [
        _check_declared(
            category="secrets",
            key="secret_store",
            env_var="ZHIXING_SECRET_STORE",
            value=_value(env, "ZHIXING_SECRET_STORE"),
            label="Secret store",
        ),
        _check_declared(
            category="secrets",
            key="secret_owner",
            env_var="ZHIXING_SECRET_OWNER",
            value=_value(env, "ZHIXING_SECRET_OWNER"),
            label="Secret owner",
        ),
        _check_rotation_cadence(_value(env, "ZHIXING_SECRET_ROTATION_CADENCE")),
        _check_declared(
            category="incident",
            key="leak_response_owner",
            env_var="ZHIXING_LEAK_RESPONSE_OWNER",
            value=_value(env, "ZHIXING_LEAK_RESPONSE_OWNER"),
            label="Leak response owner",
        ),
        _check_ready_status(
            category="credentials",
            key="jwt_secret_status",
            env_var="ZHIXING_JWT_SECRET_STATUS",
            value=_value(env, "ZHIXING_JWT_SECRET_STATUS"),
            label="JWT secret status",
        ),
        _check_ready_status(
            category="credentials",
            key="provider_key_status",
            env_var="ZHIXING_PROVIDER_KEY_STATUS",
            value=_value(env, "ZHIXING_PROVIDER_KEY_STATUS"),
            label="Provider key status",
        ),
        _check_ready_status(
            category="credentials",
            key="database_secret_status",
            env_var="ZHIXING_DATABASE_SECRET_STATUS",
            value=_value(env, "ZHIXING_DATABASE_SECRET_STATUS"),
            label="Database secret status",
        ),
        _check_ready_status(
            category="credentials",
            key="redis_secret_status",
            env_var="ZHIXING_REDIS_SECRET_STATUS",
            value=_value(env, "ZHIXING_REDIS_SECRET_STATUS"),
            label="Redis secret status",
        ),
        _check_allowed_origins(_value(env, "ZHIXING_ALLOWED_ORIGINS_STATUS")),
        _check_high_risk_actions_disabled(_value(env, "ZHIXING_REAL_PAYMENT_ORDER_DISABLED")),
    ]
    public_boundary = _public_boundary_section(check=check_public_boundary)

    blocked = [item for item in checks if item["status"] == "blocked"]
    if public_boundary["status"] == "blocked":
        blocked.append(
            {
                "category": "public_boundary",
                "key": "public_release_boundary",
                "env_var": None,
                "label": "Public release boundary",
                "status": "blocked",
                "finding": "Public release boundary scan is blocked.",
                "value_echoed": False,
            }
        )

    return {
        "version": SECURITY_RELEASE_READINESS_VERSION,
        "status": "blocked" if blocked else "passed",
        "policy": {
            "reads_dotenv": False,
            "reads_secret_values": False,
            "does_not_echo_values": True,
            "public_boundary_scan_requested": check_public_boundary,
        },
        "checks": checks,
        "public_boundary": public_boundary,
        "blocked_reasons": blocked,
        "not_proven_by_this_check": [
            "The real secret values are present or valid.",
            "Provider consoles have actually enforced least privilege and budget caps.",
            "Key rotation has been performed and old keys have been revoked.",
            "A leak response drill has actually completed.",
            "Git history is free of every past secret leak.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# Security Release Readiness",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, reads_secret_values=false",
        "",
        "## Checks",
    ]
    for item in report.get("checks") or []:
        lines.append(f"- {item.get('env_var')}: {item.get('status')} ({item.get('finding')})")
    public_boundary = report.get("public_boundary") or {}
    lines.extend(
        [
            "",
            "## Public Boundary",
            f"- status: {public_boundary.get('status')}",
            f"- checked: {public_boundary.get('checked')}",
        ]
    )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            label = item.get("env_var") or item.get("key")
            lines.append(f"- {label}: {item.get('finding')}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--check-public-boundary", action="store_true", help="Run public release boundary scan.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_security_release_readiness_report(
        check_public_boundary=args.check_public_boundary,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
