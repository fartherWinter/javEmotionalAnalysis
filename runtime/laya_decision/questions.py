"""Input normalization, local redaction, and Laya question construction."""

from __future__ import annotations

import re
from typing import Any

from .contract import contains_secret

_REDACTIONS = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[ID]"),
    (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "[CARD]"),
    (re.compile(r"(?i)(api[_ -]?key|token|secret|password|passwd)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
)


def redact_text(text: str, contact_names: dict[str, str] | None = None) -> str:
    result = text
    for pattern, replacement in _REDACTIONS:
        result = pattern.sub(replacement, result)
    for name, alias in (contact_names or {}).items():
        if name:
            result = result.replace(name, alias)
    return result


def build_state(raw_state: dict[str, Any], max_messages: int = 6, contact_names: dict[str, str] | None = None) -> dict[str, Any]:
    messages = raw_state.get("recent_messages") or []
    normalized = []
    for message in messages[-max_messages:]:
        content = redact_text(str(message.get("content", "")), contact_names)
        if contains_secret(content):
            raise ValueError("redaction did not remove a secret-like value")
        normalized.append({
            "direction": str(message.get("direction", message.get("role", "unknown"))),
            "timestamp": message.get("timestamp"),
            "content": content,
        })
    return {
        "session_id": str(raw_state.get("session_id", "unknown")),
        "recent_messages": normalized,
        "profile_summary": raw_state.get("profile_summary") or {},
        "candidate_memories": raw_state.get("candidate_memories") or [],
        "user_request": redact_text(str(raw_state.get("user_request", "")), contact_names),
    }


def question_schema(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "emotion": {"type": "choice", "labels": ["positive", "neutral", "curious", "anxious", "frustrated", "sad", "angry"]},
        "intent": {"type": "choice", "labels": ["ask_information", "request_action", "seek_advice", "share_experience", "emotional_support", "casual_chat", "correct_assistant"]},
        "desired_depth": {"type": "score", "min": 1, "max": 4},
        "needs_clarification": {"type": "noul"},
        "use_long_term_memory": {"type": "noul"},
        "profile_deviation": {"type": "noul"},
        "state": state,
    }
