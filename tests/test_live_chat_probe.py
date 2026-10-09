import json
from urllib.error import HTTPError

from scripts import collect_live_chat_probe as probe


class FakeChatClient:
    def __init__(self, events=None, conversation_id="private-conversation-id"):
        self.events = events or [
            {"type": "token", "content": "private assistant text"},
            {"type": "done", "turn_id": "turn-1"},
        ]
        self.conversation_id = conversation_id
        self.post_calls = []
        self.stream_calls = []

    def post_json(self, path, payload, *, token=None, timeout_seconds):
        self.post_calls.append(
            {
                "path": path,
                "payload": dict(payload),
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        if path == "/api/v1/users/login":
            return {"access_token": "private-login-token"}
        if path == "/api/v1/users/register":
            return {"access_token": "private-register-token"}
        return {"id": self.conversation_id}

    def stream_json_events(self, path, payload, *, token, timeout_seconds):
        self.stream_calls.append(
            {
                "path": path,
                "payload": dict(payload),
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        yield from self.events


class FailingIfCalledClient(FakeChatClient):
    def post_json(self, path, payload, *, token=None, timeout_seconds=None):  # pragma: no cover
        raise AssertionError("plan-only mode must not call the API")

    def stream_json_events(self, path, payload, *, token, timeout_seconds):  # pragma: no cover
        raise AssertionError("plan-only mode must not stream chat")


class RegisterConflictClient(FakeChatClient):
    def post_json(self, path, payload, *, token=None, timeout_seconds):
        if path == "/api/v1/users/register":
            self.post_calls.append(
                {
                    "path": path,
                    "payload": dict(payload),
                    "token": token,
                    "timeout_seconds": timeout_seconds,
                }
            )
            raise HTTPError(path, 400, "Bad Request", hdrs=None, fp=None)
        return super().post_json(path, payload, token=token, timeout_seconds=timeout_seconds)


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_plan_only_live_chat_probe_does_not_call_network():
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        access_token="secret-token",
        execute=False,
        client=FailingIfCalledClient(),
    )
    payload = _payload_text(report)

    assert report["status"] == "not_checked"
    assert report["policy"]["execute_requested"] is False
    assert report["policy"]["calls_llm"] is False
    assert report["plan"]["requires_private_auth"] is True
    assert "secret-token" not in payload
    assert "https://private.example" not in payload
    assert "<public-url>" in payload
    assert report["plan"]["supports_probe_registration"] is True
    assert "--register-probe-user" in report["plan"]["registration_command"]


def test_execute_live_chat_probe_passes_without_echoing_sensitive_values():
    client = FakeChatClient()
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        access_token="secret-token",
        prompt="private prompt with phone 13800138000",
        execute=True,
        client=client,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["target"]["base_url"] == "<public-url>"
    assert report["policy"]["calls_llm"] is True
    assert report["policy"]["creates_real_payment"] is False
    assert report["observations"]["conversation_created"] is True
    assert report["observations"]["conversation_id"] == "<conversation-id>"
    assert report["observations"]["event_type_counts"] == {"done": 1, "token": 1}
    assert report["observations"]["assistant_chars_observed"] == len("private assistant text")
    assert client.post_calls[0]["token"] == "secret-token"
    assert client.stream_calls[0]["payload"]["content"] == "private prompt with phone 13800138000"
    assert "secret-token" not in payload
    assert "https://private.example" not in payload
    assert "private prompt" not in payload
    assert "13800138000" not in payload
    assert "private assistant text" not in payload
    assert "private-conversation-id" not in payload


def test_execute_live_chat_probe_can_login_with_probe_credentials_without_echoing_them():
    client = FakeChatClient()
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        execute=True,
        client=client,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["target"]["auth_strategy"] == "probe_login"
    assert report["target"]["access_token_source"] == "login"
    assert report["observations"]["login_performed"] is True
    assert client.post_calls[0]["path"] == "/api/v1/users/login"
    assert client.post_calls[0]["token"] is None
    assert client.post_calls[1]["token"] == "private-login-token"
    assert client.stream_calls[0]["token"] == "private-login-token"
    assert "probe-user" not in payload
    assert "probe-password" not in payload
    assert "private-login-token" not in payload


def test_execute_live_chat_probe_can_register_probe_user_without_echoing_values():
    client = FakeChatClient()
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        email="probe@example.com",
        register_probe_user=True,
        execute=True,
        client=client,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["policy"]["creates_probe_user"] is True
    assert report["policy"]["writes_runtime_user_record"] is True
    assert report["target"]["access_token_source"] == "registration"
    assert report["observations"]["registration_attempted"] is True
    assert report["observations"]["registration_performed"] is True
    assert report["observations"]["login_performed"] is False
    assert client.post_calls[0]["path"] == "/api/v1/users/register"
    assert client.post_calls[1]["token"] == "private-register-token"
    assert "probe-user" not in payload
    assert "probe-password" not in payload
    assert "probe@example.com" not in payload
    assert "private-register-token" not in payload


def test_execute_live_chat_probe_reuses_existing_probe_user_after_register_conflict():
    client = RegisterConflictClient()
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        email="probe@example.com",
        register_probe_user=True,
        execute=True,
        client=client,
    )

    assert report["status"] == "passed"
    assert report["target"]["access_token_source"] == "login_after_registration_conflict"
    assert report["observations"]["registration_attempted"] is True
    assert report["observations"]["registration_performed"] is False
    assert report["observations"]["existing_probe_user_reused"] is True
    assert report["observations"]["login_performed"] is True
    assert [call["path"] for call in client.post_calls[:3]] == [
        "/api/v1/users/register",
        "/api/v1/users/login",
        "/api/v1/conversations",
    ]


def test_execute_live_chat_probe_blocks_registration_when_email_missing():
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        register_probe_user=True,
        execute=True,
        environ={},
        client=FailingIfCalledClient(),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_probe_registration_inputs"
    assert report["target"]["email_present"] is False


def test_execute_live_chat_probe_blocks_when_auth_missing():
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        execute=True,
        environ={},
        client=FailingIfCalledClient(),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_auth_credentials"
    assert report["target"]["access_token_present"] is False


def test_execute_live_chat_probe_blocks_invalid_base_url_before_network():
    report = probe.build_live_chat_probe_report(
        base_url="/relative",
        access_token="secret-token",
        execute=True,
        client=FailingIfCalledClient(),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "invalid_target"


def test_sse_error_event_blocks_without_echoing_error_message():
    client = FakeChatClient(
        events=[
            {"type": "error", "message": "api_key=private-key should not leak"},
            {"type": "done"},
        ]
    )
    report = probe.build_live_chat_probe_report(
        base_url="https://private.example",
        access_token="secret-token",
        execute=True,
        client=client,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert any(item["key"] == "sse_error" for item in report["blocked_reasons"])
    assert "private-key" not in payload
    assert "api_key" not in payload


def test_parse_sse_event_line_reads_data_frame():
    assert probe.parse_sse_event_line(b'data: {"type": "token", "content": "ok"}\n') == {
        "type": "token",
        "content": "ok",
    }
    assert probe.parse_sse_event_line(b": keepalive\n") is None
