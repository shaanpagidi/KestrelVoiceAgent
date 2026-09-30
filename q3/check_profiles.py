"""Validate Q3 localization assets and write a coverage report; no provider calls are made."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "q3" / "profiles.json"


def main():
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    requirements = {
        "philippines": {"examples": 3, "tests": {"cooperative", "sector objection", "mixed English", "colloquial", "human escalation"},
                        "terms": {"premium", "policy", "beneficiary", "rider", "lapse", "coverage", "bank referral"}},
        "indonesia": {"examples": 3, "tests": {"cooperative", "sector objection", "mixed English", "colloquial", "regional accent", "human escalation"},
                      "terms": {"cicilan", "tenor", "denda", "DP", "jatuh tempo", "angsuran", "pembiayaan"}},
    }
    failures = []
    rows = []
    for market, req in requirements.items():
        profile = profiles.get(market, {})
        examples = profile.get("localization_examples", [])
        actual_tests = {item.get("type", "").lower() for item in profile.get("test_utterances", [])}
        terms = set(profile.get("terminology", []))
        prompt_path = ROOT / "q3" / "prompts" / f"{market}.md"
        prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        missing = []
        if len(examples) < req["examples"]:
            missing.append("fewer than three localization examples")
        missing.extend(f"test case missing: {name}" for name in req["tests"] if not any(name.lower() in t for t in actual_tests))
        missing.extend(f"terminology missing: {term}" for term in req["terms"] if term.lower() not in {x.lower() for x in terms})
        if not prompt:
            missing.append("localized prompt file missing")
        if profile.get("asr", {}).get("language") not in ("tl", "id"):
            missing.append("market-specific ASR language missing")
        if not profile.get("tts", {}).get("voice"):
            missing.append("native TTS voice missing")
        if not profile.get("date_amount_guidance"):
            missing.append("localized date/amount guidance missing")
        if missing:
            failures.extend(f"{market}: {item}" for item in missing)
        rows.append((market, profile.get("sector", ""), profile.get("asr", {}), profile.get("tts", {}), len(examples), len(profile.get("test_utterances", [])), missing))

    lines = ["# Q3 localization profile checks", "",
             "Static checks only; they verify configuration and scenario coverage, not ASR accuracy, native fluency, or recorded calls.", "",
             "| Market | Sector | ASR config | TTS config | Localization examples | Scenario prompts | Static result |", "|---|---|---|---|---:|---:|---|"]
    for market, sector, asr, tts, examples, tests, missing in rows:
        asr_text = f"{asr.get('provider')} {asr.get('model')} / {asr.get('language')}"
        tts_text = f"{tts.get('provider')} {tts.get('voice')}"
        lines.append(f"| {market} | {sector} | {asr_text} | {tts_text} | {examples} | {tests} | {'FAIL: ' + '; '.join(missing) if missing else 'PASS'} |")
    lines += ["", "## Not measured yet", "",
              "No provider credentials or native-speaker WAV samples are configured in this workspace. ASR quality, Taglish/Indonesian code-switching, TTS naturalness, and regional-accent performance remain unmeasured. Record and review at least two calls per market before claiming those requirements complete."]
    out = ROOT / "out" / "q3_profile_check.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"q3_static_profiles={len(rows)} checks={'FAIL' if failures else 'PASS'} report={out.relative_to(ROOT)}")
    if failures:
        raise SystemExit("Profile issues: " + "; ".join(failures))


if __name__ == "__main__":
    main()
