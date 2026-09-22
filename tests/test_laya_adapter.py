import pytest

from runtime.laya_decision.laya_worker import LayaEngine, _normalize_model_result
from runtime.laya_decision.contract import validate_decision
from runtime.laya_decision.questions import question_schema


def sdk_result():
    return {"answers": {"emotion": {"choice": "curious", "confidence": 0.8},
                        "intent": {"choice": "ask_information", "confidence": 0.7},
                        "desired_depth": {"score": 1.5},
                        "needs_clarification": {"noul": 0.1}, "use_long_term_memory": {"noul": 0.2},
                        "profile_deviation": {"noul": 0.3}}}


def test_real_sdk_shape_and_score_offset(monkeypatch):
    monkeypatch.setenv("LAYA_DISABLE_MODEL", "1")
    class Model:
        def predict(self, state, questions):
            assert "state" not in questions
            if "intent" in questions:
                assert state == "这个接口怎么用？"
            else:
                assert state["recent_messages"][0]["content"] == "这个接口怎么用？"
                assert "criteria" in questions["emotion"]
            return sdk_result()
    engine = LayaEngine()
    engine.model = Model()
    result = engine.predict({"recent_messages": [{"direction": "in", "content": "这个接口怎么用？"}]})
    assert result["fallback"] is False
    assert result["desired_depth"] == 2.5
    assert result["confidence"] == 0.7
    validate_decision(result)


def test_invalid_sdk_output_does_not_invent_success(monkeypatch):
    monkeypatch.setenv("LAYA_DISABLE_MODEL", "1")
    class Model:
        def predict(self, *_):
            return {"answers": {}}
    engine = LayaEngine()
    engine.model = Model()
    assert engine.predict({"recent_messages": [{"direction": "in", "content": "你好"}]})["fallback"] is True


def test_missing_manifest_never_loads_remote(monkeypatch, tmp_path):
    monkeypatch.delenv("LAYA_DISABLE_MODEL", raising=False)
    monkeypatch.setenv("LAYA_MODEL_PATH", str(tmp_path))
    assert LayaEngine().check()["available"] is False


def test_oversized_context_is_not_silently_truncated(monkeypatch):
    monkeypatch.setenv("LAYA_DISABLE_MODEL", "1")
    engine = LayaEngine()
    class Tokenizer:
        mask_token = "[MASK]"
        def __call__(self, *_args, **_kwargs):
            return {"input_ids": list(range(100))}
    engine.model = object()
    engine.tokenizer = Tokenizer()
    engine.max_state_tokens = 50
    result = engine.predict({"recent_messages": [{"direction": "in", "content": "长文本"}]})
    assert result["fallback"] and result["fallback_reason"] == "context_too_long"


def test_worker_redacts_nested_profile_and_memory():
    from runtime.laya_decision.questions import build_state
    state = build_state({"profile_summary": {"nested": {"notes": "token=private"}},
                         "candidate_memories": [{"content": "联系我 a@example.com"}]})
    assert "private" not in str(state)
    assert "a@example.com" not in str(state)


def test_intent_targets_contact_and_preserves_prior_context():
    from runtime.laya_decision.questions import intent_state
    messages = [{"direction": "out", "content": "你是说周一吗？"},
                {"direction": "in", "content": "不，是周二。"},
                {"direction": "out", "content": "收到"},
                {"direction": "unknown", "content": "无法确定是谁的话"}]
    text = intent_state({"recent_messages": messages, "user_request": "帮我回复"})
    assert "你是说周一吗？" in text and text.endswith("不，是周二。")
    assert "收到" not in text and "帮我回复" not in text and "无法确定是谁的话" not in text
    assert intent_state({"recent_messages": [{"direction": "out", "content": "你好"}]}) is None
