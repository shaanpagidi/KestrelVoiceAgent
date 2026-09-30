"""Run deterministic Q4 signal tests without audio, ASR, LLM, or external services."""
from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
import statistics
import time

from q4.engine import NudgeEngine

ROOT = Path(__file__).resolve().parent.parent


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, ceil(len(ordered) * p) - 1)], 3)


def main():
    engine = NudgeEngine(threshold=0.72, cooldown_sec=45, expiry_sec=0.05)
    results = []
    latencies = []

    def check(name, passed, detail):
        results.append({"scenario": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    state = engine.create_session("demo", ["recording quality"], disclosure_deadline_sec=12)
    def process(speaker, text, audio_time, confidence=0.95):
        result = engine.process("demo", speaker, text, audio_time, confidence, True)
        latencies.append(result["signal_latency_ms"])
        return result

    process("agent", "Good afternoon. How can I help?", 0)
    missing = process("agent", "Let me check that payment option.", 13)
    check("Skipped required disclosure", any(n["rule_id"] == "missing_disclosure" for n in missing["nudges"]),
          "A compliance nudge is emitted after the configured disclosure deadline.")

    process("agent", "This call may be recorded for quality.", 14)
    seen_after_disclosure = state.disclosure_seen
    check("Disclosure recognition", seen_after_disclosure, "recorded/recording variants count as the disclosure.")

    cross_sell = process("caller", "We also bought a second vehicle.", 15)
    check("Missed cross-sell opportunity", any(n["rule_id"] == "missed_cross_sell" for n in cross_sell["nudges"]),
          "A second-vehicle mention produces a short agent suggestion.")

    risky = process("agent", "I guarantee your approval.", 16)
    check("Risky promise", any(n["rule_id"] == "risky_promise" for n in risky["nudges"]),
          "A guarantee statement produces a high-priority compliance alert.")

    frustration = process("caller", "This is frustrating. No one is helping me.", 17)
    check("Rising frustration", any(n["rule_id"] == "frustration" for n in frustration["nudges"]),
          "Frustration language prompts acknowledgement and human-help guidance.")

    hardship = process("caller", "I lost my job and cannot afford the installment.", 18)
    check("Payment difficulty", any(n["rule_id"] == "payment_hardship" for n in hardship["nudges"]),
          "Hardship language suggests the approved support or callback path.")

    engine.create_session("topic")
    topic_first = engine.process("topic", "caller", "I want to discuss the installment.", 1)
    topic_shift = engine.process("topic", "caller", "I also need to understand my policy coverage.", 2)
    check("Topic shift", any(n["rule_id"] == "topic_shift" for n in topic_shift["nudges"]),
          "A payment-to-coverage shift suggests acknowledging and confirming the new intent.")

    noisy = process("caller", "Maybe another vehicle, I am not sure.", 21, confidence=0.42)
    check("Noisy / ambiguous input", not noisy["nudges"] and noisy["suppressed"].get("low_transcript_confidence", 0) > 0,
          "Low-confidence transcript does not create a nudge.")

    engine.create_session("duplicate")
    duplicate_1 = engine.process("duplicate", "caller", "I am fed up with this.", 1)
    duplicate_2 = engine.process("duplicate", "caller", "I am fed up with this.", 2)
    check("Duplicate suppression / cooldown", bool(duplicate_1["nudges"]) and not duplicate_2["nudges"] and
          duplicate_2["suppressed"].get("duplicate", 0) > 0,
          "Repeated same-group frustration nudge is suppressed during cooldown.")

    expiring_engine = NudgeEngine(cooldown_sec=1, expiry_sec=0.01)
    expiring_engine.create_session("expiry")
    expiring_engine.process("expiry", "caller", "I lost my job and cannot pay.", 1)
    time.sleep(0.02)
    check("Nudge expiry", not expiring_engine.active_nudges("expiry"), "Expired nudges are removed from the active feed.")

    passed = sum(r["status"] == "PASS" for r in results)
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": "deterministic transcript fixtures; no audio or ASR",
        "passed": passed, "total": len(results), "scenarios": results,
        "signal_latency_ms": {"p50": percentile(latencies, .50), "p95": percentile(latencies, .95), "samples": len(latencies)},
        "asr_latency_ms": None,
        "llm_latency_ms": 0,
        "false_positive_review": "Zero nudges from one low-confidence noisy fixture (n=1). This is a control check, not a statistically meaningful false-positive rate.",
        "limits": "ASR, network delivery, and dashboard display latency require the audio replay and a real client."
    }
    out_json = ROOT / "out" / "q4_rule_eval.json"
    out_md = ROOT / "out" / "q4_rule_eval.md"
    out_json.parent.mkdir(exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Q4 deterministic signal checks", "",
             "Synthetic transcript fixtures only; no audio, ASR, LLM, or network delivery was used.", "",
             "| Scenario | Result | Detail |", "|---|---|---|"]
    lines.extend(f"| {r['scenario']} | {r['status']} | {r['detail']} |" for r in results)
    lines += ["", f"Result: {passed}/{len(results)} passed.", "",
              f"Signal detection latency: P50 {report['signal_latency_ms']['p50']} ms; P95 {report['signal_latency_ms']['p95']} ms (in-process synthetic transcript path).",
              "ASR and end-to-end audio/display latency are not measured in this report.", "",
              report["false_positive_review"]]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"q4_rule_checks={passed}/{len(results)} report={out_md.relative_to(ROOT)}")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
