"""Creates (or updates) the Vapi assistant from agent/system_prompt.md and wires tools to the API.

Usage:  python agent/create_assistant.py            # create
        python agent/create_assistant.py <assistant_id>   # update existing

NOTE: the payload shape follows Vapi's REST API as I know it; check field names against the current
docs (https://docs.vapi.ai) when you run it, as provider/model options change often.
"""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
E = os.environ


def fn_tool(name, description, properties, required=()):
    server = {"url": f"{E.get('PUBLIC_BASE_URL', '').rstrip('/')}/vapi/tools"}
    if E.get("VAPI_CREDENTIAL_ID"):
        server["credentialId"] = E["VAPI_CREDENTIAL_ID"]
    return {
        "type": "function",
        "function": {"name": name, "description": description,
                     "parameters": {"type": "object", "properties": properties, "required": list(required)}},
        "server": server,
    }


S = lambda d: {"type": "string", "description": d}
N = lambda d: {"type": "number", "description": d}

TOOLS = [
    fn_tool("search_knowledge_base",
            "Look up Kestrel products, rates, fees, eligibility policy, documents, process, FAQs and objection "
            "guidance. MUST be called before answering any factual question.",
            {"query": S("The customer's question or concern, in plain words")}, ["query"]),
    fn_tool("check_eligibility", "Preliminary eligibility check once details are collected.",
            {"entity_type": S("proprietorship | partnership | llp | private limited"),
             "vintage_years": N("Years in business"), "annual_turnover_lakh": N("Annual turnover in lakh rupees"),
             "loan_amount_lakh": N("Loan amount needed in lakh rupees"), "owner_age": N("Owner age in years"),
             "gst_registered": {"type": "boolean", "description": "Is the business GST registered"},
             "credit_score": N("Credit score if known (optional)")},
            ["entity_type", "vintage_years", "annual_turnover_lakh", "loan_amount_lakh", "owner_age", "gst_registered"]),
    fn_tool("create_lead", "Create a lead for the relationship manager.",
            {"name": S("Customer name"), "phone": S("Customer phone number"), "business_name": S("Business name"),
             "entity_type": S("Business type"), "loan_amount_lakh": N("Amount in lakh"), "purpose": S("Loan purpose"),
             "eligibility_status": S("eligible | borderline | not_eligible"), "notes": S("One-line summary")},
            ["name", "phone"]),
    fn_tool("schedule_callback", "Schedule a callback from a relationship manager.",
            {"name": S("Customer name"), "phone": S("Phone number"), "preferred_time": S("When they want the call"),
             "reason": S("Why")}, ["phone", "preferred_time"]),
    fn_tool("request_human_handoff", "Escalate to a human colleague.",
            {"reason": S("Why escalating"), "summary": S("Short summary of the call so far")}, ["reason"]),
]
if E.get("HUMAN_AGENT_NUMBER"):
    TOOLS.append({"type": "transferCall",
                  "destinations": [{"type": "number", "number": E["HUMAN_AGENT_NUMBER"],
                                    "message": "Connecting you to a colleague now."}]})

payload = {
    "name": "Kestrel Loan Qualification - Asha",
    "firstMessage": "Hello, this is Asha from Kestrel Capital, calling about your business loan enquiry. "
                    "This call may be recorded for quality. Is this a good time to talk for two minutes?",
    "model": {"provider": E.get("LLM_PROVIDER", "openai"), "model": E.get("LLM_MODEL", "gpt-4o"),
              "temperature": 0.2,
              "messages": [{"role": "system", "content": (ROOT / "agent" / "system_prompt.md").read_text(encoding="utf-8")}],
              "tools": TOOLS},
    "transcriber": {"provider": E.get("ASR_PROVIDER", "deepgram"), "model": E.get("ASR_MODEL", "nova-2"),
                    "language": E.get("ASR_LANGUAGE", "en-IN")},
    "voice": {"provider": E.get("VOICE_PROVIDER", "azure"), "voiceId": E.get("VOICE_ID", "en-IN-NeerjaNeural")},
    "endCallFunctionEnabled": True,
    "artifactPlan": {"recordingEnabled": True, "loggingEnabled": True,
                      "transcriptPlan": {"enabled": True, "assistantName": "Asha", "userName": "Customer"}},
}

if __name__ == "__main__":
    required = [name for name in ("VAPI_API_KEY", "PUBLIC_BASE_URL", "VAPI_SERVER_SECRET", "VAPI_CREDENTIAL_ID")
                if not E.get(name)]
    if E.get("VAPI_SERVER_SECRET", "").strip().lower() in ("change-me", "changeme"):
        required.append("a non-placeholder VAPI_SERVER_SECRET")
    if E.get("PUBLIC_BASE_URL", "").strip().lower().startswith("https://your-tunnel"):
        required.append("a real public HTTPS URL in PUBLIC_BASE_URL")
    if required:
        raise SystemExit("Set these environment variables before configuring Vapi: " + ", ".join(required))
    headers = {"Authorization": f"Bearer {E['VAPI_API_KEY']}", "Content-Type": "application/json"}
    if len(sys.argv) > 1:
        r = requests.patch(f"https://api.vapi.ai/assistant/{sys.argv[1]}", headers=headers, json=payload, timeout=30)
    else:
        r = requests.post("https://api.vapi.ai/assistant", headers=headers, json=payload, timeout=30)
    print(r.status_code)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2)[:1500])
