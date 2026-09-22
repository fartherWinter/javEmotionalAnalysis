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
    (re.compile(r"(?i)(api[_ -]?key|token|secret|password|passwd)\s*[:=]\s*[^\s,;]+"), "[REDACTED_SECRET]"),
    (re.compile(r"\b(?:sk-|ghp_|ghp-|glpat-)[A-Za-z0-9_-]{8,}"), "[REDACTED_SECRET]"),
)


def redact_text(text: str, contact_names: dict[str, str] | None = None) -> str:
    result = text
    for pattern, replacement in _REDACTIONS:
        result = pattern.sub(replacement, result)
    for name, alias in (contact_names or {}).items():
        if name:
            result = result.replace(name, alias)
    return result


def redact_value(value: Any, contact_names: dict[str, str] | None = None) -> Any:
    if isinstance(value, str):
        return redact_text(value, contact_names)
    if isinstance(value, dict):
        return {k: redact_value(v, contact_names) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, contact_names) for v in value]
    return value


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
        "profile_summary": redact_value(raw_state.get("profile_summary") or {}, contact_names),
        "candidate_memories": redact_value(raw_state.get("candidate_memories") or [], contact_names),
        "user_request": redact_text(str(raw_state.get("user_request", "")), contact_names),
    }


def question_schema(state: dict[str, Any]) -> dict[str, Any]:
    # laya 0.3.5 takes state and questions separately, with criteria (not labels).
    return {
        "emotion": {"type": "choice", "instructions": "Emotion of the latest incoming message, using conversation context. Unknown direction is not evidence.",
                    "criteria": {"positive": "happy or grateful", "neutral": "matter of fact", "curious": "interested", "anxious": "worried", "frustrated": "frustrated", "sad": "sad", "angry": "angry"}},
        "intent": {"type": "choice", "instructions": "这条消息的主要沟通意图是什么？",
                   "criteria": {"ask_information": "询问信息、寻求事实答案", "request_action": "要求对方完成某个行动", "seek_advice": "征求意见或建议",
                                "share_experience": "分享经历、告知情况", "emotional_support": "倾诉烦恼、寻求安慰", "casual_chat": "日常闲聊、打招呼",
                                "correct_assistant": "纠正对方之前说错的内容", "unknown": "信息不足，无法判断意图"}},
        "desired_depth": {"type": "score", "instructions": "How detailed should the reply be? Respect the current user request first.", "criteria": ["very short", "brief explanation", "detailed guidance", "comprehensive explanation"]},
        "needs_clarification": {"type": "noul", "instructions": "Is essential information missing before a useful reply can be given?"},
        "use_long_term_memory": {"type": "noul", "instructions": "Is a provided confirmed memory directly useful for this reply?"},
        "profile_deviation": {"type": "noul", "instructions": "Does this conversation clearly differ from the provided long-term preferences? With no baseline, answer false."},
    }


def intent_state(state: dict[str, Any]) -> str | None:
    """Classify the contact's message, not the operator's request to draft a reply."""
    messages = state.get("recent_messages", [])
    incoming = [i for i, message in enumerate(messages) if message.get("direction") == "in"]
    if not incoming:
        return None
    target = incoming[-1]
    text = messages[target]["content"]
    history = [f"{'我' if m['direction'] == 'out' else '对方'}：{m['content']}"
               for m in messages[:target] if m.get("direction") in {"in", "out"}]
    if not history:
        return text
    return "之前的对话：\n" + "\n".join(history) + "\n\n待判断的对方最新消息：\n" + text
