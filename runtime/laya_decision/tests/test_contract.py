import io
import json

import pytest

from runtime.laya_decision.contract import ContractError, fallback_decision, validate_request
from runtime.laya_decision.laya_worker import LayaEngine, run_jsonl
from runtime.laya_decision.questions import build_state, redact_text


def test_redaction_and_window():
    text = "手机号 13812345678 邮箱 a@example.com token=abc123"
    redacted = redact_text(text)
    assert "13812345678" not in redacted
    assert "a@example.com" not in redacted
    assert "abc123" not in redacted
    state = build_state({"recent_messages": [{"content": str(i)} for i in range(8)]})
    assert [m["content"] for m in state["recent_messages"]] == [str(i) for i in range(2, 8)]


def test_secret_input_rejected():
    with pytest.raises(ContractError):
        validate_request({"id": "1", "method": "predict", "state": {"user_request": "token=abc123"}})


def test_jsonl_fallback_and_invalid_json():
    inp = io.StringIO('{"id":"a","method":"predict","state":{"user_request":"分析","recent_messages":[]}}\nnot-json\n')
    out = io.StringIO()
    run_jsonl(LayaEngine(), inp, out)
    rows = [json.loads(line) for line in out.getvalue().splitlines()]
    assert rows[0]["ok"] is True
    assert rows[0]["privacy"] == {"redacted_input": True, "raw_messages_persisted": False}
    assert rows[0]["decision"]["fallback"] is True
    assert rows[1]["error"]["code"] == "invalid_json"


def test_fallback_contract():
    decision = fallback_decision()
    assert decision["emotion"] == "neutral"
    assert decision["intent"] == "unknown"
    assert decision["confidence"] == 0.0
