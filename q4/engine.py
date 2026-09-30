"""Low-latency, rule-based call signal detection with confidence and repetition controls."""
from collections import defaultdict, deque
from datetime import datetime, timezone
import re
import time
import uuid


RULES = [
    ("risky_promise", "compliance", "high", 0.98,
     re.compile(r"\b(guarantee(?:d)?|approved for sure|guaranteed rate|you will definitely be approved)\b", re.I),
     "Review this statement: do not guarantee approval, rates, or outcomes."),
    ("missed_cross_sell", "opportunity", "normal", 0.86,
     re.compile(r"\b(second vehicle|another vehicle|second car|additional vehicle)\b", re.I),
     "The customer mentioned another vehicle. Ask whether they want information about suitable coverage for it."),
    ("payment_hardship", "payment_support", "high", 0.90,
     re.compile(r"\b(can't pay|cannot pay|can't afford|cannot afford|lost my job|payment is difficult|miss an installment)\b", re.I),
     "Acknowledge the difficulty and offer the approved payment-support or callback path."),
    ("frustration", "sentiment", "high", 0.84,
     re.compile(r"\b(fed up|ridiculous|no one is helping|this is frustrating|very angry|this is unfair)\b", re.I),
     "Pause the sales flow, acknowledge the concern, and offer a human colleague."),
    ("human_request", "handoff", "high", 0.99,
     re.compile(r"\b(speak to a (person|human|manager)|talk to a (person|human|manager)|real person)\b", re.I),
     "The customer asked for a person. Arrange a human handoff now."),
]
TOPIC_PATTERNS = {
    "payment": re.compile(r"\b(payment|installment|cicilan|angsuran|jatuh tempo|denda)\b", re.I),
    "coverage": re.compile(r"\b(policy|premium|beneficiary|rider|coverage)\b", re.I),
    "vehicle": re.compile(r"\b(vehicle|car|mobil|kendaraan)\b", re.I),
    "complaint": re.compile(r"\b(complaint|complain|komplain|dispute|sengketa)\b", re.I),
}


class SessionState:
    def __init__(self, session_id, required_disclosure_terms=None, disclosure_deadline_sec=12.0):
        self.session_id = session_id
        self.started = time.perf_counter()
        self.required_disclosure_terms = [tuple(t.lower().split()) for t in (required_disclosure_terms or [])]
        self.disclosure_deadline_sec = disclosure_deadline_sec
        self.disclosure_seen = False
        self.disclosure_alerted = False
        self.recent = deque(maxlen=30)
        self.last_emitted = {}
        self.emitted = []
        self.nudge_expiry = {}
        self.candidates = 0
        self.suppressed = defaultdict(int)
        self.topic = None
        self.signal_latencies = []
        self.asr_latencies = []
        self.delivery_latencies = []


class NudgeEngine:
    """Processes finalized transcript segments; all signal rules are auditable and deterministic."""
    def __init__(self, threshold=0.72, cooldown_sec=45.0, expiry_sec=30.0):
        self.threshold = threshold
        self.cooldown_sec = cooldown_sec
        self.expiry_sec = expiry_sec
        self.sessions = {}

    def create_session(self, session_id, required_disclosure_terms=None, disclosure_deadline_sec=12.0):
        state = SessionState(session_id, required_disclosure_terms, disclosure_deadline_sec)
        self.sessions[session_id] = state
        return state

    def process(self, session_id, speaker, text, audio_time_sec=0.0, confidence=1.0, is_final=True,
                asr_latency_ms=None):
        state = self.sessions.setdefault(session_id, SessionState(session_id))
        started = time.perf_counter()
        if not is_final or not text.strip():
            return {"nudges": [], "suppressed": "interim_or_empty", "signal_latency_ms": 0.0}
        clean = " ".join(text.split())
        low = clean.lower()
        state.recent.append({"speaker": speaker, "text": clean, "audio_time_sec": audio_time_sec})
        if asr_latency_ms is not None:
            state.asr_latencies.append(float(asr_latency_ms))
        candidates = []

        if speaker == "caller":
            topic = next((name for name, pattern in TOPIC_PATTERNS.items() if pattern.search(low)), None)
            if topic and state.topic and topic != state.topic:
                candidates.append({"rule_id": "topic_shift", "group": "topic", "priority": "normal",
                                   "confidence": 0.79,
                                   "text": f"The caller shifted from {state.topic} to {topic}. Acknowledge the new topic and confirm what they want help with."})
            if topic:
                state.topic = topic

        if speaker == "agent":
            def disclosure_term_seen(term):
                if term in low:
                    return True
                if term in ("recording", "recorded", "record"):
                    return bool(re.search(r"\brecord(?:ed|ing)?\b", low))
                return False

            if any(all(disclosure_term_seen(term) for term in required) for required in state.required_disclosure_terms):
                state.disclosure_seen = True
            elif (state.required_disclosure_terms and not state.disclosure_seen and not state.disclosure_alerted
                  and audio_time_sec >= state.disclosure_deadline_sec):
                state.disclosure_alerted = True
                candidates.append({"rule_id": "missing_disclosure", "group": "compliance", "priority": "high",
                                   "confidence": 0.99,
                                   "text": "Required disclosure has not been heard yet. Give it before continuing."})

        for rule_id, group, priority, rule_confidence, pattern, message in RULES:
            if rule_id == "risky_promise" and speaker != "agent":
                continue
            if rule_id != "risky_promise" and speaker != "caller":
                continue
            if pattern.search(low):
                candidates.append({"rule_id": rule_id, "group": group, "priority": priority,
                                   "confidence": rule_confidence, "text": message})

        # A transcript-confidence gate suppresses weak/noisy ASR matches.
        if confidence < 0.65:
            state.suppressed["low_transcript_confidence"] += len(candidates)
            candidates = []

        emitted = []
        now = time.perf_counter()
        for candidate in candidates:
            state.candidates += 1
            group = candidate["group"]
            previous = state.last_emitted.get(group)
            if candidate["confidence"] < self.threshold:
                state.suppressed["below_signal_threshold"] += 1
                continue
            if previous and now - previous["at"] < self.cooldown_sec:
                if previous["rule_id"] == candidate["rule_id"]:
                    state.suppressed["duplicate"] += 1
                    continue
                if previous["priority"] == "high" and candidate["priority"] != "high":
                    state.suppressed["lower_priority_in_cooldown"] += 1
                    continue
            nudge = {
                "id": uuid.uuid4().hex[:10], "session_id": session_id,
                "rule_id": candidate["rule_id"], "group": group, "priority": candidate["priority"],
                "confidence": candidate["confidence"], "text": candidate["text"],
                "audio_time_sec": round(float(audio_time_sec), 3),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_in_sec": self.expiry_sec,
                "signal_latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "asr_latency_ms": asr_latency_ms,
            }
            state.last_emitted[group] = {"at": now, "rule_id": candidate["rule_id"], "priority": candidate["priority"]}
            state.emitted.append(nudge)
            state.nudge_expiry[nudge["id"]] = now + self.expiry_sec
            emitted.append(nudge)
        signal_latency = round((time.perf_counter() - started) * 1000, 3)
        state.signal_latencies.append(signal_latency)
        return {"nudges": emitted, "suppressed": dict(state.suppressed),
                "signal_latency_ms": signal_latency}

    def active_nudges(self, session_id):
        state = self.sessions.get(session_id)
        if not state:
            return []
        now = time.perf_counter()
        state.emitted = [n for n in state.emitted if state.nudge_expiry.get(n["id"], 0) > now]
        return state.emitted
