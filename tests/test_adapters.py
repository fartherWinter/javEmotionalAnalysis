import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from desktop.adapters import CipherTalk, Generator, LayaClient, parse_output
from desktop.config import Settings
from desktop.domain import AppError
from tests.test_domain_storage import snapshot


def reply():
    return {"analysis": "可能在介绍工作", "evidence_refs": ["m1"], "replies": ["你做哪块业务", "我也在学 Java", "最近项目忙吗"]}


def test_generator_repairs_once_and_never_accepts_foreign_evidence(monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        obj = {**reply(), "evidence_refs": ["not-selected"]} if len(requests) == 1 else reply()
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr("desktop.adapters.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    settings = Settings(base_url="http://localhost:1234/v1", model="fixture")
    result = asyncio.run(Generator(settings).generate(snapshot()))
    assert result == reply()
    assert len(requests) == 2
    for request in requests:
        assert json.loads(request["messages"][1]["content"])["state"] == snapshot().state()
        assert "tools" not in request


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_do_not_expose_response_or_retry(monkeypatch, status):
    count = []
    def handler(request):
        count.append(1)
        return httpx.Response(status, text="private chat and secret content")
    original = httpx.AsyncClient
    monkeypatch.setattr("desktop.adapters.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(AppError) as exc:
        asyncio.run(Generator(Settings(base_url="http://localhost/v1", model="x")).generate(snapshot()))
    assert "private" not in str(exc.value)
    assert len(count) == 1


def test_invalid_memory_evidence_and_duplicate_candidates():
    with pytest.raises(ValueError):
        parse_output(json.dumps({"candidates": [{"topic": "工作", "content": "Java", "evidence_refs": ["other"]}]}), snapshot(), True)
    with pytest.raises(ValueError):
        parse_output(json.dumps({**reply(), "replies": ["相同"] * 3}), snapshot(), False)


def test_laya_absent_returns_explicit_fallback():
    result = asyncio.run(LayaClient(Settings()).predict(snapshot().state()))
    assert result["fallback"] is True and result["confidence"] == 0


def test_actual_stdio_handshake_and_pagination():
    settings = Settings(node_path=sys.executable, cli_path=str(Path(__file__).with_name("fake_mcp.py")))
    async def run():
        adapter = CipherTalk(settings)
        sessions = await adapter.sessions()
        assert sessions["account"] == "fixture-account"
        first = await adapter.messages("fixture-account", "fixture-session")
        second = await adapter.messages("fixture-account", "fixture-session", first["cursor"])
        assert first["items"][0]["content"] == "第一页"
        assert second["items"][0]["content"] == "第二页"
        with pytest.raises(AppError, match="账号已变化"):
            await adapter.messages("other-account", "fixture-session")
    asyncio.run(run())


def test_mcp_structured_errors_are_sanitized():
    class Client:
        async def call_tool(self, *_):
            return SimpleNamespace(isError=True, structuredContent={"code": "CONFIG_MISSING", "message": "secret"})
    with pytest.raises(AppError, match="缺少数据库配置") as exc:
        asyncio.run(CipherTalk.tool(Client(), "get_messages"))
    assert "secret" not in str(exc.value)


def test_generator_timeout_and_two_invalid_results(monkeypatch):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "invalid json"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr("desktop.adapters.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(AppError, match="修复一次"):
        asyncio.run(Generator(Settings(base_url="http://localhost/v1", model="x")).generate(snapshot()))
    assert len(calls) == 2
    def timeout(request):
        raise httpx.ReadTimeout("secret endpoint details")
    monkeypatch.setattr("desktop.adapters.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(timeout), **kw))
    with pytest.raises(AppError, match="超时") as exc:
        asyncio.run(Generator(Settings(base_url="http://localhost/v1", model="x")).generate(snapshot()))
    assert "secret" not in str(exc.value)


def test_laya_cancel_kills_owned_process(monkeypatch, tmp_path):
    executable = tmp_path / "python.exe"
    executable.touch()
    class Process:
        returncode = None
        killed = False
        waited = False
        async def communicate(self, payload):
            raise asyncio.CancelledError
        def kill(self):
            self.killed = True
            self.returncode = -1
        async def wait(self):
            self.waited = True
    process = Process()
    async def spawn(*args, **kwargs):
        assert args[0] == str(executable)
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        return process
    monkeypatch.setattr("desktop.adapters.asyncio.create_subprocess_exec", spawn)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(LayaClient(Settings(laya_python=str(executable), model_path=str(tmp_path))).call("check"))
    assert process.killed and process.waited


def test_mcp_health_is_not_database_readiness():
    class Client:
        async def call_tool(self, name, *_):
            data = {"ok": True} if name == "health_check" else {"config": {"dbReady": True, "wxid": "a"}, "status": {"connection": {"ok": False}}}
            return SimpleNamespace(isError=False, structuredContent=data)
    with pytest.raises(AppError, match="数据库未连接"):
        asyncio.run(CipherTalk(Settings()).status(Client()))
