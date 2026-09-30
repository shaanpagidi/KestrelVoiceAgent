"""Q2 retrieval tests -> out/retrieval_report.md.  Run:  python -m kb.retrieval_eval

Auto-verdict is a first pass: correct = all expected keywords in top record; partial = some; incorrect = none.
For out-of-scope queries, correct = the gate refused to answer. Review the verdicts by hand before submitting.
"""
from pathlib import Path

from kb.index import KBIndex

# (type, query, expected keywords, why the selected record is relevant)
TESTS = [
    ("product", "What is a working capital loan and how much can I get?", ["working capital", "50 lakh"],
     "The product record describes the working capital facility and its indicative limit."),
    ("policy", "What is the minimum turnover required?", ["25 lakh"],
     "The credit policy record states the minimum annual turnover."),
    ("qualification", "What credit score do I need to qualify?", ["700"],
     "The credit score policy record distinguishes standard processing from manual review."),
    ("faq", "How many days does approval take?", ["3 working days"],
     "The FAQ record gives the credit decision timeline after complete documents."),
    ("objection", "Customer says the interest rate is too high", ["14%", "24%"],
     "The objection playbook addresses this concern and grounds the stated rate range."),
    ("policy", "Are there charges if I prepay my term loan?", ["4%", "12 months"],
     "The retrieved FAQ describes term-loan prepayment charges and the 12-month period."),
    ("out_of_scope", "Do you offer home loans or gold loans?", [],
     "No relevant business-loan record should pass the confidence gate for unrelated products."),
    ("policy_paraphrase", "How long must my shop have been operating?", ["2 years", "business vintage"],
     "Caller wording is normalized to the policy term for minimum business vintage."),
    ("documents_paraphrase", "What paperwork should I prepare before applying?", ["bank statements", "secure portal"],
     "Paperwork and prepare are normalized to the source's documents-required wording."),
    ("qualification_paraphrase", "I have a bureau score of 675, what happens?", ["manual review", "650 and 699"],
     "The bureau-score phrasing maps to credit score; the policy explains the 650-699 review band."),
    ("policy_paraphrase", "Can I apply if my company is just 18 months old?", ["2 years", "business vintage"],
     "A months-old business-tenure question should retrieve the minimum-vintage rule."),
    ("out_of_scope", "Can you lend me money to renovate my house?", [],
     "A personal home-renovation purpose should be refused rather than matched by the word loan."),
    ("out_of_scope", "Do you give personal loans?", [],
     "A personal-loan question should not match only on the shared word loan."),
]


def main():
    kb = KBIndex()
    lines = [f"# Retrieval test report (mode: {kb.mode}, threshold: {kb.threshold})", "",
             "Verdicts use expected keywords in the top returned record; this is a lightweight check, not a human quality score.", "",
             "| # | Type | Question | Retrieved record | Source / section / version | Conf. | Retrieved text | Relevance | Verdict |",
             "|---|---|---|---|---|---:|---|---|---|"]
    for n, (typ, q, expect, why) in enumerate(TESTS, 1):
        res = kb.search(q)
        if not expect:
            verdict = "correct (refused)" if not res["found"] else "incorrect (answered out-of-scope)"
            top, src = ("-", "-") if not res["found"] else (res["results"][0]["record_id"], res["results"][0]["source"])
            excerpt = "No record passed the confidence gate." if not res["found"] else res["results"][0]["content"]
        elif not res["found"]:
            verdict, top, src = "incorrect (no result)", "-", "-"
            excerpt = "No record passed the confidence gate."
        else:
            r = res["results"][0]
            hits = sum(k.lower() in r["content"].lower() for k in expect)
            verdict = "correct" if hits == len(expect) else "partially correct" if hits else "incorrect"
            top, src = r["record_id"], r["citation"].replace("|", "/")
            excerpt = r["content"]
        excerpt = " ".join(excerpt.split())[:360].replace("|", "\\|")
        lines.append(f"| {n} | {typ} | {q} | {top} | {src} | {res['top_confidence']} | {excerpt} | {why} | {verdict} |")
    out = Path(__file__).resolve().parent.parent / "out" / "retrieval_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
