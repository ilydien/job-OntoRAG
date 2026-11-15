"""Gold-query benchmark for retrieval quality.

The benchmark replays a small set of hand-labelled career descriptions and
measures how well the ranked occupations match the expected SOC codes.  It is
retrieval-agnostic: the caller supplies a ``recommend`` callable, so the same
gold set can compare ``lexical``, ``semantic``, and ``hybrid``.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from .scoring import Recommendation


@dataclass(frozen=True)
class GoldQuery:
    text: str
    expected_soc: tuple[str, ...]
    education: Optional[str] = None
    max_job_zone: Optional[int] = None
    language: Optional[str] = None


@dataclass(frozen=True)
class GoldSet:
    queries: List[GoldQuery]
    default_education: Optional[str] = None
    default_max_job_zone: Optional[int] = None


@dataclass
class QueryScore:
    text: str
    expected_soc: List[str]
    ranked_soc: List[str]
    recall_at_k: float
    reciprocal_rank: float

    def as_dict(self) -> Dict[str, object]:
        return {
            "text": self.text,
            "expected_soc": list(self.expected_soc),
            "ranked_soc": list(self.ranked_soc),
            "recall_at_k": self.recall_at_k,
            "reciprocal_rank": self.reciprocal_rank,
        }


@dataclass
class BenchmarkResult:
    mode: str
    k: int
    query_count: int
    recall_at_k: float
    mrr: float
    latency_seconds: float
    per_query: List[QueryScore] = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "k": self.k,
            "query_count": self.query_count,
            "recall_at_k": self.recall_at_k,
            "mrr": self.mrr,
            "latency_seconds": self.latency_seconds,
            "error": self.error,
            "per_query": [item.as_dict() for item in self.per_query],
        }


def load_gold_set(path: str | Path) -> "GoldSet":
    """Load a gold set, including its per-file default profile."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    defaults: Dict[str, object] = payload if isinstance(payload, dict) else {}
    query_items = payload.get("queries", []) if isinstance(payload, dict) else payload
    if not isinstance(query_items, list):
        raise ValueError(f"{path} must contain a list of queries")
    queries: List[GoldQuery] = []
    for index, item in enumerate(query_items):
        if not isinstance(item, dict) or not item.get("text"):
            raise ValueError(f"query #{index} needs a 'text' field")
        expected = item.get("expected_soc") or item.get("expected") or []
        if isinstance(expected, str):
            expected = [expected]
        queries.append(
            GoldQuery(
                text=str(item["text"]),
                expected_soc=tuple(str(code) for code in expected),
                education=item.get("education"),
                max_job_zone=item.get("max_job_zone"),
                language=item.get("language"),
            )
        )
    education = defaults.get("default_education")
    max_job_zone = defaults.get("default_max_job_zone")
    return GoldSet(
        queries=queries,
        default_education=str(education) if education else None,
        default_max_job_zone=int(max_job_zone) if max_job_zone is not None else None,
    )


def load_gold_queries(path: str | Path) -> List[GoldQuery]:
    """Load only the gold queries from a JSON file."""

    return load_gold_set(path).queries


def ranked_socs(recommendations: Sequence[Recommendation], k: int) -> List[str]:
    return [str(item.soc) for item in recommendations[:k] if item.soc]


def recall_at_k(ranked: Sequence[str], expected: Iterable[str], k: int) -> float:
    expected = list(expected)
    if not expected:
        return 0.0
    top = set(ranked[:k])
    return sum(1 for code in expected if code in top) / len(expected)


def reciprocal_rank(ranked: Sequence[str], expected: Iterable[str]) -> float:
    expected = set(expected)
    for position, code in enumerate(ranked, start=1):
        if code in expected:
            return 1.0 / position
    return 0.0


def evaluate(
    mode: str,
    recommend: Callable[[GoldQuery], Sequence[Recommendation]],
    queries: Sequence[GoldQuery],
    k: int = 10,
) -> BenchmarkResult:
    """Run ``recommend`` over every gold query and aggregate the metrics."""

    start = time.perf_counter()
    per_query: List[QueryScore] = []
    recalls: List[float] = []
    rrs: List[float] = []
    for query in queries:
        ranked = ranked_socs(recommend(query), k)
        recall = recall_at_k(ranked, query.expected_soc, k)
        rr = reciprocal_rank(ranked, query.expected_soc)
        recalls.append(recall)
        rrs.append(rr)
        per_query.append(
            QueryScore(
                text=query.text,
                expected_soc=list(query.expected_soc),
                ranked_soc=ranked,
                recall_at_k=recall,
                reciprocal_rank=rr,
            )
        )
    elapsed = time.perf_counter() - start
    return BenchmarkResult(
        mode=mode,
        k=k,
        query_count=len(queries),
        recall_at_k=statistics.fmean(recalls) if recalls else 0.0,
        mrr=statistics.fmean(rrs) if rrs else 0.0,
        latency_seconds=elapsed,
        per_query=per_query,
    )
