"""Measure cold/warm desktop JSONL requests, including process cleanup."""
import asyncio
import json
import time
from pathlib import Path

from desktop.adapters import LayaSession
from desktop.config import Settings


async def run():
    root = Path.cwd()
    session = LayaSession(Settings(laya_python=str(root / ".venv-laya/Scripts/python.exe"), model_path=str(root / ".venv-laya/model")))
    timings = []
    process_ids = []
    try:
        for _ in range(3):
            start = time.monotonic()
            result = await session.predict({"session_id": "benchmark", "recent_messages": [{"direction": "in", "content": "这个接口的参数有哪些？"}],
                                            "profile_summary": {}, "candidate_memories": [], "user_request": "帮我简短回复"})
            if result["fallback"]:
                raise RuntimeError("Real model returned fallback; benchmark invalid")
            timings.append(round(time.monotonic() - start, 3))
            process_ids.append(session.process.pid)
            print(f"Request {len(timings)}: {timings[-1]}s", flush=True)
        process = session.process
    finally:
        await session.close()
    report = {"seconds": timings, "same_process": len(set(process_ids)) == 1, "process_stopped": process.returncode is not None}
    (root / "build/laya-session-benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(run())
