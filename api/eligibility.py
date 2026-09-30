"""Deterministic preliminary eligibility. Rules live in config/rules.json (mirrors the credit policy in the KB).

Qualification is code, not prompt: the LLM collects answers, this decides. Always preliminary.
"""
import json
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "config" / "rules.json").read_text())

REQUIRED = ["entity_type", "vintage_years", "annual_turnover_lakh", "loan_amount_lakh", "owner_age", "gst_registered"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check(args: dict) -> dict:
    missing = [f for f in REQUIRED if args.get(f) in (None, "")]
    if missing:
        return {"status": "incomplete", "missing_fields": missing, "reasons": [],
                "message": "More details needed before a preliminary check: " + ", ".join(missing)}

    R, fails, review = RULES, [], []
    entity = str(args["entity_type"]).strip().lower().replace("pvt", "private").replace("ltd", "limited")
    if entity not in R["entity_types"]:
        fails.append(f"business type '{args['entity_type']}' is not supported")
    vintage, turnover = _num(args["vintage_years"]), _num(args["annual_turnover_lakh"])
    amount, age = _num(args["loan_amount_lakh"]), _num(args["owner_age"])
    if None in (vintage, turnover, amount, age):
        return {"status": "incomplete", "missing_fields": ["numeric values unclear"], "reasons": [],
                "message": "Some numbers were unclear; please re-confirm them with the customer."}
    if vintage < R["min_vintage_years"]:
        fails.append(f"business vintage is below {R['min_vintage_years']} years")
    if turnover < R["min_annual_turnover_lakh"]:
        fails.append(f"annual turnover is below ₹{R['min_annual_turnover_lakh']} lakh")
    if not (R["min_loan_lakh"] <= amount <= R["max_loan_lakh"]):
        fails.append(f"requested amount is outside ₹{R['min_loan_lakh']} lakh to ₹{R['max_loan_lakh']} lakh")
    if not (R["age_min"] <= age <= R["age_max"]):
        fails.append(f"applicant age is outside {R['age_min']} to {R['age_max']} years")
    gst = str(args["gst_registered"]).strip().lower() in ("true", "yes", "y", "1")
    if R["gst_required"] and not gst:
        fails.append("GST registration is mandatory")

    score = _num(args.get("credit_score"))
    if score is not None:
        if score < R["credit_score_manual_review"]:
            fails.append(f"credit score is below {R['credit_score_manual_review']}")
        elif score < R["credit_score_standard"]:
            review.append(f"credit score is between {R['credit_score_manual_review']} and {R['credit_score_standard']}; manual review")
    else:
        review.append("credit score not provided; it will be checked at formal application")
    if turnover and amount > turnover * R["max_loan_to_turnover_ratio"]:
        review.append("requested amount is above 50% of annual turnover (indicative working-capital limit)")

    if fails:
        status = "not_eligible"
    elif review:
        status = "borderline"
    else:
        status = "eligible"
    return {"status": status, "reasons": fails + review, "missing_fields": [],
            "message": "Preliminary only; subject to document verification and credit approval. Never a guarantee."}
