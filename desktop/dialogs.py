from __future__ import annotations

import asyncio
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .adapters import CipherTalk, LayaClient
from .config import Settings
from .domain import Snapshot, make_snapshot


def note(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class ManagedDialog(QDialog):
    def __init__(self, parent, bus):
        super().__init__(parent)
        self.bus = bus
        self.jobs = set()
        self.finished.connect(self.cancel_jobs)

    def run(self, coro, callback):
        def finish(value, error):
            self.jobs.discard(job)
            if self.isVisible():
                callback(value, error)
        job = self.bus.submit(coro, finish)
        self.jobs.add(job)

    def cancel_jobs(self, *_):
        for job in self.jobs:
            self.bus.cancel(job)
        self.jobs.clear()


class SettingsDialog(ManagedDialog):
    def __init__(self, parent, bus, settings):
        super().__init__(parent, bus)
        self.setWindowTitle("设置与依赖诊断")
        self.resize(780, 580)
        self.value = settings
        layout = QVBoxLayout(self)
        layout.addWidget(note("工具自身无需 Python。CipherTalk / Node 与 Laya 模型环境需独立准备；缺少依赖不影响管理本地档案。"))
        form = QFormLayout()
        layout.addLayout(form)
        self.fields = {}
        labels = {"node_path": "Node.exe", "cli_path": "CipherTalk CLI 入口 (.js)",
                  "laya_python": "Laya Python.exe", "model_path": "Laya 本地模型目录",
                  "base_url": "生成接口基础地址（包含 /v1 如需）", "model": "生成模型名称", "key_env": "密钥环境变量名"}
        for key, title in labels.items():
            field = QLineEdit(getattr(settings, key))
            self.fields[key] = field
            if key in {"node_path", "cli_path", "laya_python", "model_path"}:
                row = QWidget()
                box = QHBoxLayout(row)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(field)
                button = QPushButton("选择…")
                button.clicked.connect(lambda _, k=key: self.browse(k))
                box.addWidget(button)
                form.addRow(title, row)
            else:
                form.addRow(title, field)
        self.key_status = note("")
        layout.addWidget(self.key_status)
        self.fields["key_env"].textChanged.connect(self.key_changed)
        self.key_changed()
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setPlainText("首次使用：选择外部依赖 → 检查依赖 → 保存。\nCipherTalk 授权可能联网。模型检查只加载本地文件，不下载权重。")
        layout.addWidget(self.status)
        self.check_button = QPushButton("检查 CipherTalk 与 Laya")
        self.check_button.clicked.connect(self.check)
        layout.addWidget(self.check_button)
        discover = QPushButton("自动查找已准备的依赖（仅填充空项）")
        discover.clicked.connect(self.discover)
        layout.addWidget(discover)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def key_changed(self, *_):
        configured = bool(os.environ.get(self.fields["key_env"].text().strip()))
        self.key_status.setText("密钥状态：" + ("已配置（不显示内容）" if configured else "未配置；本机无鉴权接口可留空"))

    def browse(self, key):
        path = QFileDialog.getExistingDirectory(self, "选择模型目录") if key == "model_path" else QFileDialog.getOpenFileName(self, "选择文件")[0]
        if path:
            self.fields[key].setText(path)

    def read(self):
        return Settings(**{k: field.text().strip() for k, field in self.fields.items()})

    def discover(self):
        def done(settings, error):
            if error:
                self.status.setPlainText(error)
                return
            filled = 0
            for key in ("node_path", "cli_path", "laya_python", "model_path"):
                value = getattr(settings, key)
                if value and not self.fields[key].text().strip():
                    self.fields[key].setText(value)
                    filled += 1
            self.status.setPlainText(f"已补充 {filled} 项路径，现有填写内容保持不变。未找到的组件请手动选择。")
        self.run(asyncio.to_thread(Settings.discover), done)

    def check(self):
        self.check_button.setEnabled(False)
        self.status.setPlainText("正在检查外部依赖，最多约两分钟，可关闭窗口取消…")
        settings = self.read()
        async def check_all():
            results = await asyncio.gather(CipherTalk(settings).check(), LayaClient(settings).check(), return_exceptions=True)
            from .domain import AppError
            return "\n".join(str(r) if isinstance(r, (str, AppError)) else "依赖检查失败" for r in results)
        def done(value, error):
            self.status.setPlainText(error or value)
            self.check_button.setEnabled(True)
        self.run(check_all(), done)

    def save(self):
        settings = self.read()
        try:
            settings.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "设置未保存", str(exc))
            return
        async def write():
            await asyncio.to_thread(settings.save)
        def done(_, error):
            if error:
                QMessageBox.warning(self, "设置未保存", error)
            else:
                self.value = settings
                self.accept()
        self.run(write(), done)


class PreviewDialog(QDialog):
    def __init__(self, parent, account, session, name, messages, profile, memories, request, memory_mode):
        super().__init__(parent)
        self.setWindowTitle("确认本次模型上下文")
        self.resize(850, 650)
        self.snapshot = None
        self.args = (account, session, name, messages, profile)
        self.memories, self.request, self.memory_mode = memories[:10], request, memory_mode
        layout = QVBoxLayout(self)
        layout.addWidget(note("以下是将发给模型的脱敏上下文，请检查后确认。分析还会附加本地 Laya 判断；聊天内容不作为程序指令。"))
        self.options = []
        for memory in self.memories:
            box = QCheckBox(memory["topic"] + "：" + memory["content"][:100])
            box.setChecked(True)
            box.toggled.connect(self.refresh)
            layout.addWidget(box)
            self.options.append(box)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认并发送分析")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.refresh()

    def refresh(self):
        from .domain import AppError
        try:
            selected = [m for m, b in zip(self.memories, self.options) if b.isChecked()]
            self.snapshot = make_snapshot(*self.args, selected, self.request, memory_mode=self.memory_mode)
            self.preview.setPlainText(self.snapshot.payload)
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except AppError as exc:
            self.snapshot = None
            self.preview.setPlainText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)


class ContactsDialog(ManagedDialog):
    def __init__(self, parent, bus, store, account="", session=""):
        super().__init__(parent, bus)
        self.store, self.account, self.session = store, account, session
        self.ready = False
        self.setWindowTitle("联系人档案与已确认记忆")
        self.resize(800, 650)
        layout = QVBoxLayout(self)
        self.contacts = QListWidget()
        self.contacts.setMaximumHeight(100)
        self.contacts.currentItemChanged.connect(self.select_contact)
        layout.addWidget(self.contacts)
        form = QFormLayout()
        self.fields = {k: QLineEdit() for k in ("relationship", "notes", "style")}
        for key, title in zip(self.fields, ("关系", "备注", "沟通偏好")):
            form.addRow(title, self.fields[key])
        layout.addLayout(form)
        buttons = QHBoxLayout()
        for title, callback in (("保存档案", self.save), ("删除档案", self.delete_profile)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.memories = QListWidget()
        self.memories.currentItemChanged.connect(self.show_memory)
        layout.addWidget(self.memories)
        self.content = QPlainTextEdit()
        self.content.setMaximumHeight(85)
        layout.addWidget(self.content)
        self.pinned = QCheckBox("优先引用此记忆")
        layout.addWidget(self.pinned)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(90)
        layout.addWidget(self.evidence)
        buttons = QHBoxLayout()
        for title, callback in (("保存记忆修改", self.edit), ("删除选中记忆", self.delete)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = note("正在读取本地档案…")
        layout.addWidget(self.status)
        self.run(asyncio.to_thread(store.contacts), self.loaded_contacts)

    def loaded_contacts(self, pairs, error):
        if error:
            self.status.setText(error)
            return
        if self.account and self.session and (self.account, self.session) not in pairs:
            pairs.insert(0, (self.account, self.session))
        for pair in pairs:
            item = QListWidgetItem(" / ".join(pair))
            item.setData(Qt.ItemDataRole.UserRole, pair)
            self.contacts.addItem(item)
        if pairs:
            target = pairs.index((self.account, self.session)) if (self.account, self.session) in pairs else 0
            self.contacts.setCurrentRow(target)
        else:
            self.status.setText("暂无本地档案。连接数据源并选择会话后可新建。")

    def select_contact(self, item, _):
        if item:
            self.account, self.session = item.data(Qt.ItemDataRole.UserRole)
            self.refresh()

    def refresh(self):
        self.ready = False
        account, session = self.account, self.session
        for field in self.fields.values():
            field.clear()
        self.memories.clear()
        self.content.clear()
        self.evidence.clear()
        async def load():
            return await asyncio.to_thread(lambda: (self.store.profile(account, session), self.store.memories(account, session)))
        def done(value, error):
            if (account, session) != (self.account, self.session):
                return
            self.status.setText(error or "仅确认后的记忆会参与分析；修改内容不会改写原始证据。")
            if not error:
                self.ready = True
                profile, memories = value
                for k, field in self.fields.items():
                    field.setText(profile.get(k, ""))
                for m in memories:
                    item = QListWidgetItem(("★ " if m["pinned"] else "") + m["topic"] + "：" + m["content"])
                    item.setData(Qt.ItemDataRole.UserRole, m)
                    self.memories.addItem(item)
        self.run(load(), done)

    def mutation(self, fn, *args):
        if not self.account or not self.session or not self.ready:
            self.status.setText("请先选择联系人并等待档案加载完成")
            return
        self.run(asyncio.to_thread(fn, self.account, self.session, *args),
                 lambda _, error: self.status.setText(error) if error else self.refresh())

    def save(self):
        self.mutation(self.store.save_profile, {k: f.text() for k, f in self.fields.items()})

    def delete_profile(self):
        if QMessageBox.question(self, "删除档案", "删除该联系人档案？已确认记忆仍保留，可单独删除。") == QMessageBox.StandardButton.Yes:
            self.mutation(self.store.delete_profile)

    def show_memory(self, item, _):
        if item:
            m = item.data(Qt.ItemDataRole.UserRole)
            self.content.setPlainText(m["content"])
            self.pinned.setChecked(bool(m["pinned"]))
            self.evidence.setPlainText(json.dumps(m["evidence"], ensure_ascii=False, indent=2))

    def edit(self):
        item = self.memories.currentItem()
        if item:
            self.mutation(self.store.edit, item.data(Qt.ItemDataRole.UserRole)["id"], self.content.toPlainText(), self.pinned.isChecked())

    def delete(self):
        item = self.memories.currentItem()
        if item and QMessageBox.question(self, "删除记忆", "删除后不再用于新的分析，确认删除？") == QMessageBox.StandardButton.Yes:
            self.mutation(self.store.delete, item.data(Qt.ItemDataRole.UserRole)["id"])


class CandidatesDialog(ManagedDialog):
    def __init__(self, parent, bus, store, snapshot: Snapshot, candidates: list[dict]):
        super().__init__(parent, bus)
        self.store, self.snapshot, self.candidates = store, snapshot, candidates
        self.existing = []
        self.ready = False
        self.setWindowTitle("记忆候选：确认后才保存")
        self.resize(820, 660)
        layout = QVBoxLayout(self)
        layout.addWidget(note("请核对事实与证据，并检查是否与任何已有记忆冲突。矛盾或同主题应选中旧记忆后明确替换；临时情绪应拒绝。"))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.select)
        layout.addWidget(self.list)
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(90)
        layout.addWidget(self.text)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(110)
        layout.addWidget(self.evidence)
        layout.addWidget(note("已有记忆（选择需要替换的一条；不冲突则新增）"))
        self.old = QListWidget()
        layout.addWidget(self.old)
        row = QHBoxLayout()
        self.save_button = QPushButton("确认新增")
        self.replace_button = QPushButton("明确替换选中旧记忆")
        self.reject_button = QPushButton("拒绝候选")
        for button in (self.save_button, self.replace_button, self.reject_button):
            row.addWidget(button)
        self.save_button.clicked.connect(lambda: self.confirm(False))
        self.replace_button.clicked.connect(lambda: self.confirm(True))
        self.reject_button.clicked.connect(self.reject_candidate)
        layout.addLayout(row)
        self.status = note("候选尚未保存")
        layout.addWidget(self.status)
        self.busy = False
        for c in candidates:
            self.list.addItem(c["topic"] + "：" + c["content"])
        self.list.setCurrentRow(0)
        self.reload()

    def reload(self):
        self.ready = False
        self.run(asyncio.to_thread(self.store.memories, self.snapshot.account, self.snapshot.session), self.loaded)

    def loaded(self, memories, error):
        if error:
            self.status.setText(error)
            return
        self.existing = memories
        self.ready = True
        self.old.clear()
        for m in memories:
            item = QListWidgetItem(m["topic"] + "：" + m["content"])
            item.setData(Qt.ItemDataRole.UserRole, m["id"])
            self.old.addItem(item)

    def select(self, index):
        if 0 <= index < len(self.candidates):
            c = self.candidates[index]
            self.text.setPlainText(c["content"])
            selected = [f"{r}：{text}" for r, _, text in self.snapshot.evidence if r in c["evidence_refs"]]
            self.evidence.setPlainText("\n".join(selected))

    def reject_candidate(self):
        if self.busy:
            return
        index = self.list.currentRow()
        if index >= 0:
            self.candidates.pop(index)
            self.list.takeItem(index)
            self.text.clear()
            self.evidence.clear()
            self.list.setCurrentRow(min(index, len(self.candidates) - 1))
            self.select(self.list.currentRow())
        if not self.candidates:
            self.accept()

    def confirm(self, replace):
        index = self.list.currentRow()
        if index < 0 or self.busy:
            return
        if not self.ready:
            self.status.setText("请等待已有记忆加载完成后再确认")
            return
        old = self.old.currentItem()
        if replace and old is None:
            self.status.setText("请先选择要替换的旧记忆")
            return
        candidate = {**self.candidates[index], "content": self.text.toPlainText()}
        if replace and QMessageBox.question(self, "确认替换", "将删除选中的旧记忆并保存当前候选，是否继续？") != QMessageBox.StandardButton.Yes:
            return
        self.busy = True
        self.list.setEnabled(False)
        def done(_, error):
            self.busy = False
            self.list.setEnabled(True)
            self.status.setText(error or "已确认保存")
            if not error:
                self.reject_candidate()
                self.reload()
        self.run(asyncio.to_thread(self.store.confirm, self.snapshot, candidate,
                                   old.data(Qt.ItemDataRole.UserRole) if replace else None), done)
