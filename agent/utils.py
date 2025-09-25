"""Shared utilities for LangGraph agents."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

from langchain_core.messages import BaseMessage


DEFAULT_USER_CONTEXT = "No additional context provided."
RECENT_HISTORY_WINDOW = 6


def _coerce_content_to_text(content: Any) -> str:
    """Convert structured message content into displayable text."""

    if isinstance(content, str):
        return content

    if isinstance(content, Iterable) and not isinstance(content, (dict, bytes, str)):
        # Handle LangChain's list-of-blocks format (e.g. [{"type": "text", "text": "..."}])
        parts = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        if parts:
            return "\n".join(parts)

    try:
        return json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def _format_messages(messages: Sequence[BaseMessage]) -> str:
    lines = []
    for message in messages:
        role = (getattr(message, "type", message.__class__.__name__).upper())
        text = _coerce_content_to_text(message.content)
        lines.append(f"{role}: {text}".strip())
    return "\n".join(lines)


def get_last_user_message(messages: Sequence[BaseMessage]) -> str:
    """Return content of the most recent human message, if any."""

    for message in reversed(messages):
        if getattr(message, "type", "").lower() == "human":
            return _coerce_content_to_text(message.content)
    return ""


def get_conversation_history(
    messages: Sequence[BaseMessage], *, include_last_user: bool = False
) -> str:
    """Render conversation history, optionally excluding the latest user utterance."""

    if not include_last_user:
        trimmed = list(messages)
        for idx in range(len(trimmed) - 1, -1, -1):
            if getattr(trimmed[idx], "type", "").lower() == "human":
                trimmed = trimmed[:idx]
                break
        return _format_messages(trimmed)

    return _format_messages(messages)


def get_recent_conversation_history(
    messages: Sequence[BaseMessage], window: int = RECENT_HISTORY_WINDOW
) -> str:
    if window <= 0:
        return ""
    return _format_messages(messages[-window:])


def get_full_conversation_history(messages: Sequence[BaseMessage]) -> str:
    return _format_messages(messages)


def get_user_context(state: Mapping[str, Any]) -> str:
    """Fetch user context or provide a default placeholder."""

    context = state.get("user_context")
    if isinstance(context, str) and context.strip():
        return context
    return DEFAULT_USER_CONTEXT
