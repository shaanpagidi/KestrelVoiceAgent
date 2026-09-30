"""API for the voice agent.   Run:  uvicorn api.main:app --port 8000

POST /search           plain retrieval interface (for demos / Q2 evidence)
POST /vapi/tools       Vapi server-tool webhook -> dispatches the tool calls below
Tools: search_knowledge_base, check_eligibility, create_lead, schedule_callback, request_human_handoff
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from api.eligibility import check as eligibility_check
from kb.index import KBIndex

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
app = FastAPI(title="Kestrel Voice Agent API")
kb = KBIndex()

NO_INFO = ("NO_RELEVANT_INFORMATION: The knowledge base has nothing reliable on this. Tell the customer you "
           "don't have that information and offer a callback or a human colleague. Do not guess.")


class SearchReq(BaseModel):
    query: str
    category: str | None = None
    top_k: int = 3


def _append(filename, row):
    OUT.mkdir(exist_ok=True)
    row = {"id": uuid.uuid4().hex[:10], "ts": datetime.now(timezone.utc).isoformat(), **row}
    with open(OUT / filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row["id"]


def tool_search(args):
    res = kb.search(args.get("query", ""), top_k=2, category=args.get("category"))
    if not res["found"]:
        return NO_INFO
    parts = [f"[{r['record_id']} | {r['source']}] {r['title']}: {r['content']}" for r in res["results"]]
    return " || ".join(parts).replace("\n", " ")


def tool_eligibility(args):
    return json.dumps(eligibility_check(args))


def tool_lead(args):
    lead_id = _append("leads.jsonl", {k: args.get(k) for k in (
        "name", "phone", "business_name", "entity_type", "loan_amount_lakh", "purpose",
        "eligibility_status", "notes")})
    return f"Lead {lead_id} created. Tell the customer a relationship manager will follow up."


def tool_callback(args):
    cb_id = _append("callbacks.jsonl", {k: args.get(k) for k in ("name", "phone", "preferred_time", "reason")})
    return f"Callback {cb_id} scheduled for {args.get('preferred_time', 'the requested time')}."


def tool_handoff(args):
    row = {"reason": args.get("reason"), "summary": args.get("summary")}
    esc_id = _append("escalations.jsonl", row)
    url = os.getenv("ESCALATION_WEBHOOK_URL", "").strip()
    if url:
        try:
            requests.post(url, json={"escalation_id": esc_id, **row}, timeout=3)
        except requests.RequestException:
            pass  # never block the call on a webhook failure
    return f"Escalation {esc_id} logged. Tell the customer a human colleague will help; transfer if available."


TOOLS = {"search_knowledge_base": tool_search, "check_eligibility": tool_eligibility, "create_lead": tool_lead,
         "schedule_callback": tool_callback, "request_human_handoff": tool_handoff}


@app.get("/health")
def health():
    return {"ok": True, "records": len(kb.records), "mode": kb.mode, "threshold": kb.threshold}


@app.post("/search")
def search(req: SearchReq):
    return kb.search(req.query, top_k=req.top_k, category=req.category)


@app.post("/vapi/tools")
def vapi_tools(body: dict, x_vapi_secret: str | None = Header(default=None)):
    secret = os.getenv("VAPI_SERVER_SECRET", "")
    if secret and x_vapi_secret != secret:
        raise HTTPException(status_code=401, detail="bad secret")
    msg = body.get("message", body)
    calls = msg.get("toolCallList") or msg.get("toolCalls") or []
    results = []
    for c in calls:
        fn = c.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        handler = TOOLS.get(fn.get("name"))
        try:
            out = handler(args) if handler else f"Unknown tool {fn.get('name')}"
        except Exception as e:  # tool failure must degrade to a safe spoken fallback
            out = f"TOOL_ERROR: {type(e).__name__}. Apologise briefly and offer a callback instead."
        results.append({"toolCallId": c.get("id"), "result": out})
    return {"results": results}
