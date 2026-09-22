from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from runtime.laya_decision.questions import redact_text


class AppError(Exception):
    """A deliberately sanitized, user-facing error."""


def clean(text: str) -> str:
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[PRIVATE_KEY]", text, flags=re.S)
    text = re.sub(r"\b(?:sk-|ghp_|ghp-|glpat-)[A-Za-z0-9_-]{8,}", "[SECRET]", text)
    text = re.sub(r"(?i)Bearer\s+\S+", "[AUTHORIZATION]", text)
    return redact_text(text)


def redact(value: Any, aliases: dict[str, str] | None = None) -> Any:
    if isinstance(value, str):
        result = clean(value)
        for name, alias in sorted((aliases or {}).items(), key=lambda x: -len(x[0])):
            if name:
                result = result.replace(name, alias)
        return result
    if isinstance(value, list):
        return [redact(v, aliases) for v in value]
    if isinstance(value, dict):
        return {str(k): redact(v, aliases) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class Message:
    source_id: str
    direction: str
    timestamp: int
    content: str
    is_text: bool
    order: int = 0


def map_messages(items: list[dict], previous: list[Message] | None = None) -> list[Message]:
    result = {m.source_id: m for m in previous or []}
    for row in items:
        kind = row.get("type")
        is_text = kind in (1, "1", "text")
        server_id, local_id = row.get("serverId"), row.get("localId")
        if server_id not in (None, 0, "0", ""):
            key = "server:" + str(server_id)
        elif local_id not in (None, ""):
            key = "local:" + str(local_id) + ":" + str(row.get("createTime", ""))
        else:
            # No source identity: keep distinct occurrences, including identical text.
            import uuid
            key = "unidentified:" + uuid.uuid4().hex
        direction = row.get("direction")
        result[key] = Message(key, direction if direction in {"in", "out"} else "unknown",
                              int(row.get("createTime") or 0),
                              str(row.get("content", "")) if is_text else "[非文本消息]", is_text,
                              int(row.get("sortSeq") or local_id or 0))
    return sorted(result.values(), key=lambda m: (m.timestamp, m.order))


@dataclass(frozen=True)
class Snapshot:
    account: str
    session: str
    payload: str
    evidence: tuple[tuple[str, str, str], ...]  # model reference, source id, redacted excerpt

    def state(self) -> dict:
        return json.loads(self.payload)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.payload.encode("utf-8")).hexdigest()


def make_snapshot(account: str, session: str, display_name: str, messages: list[Message],
                  profile: dict, memories: list[dict], request: str, *, memory_mode: bool = False) -> Snapshot:
    selected = [m for m in messages if m.is_text]
    if not selected:
        raise AppError("所选范围没有可分析的文本消息")
    if not memory_mode:
        selected = selected[-6:]
        if not any(m.direction == "in" for m in selected):
            raise AppError("所选范围没有方向明确的对方消息，请重新选择")
    elif len(selected) > 50:
        raise AppError("一次最多从 50 条文本消息提取记忆")
    aliases = {account: "我", session: "联系人", display_name: "联系人"}
    evidence = tuple((f"m{i + 1}", m.source_id, redact(m.content, aliases)) for i, m in enumerate(selected))
    state = {
        "session_id": "selected_contact",
        "recent_messages": [{"ref": e[0], "direction": m.direction, "timestamp": m.timestamp,
                             "content": e[2]} for m, e in zip(selected, evidence)],
        "profile_summary": redact(profile, aliases),
        "candidate_memories": [{"content": redact(m["content"], aliases), "topic": redact(m["topic"], aliases)} for m in memories[:10]],
        "user_request": redact(request, aliases),
    }
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    if len(payload) > 24000:
        raise AppError("所选上下文过长，请减少消息或记忆，避免模型静默截断")
    return Snapshot(account, session, payload, evidence)
