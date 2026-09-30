"""Retrieval over out/records.jsonl.

- Only status == "active" records are indexed (conflicting/superseded chunks are excluded).
- Ranking: BM25 (+ dense cosine if fastembed is installed) fused with Reciprocal Rank Fusion.
- Confidence (used to decide "answer" vs "say I don't know"):
    dense mode   -> cosine similarity of the top record
    lexical mode -> IDF-weighted fraction of query terms found in the top record
  Out-of-corpus query words count against coverage, which is what makes out-of-scope questions fail the gate.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from kb.pipeline import normalize_terms

ROOT = Path(__file__).resolve().parent.parent
STOP = set("a an the is are was were be do does did i you we they it of to for in on at and or with my your our can "
           "could would should what how when where which who this that these those about me tell please there any "
           "have has get from as by if not no so am will much many long need needs want take make give too very "
           "just say says said".split())


def _stem(t):
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def tokenize(s):
    return [_stem(t) for t in re.findall(r"\w+", s.lower()) if t not in STOP]


class KBIndex:
    def __init__(self, records_path=None, embed_model=None):
        records_path = Path(records_path or ROOT / "out" / "records.jsonl")
        with open(records_path, encoding="utf-8") as f:
            allrecs = [json.loads(line) for line in f if line.strip()]
        self.records = [r for r in allrecs if r["status"] == "active"]
        self.texts = [f"{r['title']}. {r['section_path']}. {r['content']}" for r in self.records]
        self.doc_tokens = [tokenize(t) for t in self.texts]
        self.doc_sets = [set(t) for t in self.doc_tokens]
        self.bm25 = BM25Okapi(self.doc_tokens)
        self.max_idf = math.log(len(self.records) + 1) + 1
        self.emb, self.embedder = None, None
        model = embed_model if embed_model is not None else os.getenv("EMBED_MODEL", "")
        if model:
            self._load_embeddings(model)
        env_thr = os.getenv("MIN_CONFIDENCE", "").strip()
        self.threshold = float(env_thr) if env_thr else (0.55 if self.emb is not None else 0.50)
        self.mode = "hybrid" if self.emb is not None else "lexical"

    def _load_embeddings(self, model):
        try:
            from fastembed import TextEmbedding
            self.embedder = TextEmbedding(model_name=model)
            key = hashlib.sha1((model + "".join(self.texts)).encode()).hexdigest()[:12]
            cache = ROOT / "out" / f"emb_{key}.npy"
            if cache.exists():
                self.emb = np.load(cache)
            else:
                self.emb = np.array(list(self.embedder.embed(self.texts)), dtype="float32")
                self.emb /= np.linalg.norm(self.emb, axis=1, keepdims=True)
                np.save(cache, self.emb)
        except Exception as e:  # degrade gracefully to BM25-only
            print(f"[kb] dense embeddings unavailable ({e}); using lexical mode")
            self.emb, self.embedder = None, None

    def _coverage(self, q_tokens, doc_idx):
        idf = lambda t: max(self.bm25.idf.get(t, self.max_idf), 0.1)
        qset = set(q_tokens)
        total = sum(idf(t) for t in qset)
        hit = sum(idf(t) for t in qset if t in self.doc_sets[doc_idx])
        return hit / total if total else 0.0

    def search(self, query, top_k=3, category=None):
        q_tokens = tokenize(normalize_terms(query))  # same term standardisation as the KB
        if not q_tokens:
            return self._result(query, [], 0.0)
        idxs = [i for i, r in enumerate(self.records) if category in (None, r["category"])]
        if not idxs:
            return self._result(query, [], 0.0)
        bm = self.bm25.get_scores(q_tokens)
        rank_lists = [sorted(idxs, key=lambda i: -bm[i])]
        cos = None
        if self.emb is not None:
            qv = np.array(list(self.embedder.embed([query]))[0], dtype="float32")
            qv /= np.linalg.norm(qv)
            cos = self.emb @ qv
            rank_lists.append(sorted(idxs, key=lambda i: -cos[i]))
        rrf = {i: 0.0 for i in idxs}
        for rl in rank_lists:
            for rank, i in enumerate(rl):
                rrf[i] += 1.0 / (60 + rank)
        ranked = sorted(idxs, key=lambda i: -rrf[i])[:top_k]
        scored = [(i, float(cos[i]) if cos is not None else self._coverage(q_tokens, i)) for i in ranked]
        passing = [(i, s) for i, s in scored if s >= self.threshold]
        return self._result(query, passing, scored[0][1] if scored else 0.0)

    def _result(self, query, passing, top_conf):
        results = []
        for i, s in passing:
            r = self.records[i]
            results.append({
                "record_id": r["record_id"], "title": r["title"], "content": r["content"],
                "category": r["category"], "confidence": round(s, 3), "source": r["source"],
                "citation": f"{r['record_id']} | {r['source']} | {r['section_path']} | v{r['version']}",
            })
        return {"query": query, "found": bool(results), "top_confidence": round(top_conf, 3),
                "threshold": self.threshold, "mode": self.mode, "results": results}