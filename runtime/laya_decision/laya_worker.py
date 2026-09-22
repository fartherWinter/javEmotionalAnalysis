"""JSONL Laya sidecar with safe fallback when optional model dependencies are absent."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .contract import (
    CALIBRATION_VERSION, CONTRACT_VERSION, MODEL_VERSION, ContractError,
    fallback_decision, validate_decision, validate_request,
)
from .questions import build_state, question_schema, intent_state

logging.basicConfig(stream=sys.stderr, level=os.getenv("LAYA_LOG_LEVEL", "WARNING"))
LOGGER = logging.getLogger("laya-worker")


class LayaEngine:
    def __init__(self) -> None:
        self.model = None
        self.tokenizer = None
        self.max_state_tokens = 0
        self.device = "cpu"
        self.model_version = MODEL_VERSION
        self._load_optional_model()

    def _load_optional_model(self) -> None:
        if os.getenv("LAYA_DISABLE_MODEL", "").lower() in {"1", "true", "yes"}:
            return
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            model_dir = Path(os.environ.get("LAYA_MODEL_PATH", ""))
            from .model_manifest import verify_model
            verify_model(model_dir)
            if version("laya") != "0.3.5":
                raise RuntimeError("unsupported SDK version")
            with redirect_stdout(sys.stderr):
                import laya
                import torch
                self.device = os.environ.get("LAYA_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
                self.model = laya.load(str(model_dir), device=self.device)
                self.tokenizer = self.model.tok
                self.max_state_tokens = self.model.cfg.get("max_len", 1024) - self.model.cfg.get("head_max_len", 256) - 4
            from .model_manifest import MODEL_REVISION
            self.model_version = "laya-0.3.5:multilingual@" + MODEL_REVISION
            LOGGER.info("Laya model loaded")
        except Exception as exc:  # optional dependency/model cache
            LOGGER.warning("Laya unavailable (%s)", type(exc).__name__)

    def check(self) -> dict[str, Any]:
        return {
            "available": self.model is not None,
            "model_version": self.model_version,
            "calibration_version": CALIBRATION_VERSION,
            "device": self.device,
            "contract_version": CONTRACT_VERSION,
        }

    def predict(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.model is None:
            return fallback_decision()
        try:
            focused = intent_state(state)
            if focused is None:
                return fallback_decision("missing_incoming_message")
            if self.tokenizer is not None:
                for value in (json.dumps(state, ensure_ascii=False), focused):
                    tokens = self.tokenizer(value.replace(self.tokenizer.mask_token, " "), add_special_tokens=False)["input_ids"]
                    if len(tokens) > self.max_state_tokens:
                        return fallback_decision("context_too_long")
            questions = question_schema(state)
            intent_question = {"intent": questions.pop("intent")}
            with redirect_stdout(sys.stderr):
                result = self.model.predict(state, questions)
                intent_result = self.model.predict(focused, intent_question)
            result["answers"]["intent"] = intent_result["answers"]["intent"]
            decision = _normalize_model_result(result, self.model_version)
            return validate_decision(decision)
        except Exception as exc:
            LOGGER.warning("prediction failed (%s)", type(exc).__name__)
            return fallback_decision(f"prediction_error:{type(exc).__name__}")


def _normalize_model_result(result: Any, model_version: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ContractError("model result must be an object")
    answers = result["answers"]
    emotion, intent = answers["emotion"], answers["intent"]
    return {
        "emotion": emotion["choice"], "intent": intent["choice"],
        "emotion_confidence": emotion["confidence"], "intent_confidence": intent["confidence"],
        "confidence": min(emotion["confidence"], intent["confidence"]),
        # SDK ordinal scores are 0..3; the established JSONL contract is 1..4.
        "desired_depth": float(answers["desired_depth"]["score"]) + 1,
        **{key: answers[key]["noul"] for key in ("needs_clarification", "use_long_term_memory", "profile_deviation")},
        "model": model_version, "model_version": model_version,
        "calibration_version": CALIBRATION_VERSION, "fallback": False,
    }


def handle(request: dict[str, Any], engine: LayaEngine) -> dict[str, Any]:
    validate_request(request)
    if request["method"] == "check":
        return {"id": request["id"], "ok": True, "check": engine.check(), "contract_version": CONTRACT_VERSION}
    state = build_state(request["state"])
    decision = engine.predict(state)
    return {
        "id": request["id"],
        "ok": True,
        "decision": decision,
        "privacy": {"redacted_input": True, "raw_messages_persisted": False},
        "contract_version": CONTRACT_VERSION,
    }


def run_jsonl(engine: LayaEngine, stream_in: Any = sys.stdin, stream_out: Any = sys.stdout) -> None:
    for line in stream_in:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle(request, engine)
        except json.JSONDecodeError:
            response = {"id": None, "ok": False, "error": {"code": "invalid_json", "message": "request is not valid JSON"}}
        except ContractError as exc:
            response = {"id": request.get("id") if isinstance(request, dict) else None, "ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
        except Exception as exc:
            LOGGER.warning("request failed (%s)", type(exc).__name__)
            response = {"id": request.get("id") if isinstance(request, dict) else None, "ok": False, "error": {"code": "internal_error", "message": type(exc).__name__}}
        stream_out.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream_out.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="run one environment check and exit")
    args = parser.parse_args()
    engine = LayaEngine()
    if args.check:
        print(json.dumps(engine.check(), ensure_ascii=False))
        return 0 if engine.model is not None else 2
    run_jsonl(engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
