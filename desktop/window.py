from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from .adapters import CipherTalk, Generator, LayaSession
from .config import Settings
from .dialogs import CandidatesDialog, ContactsDialog, PreviewDialog, SettingsDialog, note
from .domain import map_messages
from .tasks import TaskBus
from . import __version__


class MainWindow(QMainWindow):
    stopped = Signal()

    def __init__(self, settings: Settings, store, *, first_run=False):
        super().__init__()
        self.settings, self.store = settings, store
        self.bus = TaskBus()
        self.laya = LayaSession(settings)
        self.bus.cleanups.append(self.laya.close)
        self.account = self.session = self.session_name = ""
        self.messages = []
        self.cursor = None
        self.session_offset = 0
        self.session_more = False
        self.generation = uuid.uuid4().hex
        self.job = self.session_job = self.message_job = None
        self.closing = self.shutdown_complete = False
        self.setWindowTitle(f"知语 · 本地聊天分析助手 v{__version__}")
        self.resize(1320, 850)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        header = QHBoxLayout()
        title = QLabel("知语  /  对话分析与回复辅助")
        title.setObjectName("heading")
        header.addWidget(title)
        header.addStretch()
        for label, callback in (("联系人与记忆", self.open_contacts), ("设置与诊断", self.open_settings)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            header.addWidget(button)
        layout.addLayout(header)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        left, middle, right = QWidget(), QWidget(), QWidget()
        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setSizes([240, 520, 440])
        col = QVBoxLayout(left)
        col.addWidget(note("单聊会话"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤已加载会话")
        self.filter.textChanged.connect(self.filter_sessions)
        col.addWidget(self.filter)
        self.sessions = QListWidget()
        self.sessions.currentItemChanged.connect(self.select_session)
        col.addWidget(self.sessions)
        self.refresh_button = QPushButton("刷新会话")
        self.refresh_button.clicked.connect(lambda: self.load_sessions(False))
        col.addWidget(self.refresh_button)
        self.more_sessions = QPushButton("更多会话")
        self.more_sessions.setEnabled(False)
        self.more_sessions.clicked.connect(lambda: self.load_sessions(True))
        col.addWidget(self.more_sessions)
        col = QVBoxLayout(middle)
        self.chat_title = note("选择会话后读取消息")
        col.addWidget(self.chat_title)
        self.message_list = QListWidget()
        self.message_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.message_list.setWordWrap(True)
        col.addWidget(self.message_list)
        self.more_messages = QPushButton("加载更多历史")
        self.more_messages.setEnabled(False)
        self.more_messages.clicked.connect(lambda: self.load_messages(True))
        col.addWidget(self.more_messages)
        self.scope = QComboBox()
        self.scope.addItems(["最近 6 条文本", "选中消息（回复最多取最后 6 条）"])
        col.addWidget(self.scope)
        self.request = QLineEdit()
        self.request.setPlaceholderText("本轮要求，例如：简短回应，先共情再给建议")
        col.addWidget(self.request)
        self.analyze_button = QPushButton("预览并分析 / 生成回复")
        self.analyze_button.clicked.connect(lambda: self.prepare(False))
        col.addWidget(self.analyze_button)
        self.generation_mode = QComboBox()
        self.generation_mode.addItems(["本地判断后生成回复", "仅生成回复（跳过本地判断）"])
        self.generation_mode.setToolTip("可跳过实验性判断，直接根据预览的上下文生成回复")
        col.addWidget(self.generation_mode)
        self.extract_button = QPushButton("从选中历史提取记忆候选")
        self.extract_button.clicked.connect(lambda: self.prepare(True))
        col.addWidget(self.extract_button)
        self.cancel_button = QPushButton("取消当前分析")
        self.cancel_button.clicked.connect(self.cancel_analysis)
        col.addWidget(self.cancel_button)
        col = QVBoxLayout(right)
        col.addWidget(note("分析与候选回复"))
        self.decision = note("等待分析。模型只提供可能的解释，不代表对方真实心理。")
        col.addWidget(self.decision)
        self.analysis = QPlainTextEdit()
        self.analysis.setReadOnly(True)
        self.analysis.setPlaceholderText("分析说明与消息依据")
        col.addWidget(self.analysis)
        self.reply_fields = []
        for i in range(3):
            col.addWidget(note(f"候选 {i + 1}"))
            field = QPlainTextEdit()
            field.setPlaceholderText("候选生成后可直接编辑，再复制")
            field.setMaximumHeight(95)
            col.addWidget(field)
            copy = QPushButton("复制回复")
            copy.clicked.connect(lambda _, f=field: self.copy_reply(f))
            col.addWidget(copy)
            self.reply_fields.append(field)
        self.status = note("请先在“设置与诊断”配置外部依赖。所有分析均由你手动发起。")
        layout.addWidget(self.status)
        self.stopped.connect(self.finish_shutdown)
        if first_run:
            QTimer.singleShot(100, self.open_settings)

    def copy_reply(self, field):
        if field.toPlainText():
            QApplication.clipboard().setText(field.toPlainText())
            self.status.setText("已复制；请自行检查并发送")

    def filter_sessions(self, text):
        for i in range(self.sessions.count()):
            item = self.sessions.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def cancel_analysis(self):
        self.generation = uuid.uuid4().hex
        if self.job:
            self.bus.cancel(self.job)
            self.job = None
        self.status.setText("已取消；迟到结果不会覆盖当前会话")

    def clear_results(self):
        self.decision.setText("等待分析")
        self.analysis.clear()
        for field in self.reply_fields:
            field.clear()

    def load_sessions(self, more=False):
        if self.session_job:
            self.bus.cancel(self.session_job)
        self.cancel_analysis()
        if self.message_job:
            self.bus.cancel(self.message_job)
        self.refresh_button.setEnabled(False)
        self.more_sessions.setEnabled(False)
        self.status.setText("正在连接 CipherTalk 并读取单聊列表…")
        offset = self.session_offset if more else 0
        async def query():
            return await CipherTalk(self.settings).sessions(offset)
        def done(result, error):
            self.session_job = None
            self.refresh_button.setEnabled(True)
            if error:
                self.status.setText(error)
                self.more_sessions.setEnabled(self.session_more)
                return
            changed_account = self.account != result["account"]
            if not more or changed_account:
                self.sessions.clear()
                self.account = result["account"]
            if more and changed_account:
                self.status.setText("微信账号已变化，正在重新加载会话")
                self.load_sessions(False)
                return
            known = {self.sessions.item(i).data(Qt.ItemDataRole.UserRole)["sessionId"] for i in range(self.sessions.count())}
            for row in result.get("items", []):
                if row.get("type") != "private" or row["sessionId"] in known:
                    continue
                item = QListWidgetItem(row.get("displayName") or row["sessionId"])
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.sessions.addItem(item)
                known.add(row["sessionId"])
            self.session_offset = offset + 50
            self.session_more = bool(result.get("hasMore"))
            self.more_sessions.setEnabled(self.session_more)
            self.filter_sessions(self.filter.text())
            self.status.setText("已连接；请选择单聊。会话名称过滤仅作用于已加载列表。")
        self.session_job = self.bus.submit(query(), done)

    def select_session(self, item, _):
        self.cancel_analysis()
        if self.message_job:
            self.bus.cancel(self.message_job)
        self.messages = []
        self.cursor = None
        self.more_messages.setEnabled(False)
        self.message_list.clear()
        self.clear_results()
        if not item:
            self.session = self.session_name = ""
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        self.session, self.session_name = row["sessionId"], item.text()
        self.chat_title.setText(self.session_name)
        self.load_messages()

    def load_messages(self, more=False):
        if not self.session:
            return
        if self.message_job:
            self.bus.cancel(self.message_job)
        account, session = self.account, self.session
        cursor = self.cursor if more else None
        previous = list(self.messages) if more else []
        self.more_messages.setEnabled(False)
        self.status.setText("正在读取消息…")
        async def query():
            result = await CipherTalk(self.settings).messages(account, session, cursor)
            return map_messages(result.get("items", []), previous), result.get("cursor")
        def done(result, error):
            if (account, session) != (self.account, self.session):
                return
            self.message_job = None
            if error:
                self.status.setText(error)
                self.more_messages.setEnabled(bool(self.cursor))
                return
            self.messages, self.cursor = result
            self.message_list.clear()
            for message in self.messages:
                who = {"in": "对方", "out": "我", "unknown": "方向未确认"}[message.direction]
                when = datetime.fromtimestamp(message.timestamp).strftime("%m-%d %H:%M") if message.timestamp else "时间未知"
                item = QListWidgetItem(f"{who} · {when}\n{message.content}")
                item.setData(Qt.ItemDataRole.UserRole, message)
                self.message_list.addItem(item)
            if not more:
                self.message_list.scrollToBottom()
            self.more_messages.setEnabled(bool(self.cursor) and self.cursor != cursor)
            self.status.setText(f"已读取 {len(self.messages)} 条消息；可按 Ctrl / Shift 选择历史范围")
        self.message_job = self.bus.submit(query(), done)

    def prepare(self, memory_mode):
        if not self.session or not self.messages:
            self.status.setText("请先选择会话并读取消息")
            return
        selected = [i.data(Qt.ItemDataRole.UserRole) for i in self.message_list.selectedItems()]
        if memory_mode or self.scope.currentIndex() == 1:
            if not selected:
                self.status.setText("请先在中间列表选中需要分析的消息")
                return
        else:
            selected = [m for m in self.messages if m.is_text][-6:]
        self.cancel_analysis()
        self.clear_results()
        token = self.generation
        account, session, name = self.account, self.session, self.session_name
        request = self.request.text()
        skip_judgment = self.generation_mode.currentIndex() == 1
        async def load():
            return await asyncio.to_thread(lambda: (self.store.profile(account, session), self.store.memories(account, session)))
        def done(result, error):
            if token != self.generation:
                return
            if error:
                self.status.setText(error)
                return
            dialog = PreviewDialog(self, account, session, name, selected, *result, request, memory_mode)
            if dialog.exec() == QDialog.DialogCode.Accepted and token == self.generation:
                snapshot = dialog.snapshot
                if memory_mode:
                    self.generate(snapshot, None, token, True)
                elif skip_judgment:
                    from runtime.laya_decision.contract import fallback_decision
                    self.decision.setText("本轮仅生成回复，未运行本地判断")
                    self.generate(snapshot, fallback_decision("user_skipped"), token, False)
                else:
                    self.judge(snapshot, token)
        self.status.setText("正在准备本次上下文…")
        self.job = self.bus.submit(load(), done)

    def judge(self, snapshot, token):
        self.status.setText("正在运行本地判断（首次加载较慢，后续复用模型），可取消…")
        def done(decision, error):
            if token != self.generation:
                return
            if error:
                self.status.setText(error)
                return
            if decision.get("fallback"):
                self.decision.setText("判断不可用；回退值不代表模型结论")
                reason = "上下文超出 Laya 窗口，可减少消息或记忆后重试。\n" if decision.get("fallback_reason") == "context_too_long" else ""
                answer = QMessageBox.question(self, "Laya 判断不可用", reason + "是否仅根据已确认的聊天上下文生成回复？结果会注明未使用 Laya。")
                if answer != QMessageBox.StandardButton.Yes:
                    self.status.setText("已停止，可在设置中检查 Laya")
                    return
            else:
                emotions = {"positive": "积极", "neutral": "平静", "curious": "好奇", "anxious": "焦虑", "frustrated": "受挫", "sad": "难过", "angry": "生气"}
                intents = {"ask_information": "询问信息", "request_action": "请求行动", "seek_advice": "征求建议", "share_experience": "分享经历", "emotional_support": "寻求支持", "casual_chat": "日常闲聊", "correct_assistant": "纠正内容", "unknown": "信息不足"}
                self.decision.setText(f"实验性判断\n情绪：{emotions.get(decision['emotion'], '未知')}\n可能意图：{intents.get(decision['intent'], '未知')}\n回复深度：{decision['desired_depth']:.1f} / 4\n请以消息依据为准；分数未作本场景校准")
            self.generate(snapshot, decision, token, False)
        self.job = self.bus.submit(self.laya.predict(snapshot.state()), done)

    def generate(self, snapshot, decision, token, memory_mode):
        self.status.setText("正在提取记忆候选…" if memory_mode else "正在生成三条候选回复…")
        def done(result, error):
            if token != self.generation:
                return
            self.job = None
            if error:
                self.status.setText(error + "；已完成的判断仍保留")
                return
            if memory_mode:
                if result["candidates"]:
                    CandidatesDialog(self, self.bus, self.store, snapshot, result["candidates"]).exec()
                    self.status.setText("记忆处理结束；仅明确确认的条目会保存")
                else:
                    self.status.setText("没有发现适合长期保存的明确事实")
                return
            self.present_result(snapshot, decision, result)
        self.job = self.bus.submit(Generator(self.settings).generate(snapshot, decision, memory=memory_mode), done)

    def present_result(self, snapshot, decision, result):
        prefix = "未使用 Laya 判断\n\n" if decision and decision.get("fallback") else ""
        evidence = "\n".join(f"{r}：{text}" for r, _, text in snapshot.evidence if r in result["evidence_refs"])
        self.analysis.setPlainText(prefix + result["analysis"] + "\n\n消息依据：\n" + evidence)
        for field, reply in zip(self.reply_fields, result["replies"]):
            field.setPlainText(reply)
        self.status.setText("分析完成。候选未排序，请自行选择、修改和发送。")

    def open_settings(self):
        self.cancel_analysis()
        dialog = SettingsDialog(self, self.bus, self.settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            changed_model = (self.settings.laya_python, self.settings.model_path) != (dialog.value.laya_python, dialog.value.model_path)
            if changed_model:
                old_laya = self.laya
                async def release_old():
                    await old_laya.close()
                def released(_, error):
                    if not error and old_laya.close in self.bus.cleanups:
                        self.bus.cleanups.remove(old_laya.close)
                self.bus.submit(release_old(), released)
                self.laya = LayaSession(dialog.value)
                self.bus.cleanups.append(self.laya.close)
            self.settings = dialog.value
            if self.session_job:
                self.bus.cancel(self.session_job)
            if self.message_job:
                self.bus.cancel(self.message_job)
            self.sessions.clear()
            self.account = self.session = ""
            self.refresh_button.setEnabled(True)
            self.status.setText("设置已保存，请刷新会话或重新检查依赖")

    def open_contacts(self):
        self.cancel_analysis()
        ContactsDialog(self, self.bus, self.store, self.account, self.session).exec()

    def closeEvent(self, event):
        if self.shutdown_complete:
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        self.closing = True
        self.centralWidget().setEnabled(False)
        self.status.setText("正在取消任务并关闭本应用子进程…")
        self.cancel_analysis()
        def shutdown():
            try:
                self.bus.shutdown()
            except Exception:
                pass  # Never put upstream exceptions or local paths in desktop logs.
            finally:
                self.stopped.emit()
        threading.Thread(target=shutdown, daemon=True).start()

    def finish_shutdown(self):
        self.shutdown_complete = True
        self.close()
