"""
配置管理模块
使用 pydantic-settings 管理环境变量
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from app.rag.readiness import (
    INTERNAL_VECTORSTORE_CONTRACT,
    PUBLIC_VECTORSTORE_CONTRACT,
    check_chroma_collection_readiness,
    rag_vectorstore_contract_details,
)

# 获取当前文件的上级目录（即项目根目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = Path(BASE_DIR)
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"


def _settings_env_file() -> str | None:
    if os.getenv("ZHIXING_DISABLE_DOTENV") == "1":
        return None
    return os.path.join(BASE_DIR, ".env")

RuntimeEnvironment = Literal["development", "test", "staging", "production"]
DependencyRequirement = Literal["required", "optional"]
ValuePolicy = Literal["configured", "real"]
EnvVarPolicy = Literal["all", "any"]

RUNTIME_ENVIRONMENTS: tuple[RuntimeEnvironment, ...] = (
    "development",
    "test",
    "staging",
    "production",
)
RUNTIME_READINESS_VERSION = "runtime_readiness.v1"

ENVIRONMENT_ALIASES: dict[str, RuntimeEnvironment] = {
    "dev": "development",
    "local": "development",
    "testing": "test",
    "tests": "test",
    "stage": "staging",
    "prod": "production",
}

PLACEHOLDER_MARKERS = (
    "your-",
    "change-me",
    "dev-only",
    "default",
    "placeholder",
    "not-a-real",
    "test-key",
    "dummy",
    "example",
)


@dataclass(frozen=True)
class RuntimeDependencySpec:
    """One runtime dependency in the environment readiness matrix."""

    key: str
    label: str
    description: str
    env_vars: tuple[str, ...]
    requirements: dict[RuntimeEnvironment, DependencyRequirement]
    category: str = "runtime"
    check: str = "configuration"
    env_var_policy: EnvVarPolicy = "all"
    optional_reason: str = ""
    mockable_in_test: bool = True

    def requirement_for(self, app_env: str | None = None) -> DependencyRequirement:
        return self.requirements[normalize_runtime_environment(app_env)]

    def to_dict(self, app_env: str | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload["env_vars"] = list(self.env_vars)
        payload["requirement"] = self.requirement_for(app_env)
        return payload


def _requirements(
    *,
    development: DependencyRequirement,
    test: DependencyRequirement,
    staging: DependencyRequirement,
    production: DependencyRequirement,
) -> dict[RuntimeEnvironment, DependencyRequirement]:
    return {
        "development": development,
        "test": test,
        "staging": staging,
        "production": production,
    }


RUNTIME_DEPENDENCY_SPECS: tuple[RuntimeDependencySpec, ...] = (
    RuntimeDependencySpec(
        key="postgresql",
        label="PostgreSQL（关系型数据库）",
        description="业务表、LangGraph checkpoint（执行检查点）、长期记忆和审批审计持久化。",
        env_vars=(
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        ),
        requirements=_requirements(
            development="required",
            test="optional",
            staging="required",
            production="required",
        ),
        category="storage",
        check="service",
        mockable_in_test=False,
    ),
    RuntimeDependencySpec(
        key="redis",
        label="Redis（内存数据结构存储）",
        description="多进程会话锁和未来横向扩展缓存；开发可降级为进程内本地锁。",
        env_vars=("REDIS_HOST", "REDIS_PORT", "REDIS_DB"),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="required",
            production="required",
        ),
        category="storage",
        check="service",
        optional_reason="development/test 可以使用本地会话锁替身。",
    ),
    RuntimeDependencySpec(
        key="llm",
        label="LLM（大语言模型）",
        description="主控 Agent、Router、RAG query optimizer（查询优化器）和报告生成模型。",
        env_vars=("DASHSCOPE_API_KEY",),
        requirements=_requirements(
            development="required",
            test="optional",
            staging="required",
            production="required",
        ),
        category="model",
        check="configuration",
    ),
    RuntimeDependencySpec(
        key="rag_vector_store",
        label="RAG（检索增强生成）向量库",
        description="本地目的地知识与旅行社内部知识检索所需 Chroma 向量库。",
        env_vars=(),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="required",
            production="required",
        ),
        category="knowledge",
        check="filesystem",
        optional_reason="开发和单元测试可以用内存/fixture（夹具）替身。",
    ),
    RuntimeDependencySpec(
        key="mcp",
        label="MCP（模型上下文协议）服务池",
        description="天气、搜索、地图、铁路、航班和酒店等外部能力的统一接入层。",
        env_vars=(),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="optional",
            production="optional",
        ),
        category="external_tooling",
        check="service",
        optional_reason="单个 MCP 服务不可用时应服务级降级，而不是拖垮核心会话。",
    ),
    RuntimeDependencySpec(
        key="map",
        label="地图 / 高德地图",
        description="路线预览、地理编码和部分天气 MCP 服务的上游能力。",
        env_vars=("AMAP_API_KEY",),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="required",
            production="required",
        ),
        category="external_api",
        check="configuration",
        optional_reason="开发可跳过地图预览，验收场景需要时会单独阻塞。",
    ),
    RuntimeDependencySpec(
        key="search",
        label="搜索 / Tavily",
        description="目的地补充搜索和公开信息补充能力。",
        env_vars=("TAVILY_API_KEY",),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="optional",
            production="optional",
        ),
        category="external_api",
        check="configuration",
        optional_reason="缺少时相关搜索能力降级，不能伪造搜索结果。",
    ),
    RuntimeDependencySpec(
        key="hotel",
        label="酒店 / aigohotel",
        description="真实酒店候选查询能力。",
        env_vars=("AIGOHOTEL_API_KEY", "AIGOHOTEL_MCP_API", "AIGOHOTEL_SECRET_KEY"),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="optional",
            production="optional",
        ),
        category="external_api",
        check="configuration",
        env_var_policy="any",
        optional_reason="缺少时酒店真实候选必须标记待二次核实。",
    ),
    RuntimeDependencySpec(
        key="flight",
        label="航班 / VariFlight",
        description="真实航班候选查询能力。",
        env_vars=("VARIFLIGHT_API_KEY",),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="optional",
            production="optional",
        ),
        category="external_api",
        check="configuration",
        optional_reason="缺少时航班真实候选必须标记待二次核实。",
    ),
    RuntimeDependencySpec(
        key="rail",
        label="铁路 / 12306 MCP",
        description="铁路候选查询能力。",
        env_vars=(),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="optional",
            production="optional",
        ),
        category="external_api",
        check="service",
        optional_reason="外部服务不可用时高铁候选必须标记待二次核实。",
    ),
    RuntimeDependencySpec(
        key="langsmith",
        label="LangSmith（LangChain 可观测平台）",
        description="链路追踪和调试观测能力。",
        env_vars=("LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_TRACING"),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="optional",
            production="optional",
        ),
        category="observability",
        check="configuration",
        optional_reason="缺少时不影响核心规划，但会降低排障可观测性。",
    ),
    RuntimeDependencySpec(
        key="auth_jwt",
        label="Auth（认证）/ JWT（JSON Web Token，令牌认证）",
        description="用户登录态签名密钥；生产和验收环境必须使用非默认、非占位的真实密钥。",
        env_vars=("JWT_SECRET_KEY", "JWT_ALGORITHM"),
        requirements=_requirements(
            development="optional",
            test="optional",
            staging="required",
            production="required",
        ),
        category="security",
        check="configuration",
        optional_reason="development/test 可以使用默认开发密钥，staging/production 不允许。",
        mockable_in_test=False,
    ),
)


def normalize_runtime_environment(app_env: str | None = None) -> RuntimeEnvironment:
    """Normalize APP_ENV into one of the four supported runtime tiers."""

    raw = str(app_env or os.getenv("APP_ENV") or "development").strip().lower()
    normalized = ENVIRONMENT_ALIASES.get(raw, raw)
    if normalized in RUNTIME_ENVIRONMENTS:
        return normalized  # type: ignore[return-value]
    return "development"


def value_policy_for_environment(app_env: str | None = None) -> ValuePolicy:
    """Return whether this environment accepts mock-like values or requires real ones."""

    return "real" if normalize_runtime_environment(app_env) in {"staging", "production"} else "configured"


def has_configured_value(value: str | None) -> bool:
    return value is not None and bool(str(value).strip())


def has_real_env_value(value: str | None) -> bool:
    if not has_configured_value(value):
        return False
    normalized = str(value).strip().lower()
    return not any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def env_value_satisfies_policy(value: str | None, *, policy: ValuePolicy) -> bool:
    if policy == "real":
        return has_real_env_value(value)
    return has_configured_value(value)


def load_effective_environment(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> tuple[dict[str, str], bool]:
    """Load process environment over an optional .env without exposing values."""

    path = dotenv_path or DEFAULT_DOTENV_PATH
    should_load_dotenv = environ is None or dotenv_path is not None
    dotenv_map = (
        {
            key: value
            for key, value in dotenv_values(path).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if should_load_dotenv and path.exists()
        else {}
    )
    effective = dict(dotenv_map)
    effective.update(dict(os.environ if environ is None else environ))
    return effective, path.exists()


def dependency_specs_by_key() -> dict[str, RuntimeDependencySpec]:
    return {spec.key: spec for spec in RUNTIME_DEPENDENCY_SPECS}


def runtime_dependency_matrix(app_env: str | None = None) -> dict[str, dict[str, Any]]:
    """Return the dependency matrix resolved for one runtime tier."""

    env = normalize_runtime_environment(app_env)
    return {spec.key: spec.to_dict(env) for spec in RUNTIME_DEPENDENCY_SPECS}


def _status_for_env_group(
    env: Mapping[str, str],
    env_vars: tuple[str, ...],
    *,
    requirement: DependencyRequirement,
    policy: ValuePolicy,
    env_var_policy: EnvVarPolicy = "all",
) -> tuple[str, list[str]]:
    if not env_vars:
        return "unknown", []
    present = [name for name in env_vars if has_configured_value(env.get(name))]
    valid = [name for name in env_vars if env_value_satisfies_policy(env.get(name), policy=policy)]
    if (env_var_policy == "any" and valid) or (
        env_var_policy == "all" and len(valid) == len(env_vars)
    ):
        return "configured", []

    missing = [name for name in env_vars if name not in present]
    placeholders = [name for name in present if name not in valid]
    findings: list[str] = []
    if missing:
        findings.append("Missing environment variables: " + ", ".join(missing))
    if placeholders:
        findings.append("Placeholder or non-real values: " + ", ".join(placeholders))
    if requirement == "required":
        return "blocked", findings
    return "not_configured", findings


def _resolve_project_path(configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _filesystem_dependency_status(
    spec: RuntimeDependencySpec,
    env: Mapping[str, str],
    *,
    requirement: DependencyRequirement,
) -> tuple[str, list[str], dict[str, Any]]:
    if spec.key != "rag_vector_store":
        return "service_checked", [], {}

    configured_path = env.get("RAG_VECTORSTORE_PATH") or "data/vectorstore"
    collection_name = env.get("RAG_COLLECTION_NAME") or "travel_guides"
    internal_configured_path = env.get("RAG_INTERNAL_VECTORSTORE_PATH") or "data/vectorstore_internal"
    internal_collection_name = env.get("RAG_INTERNAL_COLLECTION_NAME") or "agency_internal_knowledge"
    vectorstore_path = Path(configured_path)
    if not vectorstore_path.is_absolute():
        vectorstore_path = PROJECT_ROOT / vectorstore_path
    details = {
        "path": str(vectorstore_path),
        "collection_name": collection_name,
        "contract": rag_vectorstore_contract_details(),
        "stores": {},
    }

    findings: list[str] = []
    public_check = check_chroma_collection_readiness(
        configured_path=configured_path,
        collection_name=collection_name,
        label=PUBLIC_VECTORSTORE_CONTRACT["label"],
        expected_metadata={
            "contract_version": "rag.evidence.v1",
            "knowledge_base": PUBLIC_VECTORSTORE_CONTRACT["knowledge_base"],
            "visibility": PUBLIC_VECTORSTORE_CONTRACT["visibility"],
        },
        required_metadata=PUBLIC_VECTORSTORE_CONTRACT["required_metadata"],
        retrieval_probes=PUBLIC_VECTORSTORE_CONTRACT["retrieval_probes"],
        project_root=PROJECT_ROOT,
    )
    public_finding = public_check.finding
    public_details = public_check.details
    details["stores"]["public"] = public_details
    if public_details.get("metadata_path"):
        details["metadata_path"] = public_details["metadata_path"]
    if public_finding:
        findings.append(public_finding)

    internal_check = check_chroma_collection_readiness(
        configured_path=internal_configured_path,
        collection_name=internal_collection_name,
        label=INTERNAL_VECTORSTORE_CONTRACT["label"],
        expected_metadata={
            "contract_version": "rag.evidence.v1",
            "knowledge_base": INTERNAL_VECTORSTORE_CONTRACT["knowledge_base"],
            "visibility": INTERNAL_VECTORSTORE_CONTRACT["visibility"],
        },
        required_metadata=INTERNAL_VECTORSTORE_CONTRACT["required_metadata"],
        retrieval_probes=INTERNAL_VECTORSTORE_CONTRACT["retrieval_probes"],
        project_root=PROJECT_ROOT,
    )
    internal_finding = internal_check.finding
    internal_details = internal_check.details
    details["stores"]["internal"] = internal_details
    if internal_finding:
        findings.append(internal_finding)

    if findings:
        status = "blocked" if requirement == "required" else "not_configured"
        return status, findings, details

    return "configured", [], details


def runtime_configuration_snapshot(
    *,
    app_env: str | None = None,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    require_real_values: bool | None = None,
) -> dict[str, Any]:
    """Summarize runtime configuration without returning secret values."""

    env, dotenv_present = load_effective_environment(environ=environ, dotenv_path=dotenv_path)
    resolved_env = normalize_runtime_environment(app_env or env.get("APP_ENV"))
    policy: ValuePolicy = "real" if require_real_values else value_policy_for_environment(resolved_env)
    dependencies: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []
    degraded_optional: list[str] = []

    for spec in RUNTIME_DEPENDENCY_SPECS:
        requirement = spec.requirement_for(resolved_env)
        details: dict[str, Any] = {}
        if spec.check == "filesystem":
            env_status, findings, details = _filesystem_dependency_status(
                spec,
                env,
                requirement=requirement,
            )
            status = env_status
        else:
            env_status, findings = _status_for_env_group(
                env,
                spec.env_vars,
                requirement=requirement,
                policy=policy,
                env_var_policy=spec.env_var_policy,
            )
            details = {}
            if spec.env_vars:
                if env_status == "configured":
                    status = "configured"
                elif requirement == "required":
                    status = "blocked"
                else:
                    status = "not_configured"
            else:
                status = "service_checked" if spec.check == "service" else "not_configured"

        if status == "blocked":
            missing_required.append(spec.key)
        elif status == "not_configured":
            degraded_optional.append(spec.key)

        dependencies[spec.key] = {
            "key": spec.key,
            "label": spec.label,
            "description": spec.description,
            "category": spec.category,
            "check": spec.check,
            "requirement": requirement,
            "status": status,
            "env_vars": list(spec.env_vars),
            "value_policy": policy,
            "mockable_in_test": spec.mockable_in_test,
            "optional_reason": spec.optional_reason,
            "findings": findings,
            "details": details,
        }

    if missing_required:
        status = "blocked"
    elif degraded_optional:
        status = "degraded"
    else:
        status = "passed"

    return {
        "version": RUNTIME_READINESS_VERSION,
        "environment": resolved_env,
        "value_policy": policy,
        "dotenv_present": dotenv_present,
        "status": status,
        "dependencies": dependencies,
        "missing_required": missing_required,
        "degraded_optional": degraded_optional,
    }

class Settings(BaseSettings):
    """应用配置"""

    # ============== 应用基础配置 ==============
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    debug: bool = Field(default=False, alias="DEBUG")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")
    cors_allowed_origins_raw: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    # ============== Runtime 启动韧性配置 ==============
    runtime_startup_dependency_timeout_seconds: float = Field(
        default=12.0,
        alias="RUNTIME_STARTUP_DEPENDENCY_TIMEOUT_SECONDS",
    )
    runtime_mcp_startup_timeout_seconds: float = Field(
        default=25.0,
        alias="RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS",
    )
    runtime_mcp_optional_startup_timeout_seconds: float = Field(
        default=25.0,
        alias="RUNTIME_MCP_OPTIONAL_STARTUP_TIMEOUT_SECONDS",
    )

    # ============== LLM 配置 ==============
    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    qwen_model_name: str = Field(default="qwen3.6-plus", alias="QWEN_MODEL_NAME")
    qwen_planner_model_name: str = Field(default="qwen3.6-plus", alias="QWEN_PLANNER_MODEL_NAME")
    qwen_router_model_name: str = Field(default="qwen3.6-flash", alias="QWEN_ROUTER_MODEL_NAME")
    qwen_rag_model_name: str = Field(default="qwen3.6-flash", alias="QWEN_RAG_MODEL_NAME")
    qwen_vision_model_name: str = Field(default="qwen3.6-plus", alias="QWEN_VISION_MODEL_NAME")
    qwen_report_model_name: str = Field(default="qwen3.6-plus", alias="QWEN_REPORT_MODEL_NAME")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL"
    )
    qwen_temperature: float = 0.7
    qwen_max_tokens: int = 8000
    qwen_request_timeout_seconds: float = Field(default=180.0, alias="QWEN_REQUEST_TIMEOUT_SECONDS")
    qwen_max_retries: int = Field(default=1, alias="QWEN_MAX_RETRIES")

    # ============== LangSmith 配置 ==============
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="travel-planner-dev", alias="LANGSMITH_PROJECT")
    langsmith_tracing: bool = Field(default=True, alias="LANGSMITH_TRACING")
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        alias="LANGSMITH_ENDPOINT"
    )

    # ============== 数据库配置 ==============
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="travel_planner_db", alias="POSTGRES_DB")
    postgres_user: str = Field(default="travel_user", alias="POSTGRES_USER")
    postgres_password: str = Field(default="change-me", alias="POSTGRES_PASSWORD")
    postgres_connect_timeout_seconds: float = Field(
        default=5.0,
        alias="POSTGRES_CONNECT_TIMEOUT_SECONDS",
    )
    postgres_pool_timeout_seconds: float = Field(
        default=5.0,
        alias="POSTGRES_POOL_TIMEOUT_SECONDS",
    )
    postgres_statement_timeout_seconds: float = Field(
        default=10.0,
        alias="POSTGRES_STATEMENT_TIMEOUT_SECONDS",
    )

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")

    rag_vectorstore_path: str = Field(default="data/vectorstore", alias="RAG_VECTORSTORE_PATH")
    rag_collection_name: str = Field(default="travel_guides", alias="RAG_COLLECTION_NAME")
    rag_internal_vectorstore_path: str = Field(
        default="data/vectorstore_internal",
        alias="RAG_INTERNAL_VECTORSTORE_PATH",
    )
    rag_internal_collection_name: str = Field(
        default="agency_internal_knowledge",
        alias="RAG_INTERNAL_COLLECTION_NAME",
    )
    rag_enable_multimodal_auto_extract: bool = Field(
        default=False,
        alias="RAG_ENABLE_MULTIMODAL_AUTO_EXTRACT",
    )
    rag_multimodal_cache_path: str = Field(
        default=".runtime/rag_multimodal_cache",
        alias="RAG_MULTIMODAL_CACHE_PATH",
    )
    rag_multimodal_max_image_bytes: int = Field(
        default=6_000_000,
        alias="RAG_MULTIMODAL_MAX_IMAGE_BYTES",
    )
    rag_multimodal_video_frame_count: int = Field(
        default=3,
        alias="RAG_MULTIMODAL_VIDEO_FRAME_COUNT",
    )
    rag_multimodal_video_frame_width: int = Field(
        default=640,
        alias="RAG_MULTIMODAL_VIDEO_FRAME_WIDTH",
    )
    rag_ffmpeg_path: str = Field(default="", alias="RAG_FFMPEG_PATH")
    rag_multimodal_transcript_command: str = Field(
        default="",
        alias="RAG_MULTIMODAL_TRANSCRIPT_COMMAND",
    )

    # ============== 会话一致性配置 ==============
    session_lock_backend: str = Field(default="auto", alias="SESSION_LOCK_BACKEND")
    session_lock_key_prefix: str = Field(
        default="zhixing:session_lock",
        alias="SESSION_LOCK_KEY_PREFIX",
    )
    session_lock_ttl_seconds: float = Field(
        default=300.0,
        alias="SESSION_LOCK_TTL_SECONDS",
    )
    session_lock_renew_interval_seconds: float = Field(
        default=30.0,
        alias="SESSION_LOCK_RENEW_INTERVAL_SECONDS",
    )
    session_lock_acquire_wait_seconds: float = Field(
        default=0.0,
        alias="SESSION_LOCK_ACQUIRE_WAIT_SECONDS",
    )
    session_lock_busy_retry_after_seconds: int = Field(
        default=3,
        alias="SESSION_LOCK_BUSY_RETRY_AFTER_SECONDS",
    )
    session_lock_redis_operation_timeout_seconds: float = Field(
        default=0.5,
        alias="SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS",
    )
    session_lock_redis_fallback_to_local: bool = Field(
        default=True,
        alias="SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL",
    )
    session_lock_redis_retry_interval_seconds: float = Field(
        default=5.0,
        alias="SESSION_LOCK_REDIS_RETRY_INTERVAL_SECONDS",
    )

    # ============== API 过载保护配置 ==============
    api_rate_limit_enabled: bool = Field(default=False, alias="API_RATE_LIMIT_ENABLED")
    api_rate_limit_backend: str = Field(default="redis", alias="API_RATE_LIMIT_BACKEND")
    api_rate_limit_requests_per_window: int = Field(
        default=120,
        alias="API_RATE_LIMIT_REQUESTS_PER_WINDOW",
    )
    api_rate_limit_window_seconds: int = Field(default=60, alias="API_RATE_LIMIT_WINDOW_SECONDS")
    api_rate_limit_key_prefix: str = Field(
        default="zhixing:rate_limit",
        alias="API_RATE_LIMIT_KEY_PREFIX",
    )
    api_rate_limit_protected_prefixes_raw: str = Field(
        default="/api/v1",
        alias="API_RATE_LIMIT_PROTECTED_PREFIXES",
    )
    api_rate_limit_exempt_paths_raw: str = Field(
        default="",
        alias="API_RATE_LIMIT_EXEMPT_PATHS",
    )
    api_rate_limit_local_fallback: bool = Field(
        default=False,
        alias="API_RATE_LIMIT_LOCAL_FALLBACK",
    )
    api_rate_limit_redis_operation_timeout_seconds: float = Field(
        default=0.5,
        alias="API_RATE_LIMIT_REDIS_OPERATION_TIMEOUT_SECONDS",
    )
    chat_turn_quota_enabled: bool = Field(default=False, alias="CHAT_TURN_QUOTA_ENABLED")
    chat_turn_quota_daily_limit: int = Field(default=30, alias="CHAT_TURN_QUOTA_DAILY_LIMIT")
    chat_turn_quota_admin_exempt: bool = Field(
        default=True,
        alias="CHAT_TURN_QUOTA_ADMIN_EXEMPT",
    )

    # ============== LangGraph 运行配置 ==============
    langgraph_recursion_limit: int = Field(default=60, alias="LANGGRAPH_RECURSION_LIMIT")

    # ============== MCP 服务配置 ==============
    amap_api_key: str = Field(default="", alias="AMAP_API_KEY")
    amap_web_js_key: str = Field(default="", alias="AMAP_WEB_JS_KEY")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    variflight_api_key: str = Field(default="", alias="VARIFLIGHT_API_KEY")
    aigohotel_api_key: str = Field(default="", alias="AIGOHOTEL_API_KEY")
    aigohotel_mcp_api: str = Field(default="", alias="AIGOHOTEL_MCP_API")
    aigohotel_secret_key: str = Field(default="", alias="AIGOHOTEL_SECRET_KEY")
    jwt_secret_key: str = Field(default="dev-only-jwt-secret-change-me", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60 * 24 * 7, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    auth_cookie_name: str = Field(default="zhixing_access_token", alias="AUTH_COOKIE_NAME")
    auth_cookie_secure: bool = Field(default=False, alias="AUTH_COOKIE_SECURE")
    auth_cookie_samesite: str = Field(default="lax", alias="AUTH_COOKIE_SAMESITE")
    auth_registration_enabled: bool = Field(default=True, alias="AUTH_REGISTRATION_ENABLED")
    auth_rate_limit_max_attempts: int = Field(default=5, alias="AUTH_RATE_LIMIT_MAX_ATTEMPTS")
    auth_rate_limit_window_seconds: int = Field(default=600, alias="AUTH_RATE_LIMIT_WINDOW_SECONDS")

    model_config = SettingsConfigDict(
        env_file=_settings_env_file(),     # 自动拼接路径，不管代码在哪运行都能找到
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"              # 忽略 .env 中多余的字段，防止报错
    )

    @property
    def database_url(self) -> str:
        """生成 PostgreSQL 连接字符串"""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """生成 Redis 连接字符串"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def api_rate_limit_protected_prefixes(self) -> list[str]:
        return [
            value.strip()
            for value in self.api_rate_limit_protected_prefixes_raw.split(",")
            if value.strip()
        ] or ["/api/v1"]

    @property
    def api_rate_limit_exempt_paths(self) -> list[str]:
        return [
            value.strip()
            for value in self.api_rate_limit_exempt_paths_raw.split(",")
            if value.strip()
        ]

    @property
    def runtime_environment(self) -> RuntimeEnvironment:
        """当前运行环境档位。"""
        return normalize_runtime_environment(self.app_env)

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Return an explicit CORS allowlist instead of using wildcard origins."""

        if self.cors_allowed_origins_raw.strip():
            origins = [
                value.strip()
                for value in self.cors_allowed_origins_raw.split(",")
                if value.strip()
            ]
            return list(dict.fromkeys(origins))

        if self.runtime_environment in {"development", "test"}:
            return [
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "null",
            ]

        return []

    @property
    def allow_origin_regex(self) -> str | None:
        """Allow localhost/dev ports without reopening wildcard access."""

        if self.runtime_environment in {"development", "test"}:
            return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
        return None

    @property
    def auth_cookie_secure_resolved(self) -> bool:
        """Secure cookies are mandatory outside local development/test."""

        if self.auth_cookie_secure:
            return True
        return self.runtime_environment in {"staging", "production"}

    @property
    def auth_cookie_samesite_resolved(self) -> str:
        raw = str(self.auth_cookie_samesite or "lax").strip().lower()
        if raw in {"lax", "strict", "none"}:
            return raw
        return "lax"

    def validate_security_baseline(self) -> None:
        """Fail fast when a production-like environment keeps unsafe auth defaults."""

        if self.runtime_environment not in {"staging", "production"}:
            return

        findings: list[str] = []
        if not has_real_env_value(self.jwt_secret_key):
            findings.append("JWT_SECRET_KEY must be a real non-placeholder secret")
        if self.auth_cookie_samesite_resolved == "none" and not self.auth_cookie_secure_resolved:
            findings.append("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true")

        invalid_origins = [
            origin
            for origin in self.cors_allowed_origins
            if origin != "null" and not urlparse(origin).scheme
        ]
        if invalid_origins:
            findings.append(
                "CORS_ALLOWED_ORIGINS contains invalid origins: " + ", ".join(invalid_origins)
            )

        if findings:
            raise ValueError("; ".join(findings))


@lru_cache
def get_settings() -> Settings:
    """获取配置单例（缓存）"""
    return Settings()


# 全局配置对象
settings = get_settings()

# 测试
# if __name__ == '__main__':
#     print(settings.database_url)
#     print(settings.redis_url)
#     print(settings.qwen_model_name)
#     print(settings.qwen_base_url)
#     print(settings.qwen_temperature)
#     print(settings.qwen_max_tokens)
#     print(settings.langsmith_api_key)
