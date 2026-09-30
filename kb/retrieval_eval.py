"""Q2 retrieval tests -> out/retrieval_report.md.  Run:  python -m kb.retrieval_eval

Auto-verdict is a first pass: correct = all expected keywords in top record; partial = some; incorrect = none.
For out-of-scope queries, correct = the gate refused to answer. Review the verdicts by hand before submitting.
"""
from pathlib import Path

from kb.index import KBIndex

# (type, query, expected keywords in the top record; empty list = should NOT be answered)
TESTS = [
    ("product", "What is a working capital loan and how much can I get?", ["working capital", "50 lakh"]),
    ("policy", "What is the minimum turnover required?", ["25 lakh"]),
    ("qualification", "What credit score do I need to qualify?", ["700"]),
    ("faq", "How many days does approval take?", ["3 working days"]),
    ("objection", "Customer says the interest rate is too high", ["14%", "24%"]),
    ("policy", "Are there charges if I prepay my term loan?", ["4%", "12 months"]),
    ("out_of_scope", "Do you offer home loans or gold loans?", []),
]


def main():
    kb = KBIndex()
    lines = [f"# Retrieval test report (mode: {kb.mode}, threshold: {kb.threshold})", "",
             "| # | Type | Question | Top record | Source | Conf. | Verdict |", "|---|---|---|---|---|---|---|"]
    for n, (typ, q, expect) in enumerate(TESTS, 1):
        res = kb.search(q)
        if not expect:
            verdict = "correct (refused)" if not res["found"] else "incorrect (answered out-of-scope)"
            top, src = ("-", "-") if not res["found"] else (res["results"][0]["record_id"], res["results"][0]["source"])
        elif not res["found"]:
            verdict, top, src = "incorrect (no result)", "-", "-"
        else:
            r = res["results"][0]
            hits = sum(k.lower() in r["content"].lower() for k in expect)
            verdict = "correct" if hits == len(expect) else "partially correct" if hits else "incorrect"
            top, src = r["record_id"], r["citation"].replace("|", "/")
        lines.append(f"| {n} | {typ} | {q} | {top} | {src} | {res['top_confidence']} | {verdict} |")
    out = Path(__file__).resolve().parent.parent / "out" / "retrieval_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()