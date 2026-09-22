"""Smoke-test a copied onedir build with Python/Node absent from PATH."""
import os
from pathlib import Path
import shutil
import subprocess


def main():
    source = Path("dist/JevLocalAssistant").resolve()
    test_root = Path("build/中文路径验收").resolve()
    app_dir = test_root / "JevLocalAssistant"
    shutil.copytree(source, app_dir, dirs_exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "QT_", "LAYA_", "MIYU_"))}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["LOCALAPPDATA"] = str(test_root / "local-data")
    screenshot = test_root / "desktop.png"
    result = subprocess.run([str(app_dir / "JevLocalAssistant.exe"), "--smoke-test", "--smoke-output", str(screenshot)],
                            cwd=test_root, env=env, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not screenshot.exists() or screenshot.stat().st_size < 1000:
        raise RuntimeError("Packaged desktop smoke test failed")
    assert (test_root / "local-data/JevLocalAssistant/assistant.sqlite3").exists()
    print("PASS: EXE startup, Chinese deployment path, isolated PATH, bundled Python, local database, screenshot and orderly exit.")
    print("This does not replace testing on a clean Windows machine.")


if __name__ == "__main__":
    main()
