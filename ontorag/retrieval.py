"""Dense semantic retrieval over occupation-card embeddings.

The retriever loads every stored vector once, encodes the profile text with
the configured backend, and returns cosine similarities for the structured
candidate set.  Ranking stays in :mod:`ontorag.scoring`; this module is only
responsible for recall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .embeddings import CARD_VERSION, EmbeddingBackend, cosine, unpack_vector
from .query_engine import Index

try:  # optional acceleration; the pure-Python path keeps tests dependency-free
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover - depends on the environment
    _np = None

_CACHE_LIMIT = 64


class EmbeddingIndexMismatch(RuntimeError):
    """The stored vectors were built with a different model or configuration."""


@dataclass(frozen=True)
class RetrievalInfo:
    model: str
    dim: int
    vector_count: int
    built_at: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "model": self.model,
            "dim": str(self.dim),
            "count": str(self.vector_count),
            "built_at": self.built_at,
        }


class SemanticRetriever:
    def __init__(self, index: Index, backend: EmbeddingBackend) -> None:
        self.index = index
        self.backend = backend
        self._cache: Dict[str, Tuple[float, ...]] = {}

        meta = index.embedding_meta()
        if not meta:
            raise EmbeddingIndexMismatch(
                "the index has no occupation embeddings; run "
                "'python -m ontorag.cli build-embeddings' first"
            )
        self._check(meta)

        self._iris: List[str] = []
        self._vectors: List[Tuple[float, ...]] = []
        for row in index.embedding_rows():
            vector = unpack_vector(row["vector"])
            if len(vector) != int(backend.dim):
                raise EmbeddingIndexMismatch(
                    f"stored vector for {row['occupation_iri']} has {len(vector)} "
                    f"dimensions, model expects {backend.dim}"
                )
            self._iris.append(str(row["occupation_iri"]))
            self._vectors.append(tuple(float(value) for value in vector))
        if not self._iris:
            raise EmbeddingIndexMismatch(
                "the index has no occupation embeddings; run "
                "'python -m ontorag.cli build-embeddings' first"
            )
        self._position = {iri: position for position, iri in enumerate(self._iris)}
        self._matrix = (
            _np.asarray(self._vectors, dtype=_np.float32)
            if _np is not None and self._vectors
            else None
        )
        self.info = RetrievalInfo(
            model=str(meta.get("model") or ""),
            dim=int(meta.get("dim") or 0),
            vector_count=len(self._iris),
            built_at=str(meta.get("built_at") or ""),
        )

    # ------------------------------------------------------------------
    # Compatibility
    # ------------------------------------------------------------------

    def _check(self, meta: Mapping[str, str]) -> None:
        problems: List[str] = []
        stored_model = meta.get("model") or ""
        if stored_model != self.backend.name:
            problems.append(
                f"model: index has {stored_model!r}, backend is {self.backend.name!r}"
            )
        try:
            stored_dim = int(meta.get("dim") or 0)
        except ValueError:
            stored_dim = 0
        if stored_dim != int(self.backend.dim):
            problems.append(f"dimension: index has {stored_dim}, backend has {self.backend.dim}")
        stored_version = meta.get("card_version") or ""
        if stored_version != CARD_VERSION:
            problems.append(
                f"card version: index has {stored_version!r}, code expects {CARD_VERSION!r}"
            )
        for key, attribute in (("prefix_query", "query_prefix"), ("prefix_passage", "passage_prefix")):
            expected = getattr(self.backend, attribute, None)
            if expected is not None and key in meta and meta.get(key, "") != expected:
                problems.append(f"{key}: index has {meta.get(key)!r}, backend uses {expected!r}")
        if problems:
            raise EmbeddingIndexMismatch(
                "stored occupation embeddings do not match the requested backend "
                f"({'; '.join(problems)}). Rebuild them with "
                "'python -m ontorag.cli build-embeddings --rebuild'."
            )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_query(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _encode(self, text: str) -> Tuple[float, ...]:
        key = self.normalize_query(text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        vectors = self.backend.encode([key], kind="query")
        if len(vectors) != 1:
            raise EmbeddingIndexMismatch("embedding backend did not return exactly one query vector")
        vector = tuple(float(value) for value in vectors[0])
        if len(vector) != int(self.backend.dim):
            raise EmbeddingIndexMismatch(
                f"query vector has {len(vector)} dimensions, expected {self.backend.dim}"
            )
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = vector
        return vector

    def scores(
        self,
        text: str,
        candidate_iris: Optional[Iterable[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, float]:
        """Return cosine similarity for candidate occupations, best first."""

        query_text = self.normalize_query(text)
        if not query_text:
            return {}

        allowed: Optional[Set[str]] = set(candidate_iris) if candidate_iris is not None else None
        if allowed is not None and not allowed:
            return {}
        positions = [
            position
            for iri, position in self._position.items()
            if allowed is None or iri in allowed
        ]
        if not positions:
            return {}

        query = self._encode(query_text)
        scored: List[Tuple[float, str]] = []
        if self._matrix is not None and _np is not None:
            matrix = self._matrix[positions]
            query_array = _np.asarray(query, dtype=_np.float32)
            similarities = matrix @ query_array
            for position, similarity in zip(positions, similarities):
                scored.append((float(similarity), self._iris[position]))
        else:
            for position in positions:
                scored.append((cosine(query, self._vectors[position]), self._iris[position]))

        scored.sort(key=lambda item: (-item[0], item[1]))
        if limit is not None and limit >= 0:
            scored = scored[: int(limit)]
        return {iri: score for score, iri in scored}

    def __len__(self) -> int:
        return len(self._iris)
