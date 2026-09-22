import json

import pytest

from desktop.config import Settings
from desktop.domain import AppError, Message, make_snapshot, map_messages
from desktop.storage import Store
from runtime.laya_decision.contract import validate_request


def snapshot():
    return make_snapshot("account", "contact", "小明", [Message("local:1", "in", 1, "我主要写 Java", True)], {}, [], "简短")


def test_message_identity_preserves_repeated_text_and_large_ids():
    rows = [{"serverId": "9223372036854775807", "direction": "in", "type": 1, "content": "好的", "createTime": 1},
            {"localId": 2, "direction": "in", "type": 1, "content": "好的", "createTime": 2},
            {"localId": 3, "direction": "weird", "type": 3, "content": "图片正文不应作为文字", "createTime": 3}]
    messages = map_messages(rows)
    assert len(map_messages(rows, messages)) == 3
    assert messages[0].source_id == "server:9223372036854775807"
    assert messages[2].content == "[非文本消息]"
    assert messages[2].direction == "unknown"
    assert len(map_messages([{"content": "好", "type": 1}] * 2)) == 2


def test_snapshot_redacts_all_context_and_is_immutable():
    s = make_snapshot("account", "contact", "小明", [Message("id", "in", 1, "小明电话13812345678", True)],
                      {"notes": "token=abc123"}, [{"topic": "邮箱", "content": "a@example.com"}], "sk-abcdefghijklmnop")
    assert "13812345678" not in s.payload and "abc123" not in s.payload and "a@example.com" not in s.payload
    assert "小明" not in s.payload and "abcdefghijklmnop" not in s.payload
    validate_request({"id": "1", "method": "predict", "state": s.state()})
    state = s.state()
    state["user_request"] = "changed"
    assert s.state()["user_request"] != "changed"


def test_no_incoming_or_no_text_rejected():
    with pytest.raises(AppError):
        make_snapshot("a", "s", "n", [Message("1", "unknown", 1, "你好", True)], {}, [], "")
    with pytest.raises(AppError):
        make_snapshot("a", "s", "n", [Message("1", "in", 1, "图片", False)], {}, [], "")


def test_confirm_replace_rollback_isolation_and_restart(tmp_path):
    path = tmp_path / "中文" / "store.sqlite3"
    store = Store(path)
    s = snapshot()
    c = {"topic": "职业", "content": "写 Java", "evidence_refs": ["m1"]}
    assert not store.memories("account", "contact")  # candidate alone is never persisted
    with pytest.raises(AppError):
        store.confirm(s, {**c, "evidence_refs": ["outside"]})
    store.confirm(s, c)
    first = store.memories("account", "contact")[0]
    with pytest.raises(AppError):
        store.confirm(s, c)
    store.confirm(s, {**c, "content": "Java 后端"}, first["id"])
    assert not store.memories("other", "contact")
    assert not store.memories("account", "other")
    store = Store(path)
    second = store.memories("account", "contact")[0]
    assert second["content"] == "Java 后端"
    assert second["evidence"][0]["source_id"] == "local:1"
    store.confirm(s, {**c, "topic": "语言"})
    with pytest.raises(AppError):
        store.confirm(s, {**c, "topic": "语言"}, second["id"])
    assert len(store.memories("account", "contact")) == 2  # failed replace is atomic
    store.delete("other", "contact", second["id"])
    assert len(store.memories("account", "contact")) == 2
    store.delete("account", "contact", second["id"])
    assert len(store.memories("account", "contact")) == 1


def test_profile_persistence_and_settings_validation(tmp_path):
    store = Store(tmp_path / "db")
    store.save_profile("a", "s", {"relationship": "朋友", "notes": "password=hidden", "style": "简短"})
    assert store.profile("a", "s")["style"] == "简短"
    assert "hidden" not in store.profile("a", "s")["notes"]
    store.delete_profile("a", "s")
    assert store.profile("a", "s") == {}
    for url in ["https://user:password@example.com", "http://example.com", "https://example.com?key=x"]:
        with pytest.raises(ValueError):
            Settings(base_url=url).save(tmp_path / "settings.json")
    settings = Settings(base_url="http://127.0.0.1:11434/v1", model="中文")
    settings.save(tmp_path / "settings.json")
    assert Settings.load(tmp_path / "settings.json") == settings
    assert not (tmp_path / "settings.json").read_bytes().startswith(b"\xef\xbb\xbf")


def test_dependency_discovery_only_returns_existing_paths(tmp_path):
    python = tmp_path / ".venv-laya/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    model = tmp_path / ".venv-laya/model"
    model.mkdir()
    assert Settings.discover([tmp_path]).model_path == ""
    (model / "assistant-manifest.json").write_text("{}", encoding="utf-8")
    found = Settings.discover([tmp_path])
    assert found.laya_python == str(python.resolve())
    assert found.model_path == str(model.resolve())
    assert found.cli_path == ""
