"""Pinned multilingual checkpoint; generated manifest is verified before loading."""
import hashlib
import json
from pathlib import Path

MODEL_REPO = "convaiinnovations/laya"
MODEL_REVISION = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
MODEL_FILES = ("rl_agent_config.json", "model.safetensors", "encoder/config.json",
               "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model(root: Path) -> None:
    manifest = json.loads((root / "assistant-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("repo") != MODEL_REPO or manifest.get("revision") != MODEL_REVISION:
        raise ValueError("unexpected checkpoint")
    for name in MODEL_FILES:
        if sha256(root / name) != manifest["sha256"][name]:
            raise ValueError("model file integrity failure")
