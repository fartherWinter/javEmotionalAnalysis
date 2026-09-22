"""Run the authored Chinese cases with real local weights; never downloads."""
import argparse
import json
import time
from pathlib import Path

from runtime.laya_decision.laya_worker import LayaEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build/laya-evaluation.json"))
    args = parser.parse_args()
    start = time.monotonic()
    engine = LayaEngine()
    load_seconds = time.monotonic() - start
    if not engine.check()["available"]:
        print("Local model unavailable; evaluation NOT passed.")
        return 2
    cases = json.loads(Path("tests/fixtures/chinese_eval.json").read_text(encoding="utf-8"))
    results = []
    for i, case in enumerate(cases):
        start = time.monotonic()
        decision = engine.predict({"session_id": "evaluation", "recent_messages": [{"direction": "in", "content": case["text"]}],
                                   "profile_summary": {}, "candidate_memories": [], "user_request": "帮助我回复对方"})
        results.append({"case": i + 1, "expected": case, "decision": decision, "seconds": round(time.monotonic() - start, 3)})
        print(f"Case {i + 1}/{len(cases)} fallback={decision['fallback']}", flush=True)
    report = {
        "dataset": "30 authored synthetic Chinese examples; not independent human evaluation",
        "model": engine.check(), "load_seconds": round(load_seconds, 3), "cases": len(cases),
        "fallbacks": sum(r["decision"]["fallback"] for r in results),
        "emotion_matches": sum(r["decision"]["emotion"] == r["expected"]["emotion"] and not r["decision"]["fallback"] for r in results),
        "intent_matches": sum(r["decision"]["intent"] == r["expected"]["intent"] and not r["decision"]["fallback"] for r in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
    return 2 if report["fallbacks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
