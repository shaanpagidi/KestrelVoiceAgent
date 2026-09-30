"""Run reproducible Q1 logic checks without making a voice call or external webhook request.

Run after building the KB: python -m qa.local_scenario_check
Writes a clearly labelled local-check report to out/local_scenario_report.md.
"""
from datetime import date
from pathlib import Path

from api.eligibility import check
from api.main import NO_INFO, TOOLS, tool_search

ROOT = Path(__file__).resolve().parent.parent


def main():
    prompt = (ROOT / "agent" / "system_prompt.md").read_text(encoding="utf-8").lower()
    cases = []

    def record(name, actual, expected, passed, detail):
        cases.append({"name": name, "actual": actual, "expected": expected,
                      "status": "PASS" if passed else "FAIL", "detail": detail})

    cooperative = check({"entity_type": "llp", "vintage_years": 4, "annual_turnover_lakh": 80,
                         "loan_amount_lakh": 20, "owner_age": 35, "gst_registered": True,
                         "credit_score": 720})
    record("Cooperative customer / preliminary eligibility", cooperative["status"], "eligible",
           cooperative["status"] == "eligible", "; ".join(cooperative["reasons"]) or cooperative["message"])

    objection = tool_search({"query": "Customer says the interest rate is too high"})
    objection_ok = "14%" in objection and "24%" in objection and "objections.md" in objection
    record("Interest-rate objection / grounded answer", "objection source and 14%-24% range returned" if objection_ok else "expected source/range missing",
           "objections.md and the source rate range", objection_ok,
           "Checks the actual webhook search handler output and its citation.")

    incomplete = check({})
    record("Incomplete qualification details", incomplete["status"], "incomplete",
           incomplete["status"] == "incomplete", ", ".join(incomplete.get("missing_fields", [])))

    rejected = check({"entity_type": "llp", "vintage_years": 1, "annual_turnover_lakh": 10,
                      "loan_amount_lakh": 120, "owner_age": 20, "gst_registered": False,
                      "credit_score": 620})
    record("Outside-policy qualification", rejected["status"], "not_eligible",
           rejected["status"] == "not_eligible", "; ".join(rejected["reasons"]))

    out_of_scope = tool_search({"query": "Do you offer home loans or gold loans?"})
    refused = out_of_scope.startswith("NO_RELEVANT_INFORMATION")
    record("Out-of-scope question", "safe no-information response" if refused else "retrieval returned an answer",
           "safe no-information response", refused, out_of_scope.split(" Tell ")[0])

    conflict_instruction = "earlier you mentioned" in prompt and "re-confirm once" in prompt
    record("Conflicting details / prompt rule", "re-confirm-once instruction present" if conflict_instruction else "instruction missing",
           "ask once and use only confirmed value", conflict_instruction,
           "Prompt-content check only; turn-by-turn voice behavior needs a live call.")

    handoff_registered = "request_human_handoff" in TOOLS and "immediately" in prompt
    record("Human-assistance request / handoff wiring", "handler registered; not invoked" if handoff_registered else "handler or prompt rule missing",
           "handoff handler registered and escalation rule present", handoff_registered,
           "Not invoked here because it writes an escalation and may call ESCALATION_WEBHOOK_URL.")

    do_not_call = "do-not-call" in prompt and "end the call" in prompt
    record("Do-not-call request", "honor-and-end instruction present" if do_not_call else "instruction missing",
           "apologize, confirm, and end the call", do_not_call,
           "Prompt-content check only; no call was placed.")

    sensitive_data = ("never ask for or accept otp, pan, aadhaar" in prompt and
                      "secure portal" in prompt)
    record("Sensitive information protection", "prohibition and secure-submission instruction present" if sensitive_data else "instruction missing",
           "do not collect credentials/identity numbers by phone", sensitive_data,
           "Prompt-content check only; it does not simulate speech recognition.")

    lines = ["# Q1 local scenario checks", "",
             f"Run date: {date.today().isoformat()}", "",
             "These are local logic and prompt checks. They do not use speech recognition, a voice model, or audio, and are not recorded calls/transcripts.", "",
             "| Scenario | Actual | Expected | Result | Notes |", "|---|---|---|---|---|"]
    for case in cases:
        cells = [case[k] for k in ("name", "actual", "expected", "status", "detail")]
        cells = [str(v).replace("|", "\\|").replace("\n", " ") for v in cells]
        lines.append("| " + " | ".join(cells) + " |")
    passed = sum(c["status"] == "PASS" for c in cases)
    lines += ["", f"Result: {passed}/{len(cases)} local checks passed.", "",
              "Manual follow-up: the conflicting-details scenario only verifies the prompt instruction; it cannot validate multi-turn behavior without running the assistant. The human handoff handler was deliberately not invoked."]
    out = ROOT / "out" / "local_scenario_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"local_checks={passed}/{len(cases)} report={out.relative_to(ROOT)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
