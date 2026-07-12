"""Shared helpers for LangChain-style message objects and dictionaries."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage


STATE_TRANSITION_OUTCOME_SCHEMA = "state_transition_outcome.v1"
APPLIED_STATE_TRANSITION_STATUSES = frozenset({"applied", "already_applied"})


def message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "")
    message_type = getattr(message, "type", None)
    if message_type:
        return str(message_type)
    return message.__class__.__name__.replace("Message", "").lower()


def message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content or "")


def state_transition_outcome_from_message(message: Any) -> dict[str, Any] | None:
    """Return a validated state-transition outcome stored outside model-visible content."""

    if not isinstance(message, ToolMessage) and message_role(message) != "tool":
        return None
    artifact = (
        message.get("artifact")
        if isinstance(message, dict)
        else getattr(message, "artifact", None)
    )
    if not isinstance(artifact, dict):
        return None
    if artifact.get("schema") != STATE_TRANSITION_OUTCOME_SCHEMA:
        return None
    if not isinstance(artifact.get("tool"), str) or not artifact["tool"]:
        return None
    if not isinstance(artifact.get("status"), str) or not artifact["status"]:
        return None
    return artifact


def applied_state_transition_tool_name(message: Any) -> str | None:
    """Return the tool name only when its result proves that state was applied."""

    message_status = (
        message.get("status")
        if isinstance(message, dict)
        else getattr(message, "status", None)
    )
    if message_status == "error":
        return None

    outcome = state_transition_outcome_from_message(message)
    if not outcome or outcome["status"] not in APPLIED_STATE_TRANSITION_STATUSES:
        return None
    return str(outcome["tool"])


def tool_names_from_message(message: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(message, ToolMessage):
        name = getattr(message, "name", None)
        if name:
            names.add(str(name))

    if isinstance(message, dict):
        role = message.get("role") or message.get("type")
        if role == "tool" and message.get("name"):
            names.add(str(message["name"]))
        tool_calls = message.get("tool_calls") or []
    else:
        tool_calls = getattr(message, "tool_calls", None) or []

    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            name = tool_call.get("name") or tool_call.get("function", {}).get("name")
        else:
            name = getattr(tool_call, "name", None)
        if name:
            names.add(str(name))

    outcome = state_transition_outcome_from_message(message)
    if outcome:
        names.add(str(outcome["tool"]))
    return names
