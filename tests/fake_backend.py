"""Deterministic embedding backends for tests.

The vectors are keyword based on purpose: the tests verify the retrieval and
scoring plumbing, not the quality of a neural model, and they must run without
``sentence-transformers`` or network access.
"""

from __future__ import annotations

from typing import List, Sequence

from ontorag.embeddings import normalize_vector


class KeywordBackend:
    name = "fake/keyword"
    dim = 4
    query_prefix = ""
    passage_prefix = ""
    normalized = True

    def __init__(self, name: str | None = None, dim: int | None = None) -> None:
        if name:
            self.name = name
        if dim:
            self.dim = dim
        self.encoded = 0

    def encode(self, texts: Sequence[str], kind: str = "passage") -> List[List[float]]:
        self.encoded += len(texts)
        vectors: List[List[float]] = []
        for text in texts:
            lower = text.lower()
            values = [0.0] * self.dim
            if any(word in lower for word in ("data", "analys", "statistic", "model", "program")):
                values[0] += 1.0
            if any(word in lower for word in ("fire", "inspect", "safety", "building", "construction")):
                values[min(1, self.dim - 1)] += 1.0
            if self.dim > 3:
                values[3] = 0.05
            vectors.append(list(normalize_vector(values)))
        return vectors


class MismatchedBackend(KeywordBackend):
    name = "fake/other-model"
