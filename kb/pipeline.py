"""Q2 pipeline: raw sources -> cleaned, deduped, PII-masked, chunked, traceable KB records.

Run:  python -m kb.pipeline
Out:  out/records.jsonl  (the KB)   out/pipeline_report.json  (what was removed/flagged and why)
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from dateutil import parser as dparser

from kb import config as C

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR, OUT_DIR = ROOT / "data" / "raw", ROOT / "out"

try:  # optional: adds PERSON detection
    from presidio_analyzer import AnalyzerEngine
    _ANALYZER = AnalyzerEngine()
except Exception:
    _ANALYZER = None


# ---------------------------------------------------------------- parsing
class SectionBuilder:
    """Collects (heading_path, text) sections and records headings that have no content."""
    def __init__(self):
        self.stack, self.levels, self.buf, self.sections, self.empty, self._lvl = [], [], [], [], [], 0

    def heading(self, level, title):
        self._flush(level)
        while self.levels and self.levels[-1] >= level:  # drop sibling/deeper headings
            self.levels.pop()
            self.stack.pop()
        self.levels.append(level)
        self.stack.append(title.strip())
        self._lvl = level

    def add(self, line):
        line = line.strip()
        if line:
            self.buf.append(re.sub(r"^[-*]\s+", "", line))

    def _flush(self, next_level):
        text = "\n".join(self.buf).strip()
        if text:
            self.sections.append((list(self.stack), text))
        elif self.stack and (next_level is None or next_level <= self._lvl):
            self.empty.append(" > ".join(self.stack))
        self.buf = []

    def finish(self):
        self._flush(None)
        return self.sections, self.empty


def rows_to_sentences(rows):
    """Table rows (list of cell lists, header first) -> 'Header: value; Header: value.' lines."""
    if len(rows) < 2:
        return []
    headers = rows[0]
    return ["; ".join(f"{h}: {c}" for h, c in zip(headers, r)) + "." for r in rows[1:]]


def parse_html(path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    canon = soup.find("link", rel="canonical")
    meta = {"source_type": "website", "source_url": canon["href"] if canon else str(path.name),
            "title": soup.title.get_text(strip=True) if soup.title else path.stem}
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        t.decompose()
    for t in soup.select("[class*=cookie],[class*=banner],[id*=cookie]"):
        t.decompose()
    root = soup.find("main") or soup.body or soup  # fallback if no <main>
    for table in root.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        p = soup.new_tag("p")
        p.string = "\n".join(rows_to_sentences(rows))
        table.replace_with(p)
    sb = SectionBuilder()
    for el in root.find_all(["h1", "h2", "h3", "p", "li"]):
        if el.name[0] == "h":
            sb.heading(int(el.name[1]), el.get_text(" ", strip=True))
        else:
            for line in el.get_text(" ", strip=True).split("\n"):
                sb.add(line)
    sections, empty = sb.finish()
    return meta, sections, empty


def parse_md(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        raw = raw[m.end():]
    sb, table = SectionBuilder(), []

    def flush_table():
        rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in table
                if not set(r.replace("|", "").strip()) <= set("-: ")]
        for s in rows_to_sentences(rows):
            sb.add(s)
        table.clear()

    for line in raw.splitlines():
        h = re.match(r"^(#{1,4})\s+(.*)", line)
        if h:
            flush_table()
            sb.heading(len(h.group(1)), h.group(2))
        elif line.strip().startswith("|"):
            table.append(line)
        else:
            flush_table()
            sb.add(line)
    flush_table()
    sections, empty = sb.finish()
    meta.setdefault("source_type", "policy")
    meta.setdefault("source_url", path.name)
    meta.setdefault("title", path.stem)
    return meta, sections, empty


# ---------------------------------------------------------------- cleaning
MONTHS = "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
DATE_PATTERNS = [
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})\s+\d{{4}}\b",
    rf"\b(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b",
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",  # Indian convention: DD/MM/YYYY
]


def normalize_dates(text):
    def conv(m):
        try:
            return dparser.parse(m.group(0), dayfirst=True).date().isoformat()
        except Exception:
            return m.group(0)
    for pat in DATE_PATTERNS:
        text = re.sub(pat, conv, text, flags=re.I)
    return text


def normalize_terms(text):
    for pat, rep in C.TERMINOLOGY:
        text = re.sub(pat, rep, text, flags=re.I)
    return re.sub(r"[ \t]+", " ", text)


def mask_pii(text):
    """Returns (masked_text, sorted list of PII types found). Originals are never stored."""
    found = set()
    for label, pat in C.PII_PATTERNS.items():
        def repl(m, label=label):
            if m.group(0) in C.PII_ALLOWLIST:
                return m.group(0)
            found.add(label)
            return f"[{label}]"
        text = re.sub(pat, repl, text)
    if _ANALYZER:
        for r in sorted(_ANALYZER.analyze(text=text, language="en", entities=["PERSON"]),
                        key=lambda r: r.start, reverse=True):
            if r.score >= 0.6:
                text = text[: r.start] + "[PERSON]" + text[r.end:]
                found.add("PERSON")
    else:
        # Fallback heuristic without Presidio: "manager/contact <Name Name>" patterns.
        def name_repl(m):
            found.add("PERSON")
            return f"{m.group(1)} [PERSON]"
        text = re.sub(r"\b(manager|contact:|officer)\s+([A-Z][a-z]+ [A-Z][a-z]+)", name_repl, text)
    return text, sorted(found)


def is_boilerplate(line, line_sources):
    low = line.lower().strip()
    if any(re.search(p, low) for p in C.BOILERPLATE_PATTERNS):
        return True
    return len(line_sources.get(low, ())) >= C.BOILERPLATE_MIN_SOURCES and len(line) < 120


# ---------------------------------------------------------------- chunking / dedup / facts
def chunk_text(text, max_words=C.MAX_CHUNK_WORDS):
    paras = [p for p in text.split("\n") if p.strip()]
    chunks, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > max_words:
            chunks.append("\n".join(cur))
            cur = [cur[-1]] if len(cur[-1].split()) < 60 else []  # 1-paragraph overlap
            n = sum(len(c.split()) for c in cur)
        cur.append(p)
        n += w
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def shingles(text, k=3):
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def facts_in(text):
    out = {}
    for name, pat in C.FACT_PATTERNS.items():
        vals = {tuple(g for g in m.groups() if g) for m in re.finditer(pat, text, flags=re.I)}
        if vals:
            out[name] = vals
    return out


def pick_category(meta, heading_path, title):
    cat = meta.get("category")
    if cat and cat != "auto":
        return cat
    hay = " ".join(heading_path + [title]).lower()
    for pat, c in C.CATEGORY_RULES:
        if re.search(pat, hay):
            return c
    return "general"


# ---------------------------------------------------------------- main
def run():
    OUT_DIR.mkdir(exist_ok=True)
    report = {"run_date": date.today().isoformat(), "extraction_failures": [], "empty_sections": [],
              "boilerplate_removed": 0, "too_short_dropped": 0, "duplicates": [], "conflicts": [],
              "pii_masked": Counter(), "records_written": 0}

    docs = []
    for path in sorted(RAW_DIR.rglob("*")):
        if path.suffix not in (".html", ".md"):
            continue
        try:
            meta, sections, empty = (parse_html if path.suffix == ".html" else parse_md)(path)
            if not sections:
                raise ValueError("no extractable content")
            report["empty_sections"] += [{"source": path.name, "section": e} for e in empty]
            docs.append((path, meta, sections))
        except Exception as e:  # one bad file must not kill the run
            report["extraction_failures"].append({"source": path.name, "error": str(e)})

    # Cross-source boilerplate: short lines that appear in many sources
    line_sources = defaultdict(set)
    for path, _, secs in docs:
        for _, text in secs:
            for ln in text.split("\n"):
                line_sources[ln.lower().strip()].add(path.name)

    # Highest-priority sources first so they become the canonical record in dedup
    docs.sort(key=lambda d: -C.SOURCE_PRIORITY.get(d[1]["source_type"], 0))

    kept, kept_shingles = [], []
    for path, meta, secs in docs:
        prio = C.SOURCE_PRIORITY.get(meta["source_type"], 0)
        eff = normalize_dates(meta.get("effective_date", "")) if meta.get("effective_date") else None
        for heading_path, text in secs:
            lines = [ln for ln in text.split("\n") if not is_boilerplate(ln, line_sources)]
            report["boilerplate_removed"] += len(text.split("\n")) - len(lines)
            text = normalize_terms(normalize_dates("\n".join(lines)))
            text, pii_types = mask_pii(text)
            if len(text.split()) < C.MIN_WORDS:
                report["too_short_dropped"] += 1
                continue
            path_list = heading_path or [meta["title"]]
            title = re.sub(r"^Q:\s*", "", path_list[-1])
            category = pick_category(meta, path_list, title)
            for i, chunk in enumerate(chunk_text(text)):
                sh = shingles(chunk)
                dup = next((k for k, s in zip(kept, kept_shingles) if jaccard(sh, s) >= C.DEDUP_JACCARD), None)
                if dup:
                    report["duplicates"].append({"dropped_source": path.name, "dropped_section": " > ".join(path_list),
                                                 "kept_as": dup["title"], "kept_source": dup["source"]})
                    continue
                rec = {
                    "title": title + (f" (part {i + 1})" if i else ""),
                    "content": chunk,
                    "category": category,
                    "section_path": " > ".join(path_list),
                    "source": path.name,
                    "source_type": meta["source_type"],
                    "source_url": meta["source_url"],
                    "version": meta.get("version", "1.0"),
                    "effective_date": eff,
                    "updated_at": report["run_date"],
                    "language": "en",
                    "pii": bool(pii_types),
                    "pii_types": pii_types,
                    "priority": prio,
                    "status": "active",
                    "content_hash": hashlib.sha1(chunk.encode()).hexdigest()[:12],
                }
                for t in pii_types:
                    report["pii_masked"][t] += 1
                kept.append(rec)
                kept_shingles.append(sh)

    # Conflict detection: lower-priority records disagreeing with the canonical (highest-priority) values
    top_prio = {}
    for r in kept:
        for name in facts_in(r["content"]):
            top_prio[name] = max(top_prio.get(name, 0), r["priority"])
    canon = {name: (p, set()) for name, p in top_prio.items()}
    for r in kept:
        for name, vals in facts_in(r["content"]).items():
            if r["priority"] == top_prio[name]:
                canon[name][1].update(vals)
    for r in kept:
        for name, vals in facts_in(r["content"]).items():
            p, cvals = canon[name]
            if r["priority"] < p and not vals <= cvals:
                r["status"] = "flagged_conflict"
                report["conflicts"].append({"fact": name, "record_source": r["source"], "section": r["section_path"],
                                            "found": sorted(map(list, vals)), "canonical": sorted(map(list, cvals)),
                                            "resolution": "excluded from index; higher-priority source wins"})

    # Stable IDs: kb_<category>_<nnn>
    counters = Counter()
    for r in kept:
        counters[r["category"]] += 1
        r["record_id"] = f"kb_{r['category']}_{counters[r['category']]:03d}"
    order = ["record_id", "title", "content", "category", "section_path", "source", "source_type", "source_url",
             "version", "effective_date", "updated_at", "language", "pii", "pii_types", "priority", "status",
             "content_hash"]
    with open(OUT_DIR / "records.jsonl", "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps({k: r[k] for k in order}, ensure_ascii=False) + "\n")
    report["records_written"] = len(kept)
    report["active_records"] = sum(r["status"] == "active" for r in kept)
    report["pii_masked"] = dict(report["pii_masked"])
    (OUT_DIR / "pipeline_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"records={report['records_written']} active={report['active_records']} "
          f"dups={len(report['duplicates'])} conflicts={len(report['conflicts'])} "
          f"failures={len(report['extraction_failures'])}")


if __name__ == "__main__":
    run()
