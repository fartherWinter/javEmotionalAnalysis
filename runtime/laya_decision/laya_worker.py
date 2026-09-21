"""JSONL Laya sidecar with safe fallback when optional model dependencies are absent."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from .contract import (
    CALIBRATION_VERSION, CONTRACT_VERSION, MODEL_VERSION, ContractError,
    fallback_decision, validate_decision, validate_request,
)
from .questions import build_state, question_schema

logging.basicConfig(stream=sys.stderr, level=os.getenv("LAYA_LOG_LEVEL", "WARNING"))
LOGGER = logging.getLogger("laya-worker")


class LayaEngine:
    def __init__(self) -> None:
        self.model = None
        self.model_version = os.getenv("LAYA_MODEL_VERSION", MODEL_VERSION)
        self._load_optional_model()

    def _load_optional_model(self) -> None:
        if os.getenv("LAYA_DISABLE_MODEL", "").lower() in {"1", "true", "yes"}:
            return
        try:
            from laya import Router  # type: ignore
            device = "cpu"
            try:
                import torch  # type: ignore
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                pass
            self.model = Router(preload=True, device=device, max_loaded=1)
            LOGGER.info("Laya model loaded on %s", device)
        except Exception as exc:  # optional dependency/model cache
            LOGGER.warning("Laya unavailable: %s", exc)

    def check(self) -> dict[str, Any]:
        return {
            "available": self.model is not None,
            "model_version": self.model_version,
            "calibration_version": CALIBRATION_VERSION,
            "device": os.getenv("LAYA_DEVICE", "auto"),
            "contract_version": CONTRACT_VERSION,
        }

    def predict(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.model is None:
            return fallback_decision()
        try:
            payload = question_schema(state)
            # Laya releases may expose different invocation names; keep this adapter isolated.
            result = self.model.predict(payload) if hasattr(self.model, "predict") else self.model(payload)
            decision = _normalize_model_result(result, self.model_version)
            return validate_decision(decision)
        except Exception as exc:
            LOGGER.exception("prediction failed")
            return fallback_decision(f"prediction_error:{type(exc).__name__}")


def _normalize_model_result(result: Any, model_version: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ContractError("model result must be an object")
    decision = dict(result.get("decision", result))
    decision.setdefault("emotion_confidence", decision.get("confidence", 0.0))
    decision.setdefault("intent_confidence", decision.get("confidence", 0.0))
    decision.setdefault("confidence", 0.0)
    decision.setdefault("desired_depth", 2.0)
    decision.setdefault("needs_clarification", 0.0)
    decision.setdefault("use_long_term_memory", 0.0)
    decision.setdefault("profile_deviation", 0.0)
    decision.setdefault("model", model_version)
    decision.setdefault("model_version", model_version)
    decision.setdefault("calibration_version", CALIBRATION_VERSION)
    decision.setdefault("fallback", False)
    return decision


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
            LOGGER.exception("request failed")
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
