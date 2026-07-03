import json

from scripts import check_security_release_readiness as readiness


def _valid_env() -> dict[str, str]:
    return {
        "ZHIXING_SECRET_STORE": "cloud secret manager",
        "ZHIXING_SECRET_OWNER": "deployment lead",
        "ZHIXING_SECRET_ROTATION_CADENCE": "90 days",
        "ZHIXING_LEAK_RESPONSE_OWNER": "security owner",
        "ZHIXING_JWT_SECRET_STATUS": "ready in secret store",
        "ZHIXING_PROVIDER_KEY_STATUS": "ready with budget caps",
        "ZHIXING_DATABASE_SECRET_STATUS": "managed and ready",
        "ZHIXING_REDIS_SECRET_STATUS": "rotated and ready",
        "ZHIXING_ALLOWED_ORIGINS_STATUS": "restricted to production domain",
        "ZHIXING_REAL_PAYMENT_ORDER_DISABLED": "true",
    }


def test_security_release_readiness_blocks_missing_inputs_without_dotenv():
    report = readiness.build_security_release_readiness_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["reads_secret_values"] is False
    assert report["policy"]["public_boundary_scan_requested"] is False
    assert any(item["env_var"] == "ZHIXING_SECRET_STORE" for item in report["blocked_reasons"])


def test_security_release_readiness_passes_complete_declarations_without_echoing_values():
    env = _valid_env()

    report = readiness.build_security_release_readiness_report(environ=env)
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    for value in [
        "cloud secret manager",
        "deployment lead",
        "security owner",
        "restricted to production domain",
    ]:
        assert value not in payload
    assert all(item["value_echoed"] is False for item in report["checks"])


def test_security_release_readiness_blocks_rotation_cadence_without_number():
    env = _valid_env()
    env["ZHIXING_SECRET_ROTATION_CADENCE"] = "after each trial"

    report = readiness.build_security_release_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_SECRET_ROTATION_CADENCE" for item in report["blocked_reasons"])


def test_security_release_readiness_blocks_unrestricted_browser_origins():
    env = _valid_env()
    env["ZHIXING_ALLOWED_ORIGINS_STATUS"] = "all origins allowed"

    report = readiness.build_security_release_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_ALLOWED_ORIGINS_STATUS" for item in report["blocked_reasons"])


def test_security_release_readiness_blocks_if_real_actions_are_enabled():
    env = _valid_env()
    env["ZHIXING_REAL_PAYMENT_ORDER_DISABLED"] = "false"

    report = readiness.build_security_release_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_REAL_PAYMENT_ORDER_DISABLED" for item in report["blocked_reasons"])


def test_security_release_readiness_can_include_public_boundary(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "build_public_release_boundary_report",
        lambda: {"status": "passed", "candidate_count": 3, "scanned_count": 3, "blocked_reasons": []},
    )

    report = readiness.build_security_release_readiness_report(
        environ=_valid_env(),
        check_public_boundary=True,
    )

    assert report["status"] == "passed"
    assert report["policy"]["public_boundary_scan_requested"] is True
    assert report["public_boundary"]["status"] == "passed"
    assert report["public_boundary"]["candidate_count"] == 3
