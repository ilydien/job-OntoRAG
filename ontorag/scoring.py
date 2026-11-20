"""Generic policy-driven scoring and ranking.

SWRL decides logical eligibility tiers.  This module only combines continuous
component scores and sorts by ``tier ASC, score DESC``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from .extraction import Profile
from .policy import RankingPolicy
from .query_engine import Index


@dataclass
class Recommendation:
    occupation_iri: str
    title_en: str
    title_id: Optional[str]
    soc: Optional[str]
    tier: str
    score: float
    component_scores: Dict[str, float] = field(default_factory=dict)
    element_matches: List[dict] = field(default_factory=list)
    evidence: List[dict] = field(default_factory=list)
    explanation: str = ""
    description_en: Optional[str] = None
    description_id: Optional[str] = None
    row: dict = field(default_factory=dict)
    rank: int = 0

    def display_title(self, lang: str = "id") -> str:
        if lang == "id" and self.title_id:
            return self.title_id
        return self.title_en or self.title_id or self.occupation_iri

    def display_description(self, lang: str = "id", limit: int = 0) -> str:
        value = (
            self.description_id
            if lang == "id" and self.description_id
            else (self.description_en or self.description_id or "")
        )
        text = " ".join(str(value).split())
        if limit and len(text) > limit:
            shortened = text[:limit].rsplit(" ", 1)[0].rstrip()
            return (shortened or text[:limit]).rstrip() + "..."
        return text


def holland_score(
    profile: Profile,
    row: Mapping[str, object],
    policy: RankingPolicy,
) -> Optional[float]:
    if not profile.holland:
        return None
    code_weights = {
        str(row.get("holland_primary") or ""): policy.holland_primary_weight,
        str(row.get("holland_secondary") or ""): policy.holland_secondary_weight,
        str(row.get("holland_tertiary") or ""): policy.holland_tertiary_weight,
    }
    total_preference = sum(profile.holland.values()) or 1.0
    matched = 0.0
    for code, code_weight in code_weights.items():
        if not code:
            continue
        matched += profile.holland.get(code, 0.0) * code_weight
    return max(0.0, min(1.0, matched / total_preference))


def _aggregate(values: Sequence[float], method: str) -> float:
    if not values:
        return 0.0
    if method.lower() == "mean":
        return sum(values) / len(values)
    return max(values)


def element_score(
    profile: Profile,
    rows: Iterable[Mapping[str, object]],
    policy: RankingPolicy,
) -> tuple[Optional[float], List[dict]]:
    if not profile.elements:
        return None, []
    by_element: Dict[str, List[float]] = {}
    labels: Dict[str, str] = {}
    rating_types: Dict[str, str] = {}
    for row in rows:
        element_iri = str(row.get("element_iri") or "")
        norm = row.get("norm_value")
        if not element_iri or norm is None:
            continue
        by_element.setdefault(element_iri, []).append(float(norm))
        labels.setdefault(
            element_iri,
            str(row.get("element_name_id") or row.get("element_name_en") or element_iri),
        )
        if element_iri not in rating_types:
            rating_types[element_iri] = str(row.get("rating_type") or "")

    total_preference = sum(profile.elements.values()) or 1.0
    matched = 0.0
    matches: List[dict] = []
    for element_iri, preference in profile.elements.items():
        values = by_element.get(element_iri, [])
        if not values:
            continue
        norm = _aggregate(values, policy.element_aggregation)
        matched += preference * norm
        matches.append(
            {
                "element_iri": element_iri,
                "element_name": labels.get(
                    element_iri, profile.element_labels.get(element_iri, element_iri)
                ),
                "preference_weight": preference,
                "normalized_rating": norm,
                "rating_type": rating_types.get(element_iri, ""),
            }
        )
    matches.sort(key=lambda item: item["preference_weight"] * item["normalized_rating"], reverse=True)
    return max(0.0, min(1.0, matched / total_preference)), matches


def normalize_lexical(
    lexical_scores: Mapping[str, float],
    candidate_iris: Iterable[str],
    method: str = "minmax",
) -> Dict[str, float]:
    """Normalise a sparse retrieval score map over the candidate set.

    The same min-max rule is used for lexical (BM25) and semantic (cosine)
    evidence so that policy weights stay comparable.
    """

    candidates = list(candidate_iris)
    if not lexical_scores:
        return {}
    values = [lexical_scores.get(iri) for iri in candidates if iri in lexical_scores]
    if not values:
        return {}
    if method.lower() != "minmax":
        return {iri: lexical_scores.get(iri, 0.0) for iri in candidates}
    low, high = min(values), max(values)
    if high <= low:
        return {iri: (0.5 if iri in lexical_scores else 0.0) for iri in candidates}
    return {
        iri: max(0.0, min(1.0, (lexical_scores.get(iri, low) - low) / (high - low)))
        for iri in candidates
    }


def _tier_from_flags(flags: Optional[Mapping[str, object]], default_tier: str) -> str:
    if not flags:
        return default_tier
    tier = flags.get("tier")
    if isinstance(tier, str) and tier:
        return tier
    if flags.get("eligible_strong"):
        return "EligibleStrong"
    if flags.get("eligible"):
        return "Eligible"
    return "NotEligible"


def score_candidates(
    index: Index,
    profile: Profile,
    policy: RankingPolicy,
    candidates: Sequence[dict],
    lexical_scores: Optional[Mapping[str, float]] = None,
    reasoning_flags: Optional[Mapping[str, Mapping[str, object]]] = None,
    top_k: Optional[int] = None,
    semantic_scores: Optional[Mapping[str, float]] = None,
    semantic_normalization: Optional[str] = None,
    element_rows: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
) -> List[Recommendation]:
    """Score and rank candidate rows.

    Retrieval evidence is optional: ``semantic_scores`` (cosine similarity)
    and ``lexical_scores`` (BM25) are only added to a row when the caller
    computed them for this request.  Relative component weights are
    renormalised over the components that are actually available.

    ``element_rows`` is an optional pre-fetched mapping (see
    :meth:`Index.elements_for_many`) so the whole pool shares one batch
    lookup instead of a query per occupation.
    """

    lexical_scores = lexical_scores or {}
    semantic_scores = semantic_scores or {}
    reasoning_flags = reasoning_flags or {}
    candidate_iris = [str(row["iri"]) for row in candidates]
    normalized_lexical = normalize_lexical(
        lexical_scores, candidate_iris, policy.lexical_normalization
    )
    normalized_semantic = normalize_lexical(
        semantic_scores,
        candidate_iris,
        semantic_normalization or policy.semantic_normalization,
    )
    if (
        element_rows is None
        and profile.elements
        and hasattr(index, "elements_for_many")
    ):
        element_rows = index.elements_for_many(candidate_iris, profile.elements.keys())
    weights = {component.component_type: component.weight for component in policy.components}
    recommendations: List[Recommendation] = []

    for row in candidates:
        iri = str(row["iri"])
        component_values: Dict[str, float] = {}
        holland = holland_score(profile, row, policy)
        if holland is not None:
            component_values["holland"] = holland
        if not profile.elements:
            element, element_matches = None, []
        elif element_rows is not None:
            element, element_matches = element_score(
                profile, element_rows.get(iri, ()), policy
            )
        else:
            element, element_matches = element_score(
                profile, index.elements_for(iri), policy
            )
        if element is not None:
            component_values["element"] = element
        if lexical_scores:
            component_values["lexical"] = normalized_lexical.get(iri, 0.0)
        if semantic_scores:
            component_values["semantic"] = normalized_semantic.get(iri, 0.0)

        available_weight = sum(weights.get(name, 0.0) for name in component_values)
        if available_weight > 0:
            combined = (
                sum(weights.get(name, 0.0) * value for name, value in component_values.items())
                / available_weight
            )
        else:
            combined = 0.0

        tier = _tier_from_flags(reasoning_flags.get(iri), policy.fallback_tier)
        if policy.require_eligible and tier == "NotEligible":
            continue

        recommendations.append(
            Recommendation(
                occupation_iri=iri,
                title_en=str(row.get("title_en") or ""),
                title_id=str(row.get("title_id") or "") or None,
                soc=str(row.get("soc") or "") or None,
                tier=tier,
                score=round(max(0.0, min(1.0, combined)), 8),
                component_scores={name: round(value, 8) for name, value in component_values.items()},
                element_matches=element_matches,
                row=dict(row),
            )
        )

    recommendations.sort(
        key=lambda item: (
            policy.tier_rank(item.tier),
            -item.score,
            item.title_en or "",
            item.occupation_iri,
        )
    )
    limit = int(top_k or policy.top_k)
    recommendations = recommendations[:limit]
    for rank, recommendation in enumerate(recommendations, start=1):
        recommendation.rank = rank
    return recommendations
