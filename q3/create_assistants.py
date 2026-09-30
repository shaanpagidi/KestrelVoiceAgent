"""Create Q3 Vapi prototypes after configuring provider keys in Vapi and VAPI_API_KEY locally.

Examples:
  python -m q3.create_assistants --dry-run
  python -m q3.create_assistants --market philippines
  python -m q3.create_assistants --market indonesia
"""
import argparse
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def payload(profile, prompt):
    return {
        "name": profile["name"],
        "firstMessage": profile["localized_phrases"].get("opening", profile["localized_phrases"].get("opening_formal")),
        "model": {"provider": os.getenv("LLM_PROVIDER", "openai"),
                  "model": os.getenv("LLM_MODEL", "gpt-4o"), "temperature": 0.2,
                  "messages": [{"role": "system", "content": prompt}]},
        "transcriber": {"provider": profile["asr"]["provider"].lower(),
                        "model": profile["asr"]["model"], "language": profile["asr"]["language"]},
        "voice": {"provider": "azure", "voiceId": profile["tts"]["voice"]},
        "artifactPlan": {"recordingEnabled": True, "loggingEnabled": True,
                         "transcriptPlan": {"enabled": True, "assistantName": profile["name"], "userName": "Customer"}}
    }


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("all", "philippines", "indonesia"), default="all")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without calling Vapi")
    args = parser.parse_args()
    profiles = json.loads((ROOT / "q3" / "profiles.json").read_text(encoding="utf-8"))
    markets = ([name for name, profile in profiles.items() if isinstance(profile, dict) and "sector" in profile]
               if args.market == "all" else [args.market])
    if not args.dry_run and not os.getenv("VAPI_API_KEY"):
        parser.error("Set VAPI_API_KEY in .env; ensure the required provider credentials are configured in Vapi")
    headers = {"Authorization": f"Bearer {os.getenv('VAPI_API_KEY', '')}", "Content-Type": "application/json"}
    for market in markets:
        profile = profiles[market]
        prompt = (ROOT / "q3" / "prompts" / f"{market}.md").read_text(encoding="utf-8")
        body = payload(profile, prompt)
        if args.dry_run:
            print(f"--- {market} ---")
            print(json.dumps(body, indent=2, ensure_ascii=False))
            continue
        response = requests.post("https://api.vapi.ai/assistant", headers=headers, json=body, timeout=30)
        response.raise_for_status()
        created = response.json()
        print(json.dumps({"market": market, "assistantId": created.get("id"), "name": created.get("name")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
