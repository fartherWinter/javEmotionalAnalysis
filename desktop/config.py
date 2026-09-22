from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "JevLocalAssistant"
    root.mkdir(parents=True, exist_ok=True)
    return root


def resource_root() -> Path:
    import sys
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


@dataclass(frozen=True)
class Settings:
    node_path: str = ""
    cli_path: str = ""
    laya_python: str = ""
    model_path: str = ""
    base_url: str = ""
    model: str = ""
    key_env: str = "OPENAI_API_KEY"

    @classmethod
    def discover(cls, roots: list[Path] | None = None) -> Settings:
        import shutil
        import sys
        if roots is None:
            roots = [resource_root()]
            if getattr(sys, "frozen", False):
                executable_dir = Path(sys.executable).resolve().parent
                roots += [executable_dir, *list(executable_dir.parents)[:2]]
        def first(relative: str, *, directory=False) -> str:
            for root in roots:
                candidate = root / relative
                found = (candidate / "assistant-manifest.json").is_file() if directory else candidate.is_file()
                if found:
                    return str(candidate.resolve())
            return ""
        return cls(node_path=shutil.which("node") or "",
                   cli_path=first("CipherTalk-CLI/bin/miyu.js"),
                   laya_python=first(".venv-laya/Scripts/python.exe"),
                   model_path=first(".venv-laya/model", directory=True))

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or data_dir() / "settings.json"
        if not path.exists():
            return cls.discover()
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict) or any(not isinstance(v, str) for v in obj.values()):
                raise ValueError
            return cls(**{k: v for k, v in obj.items() if k in cls.__dataclass_fields__})
        except (ValueError, TypeError):
            raise ValueError("设置文件格式无效，请在应用数据目录备份后修正 settings.json") from None

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", self.key_env):
            raise ValueError("请填写环境变量名称，而不是密钥内容")
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("接口地址不得包含凭据、查询参数或片段")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("云端接口必须使用 HTTPS；HTTP 仅限本机")

    def save(self, path: Path | None = None) -> None:
        self.validate()
        path = path or data_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
