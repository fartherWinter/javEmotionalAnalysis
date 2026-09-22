"""Explicit, setup-only download. Never called by desktop or worker."""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Run as `python -m scripts.prepare_laya_model` from the repository root.
from runtime.laya_decision.model_manifest import MODEL_FILES, MODEL_REPO, MODEL_REVISION, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in MODEL_FILES:
        target = args.destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/multilingual/{name}"
        print(f"Downloading {name}", flush=True)
        temp = target.with_suffix(target.suffix + ".partial")
        with urllib.request.urlopen(url, timeout=120) as response, temp.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temp.replace(target)
        hashes[name] = sha256(target)
    manifest = {"repo": MODEL_REPO, "revision": MODEL_REVISION, "sha256": hashes}
    (args.destination / "assistant-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Model ready; select this directory in desktop settings.")


if __name__ == "__main__":
    main()
