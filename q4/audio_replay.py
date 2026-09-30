"""Replay PCM WAV audio at real-time speed through Deepgram streaming ASR and the nudge API.

Requires the optional dependency in requirements-q4-audio.txt and DEEPGRAM_API_KEY.
This deliberately accepts a real WAV file rather than pretending transcript fixtures are audio.
"""
import argparse
from datetime import datetime, timezone
import json
from math import ceil
import os
from pathlib import Path
import struct
import threading
import time
import uuid
import wave

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, ceil(len(ordered) * p) - 1)], 3)


def _mono_pcm(raw, channels):
    if channels == 1:
        return raw
    # Signed 16-bit little-endian stereo -> mono average.
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    mono = [int((samples[i] + samples[i + 1]) / 2) for i in range(0, len(samples) - 1, 2)]
    return struct.pack("<" + "h" * len(mono), *mono)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", help="16-bit PCM WAV; mono or stereo")
    parser.add_argument("--language", default="en-US", help="Deepgram Nova-3 language, e.g. tl, id, en-US")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--agent-speaker-id", type=int, default=None,
                        help="Diarization speaker ID for the agent; inspect the first transcript to determine it")
    parser.add_argument("--session-id", default=f"audio-{uuid.uuid4().hex[:8]}")
    parser.add_argument("--chunk-ms", type=int, default=200)
    args = parser.parse_args()
    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not key:
        parser.error("Set DEEPGRAM_API_KEY in .env before audio replay")
    try:
        from deepgram import DeepgramClient
        from deepgram.core.events import EventType
    except ImportError as exc:
        parser.error("Install the optional audio dependencies: pip install -r requirements-q4-audio.txt")

    audio_path = Path(args.wav)
    with wave.open(str(audio_path), "rb") as wav:
        if wav.getcomptype() != "NONE" or wav.getsampwidth() != 2 or wav.getnchannels() not in (1, 2):
            parser.error("WAV must be uncompressed 16-bit PCM, mono or stereo")
        sample_rate, channels = wav.getframerate(), wav.getnchannels()
        frames_per_chunk = max(1, int(sample_rate * args.chunk_ms / 1000))
        chunks = []
        while data := wav.readframes(frames_per_chunk):
            chunks.append(_mono_pcm(data, channels))
    audio_duration = sum(len(chunk) for chunk in chunks) / (sample_rate * 2)
    created = requests.post(f"{args.base_url}/sessions", json={"session_id": args.session_id}, timeout=10)
    created.raise_for_status()

    client = DeepgramClient(api_key=key)
    observations, errors = [], []
    playback_started = None
    finished = threading.Event()
    connection_error = []

    def on_message(message):
        msg_type = getattr(message, "type", "")
        if msg_type != "Results":
            return
        is_final = bool(getattr(message, "is_final", False))
        channel = getattr(message, "channel", None)
        alternatives = getattr(channel, "alternatives", []) if channel else []
        if not alternatives:
            return
        alt = alternatives[0]
        text = getattr(alt, "transcript", "").strip()
        if not is_final or not text:
            return
        segment_start = float(getattr(message, "start", 0.0) or 0.0)
        duration = float(getattr(message, "duration", 0.0) or 0.0)
        words = getattr(alt, "words", []) or []
        speaker_ids = [getattr(word, "speaker", None) for word in words]
        known_speakers = [s for s in speaker_ids if s is not None]
        speaker = "agent" if args.agent_speaker_id is not None and args.agent_speaker_id in known_speakers else "caller"
        source_audio_sent_at = (playback_started or time.perf_counter()) + segment_start + duration
        asr_ms = max(0.0, (time.perf_counter() - source_audio_sent_at) * 1000)
        confidence = float(getattr(alt, "confidence", 1.0) or 0.0)
        event = {"speaker": speaker, "text": text, "audio_time_sec": segment_start,
                 "confidence": confidence, "is_final": True, "asr_latency_ms": asr_ms}
        try:
            started = time.perf_counter()
            response = requests.post(f"{args.base_url}/sessions/{args.session_id}/transcripts", json=event, timeout=10)
            response.raise_for_status()
            delivered = (time.perf_counter() - started) * 1000
            result = response.json()
            observations.append({"asr_latency_ms": asr_ms, "signal_latency_ms": result["signal_latency_ms"],
                                "delivery_rtt_ms": delivered, "text": text,
                                "nudges": result["nudges"], "confidence": confidence,
                                "diarization_speaker_ids": sorted({s for s in known_speakers})})
            print(f"[{segment_start:6.2f}s {speaker} speaker_ids={observations[-1]['diarization_speaker_ids']} conf={confidence:.2f}] {text}")
            for nudge in result["nudges"]:
                print(f"  NUDGE {nudge['priority'].upper()}: {nudge['text']}")
        except Exception as exc:
            errors.append(type(exc).__name__)

    def on_error(error):
        connection_error.append(str(error))
        finished.set()

    def on_close(_):
        finished.set()

    config = {"model": "nova-3", "language": args.language, "interim_results": True,
              "endpointing": 300, "diarize": True, "encoding": "linear16",
              "sample_rate": sample_rate, "channels": 1}
    with client.listen.v1.connect(**config) as connection:
        connection.on(EventType.MESSAGE, on_message)
        connection.on(EventType.ERROR, on_error)
        connection.on(EventType.CLOSE, on_close)
        connection.start_listening()
        playback_started = time.perf_counter()
        for chunk in chunks:
            connection.send_media(chunk)
            time.sleep(len(chunk) / (sample_rate * 2))
        connection.send_close_stream()
        finished.wait(timeout=max(10, audio_duration * 0.5 + 10))

    asr = [o["asr_latency_ms"] for o in observations]
    signal = [o["signal_latency_ms"] for o in observations]
    delivery = [o["delivery_rtt_ms"] for o in observations]
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(), "session_id": args.session_id,
        "input": str(audio_path), "input_mode": "real WAV replayed at real-time speed in PCM chunks",
        "asr": {"provider": "Deepgram", "model": "nova-3", "language": args.language,
                "chunk_ms": args.chunk_ms, "sample_rate": sample_rate, "duration_sec": round(audio_duration, 3)},
        "transcript_segments": len(observations), "connection_errors": len(connection_error),
        "delivery_errors": errors,
        "latency_ms": {
            "asr": {"p50": percentile(asr, .50), "p95": percentile(asr, .95), "samples": len(asr)},
            "signal": {"p50": percentile(signal, .50), "p95": percentile(signal, .95), "samples": len(signal)},
            "delivery_http_round_trip": {"p50": percentile(delivery, .50), "p95": percentile(delivery, .95), "samples": len(delivery)},
            "llm": {"p50": 0, "p95": 0, "note": "not used; rule-based signal detection"},
            "display": {"note": "console/API response is the demo display; a dashboard should measure its own poll-to-render time"}
        },
        "nudges": [n for observation in observations for n in observation["nudges"]],
        "transcripts": [{k: o[k] for k in ("text", "confidence", "diarization_speaker_ids")} for o in observations],
        "speaker_mapping": {"agent_speaker_id": args.agent_speaker_id, "other_or_unmapped_speakers": "treated as caller"},
        "limitations": "Real ASR and latency measured for this file only. Accent and language quality need human-labelled native test audio; never interpret one file as a benchmark."
    }
    out = ROOT / "out" / f"q4_audio_{args.session_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"audio_sec={audio_duration:.1f} segments={len(observations)} report={out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
