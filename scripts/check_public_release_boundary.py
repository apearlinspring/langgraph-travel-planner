"""Check public release boundaries without reading local secrets or runtime data."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence


PUBLIC_RELEASE_BOUNDARY_VERSION = "public_release_boundary.v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_EXACT_PATHS = {
    ".env",
    ".env.local",
    ".env.production",
}
ALLOWED_ENV_EXAMPLE_PATHS = {
    ".env.example",
}
FORBIDDEN_PREFIXES = (
    ".env.",
    ".runtime/",
    ".venv/",
    "backups/",
    "data/vectorstore/",
    "data/vectorstore_internal/",
    "logs/",
)
CONTENT_SKIP_PREFIXES = (
    "tests/",
)
TEXT_EXTENSIONS = {
    ".css",
    ".env.example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?P<key>[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION|COOKIE)"
    r"[A-Z0-9_]*)\s*[:=]\s*['\"]?(?P<value>[^'\"\s,#]+)"
)
URL_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)[?&](?P<key>api[_-]?key|apikey|key|access[_-]?token|refresh[_-]?token|"
    r"token|secret|password|authorization)=(?P<value>[^&#\s]+)"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}\b")
API_KEY_SHAPE_PATTERN = re.compile(
    r"\b(?:sk|rk)[-_][A-Za-z0-9][A-Za-z0-9_-]{16,}\b",
    re.IGNORECASE,
)
SAFE_ASSIGNMENT_KEY_PARTS = (
    "access_token_expire",
    "auth_cookie_name",
    "auth_cookie_samesite",
    "auth_cookie_secure",
    "context_token",
    "estimated_total_token",
    "estimated_input_token",
    "estimated_output_token",
    "first_token",
    "left_tokens",
    "llm_max_tokens",
    "max_tokens",
    "output_tokens",
    "prompt_tokens",
    "query_tokens",
    "recent_message_tokens",
    "right_tokens",
    "state_token",
    "statetoken",
    "token_budget",
    "token_count",
    "token_event",
    "token_ratio",
    "token_set",
    "tokens",
    "used_tokens",
)
SENSITIVE_ASSIGNMENT_KEY_PARTS = (
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "jwt_secret",
    "password",
    "refresh_token",
    "secret",
)

PLACEHOLDER_EXACT_VALUES = {
    "",
    "...",
    "[redacted]",
    "none",
    "null",
}
PLACEHOLDER_PREFIXES = (
    "$",
    "${",
    "{",
    "<",
    "...",
    "change-me",
    "dev-only",
    "dummy",
    "example-",
    "placeholder",
    "settings.",
    "test-",
    "your-",
)


def _normalize_repo_path(path: str | Path) -> str:
    text = Path(path).as_posix()
    return text[2:] if text.startswith("./") else text


def _is_forbidden_release_path(path: str | Path) -> bool:
    relative = _normalize_repo_path(path)
    if relative in ALLOWED_ENV_EXAMPLE_PATHS:
        return False
    if relative in FORBIDDEN_EXACT_PATHS:
        return True
    return any(relative.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)


def _should_scan_content(path: str | Path) -> bool:
    relative = _normalize_repo_path(path)
    if _is_forbidden_release_path(relative):
        return False
    if any(relative.startswith(prefix) for prefix in CONTENT_SKIP_PREFIXES):
        return False
    suffix = Path(relative).suffix.lower()
    if relative.endswith(".env.example"):
        return True
    return suffix in TEXT_EXTENSIONS


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").strip()
    lowered = normalized.lower()
    if lowered in PLACEHOLDER_EXACT_VALUES:
        return True
    if any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES):
        return True
    if "change-me" in lowered or "placeholder" in lowered:
        return True
    if lowered.startswith("os.environ") or lowered.startswith("env["):
        return True
    return False


def _is_sensitive_assignment_key(key: str) -> bool:
    lowered = key.lower()
    if any(part in lowered for part in SAFE_ASSIGNMENT_KEY_PARTS):
        return False
    return any(part in lowered for part in SENSITIVE_ASSIGNMENT_KEY_PARTS)


def _looks_like_secret_value(value: str) -> bool:
    normalized = value.strip().strip("'\"").strip()
    if _looks_like_placeholder(normalized):
        return False
    if JWT_PATTERN.search(normalized) or BEARER_PATTERN.search(normalized):
        return True
    if API_KEY_SHAPE_PATTERN.search(normalized):
        return True
    if any(char in normalized for char in "()[]{}"):
        return False
    if "." in normalized and not normalized.startswith(("sk-", "rk-")):
        return False
    return (
        len(normalized) >= 20
        and any(char.isalpha() for char in normalized)
        and any(char.isdigit() for char in normalized)
    )


def _git_paths(repo_root: Path) -> list[Path]:
    paths: list[str] = []
    for args in (
        ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
        ["git", "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        try:
            result = subprocess.run(
                args,
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=False,
            )
        except (OSError, subprocess.CalledProcessError):
            return []
        paths.extend(
            item.decode("utf-8", errors="replace")
            for item in result.stdout.split(b"\0")
            if item
        )
    return [Path(path) for path in sorted(set(paths))]


def _filesystem_paths(repo_root: Path) -> list[Path]:
    ignored_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".runtime",
        ".venv",
        "__pycache__",
        "backups",
        "logs",
        "node_modules",
    }
    paths: list[Path] = []
    for path in repo_root.rglob("*"):
        try:
            relative = path.relative_to(repo_root)
        except ValueError:
            continue
        if any(part in ignored_dirs for part in relative.parts):
            continue
        if path.is_file():
            paths.append(relative)
    return sorted(paths)


def candidate_release_paths(repo_root: Path = PROJECT_ROOT) -> list[Path]:
    """Return public release candidates without expanding ignored runtime folders."""

    root = Path(repo_root)
    git_paths = _git_paths(root)
    return git_paths or _filesystem_paths(root)


def _read_text_if_safe(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _content_findings_for_text(path: str, text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in SENSITIVE_ASSIGNMENT_PATTERN.finditer(line):
            if not _is_sensitive_assignment_key(match.group("key")):
                continue
            if not _looks_like_secret_value(match.group("value")):
                continue
            findings.append(
                {
                    "path": path,
                    "line": line_number,
                    "kind": "secret_assignment",
                    "key": match.group("key"),
                }
            )
        for match in URL_QUERY_SECRET_PATTERN.finditer(line):
            if _looks_like_placeholder(match.group("value")):
                continue
            findings.append(
                {
                    "path": path,
                    "line": line_number,
                    "kind": "url_query_secret",
                    "key": match.group("key"),
                }
            )
        for kind, pattern in (
            ("jwt", JWT_PATTERN),
            ("bearer_token", BEARER_PATTERN),
            ("api_key_shape", API_KEY_SHAPE_PATTERN),
        ):
            if pattern.search(line):
                findings.append(
                    {
                        "path": path,
                        "line": line_number,
                        "kind": kind,
                        "key": None,
                    }
                )
    return findings


def build_public_release_boundary_report(
    *,
    repo_root: str | Path = PROJECT_ROOT,
    candidate_paths: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Build a release-boundary report without opening forbidden local secret paths."""

    root = Path(repo_root).resolve()
    candidates = [
        Path(path)
        for path in (candidate_paths if candidate_paths is not None else candidate_release_paths(root))
    ]
    forbidden_paths = [
        _normalize_repo_path(path)
        for path in candidates
        if _is_forbidden_release_path(path)
    ]
    content_findings: list[dict[str, Any]] = []
    scanned_paths: list[str] = []
    skipped_content_paths: list[str] = []

    for relative_path in candidates:
        normalized = _normalize_repo_path(relative_path)
        if _is_forbidden_release_path(normalized):
            skipped_content_paths.append(normalized)
            continue
        if not _should_scan_content(normalized):
            skipped_content_paths.append(normalized)
            continue
        text = _read_text_if_safe(root / relative_path)
        if text is None:
            skipped_content_paths.append(normalized)
            continue
        scanned_paths.append(normalized)
        content_findings.extend(_content_findings_for_text(normalized, text))

    status = "blocked" if forbidden_paths or content_findings else "passed"
    return {
        "version": PUBLIC_RELEASE_BOUNDARY_VERSION,
        "status": status,
        "candidate_count": len(candidates),
        "scanned_count": len(scanned_paths),
        "forbidden_paths": sorted(set(forbidden_paths)),
        "content_findings": content_findings,
        "skipped_content_paths": sorted(set(skipped_content_paths)),
        "policy": {
            "does_not_read_forbidden_paths": True,
            "checks_tracked_and_untracked_release_candidates": candidate_paths is None,
            "tests_content_scan_skipped_by_default": True,
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_public_release_boundary_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Public release boundary: {report['status']}")
        print(f"- Candidates: {report['candidate_count']}")
        print(f"- Scanned text files: {report['scanned_count']}")
        if report["forbidden_paths"]:
            print("- Forbidden paths:")
            for path in report["forbidden_paths"]:
                print(f"  - {path}")
        if report["content_findings"]:
            print("- Sensitive content findings:")
            for item in report["content_findings"]:
                key = f" key={item['key']}" if item.get("key") else ""
                print(f"  - {item['path']}:{item['line']} {item['kind']}{key}")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
