import pytest

from scripts import init_rag


def test_init_rag_blocks_without_real_dashscope_key(monkeypatch):
    class FakeSettings:
        dashscope_api_key = ""

    monkeypatch.setattr(init_rag, "settings", FakeSettings())
    monkeypatch.setattr(init_rag, "has_real_env_value", lambda value: bool(value))

    with pytest.raises(init_rag.RagInitializationError) as exc_info:
        init_rag._ensure_model_credentials()

    message = str(exc_info.value)
    assert message.startswith("blocked:")
    assert "DASHSCOPE_API_KEY" in message
    assert "text-embedding-v2" in message
    assert "scripts.init_rag" in message
