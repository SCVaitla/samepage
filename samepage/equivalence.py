"""Question equivalence: map a new question onto a question we already know.

Default backend: TF-IDF over glossary-aware word tokens plus character 3-grams, with
cosine similarity. It is small, needs no download, and gives the same answer every
run. Any `Embedder` (for example a sentence-transformers model) can replace it.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Protocol

from samepage.text import Glossary


class Embedder(Protocol):
    def fit(self, texts: list[str]) -> None: ...
    def vector(self, text: str) -> dict[str, float]: ...


# Words that appear in nearly every question about a product and say nothing about which
# fact is asked: the company's name and its generic nouns.
DOMAIN_STOPWORDS = frozenset({"g:plan", "g:workspace", "juniper", "desk", "customer", "team", "allow"})


class TfidfEmbedder:
    def __init__(self, glossary: Glossary, stopwords: frozenset[str] = DOMAIN_STOPWORDS) -> None:
        self.glossary = glossary
        self.stopwords = stopwords
        self.idf: dict[str, float] = {}

    def features(self, text: str) -> Counter[str]:
        words = [w for w in self.glossary.tokens(text) if w not in self.stopwords]
        feats: Counter[str] = Counter(f"w:{w}" for w in words)
        for w in words:
            padded = f"#{w}#"
            feats.update(f"c:{padded[i : i + 3]}" for i in range(len(padded) - 2))
        return feats

    def fit(self, texts: list[str]) -> None:
        docs = [set(self.features(t)) for t in texts]
        df: Counter[str] = Counter(f for d in docs for f in d)
        n = len(docs)
        self.idf = {f: math.log((1 + n) / (1 + c)) + 1 for f, c in df.items()}

    def vector(self, text: str) -> dict[str, float]:
        feats = self.features(text)
        vec = {
            f: (1 + math.log(c)) * self.idf.get(f, 1.0) * (2.0 if f.startswith("w:") else 1.0) for f, c in feats.items()
        }
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {f: v / norm for f, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(f, 0.0) for f, v in a.items())


class QuestionIndex:
    def __init__(self, embedder: Embedder, threshold: float) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self.items: list[tuple[str, str]] = []  # (canonical_id, text)
        self._vectors: list[dict[str, float]] = []

    def add(self, canonical_id: str, text: str) -> None:
        self.items.append((canonical_id, text))
        self.embedder.fit([t for _, t in self.items])
        self._vectors = [self.embedder.vector(t) for _, t in self.items]

    def best(self, text: str) -> tuple[str | None, float]:
        """The closest known question's canonical id and its similarity (None if below threshold)."""
        if not self.items:
            return None, 0.0
        v = self.embedder.vector(text)
        scores = [cosine(v, known) for known in self._vectors]
        i = max(range(len(scores)), key=scores.__getitem__)
        return (self.items[i][0] if scores[i] >= self.threshold else None), scores[i]

    def paraphrases(self, canonical_id: str) -> list[str]:
        return [t for cid, t in self.items if cid == canonical_id]
