import json

from scripts import check_external_api_readiness as readiness


def _valid_env() -> dict[str, str]:
    return {
        "ZHIXING_LLM_PROVIDER_READY": "ready",
        "ZHIXING_MAP_API_READY": "ready",
        "ZHIXING_OPTIONAL_EXTERNAL_APIS": "none",
        "ZHIXING_EXTERNAL_API_QUOTA_BUDGET": "LLM 200 CNY/day, map 10000 calls/day",
        "ZHIXING_PROVIDER_CONSOLE_OWNER": "ops owner",
        "ZHIXING_PROVIDER_SUPPORT_CHANNEL": "provider ticket and ops email",
        "ZHIXING_EXTERNAL_API_DEGRADATION_POLICY": "search can degrade; flight/hotel stay manual and pending verification",
        "ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY": "timeout 15 seconds, retry 1 time with backoff",
    }


def test_external_api_readiness_blocks_missing_inputs_without_dotenv_or_network():
    report = readiness.build_external_api_readiness_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["calls_external_providers"] is False
    assert report["policy"]["reads_secret_values"] is False
    assert any(item["env_var"] == "ZHIXING_LLM_PROVIDER_READY" for item in report["blocked_reasons"])


def test_external_api_readiness_passes_complete_minimal_declarations_without_echoing_values():
    env = _valid_env()

    report = readiness.build_external_api_readiness_report(environ=env)
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["optional_services"] == []
    assert report["blocked_reasons"] == []
    for value in [
        "ops owner",
        "provider ticket and ops email",
        "LLM 200 CNY/day",
        "timeout 15 seconds",
    ]:
        assert value not in payload
    assert all(item["value_echoed"] is False for item in [*report["checks"], *report["service_checks"]])


def test_external_api_readiness_blocks_budget_without_number():
    env = _valid_env()
    env["ZHIXING_EXTERNAL_API_QUOTA_BUDGET"] = "budget is configured"

    report = readiness.build_external_api_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_EXTERNAL_API_QUOTA_BUDGET" for item in report["blocked_reasons"])


def test_external_api_readiness_blocks_timeout_policy_without_retry():
    env = _valid_env()
    env["ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY"] = "timeout 15 seconds"

    report = readiness.build_external_api_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY" for item in report["blocked_reasons"])


def test_external_api_readiness_blocks_enabled_optional_service_without_status():
    env = _valid_env()
    env["ZHIXING_OPTIONAL_EXTERNAL_APIS"] = "tavily"

    report = readiness.build_external_api_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert report["optional_services"] == ["tavily"]
    assert any(item["env_var"] == "ZHIXING_TAVILY_SERVICE_STATUS" for item in report["blocked_reasons"])


def test_external_api_readiness_reports_degraded_optional_service():
    env = _valid_env()
    env["ZHIXING_OPTIONAL_EXTERNAL_APIS"] = "tavily,variflight"
    env["ZHIXING_TAVILY_SERVICE_STATUS"] = "ready"
    env["ZHIXING_VARIFLIGHT_SERVICE_STATUS"] = "degraded, manual verification required"

    report = readiness.build_external_api_readiness_report(environ=env)

    assert report["status"] == "degraded"
    assert report["blocked_reasons"] == []
    assert any(item["env_var"] == "ZHIXING_VARIFLIGHT_SERVICE_STATUS" for item in report["degraded_reasons"])


def test_external_api_readiness_blocks_optional_service_marked_disabled_after_enabled():
    env = _valid_env()
    env["ZHIXING_OPTIONAL_EXTERNAL_APIS"] = "aigohotel"
    env["ZHIXING_AIGOHOTEL_SERVICE_STATUS"] = "disabled"

    report = readiness.build_external_api_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_AIGOHOTEL_SERVICE_STATUS" for item in report["blocked_reasons"])
