import asyncio
import sys
from pathlib import Path

import pytest

from desktop.adapters import LayaSession
from desktop.config import Settings
from desktop.domain import AppError


def setup_session(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []
    async def launch(*args, **kwargs):
        process = await original(sys.executable, str(Path(__file__).with_name("fake_laya_worker.py")), **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr("desktop.adapters.asyncio.create_subprocess_exec", launch)
    return LayaSession(Settings(laya_python=sys.executable, model_path=str(Path(__file__).parent))), processes


def test_reuses_process_and_serializes_requests(monkeypatch):
    session, processes = setup_session(monkeypatch)
    async def run():
        try:
            responses = await asyncio.gather(*(session.call("predict", {}) for _ in range(4)))
            assert len({r["pid"] for r in responses}) == 1
            assert len({r["id"] for r in responses}) == 4
            assert len(processes) == 1
            assert session.process.returncode is None
        finally:
            await session.close()
        assert processes[0].returncode is not None
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["wrong_id", "crash", "timeout", "cancel"])
def test_resets_failed_stream_before_next_request(monkeypatch, failure):
    session, processes = setup_session(monkeypatch)
    async def run():
        try:
            first = await session.call("check")
            if failure in {"wrong_id", "crash"}:
                with pytest.raises(AppError):
                    await session.call("predict", {failure: True})
            elif failure == "timeout":
                session.request_timeout = .05
                with pytest.raises(AppError):
                    await session.call("predict", {"delay": 10})
            else:
                task = asyncio.create_task(session.call("predict", {"delay": 10}))
                await asyncio.sleep(.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert processes[0].returncode is not None
            second = await session.call("check")
            assert first["pid"] != second["pid"]
        finally:
            await session.close()
        assert all(p.returncode is not None for p in processes)
    asyncio.run(run())
