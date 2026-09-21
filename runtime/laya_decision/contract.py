"""Versioned request/response contract and privacy validation."""

from __future__ import annotations

import re
from typing import Any

CONTRACT_VERSION = "1.0"
MODEL_VERSION = "laya-multilingual:unconfigured"
CALIBRATION_VERSION = "uncalibrated"

EMOTIONS = ("positive", "neutral", "curious", "anxious", "frustrated", "sad", "angry")
INTENTS = (
    "ask_information", "request_action", "seek_advice", "share_experience",
    "emotional_support", "casual_chat", "correct_assistant", "unknown",
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_ -]?key|token|secret|password|passwd)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b(?:sk|ghp|glpat)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b\d{16,19}\b"),
)


class ContractError(ValueError):
    """Raised when a request or decision violates the sidecar contract."""


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a number")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ContractError(f"{field} must be between 0 and 1")
    return value


def validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ContractError("request must be an object")
    if not isinstance(request.get("id"), str) or not request["id"]:
        raise ContractError("id is required")
    if request.get("method") not in ("predict", "check"):
        raise ContractError("method must be predict or check")
    if request["method"] == "check":
        return request
    state = request.get("state")
    if not isinstance(state, dict):
        raise ContractError("state is required")
    if not isinstance(state.get("user_request", ""), str):
        raise ContractError("state.user_request must be a string")
    if contains_secret(state.get("user_request", "")):
        raise ContractError("input contains a secret-like value; redact before sending")
    messages = state.get("recent_messages", [])
    if not isinstance(messages, list):
        raise ContractError("state.recent_messages must be an array")
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ContractError("each recent message requires string content")
        if contains_secret(message["content"]):
            raise ContractError("input contains a secret-like value; redact before sending")
    return request


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def fallback_decision(reason: str = "laya_unavailable") -> dict[str, Any]:
    return {
        "emotion": "neutral",
        "emotion_confidence": 0.0,
        "intent": "unknown",
        "intent_confidence": 0.0,
        "desired_depth": 2.0,
        "needs_clarification": 0.0,
        "use_long_term_memory": 0.0,
        "profile_deviation": 0.0,
        "confidence": 0.0,
        "model": MODEL_VERSION,
        "model_version": MODEL_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "fallback": True,
        "fallback_reason": reason,
    }


def validate_decision(decision: Any) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ContractError("decision must be an object")
    if decision.get("emotion") not in EMOTIONS:
        raise ContractError("invalid emotion")
    if decision.get("intent") not in INTENTS:
        raise ContractError("invalid intent")
    for field in ("emotion_confidence", "intent_confidence", "needs_clarification", "use_long_term_memory", "profile_deviation", "confidence"):
        _probability(decision.get(field), field)
    depth = decision.get("desired_depth")
    if isinstance(depth, bool) or not isinstance(depth, (int, float)) or not 1.0 <= float(depth) <= 4.0:
        raise ContractError("desired_depth must be between 1 and 4")
    return decision
