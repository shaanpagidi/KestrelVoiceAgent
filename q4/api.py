"""Polling API for live or replayed transcript chunks and operator nudges."""
from statistics import median
from math import ceil
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from q4.engine import NudgeEngine

app = FastAPI(title="Kestrel Live Call Insights", version="0.1.0")
engine = NudgeEngine(threshold=0.72, cooldown_sec=45, expiry_sec=30)


class NewSession(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    required_disclosure_terms: list[str] = ["recording quality"]
    disclosure_deadline_sec: float = Field(default=12.0, ge=1.0, le=120.0)


class TranscriptChunk(BaseModel):
    speaker: Literal["caller", "agent"]
    text: str = Field(max_length=5000)
    audio_time_sec: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_final: bool = True
    asr_latency_ms: float | None = Field(default=None, ge=0.0)


def _percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, min(len(ordered) - 1, ceil(len(ordered) * p) - 1))], 3)


@app.get("/health")
def health():
    return {"ok": True, "sessions": len(engine.sessions), "mode": "rule-based signals"}


@app.post("/sessions", status_code=201)
def create_session(body: NewSession):
    engine.create_session(body.session_id, body.required_disclosure_terms, body.disclosure_deadline_sec)
    return {"session_id": body.session_id, "status": "ready", "nudge_threshold": engine.threshold,
            "cooldown_sec": engine.cooldown_sec, "expiry_sec": engine.expiry_sec}


@app.post("/sessions/{session_id}/transcripts")
def transcript(session_id: str, body: TranscriptChunk):
    state = engine.sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Create the session before sending transcript chunks")
    started = time.perf_counter()
    result = engine.process(session_id, body.speaker, body.text, body.audio_time_sec,
                            body.confidence, body.is_final, body.asr_latency_ms)
    delivery_ms = round((time.perf_counter() - started) * 1000, 3)
    state.delivery_latencies.append(delivery_ms)
    result["api_latency_ms"] = delivery_ms
    return result


@app.get("/sessions/{session_id}/nudges")
def nudges(session_id: str):
    if session_id not in engine.sessions:
        raise HTTPException(status_code=404, detail="Unknown session")
    return {"session_id": session_id, "nudges": engine.active_nudges(session_id)}


@app.get("/sessions/{session_id}/metrics")
def metrics(session_id: str):
    state = engine.sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    signals = [n["rule_id"] for n in state.emitted]
    return {
        "session_id": session_id,
        "transcript_segments": len(state.recent),
        "nudge_count": len(state.emitted),
        "signal_candidates": state.candidates,
        "suppressed": dict(state.suppressed),
        "signals": signals,
        "latency_ms": {
            "asr": {"p50": _percentile(state.asr_latencies, .50), "p95": _percentile(state.asr_latencies, .95), "samples": len(state.asr_latencies)},
            "signal": {"p50": _percentile(state.signal_latencies, .50), "p95": _percentile(state.signal_latencies, .95), "samples": len(state.signal_latencies)},
            "api_processing": {"p50": _percentile(state.delivery_latencies, .50), "p95": _percentile(state.delivery_latencies, .95), "samples": len(state.delivery_latencies)},
            "llm": {"p50": 0, "p95": 0, "note": "not used; deterministic rules"},
            "display": {"note": "Polling client observes nudge on its next poll; measure client-side for an end-to-end number."}
        }
    }
