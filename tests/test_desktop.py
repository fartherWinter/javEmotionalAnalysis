import asyncio

from PySide6.QtWidgets import QApplication

from desktop.config import Settings
from desktop.dialogs import PreviewDialog
from desktop.domain import Message
from desktop.storage import Store
from desktop.tasks import TaskBus
from desktop.window import MainWindow
from tests.test_domain_storage import snapshot
from tests.test_adapters import reply


def test_native_window_copy_and_shutdown(qtbot, tmp_path):
    window = MainWindow(Settings(), Store(tmp_path / "db"))
    qtbot.addWidget(window)
    window.show()
    window.present_result(snapshot(), {"fallback": True}, reply())
    assert "未使用 Laya" in window.analysis.toPlainText()
    window.copy_reply(window.reply_fields[0])
    assert QApplication.clipboard().text() == reply()["replies"][0]
    assert not window.reply_fields[0].isReadOnly()
    window.reply_fields[0].setPlainText("我改过的回复")
    window.copy_reply(window.reply_fields[0])
    assert QApplication.clipboard().text() == "我改过的回复"
    window.close()
    qtbot.waitUntil(lambda: window.shutdown_complete, timeout=20000)


def test_task_bus_closes_idle_model_process(qtbot, monkeypatch):
    from tests.test_laya_session import setup_session
    session, processes = setup_session(monkeypatch)
    bus = TaskBus()
    bus.cleanups.append(session.close)
    completed = []
    bus.submit(session.call("check"), lambda result, error: completed.append((result, error)))
    qtbot.waitUntil(lambda: bool(completed), timeout=10000)
    assert completed[0][1] == ""
    assert processes[0].returncode is None
    bus.shutdown()
    assert processes[0].returncode is not None


def test_generation_only_mode_does_not_start_laya(qtbot, tmp_path, monkeypatch):
    from desktop.domain import Message
    from PySide6.QtWidgets import QDialog
    window = MainWindow(Settings(), Store(tmp_path / "db"))
    qtbot.addWidget(window)
    window.show()
    window.account, window.session, window.session_name = "a", "s", "联系人"
    window.messages = [Message("1", "in", 1, "你好", True)]
    window.generation_mode.setCurrentIndex(1)
    monkeypatch.setattr("desktop.window.PreviewDialog.exec", lambda _self: QDialog.DialogCode.Accepted)
    generated = []
    monkeypatch.setattr(window, "generate", lambda *args: generated.append(args))
    def unexpected(*_):
        raise AssertionError("generation-only mode must not invoke Laya")
    monkeypatch.setattr(window, "judge", unexpected)
    window.prepare(False)
    qtbot.waitUntil(lambda: bool(generated), timeout=3000)
    assert generated[0][1]["fallback_reason"] == "user_skipped"
    window.close()
    qtbot.waitUntil(lambda: window.shutdown_complete, timeout=20000)
    assert not window.bus.thread.is_alive()


def test_cancelled_task_never_delivers_late_result(qtbot):
    bus = TaskBus()
    values = []
    async def delayed():
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            return "late"
        return "done"
    task = bus.submit(delayed(), lambda value, error: values.append(value))
    bus.cancel(task)
    qtbot.wait(400)
    assert values == []
    bus.shutdown()


def test_preview_memory_toggle_changes_only_approved_snapshot(qtbot):
    dialog = PreviewDialog(None, "a", "s", "联系人", [Message("1", "in", 1, "你好", True)], {},
                           [{"topic": "工作", "content": "后端开发"}], "简短", False)
    qtbot.addWidget(dialog)
    assert len(dialog.snapshot.state()["candidate_memories"]) == 1
    first = dialog.snapshot
    dialog.options[0].setChecked(False)
    assert dialog.snapshot.state()["candidate_memories"] == []
    assert first.state()["candidate_memories"] != []


def test_switch_or_cancel_discards_generation_and_failure_keeps_decision(qtbot, tmp_path, monkeypatch):
    from desktop.domain import AppError
    window = MainWindow(Settings(), Store(tmp_path / "db"))
    qtbot.addWidget(window)
    window.show()
    async def late(*args, **kwargs):
        try:
            await asyncio.sleep(.2)
        except asyncio.CancelledError:
            pass
        return reply()
    monkeypatch.setattr("desktop.window.Generator.generate", late)
    window.generate(snapshot(), {"fallback": False}, window.generation, False)
    window.cancel_analysis()
    qtbot.wait(350)
    assert window.analysis.toPlainText() == ""
    assert all(not field.toPlainText() for field in window.reply_fields)
    async def fail(*args, **kwargs):
        raise AppError("生成接口超时")
    monkeypatch.setattr("desktop.window.Generator.generate", fail)
    window.decision.setText("已完成的判断")
    window.generate(snapshot(), {"fallback": False}, window.generation, False)
    qtbot.waitUntil(lambda: "超时" in window.status.text())
    assert window.decision.text() == "已完成的判断"
    window.close()
    qtbot.waitUntil(lambda: window.shutdown_complete, timeout=20000)
