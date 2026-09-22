from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import uuid

from PySide6.QtCore import QObject, Signal

from .domain import AppError


class TaskBus(QObject):
    finished = Signal(str, object, str)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True, name="assistant-io")
        self.futures = {}
        self.callbacks = {}
        self.cleanups = []
        self.finished.connect(self._dispatch)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, callback) -> str:
        task_id = uuid.uuid4().hex
        self.callbacks[task_id] = callback
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        self.futures[task_id] = future
        def done(f):
            try:
                self.finished.emit(task_id, f.result(), "")
            except concurrent.futures.CancelledError:
                self.finished.emit(task_id, None, "已取消")
            except AppError as exc:
                self.finished.emit(task_id, None, str(exc))
            except Exception:
                self.finished.emit(task_id, None, "操作失败，请检查运行状态；错误详情未记录，以避免泄露聊天内容")
        future.add_done_callback(done)
        return task_id

    def _dispatch(self, task_id, result, error):
        self.futures.pop(task_id, None)
        callback = self.callbacks.pop(task_id, None)
        if callback:
            callback(result, error)

    def cancel(self, task_id):
        self.callbacks.pop(task_id, None)
        future = self.futures.pop(task_id, None)
        if future:
            future.cancel()

    def shutdown(self):
        self.callbacks.clear()
        async def drain():
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for cleanup in tuple(self.cleanups):
                await cleanup()
            await self.loop.shutdown_default_executor()
        future = asyncio.run_coroutine_threadsafe(drain(), self.loop)
        # Called from a separate shutdown thread so the Qt window stays responsive.
        future.result(timeout=15)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)
