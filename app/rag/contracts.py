"""
RAG knowledge contracts.

The travel agent still receives tool output as text, but this module defines a
stable evidence shape that downstream prompts, tests, and evaluators can parse.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, NotRequired, TypedDict

try:  # PyYAML is present in requirements.txt, but keep a tiny fallback for scripts.
    import yaml
except Exception:  # pragma: no cover - exercised only in minimal dependency shells
    yaml = None


CONTRACT_VERSION = "rag.evidence.v1"

PUBLIC_KNOWLEDGE_BASE = "public_destination_guides"
INTERNAL_KNOWLEDGE_BASE = "agency_internal_knowledge"
INTERNAL_REVIEW_MAX_AGE_DAYS = 365
PLANNING_MODES = {"agency_plan", "free_planning"}
LOW_CONFIDENCE_EVIDENCE_LEVELS = {"reference", "example", "low_confidence"}
ALLOWED_INTERNAL_EVIDENCE_LEVELS = {
    "standard",
    "rule",
    "warning",
    "reference",
    "example",
    "low_confidence",
}
REQUIRED_INTERNAL_METADATA_FIELDS = {
    "source_type",
    "category",
    "visibility",
    "applicable_modes",
    "evidence_level",
    "last_reviewed",
}
REQUIRED_PRODUCT_MATCHING_FIELDS = {
    "product_id",
    "source_kind",
    "inventory_status",
    "destination",
    "theme",
    "duration",
    "audience",
    "persona_tags",
    "service_level",
    "price_band",
    "source",
    "category",
    "evidence_type",
}
PRODUCT_METADATA_FIELDS = {
    "product_id",
    "source_kind",
    "inventory_status",
    "external_product_ref",
    "destination",
    "theme",
    "duration",
    "audience",
    "persona_tags",
    "service_level",
    "price_band",
    "demo_price_label",
    "price_basis",
    "evidence_type",
    "service_boundary",
    "quote_basis",
    "included",
    "excluded",
    "transport_lodging_basis",
    "verification_items",
}
PROHIBITED_DYNAMIC_COMMITMENTS = (
    "锁价",
    "库存",
    "余票",
    "房型",
    "支付",
    "预订承诺",
    "成团状态",
    "客服联系方式",
)


class RetrievedEvidence(TypedDict):
    """Structured evidence returned by RAG-backed tools."""

    source: str
    source_type: str
    category: str
    visibility: str
    title: str
    snippet: str
    relevance_score: float
    evidence_level: str
    applicable_modes: list[str]
    constraints: list[str]
    user_segments: NotRequired[list[str]]
    budget_levels: NotRequired[list[str]]
    travel_days_range: NotRequired[str]
    regions: NotRequired[list[str]]
    product_id: NotRequired[str]
    source_kind: NotRequired[str]
    inventory_status: NotRequired[str]
    external_product_ref: NotRequired[str]
    destination: NotRequired[str]
    theme: NotRequired[str]
    duration: NotRequired[str]
    audience: NotRequired[list[str]]
    persona_tags: NotRequired[list[str]]
    service_level: NotRequired[str]
    price_band: NotRequired[str]
    demo_price_label: NotRequired[str]
    price_basis: NotRequired[list[str]]
    product_source: NotRequired[str]
    evidence_type: NotRequired[str]
    service_boundary: NotRequired[list[str]]
    quote_basis: NotRequired[list[str]]
    included: NotRequired[list[str]]
    excluded: NotRequired[list[str]]
    transport_lodging_basis: NotRequired[list[str]]
    verification_items: NotRequired[list[str]]
    last_reviewed: NotRequired[str]
    freshness_status: NotRequired[str]
    requires_verification: NotRequired[bool]
    prohibited_commitments: NotRequired[list[str]]


@dataclass(frozen=True)
class KnowledgeContract:
    """Metadata policy for one knowledge category."""

    category: str
    source_type: str
    visibility: str
    evidence_level: str
    applicable_modes: tuple[str, ...]
    constraints: tuple[str, ...]
    user_segments: tuple[str, ...] = ("general",)
    budget_levels: tuple[str, ...] = ("economy", "comfort", "luxury")
    travel_days_range: str = "1-14"
    regions: tuple[str, ...] = ("general",)
    last_reviewed: str = "2026-05-10"


PUBLIC_DESTINATION_CONTRACT = KnowledgeContract(
    category="destinations",
    source_type="destination_guide",
    visibility="public",
    evidence_level="guide",
    applicable_modes=("free_planning", "agency_plan"),
    constraints=(
        "仅可作为公开攻略参考",
        "门票、开放时间、预约、天气和价格必须出发前二次核实",
        "不得把其他目的地内容用于当前目的地",
    ),
    user_segments=("general", "family", "couple", "senior"),
    regions=("destination_specific",),
)


INTERNAL_CONTRACTS: dict[str, KnowledgeContract] = {
    "products": KnowledgeContract(
        category="products",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="standard",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可转化为成熟路线结构、适配人群和方案依据",
            "不得承诺真实库存、成团状态、锁价或履约结果",
            "自由行模式只引用路线结构，不做强销售表达",
        ),
        user_segments=("family", "couple", "senior", "team", "free_planning"),
        regions=("domestic", "general"),
    ),
    "sop": KnowledgeContract(
        category="sop",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="rule",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可转化为顾问服务流程和表达原则",
            "不得向用户暴露内部 SOP、工具名、RAG 或文档路径",
        ),
        user_segments=("general",),
        regions=("general",),
    ),
    "pricing": KnowledgeContract(
        category="pricing",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="rule",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "必须区分真实工具返回、模型估算和待核验价格",
            "不得承诺锁价、余票、房型、支付或免费退改",
            "费用说明必须保留费用包含、不含和待核验边界",
        ),
        user_segments=("general",),
        regions=("general",),
    ),
    "risk": KnowledgeContract(
        category="risk",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="warning",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可转化为温和、可行动的风险提醒和 Plan B",
            "不得制造焦虑或替代实时天气、交通、酒店、预约核验",
        ),
        user_segments=("family", "couple", "senior", "team", "general"),
        regions=("general",),
    ),
    "report": KnowledgeContract(
        category="report",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="standard",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可用于最终报告结构和禁止内容约束",
            "不得补写无事实来源的客服、优惠、支付链接或真实订单履约信息",
        ),
        user_segments=("general",),
        regions=("general",),
    ),
}

INTERNAL_CATEGORIES = set(INTERNAL_CONTRACTS)


@dataclass(frozen=True)
class MarkdownMetadata:
    """Parsed Markdown body plus optional front matter metadata."""

    metadata: dict[str, Any]
    body: str


@dataclass(frozen=True)
class KnowledgeValidationFinding:
    """One deterministic knowledge governance finding."""

    severity: str
    path: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "path": self.path,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class KnowledgeValidationReport:
    """Validation result for an internal knowledge directory."""

    checked_files: int
    findings: tuple[KnowledgeValidationFinding, ...]
    max_age_days: int = INTERNAL_REVIEW_MAX_AGE_DAYS

    @property
    def errors(self) -> tuple[KnowledgeValidationFinding, ...]:
        return tuple(item for item in self.findings if item.severity == "error")

    @property
    def warnings(self) -> tuple[KnowledgeValidationFinding, ...]:
        return tuple(item for item in self.findings if item.severity == "warning")

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "checked_files": self.checked_files,
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "max_age_days": self.max_age_days,
            "findings": [item.to_dict() for item in self.findings],
        }


def _join(values: tuple[str, ...]) -> str:
    return "|".join(values)


def _split(value: object, fallback: tuple[str, ...] = ()) -> list[str]:
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split("|") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(fallback)


def _metadata_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return _join(tuple(str(item).strip() for item in value if str(item).strip()))
    return str(value).strip()


def _fallback_front_matter_parser(raw: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in raw.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith((" ", "\t")) and current_key:
            item = raw_line.strip()
            if item.startswith("- "):
                existing = metadata.setdefault(current_key, [])
                if isinstance(existing, list):
                    existing.append(item[2:].strip().strip("'\""))
            continue
        if ":" not in raw_line:
            current_key = None
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        stripped = value.strip()
        if not stripped:
            metadata[current_key] = []
        elif stripped.startswith("[") and stripped.endswith("]"):
            metadata[current_key] = [
                item.strip().strip("'\"")
                for item in stripped.strip("[]").split(",")
                if item.strip()
            ]
        else:
            metadata[current_key] = stripped.strip("'\"")
    return metadata


def parse_markdown_metadata(text: str) -> MarkdownMetadata:
    """Parse YAML-style Markdown front matter and return a stripped body."""

    normalized = text.lstrip("\ufeff")
    if not normalized.startswith("---"):
        return MarkdownMetadata(metadata={}, body=normalized)

    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return MarkdownMetadata(metadata={}, body=normalized)

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break

    if closing_index is None:
        return MarkdownMetadata(metadata={}, body=normalized)

    raw_metadata = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :]).lstrip()
    if yaml is not None:
        loaded = yaml.safe_load(raw_metadata) or {}
        metadata = loaded if isinstance(loaded, dict) else {}
    else:
        metadata = _fallback_front_matter_parser(raw_metadata)
    return MarkdownMetadata(metadata=dict(metadata), body=body)


def parse_review_date(value: object) -> date | None:
    """Parse a last_reviewed value as an ISO date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def review_age_days(value: object, *, today: date | None = None) -> int | None:
    reviewed_at = parse_review_date(value)
    if reviewed_at is None:
        return None
    return ((today or date.today()) - reviewed_at).days


def freshness_status(
    last_reviewed: object,
    *,
    today: date | None = None,
    max_age_days: int = INTERNAL_REVIEW_MAX_AGE_DAYS,
) -> str:
    age = review_age_days(last_reviewed, today=today)
    if age is None:
        return "unknown"
    if age < 0:
        return "future"
    if age > max_age_days:
        return "expired"
    return "current"


def evidence_requires_verification(
    metadata: Mapping[str, Any],
    *,
    today: date | None = None,
    max_age_days: int = INTERNAL_REVIEW_MAX_AGE_DAYS,
) -> bool:
    """Return True when evidence must stay in a pending-verification lane."""

    evidence_level = str(metadata.get("evidence_level") or "").strip().lower()
    if evidence_level in LOW_CONFIDENCE_EVIDENCE_LEVELS:
        return True
    return freshness_status(
        metadata.get("last_reviewed"),
        today=today,
        max_age_days=max_age_days,
    ) in {"expired", "unknown", "future"}


def prohibited_commitments_for_metadata(metadata: Mapping[str, Any]) -> list[str]:
    """Return commitments that stale or low-confidence evidence must not support."""

    if evidence_requires_verification(metadata):
        return list(PROHIBITED_DYNAMIC_COMMITMENTS)
    return []


def get_contract(category: str | None, visibility: str | None = None) -> KnowledgeContract:
    """Return a category contract with conservative fallbacks."""

    normalized_visibility = (visibility or "").strip().lower()
    normalized_category = (category or "").strip().lower()
    if normalized_visibility == "public" or normalized_category == "destinations":
        return PUBLIC_DESTINATION_CONTRACT
    return INTERNAL_CONTRACTS.get(
        normalized_category,
        KnowledgeContract(
            category=normalized_category or "general",
            source_type="agency_internal",
            visibility="internal",
            evidence_level="reference",
            applicable_modes=("agency_plan", "free_planning"),
            constraints=(
                "仅可作为内部顾问参考",
                "不得对用户暴露内部文档或作出未核验承诺",
            ),
        ),
    )


def infer_category_from_source(source: object) -> str | None:
    """Infer a knowledge category from a document source path."""

    source_text = str(source or "").replace("\\", "/").lower()
    for category in INTERNAL_CONTRACTS:
        if f"/{category}/" in source_text or source_text.startswith(f"{category}/"):
            return category
    if "/destinations/" in source_text or source_text.endswith("xian.md"):
        return "destinations"
    return None


def infer_category_from_metadata(metadata: dict) -> str | None:
    """Infer a category from metadata first, then source path."""

    category = metadata.get("category")
    if isinstance(category, str) and category:
        return category
    return infer_category_from_source(metadata.get("source"))


def metadata_for_document(
    *,
    source_type: str,
    category: str,
    visibility: str,
    declared_metadata: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Build Chroma-safe document metadata for the RAG contract."""

    declared_metadata = declared_metadata or {}
    contract = get_contract(category, visibility)
    effective_category = str(declared_metadata.get("category") or category).strip()
    effective_visibility = str(declared_metadata.get("visibility") or visibility).strip()
    effective_source_type = str(
        declared_metadata.get("source_type") or source_type
    ).strip()
    effective_evidence_level = str(
        declared_metadata.get("evidence_level") or contract.evidence_level
    ).strip()
    effective_applicable_modes = _split(
        declared_metadata.get("applicable_modes"),
        contract.applicable_modes,
    )
    effective_last_reviewed = _metadata_value(
        declared_metadata.get("last_reviewed") or contract.last_reviewed
    )
    knowledge_base = (
        PUBLIC_KNOWLEDGE_BASE
        if effective_visibility == "public"
        else INTERNAL_KNOWLEDGE_BASE
    )
    metadata: dict[str, str] = {
        "contract_version": CONTRACT_VERSION,
        "knowledge_base": knowledge_base,
        "source_type": effective_source_type,
        "category": effective_category,
        "visibility": effective_visibility,
        "evidence_level": effective_evidence_level,
        "applicable_modes": _join(tuple(effective_applicable_modes)),
        "constraints": _join(
            tuple(_split(declared_metadata.get("constraints"), contract.constraints))
        ),
        "user_segments": _join(contract.user_segments),
        "budget_levels": _join(contract.budget_levels),
        "travel_days_range": contract.travel_days_range,
        "regions": _join(contract.regions),
        "last_reviewed": effective_last_reviewed,
    }
    if "title" in declared_metadata:
        metadata["title"] = _metadata_value(declared_metadata["title"])
    for field in sorted(PRODUCT_METADATA_FIELDS):
        if field in declared_metadata:
            metadata[field] = _metadata_value(declared_metadata[field])
    if effective_category == "products" and "source" in declared_metadata:
        metadata["product_source"] = _metadata_value(declared_metadata["source"])

    metadata["freshness_status"] = freshness_status(effective_last_reviewed)
    metadata["requires_verification"] = _metadata_value(
        evidence_requires_verification(metadata)
    )
    metadata["prohibited_commitments"] = _join(
        tuple(prohibited_commitments_for_metadata(metadata))
    )
    return metadata


def metadata_list(value: object, fallback: tuple[str, ...] = ()) -> list[str]:
    """Read a pipe-delimited metadata list."""

    return _split(value, fallback)


def normalized_source(metadata: dict) -> str:
    """Return a stable source reference for evidence."""

    source = metadata.get("source") or "unknown"
    try:
        return str(Path(str(source)))
    except (TypeError, ValueError):
        return str(source)


def _relative_path(path: Path, root: Path | None = None) -> str:
    try:
        return str(path.relative_to(root)) if root else str(path)
    except ValueError:
        return str(path)


def _finding(
    *,
    path: Path,
    field: str,
    message: str,
    root: Path | None = None,
    severity: str = "error",
) -> KnowledgeValidationFinding:
    return KnowledgeValidationFinding(
        severity=severity,
        path=_relative_path(path, root),
        field=field,
        message=message,
    )


def validate_internal_metadata(
    metadata: Mapping[str, Any],
    *,
    path: Path,
    internal_root: Path | None = None,
    today: date | None = None,
    max_age_days: int = INTERNAL_REVIEW_MAX_AGE_DAYS,
) -> list[KnowledgeValidationFinding]:
    """Validate internal knowledge metadata against the governance contract."""

    findings: list[KnowledgeValidationFinding] = []
    root = internal_root.resolve() if internal_root else None
    missing = [
        field
        for field in sorted(REQUIRED_INTERNAL_METADATA_FIELDS)
        if field not in metadata or metadata.get(field) in (None, "", [])
    ]
    for field in missing:
        findings.append(
            _finding(
                path=path,
                root=root,
                field=field,
                message=f"缺少内部知识 metadata 字段: {field}",
            )
        )

    source_type = str(metadata.get("source_type") or "").strip()
    if source_type and source_type != "agency_internal":
        findings.append(
            _finding(
                path=path,
                root=root,
                field="source_type",
                message="内部知识 source_type 必须是 agency_internal",
            )
        )

    visibility = str(metadata.get("visibility") or "").strip()
    if visibility and visibility != "internal":
        findings.append(
            _finding(
                path=path,
                root=root,
                field="visibility",
                message="内部知识 visibility 必须是 internal，不能误暴露为 public",
            )
        )

    category = str(metadata.get("category") or "").strip()
    if category and category not in INTERNAL_CATEGORIES:
        findings.append(
            _finding(
                path=path,
                root=root,
                field="category",
                message=f"内部知识 category 不在允许集合: {', '.join(sorted(INTERNAL_CATEGORIES))}",
            )
        )

    if internal_root:
        try:
            path_category = path.resolve().relative_to(internal_root.resolve()).parts[0]
        except (IndexError, ValueError):
            path_category = None
        if path_category and category and path_category != category:
            findings.append(
                _finding(
                    path=path,
                    root=root,
                    field="category",
                    message=f"category={category} 与目录分类 {path_category} 不一致",
                )
            )

    if category == "products":
        missing_product_fields = [
            field
            for field in sorted(REQUIRED_PRODUCT_MATCHING_FIELDS)
            if field not in metadata or metadata.get(field) in (None, "", [])
        ]
        for field in missing_product_fields:
            findings.append(
                _finding(
                    path=path,
                    root=root,
                    field=field,
                    message=f"产品知识缺少产品匹配字段: {field}",
                )
            )

    applicable_modes = set(metadata_list(metadata.get("applicable_modes")))
    invalid_modes = sorted(applicable_modes - PLANNING_MODES)
    if applicable_modes and invalid_modes:
        findings.append(
            _finding(
                path=path,
                root=root,
                field="applicable_modes",
                message=f"applicable_modes 包含非法模式: {', '.join(invalid_modes)}",
            )
        )

    evidence_level = str(metadata.get("evidence_level") or "").strip().lower()
    if evidence_level and evidence_level not in ALLOWED_INTERNAL_EVIDENCE_LEVELS:
        findings.append(
            _finding(
                path=path,
                root=root,
                field="evidence_level",
                message=(
                    "evidence_level 不在允许集合: "
                    f"{', '.join(sorted(ALLOWED_INTERNAL_EVIDENCE_LEVELS))}"
                ),
            )
        )

    reviewed_at = parse_review_date(metadata.get("last_reviewed"))
    if metadata.get("last_reviewed") and reviewed_at is None:
        findings.append(
            _finding(
                path=path,
                root=root,
                field="last_reviewed",
                message="last_reviewed 必须是 YYYY-MM-DD 格式",
            )
        )
    elif reviewed_at:
        status = freshness_status(
            reviewed_at,
            today=today,
            max_age_days=max_age_days,
        )
        if status == "future":
            findings.append(
                _finding(
                    path=path,
                    root=root,
                    field="last_reviewed",
                    message="last_reviewed 不能晚于当前日期",
                )
            )
        elif status == "expired":
            findings.append(
                _finding(
                    path=path,
                    root=root,
                    field="last_reviewed",
                    message=f"内部知识已超过 {max_age_days} 天未复审",
                )
            )

    return findings


def validate_internal_document_file(
    path: Path,
    *,
    internal_root: Path | None = None,
    today: date | None = None,
    max_age_days: int = INTERNAL_REVIEW_MAX_AGE_DAYS,
) -> list[KnowledgeValidationFinding]:
    """Validate one internal Markdown knowledge document."""

    text = path.read_text(encoding="utf-8")
    parsed = parse_markdown_metadata(text)
    findings = validate_internal_metadata(
        parsed.metadata,
        path=path,
        internal_root=internal_root,
        today=today,
        max_age_days=max_age_days,
    )

    if "sk-" in text or "BEGIN PRIVATE KEY" in text:
        findings.append(
            _finding(
                path=path,
                root=internal_root,
                field="content",
                message="内部知识文档疑似包含真实密钥或私钥片段",
            )
        )
    return findings


def validate_internal_knowledge_base(
    internal_dir: str | Path,
    *,
    today: date | None = None,
    max_age_days: int = INTERNAL_REVIEW_MAX_AGE_DAYS,
) -> KnowledgeValidationReport:
    """Validate all internal Markdown knowledge files for CI and local preflight."""

    root = Path(internal_dir)
    findings: list[KnowledgeValidationFinding] = []
    files = sorted(root.rglob("*.md")) if root.exists() else []
    if not root.exists():
        findings.append(
            KnowledgeValidationFinding(
                severity="error",
                path=str(root),
                field="path",
                message="内部知识目录不存在",
            )
        )

    for path in files:
        findings.extend(
            validate_internal_document_file(
                path,
                internal_root=root,
                today=today,
                max_age_days=max_age_days,
            )
        )

    return KnowledgeValidationReport(
        checked_files=len(files),
        findings=tuple(findings),
        max_age_days=max_age_days,
    )
