from __future__ import annotations

import os
import sys
import asyncio
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop.config import Settings, data_dir
from desktop.storage import Store
from desktop.window import MainWindow


async def diagnostics(settings):
    from desktop.adapters import CipherTalk, LayaClient
    from desktop.domain import AppError
    results = await asyncio.gather(CipherTalk(settings).check(), LayaClient(settings).check(), return_exceptions=True)
    return {name: {"ok": isinstance(result, str), "message": str(result) if isinstance(result, (str, AppError)) else "检查失败"}
            for name, result in zip(("ciphertalk", "laya"), results)}


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("JevLocalAssistant")
    app.setOrganizationName("LocalTools")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; }
        QMainWindow { background: #f3f5f8; }
        QLabel#heading { font-size: 21px; font-weight: 600; padding: 8px; color: #203b50; }
        QPushButton { padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; }
        QPushButton:hover { background: #e7f0f8; }
        QPushButton:disabled { color: #9aa4b2; }
        QLineEdit, QPlainTextEdit, QListWidget, QComboBox { background: white; color: #182a3b; border: 1px solid #cbd5e1; border-radius: 4px; padding: 5px; }
        QListWidget::item { padding: 8px; }
        QListWidget::item:selected { background: #dbeafe; color: #173954; }
    """)
    path = data_dir()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            settings = pool.submit(Settings.load).result()
            store = pool.submit(Store, path / "assistant.sqlite3").result()
    except Exception:
        QMessageBox.critical(None, "启动失败", "无法读取本地设置或数据库，请检查应用数据目录及 settings.json 格式。")
        return 1
    if "--diagnose-output" in sys.argv:
        result = asyncio.run(diagnostics(settings))
        target = Path(sys.argv[sys.argv.index("--diagnose-output") + 1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if all(r["ok"] for r in result.values()) else 2
    smoke = "--smoke-test" in sys.argv
    window = MainWindow(settings, store, first_run=not (path / "settings.json").exists() and not smoke)
    window.show()
    if smoke:
        if "--smoke-output" in sys.argv:
            target = Path(sys.argv[sys.argv.index("--smoke-output") + 1])
            target.parent.mkdir(parents=True, exist_ok=True)
            QTimer.singleShot(700, lambda: window.grab().save(str(target)))
        QTimer.singleShot(1200, window.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
