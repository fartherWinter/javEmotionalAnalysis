"""Copy installed distribution notices for the local desktop build."""
from importlib.metadata import distributions
from pathlib import Path
import shutil


def main():
    root = Path("dist/JevLocalAssistant/third-party")
    root.mkdir(parents=True, exist_ok=True)
    rows = ["# 第三方组件\n", "本清单记录构建环境中的组件，部分仅用于测试或打包。Qt/PySide6 DLL 动态链接并可替换。\n",
            "Qt/PySide6 6.8.3 对应源码：https://download.qt.io/archive/qt/6.8/6.8.3/ 与 https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.8.3\n",
            "PyInstaller 引导程序按其 GPL 及打包例外使用：https://pyinstaller.org/en/stable/license.html\n"]
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].casefold()):
        name = dist.metadata["Name"]
        rows.append(f"- {name} {dist.version}\n")
        for file in dist.files or []:
            if any(word in file.name.lower() for word in ("license", "copying", "notice")) and str(file).endswith((".txt", ".md", "LICENSE", "COPYING", "NOTICE")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = root / name / str(file).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    (root / "README.md").write_text("\n".join(rows), encoding="utf-8")
    for file in Path("licenses").glob("*.txt"):
        shutil.copyfile(file, root / file.name)


if __name__ == "__main__":
    main()
