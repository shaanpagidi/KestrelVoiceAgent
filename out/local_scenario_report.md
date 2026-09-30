# Q1 local scenario checks

Run date: 2026-09-30

These are local logic and prompt checks. They do not use speech recognition, a voice model, or audio, and are not recorded calls/transcripts.

| Scenario | Actual | Expected | Result | Notes |
|---|---|---|---|---|
| Cooperative customer / preliminary eligibility | eligible | eligible | PASS | Preliminary only; subject to document verification and credit approval. Never a guarantee. |
| Interest-rate objection / grounded answer | objection source and 14%-24% range returned | objections.md and the source rate range | PASS | Checks the actual webhook search handler output and its citation. |
| Incomplete qualification details | incomplete | incomplete | PASS | entity_type, vintage_years, annual_turnover_lakh, loan_amount_lakh, owner_age, gst_registered |
| Outside-policy qualification | not_eligible | not_eligible | PASS | business vintage is below 2 years; annual turnover is below ₹25 lakh; requested amount is outside ₹5 lakh to ₹100 lakh; applicant age is outside 25 to 65 years; GST registration is mandatory; credit score is below 650; requested amount is above 50% of annual turnover (indicative working-capital limit) |
| Out-of-scope question | safe no-information response | safe no-information response | PASS | NO_RELEVANT_INFORMATION: The knowledge base has nothing reliable on this. |
| Conflicting details / prompt rule | re-confirm-once instruction present | ask once and use only confirmed value | PASS | Prompt-content check only; turn-by-turn voice behavior needs a live call. |
| Human-assistance request / handoff wiring | handler registered; not invoked | handoff handler registered and escalation rule present | PASS | Not invoked here because it writes an escalation and may call ESCALATION_WEBHOOK_URL. |
| Do-not-call request | honor-and-end instruction present | apologize, confirm, and end the call | PASS | Prompt-content check only; no call was placed. |
| Sensitive information protection | prohibition and secure-submission instruction present | do not collect credentials/identity numbers by phone | PASS | Prompt-content check only; it does not simulate speech recognition. |

Result: 9/9 local checks passed.

Manual follow-up: the conflicting-details scenario only verifies the prompt instruction; it cannot validate multi-turn behavior without running the assistant. The human handoff handler was deliberately not invoked.
