from app.config import settings
from app.utils import llm_factory
from app.utils.llm_factory import resolve_model_name


def test_resolve_model_name_uses_profile_defaults():
    assert resolve_model_name(profile="planner") == settings.qwen_planner_model_name
    assert resolve_model_name(profile="router") == settings.qwen_router_model_name
    assert resolve_model_name(profile="rag") == settings.qwen_rag_model_name
    assert resolve_model_name(profile="report") == settings.qwen_report_model_name
    assert resolve_model_name(profile="transport") == settings.qwen_router_model_name


def test_resolve_model_name_prefers_explicit_model():
    assert resolve_model_name(profile="planner", model="custom-model") == "custom-model"


def test_build_chat_model_applies_timeout_and_retry_settings(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_factory, "ChatOpenAI", FakeChatOpenAI)

    llm_factory.build_chat_model(profile="planner", streaming=True)

    assert captured["timeout"] == settings.qwen_request_timeout_seconds
    assert captured["max_retries"] == settings.qwen_max_retries
