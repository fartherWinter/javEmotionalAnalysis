"""Real process used to test JSONL reuse, cancellation, and recovery."""
import json
import os
import sys
import time

from runtime.laya_decision.contract import fallback_decision


for line in sys.stdin:
    req = json.loads(line)
    state = req.get("state", {})
    if state.get("crash"):
        raise SystemExit(3)
    if state.get("delay"):
        time.sleep(state["delay"])
    response = {"id": "wrong" if state.get("wrong_id") else req["id"], "ok": True,
                "check": {"available": True}, "decision": fallback_decision("fixture"), "pid": os.getpid()}
    print(json.dumps(response), flush=True)
