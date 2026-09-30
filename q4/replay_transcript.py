"""Replay transcript segments on a real-time schedule into the Q4 polling API.

This is useful for deterministic signal tests, but it does not exercise audio or ASR.
Use `python -m q4.audio_replay` for a real WAV-to-streaming-ASR path.
"""
import argparse
from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
import time
import uuid

import requests

ROOT = Path(__file__).resolve().parent.parent


def percentile(values, p):
    if not values:
        return None
    vals = sorted(values)
    return round(vals[min(len(vals) - 1, ceil(len(vals) * p) - 1)], 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/q4/demo_call.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--speed", type=float, default=1.0, help="1.0 replays on the original real-time offsets")
    parser.add_argument("--session-id", default=f"replay-{uuid.uuid4().hex[:8]}")
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be greater than zero")
    rows = [json.loads(line) for line in (ROOT / args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    created = requests.post(f"{args.base_url}/sessions", json={"session_id": args.session_id}, timeout=10)
    created.raise_for_status()
    start = time.perf_counter()
    rtts, emitted = [], []
    for row in rows:
        target = float(row["offset_sec"]) / args.speed
        delay = target - (time.perf_counter() - start)
        if delay > 0:
            time.sleep(delay)
        sent = time.perf_counter()
        response = requests.post(f"{args.base_url}/sessions/{args.session_id}/transcripts", json={
            "speaker": row["speaker"], "text": row["text"], "audio_time_sec": row["offset_sec"],
            "confidence": row.get("confidence", 1.0), "is_final": True,
            "asr_latency_ms": None
        }, timeout=10)
        response.raise_for_status()
        rtts.append((time.perf_counter() - sent) * 1000)
        emitted.extend(response.json()["nudges"])
    metrics = requests.get(f"{args.base_url}/sessions/{args.session_id}/metrics", timeout=10)
    metrics.raise_for_status()
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(), "session_id": args.session_id,
        "input_mode": "synthetic transcript replay; no audio or ASR",
        "chunks": len(rows), "nudges": emitted,
        "client_api_round_trip_ms": {"p50": percentile(rtts, .50), "p95": percentile(rtts, .95), "samples": len(rtts)},
        "pipeline_metrics": metrics.json(),
        "latency_limitations": "ASR latency and real dashboard display latency are not measured in transcript replay. Use q4.audio_replay with an audio WAV and Deepgram credentials for those components."
    }
    out = ROOT / "out" / f"q4_transcript_replay_{args.session_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"chunks={len(rows)} nudges={len(emitted)} api_rtt_p50_ms={report['client_api_round_trip_ms']['p50']} report={out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
