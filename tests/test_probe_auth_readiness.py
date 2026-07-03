import json

from scripts import check_probe_auth_readiness as probe


class FakeProbeAuthClient:
    def __init__(self, token="login-token", user_id="user-1", username="probe-user"):
        self.token = token
        self.user_id = user_id
        self.username = username
        self.post_calls = []
        self.get_calls = []

    def post_json(self, path, payload, *, token=None, timeout_seconds=20.0):
        self.post_calls.append(
            {
                "path": path,
                "payload": dict(payload),
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"access_token": self.token}

    def get_json(self, path, *, token, timeout_seconds=20.0):
        self.get_calls.append(
            {
                "path": path,
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"id": self.user_id, "username": self.username}


class FailingIfCalledClient(FakeProbeAuthClient):
    def post_json(self, path, payload, *, token=None, timeout_seconds=20.0):  # pragma: no cover
        raise AssertionError("plan mode must not call login")

    def get_json(self, path, *, token, timeout_seconds=20.0):  # pragma: no cover
        raise AssertionError("plan mode must not call /users/me")


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_probe_auth_plan_degrades_when_credentials_present_without_network():
    report = probe.build_probe_auth_readiness_report(
        base_url="https://private.example",
        access_token="secret-token",
        execute_login=False,
        client=FailingIfCalledClient(),
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["target"]["auth_strategy"] == "bearer_token"
    assert report["policy"]["execute_login_requested"] is False
    assert report["degraded_reasons"][0]["key"] == "auth_not_executed"
    assert "secret-token" not in payload
    assert "https://private.example" not in payload


def test_probe_auth_blocks_when_credentials_missing():
    report = probe.build_probe_auth_readiness_report(
        base_url="https://private.example",
        execute_login=False,
        environ={},
        client=FailingIfCalledClient(),
    )

    assert report["status"] == "blocked"
    assert report["target"]["auth_strategy"] == "missing"
    assert report["blocked_reasons"][0]["key"] == "missing_probe_auth"


def test_probe_auth_execute_validates_existing_token_without_echoing_values():
    client = FakeProbeAuthClient(user_id="private-user-id", username="private-user")
    report = probe.build_probe_auth_readiness_report(
        base_url="https://private.example",
        access_token="secret-token",
        execute_login=True,
        client=client,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["observations"]["login_performed"] is False
    assert report["observations"]["me_checked"] is True
    assert report["observations"]["token_validated"] is True
    assert client.post_calls == []
    assert client.get_calls[0]["path"] == "/api/v1/users/me"
    assert client.get_calls[0]["token"] == "secret-token"
    assert "secret-token" not in payload
    assert "private-user-id" not in payload
    assert "private-user" not in payload


def test_probe_auth_execute_login_then_validates_token_without_echoing_credentials():
    client = FakeProbeAuthClient(token="private-login-token")
    report = probe.build_probe_auth_readiness_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        execute_login=True,
        client=client,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["target"]["auth_strategy"] == "probe_login"
    assert report["target"]["access_token_source"] == "login"
    assert report["observations"]["login_performed"] is True
    assert client.post_calls[0]["path"] == "/api/v1/users/login"
    assert client.get_calls[0]["token"] == "private-login-token"
    assert "probe-user" not in payload
    assert "probe-password" not in payload
    assert "private-login-token" not in payload


def test_probe_auth_invalid_base_url_blocks_before_network():
    report = probe.build_probe_auth_readiness_report(
        base_url="/relative",
        access_token="secret-token",
        execute_login=True,
        client=FailingIfCalledClient(),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "invalid_target"


def test_probe_auth_markdown_is_redacted():
    report = probe.build_probe_auth_readiness_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        execute_login=False,
    )
    markdown = probe.build_probe_auth_readiness_markdown(report)

    assert "Probe Auth Readiness" in markdown
    assert "probe-user" not in markdown
    assert "probe-password" not in markdown
    assert "https://private.example" not in markdown
