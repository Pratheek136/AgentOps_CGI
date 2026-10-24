"""TF-IDF search over the synthetic knowledge base (runbooks + past postmortems)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .config import paths


@dataclass
class KBDoc:
    id: str
    title: str
    kind: str  # runbook | postmortem
    text: str
    paragraphs: list[str]


def _load() -> list[KBDoc]:
    docs = []
    for kind, folder in (("runbook", "runbooks"), ("postmortem", "incidents")):
        for f in sorted((paths.kb / folder).glob("*.md")):
            text = f.read_text(encoding="utf-8")
            first = text.splitlines()[0].lstrip("# ").strip()
            doc_id, _, title = first.partition(":")
            paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip() and not p.startswith("# ")]
            docs.append(KBDoc(doc_id.strip(), title.strip(), kind, text, paras))
    return docs


@lru_cache(maxsize=1)
def _index():
    docs = _load()
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    # weight the title by repeating it
    matrix = vec.fit_transform([f"{d.title} {d.title} {d.text}" for d in docs])
    return docs, vec, matrix


def search(query: str, k: int = 3) -> list[dict]:
    k = max(1, min(int(k), 5))
    docs, vec, matrix = _index()
    q = vec.transform([query])
    scores = linear_kernel(q, matrix).ravel()
    ranked = scores.argsort()[::-1][:k]
    out = []
    for i in ranked:
        d = docs[i]
        out.append({"id": d.id, "title": d.title, "kind": d.kind, "score": round(float(scores[i]), 3),
                    "snippet": _best_paragraph(d, vec, q)})
    return out


def _best_paragraph(doc: KBDoc, vec, q) -> str:
    if not doc.paragraphs:
        return ""
    s = linear_kernel(q, vec.transform(doc.paragraphs)).ravel()
    return doc.paragraphs[int(s.argmax())][:400]


def get(doc_id: str) -> dict | None:
    docs, _, _ = _index()
    d = next((d for d in docs if d.id.upper() == doc_id.upper()), None)
    return {"id": d.id, "title": d.title, "kind": d.kind, "text": d.text} if d else None
