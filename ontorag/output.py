"""Terminal and machine-readable output helpers."""

from __future__ import annotations

import json
from typing import Iterable, List, Sequence

from .extraction import Profile, format_decimal, normalize_iri
from .ontology import Ontology
from .scoring import Recommendation


def recommendation_dict(
    recommendation: Recommendation,
    language: str = "id",
    precision: int = 4,
) -> dict:
    return {
        "rank": recommendation.rank,
        "tier": recommendation.tier,
        "score": round(recommendation.score, precision),
        "occupation_iri": recommendation.occupation_iri,
        "title": recommendation.display_title(language),
        "title_en": recommendation.title_en,
        "title_id": recommendation.title_id,
        "soc": recommendation.soc,
        "description": recommendation.display_description(language),
        "description_en": recommendation.description_en,
        "description_id": recommendation.description_id,
        "component_scores": {
            key: round(value, precision)
            for key, value in recommendation.component_scores.items()
        },
        "evidence": recommendation.evidence,
        "explanation": recommendation.explanation,
    }


def recommendations_json(
    recommendations: Sequence[Recommendation],
    profile: Profile | None = None,
    language: str = "id",
    precision: int = 4,
) -> str:
    payload = {
        "profile": {
            "user_iri": profile.user_iri if profile else None,
            "language": profile.language if profile else language,
            "education_level": profile.education_local if profile else None,
            "max_job_zone": profile.max_job_zone if profile else None,
            "holland": profile.holland if profile else {},
            "elements": profile.element_labels if profile else {},
        },
        "recommendations": [
            recommendation_dict(item, language=language, precision=precision)
            for item in recommendations
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def recommendations_table(
    recommendations: Sequence[Recommendation],
    language: str = "id",
    precision: int = 4,
) -> str:
    if not recommendations:
        return "No recommendations."
    headers = ("#", "Tier", "Score", "Occupation", "SOC")
    rows: List[tuple[str, str, str, str, str]] = []
    for item in recommendations:
        rows.append(
            (
                str(item.rank),
                item.tier,
                f"{item.score:.{precision}f}",
                item.display_title(language),
                item.soc or "",
            )
        )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    line = "  ".join(headers[index].ljust(widths[index]) for index in range(len(headers)))
    separator = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(row[index].ljust(widths[index]) for index in range(len(headers)))
        for row in rows
    ]
    return "\n".join([line, separator, *body])


def _ttl_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def recommendations_ttl(
    profile: Profile,
    recommendations: Sequence[Recommendation],
    ontology: Ontology,
    language: str = "id",
    description_limit: int | None = None,
) -> str:
    lines: List[str] = [profile.to_ttl(ontology), ""]
    user = normalize_iri(profile.user_iri)
    for item in recommendations:
        rec_iri = f"career:recommendation_{item.rank}_{_local_suffix(item.occupation_iri)}"
        reason = item.explanation or ""
        description = item.display_description(language, limit=description_limit or 0)
        lang = "id" if (language or "id").lower() == "id" else "en"
        predicates = [
            f"    career:recommendationFor <{user}>",
            f"    career:recommendedOccupation <{item.occupation_iri}>",
            f"    career:recommendationRank \"{item.rank}\"^^xsd:positiveInteger",
            f"    career:recommendationScore \"{format_decimal(item.score)}\"^^xsd:decimal",
        ]
        if description:
            predicates.append(
                f"    career:recommendationDescription \"{_ttl_escape(description)}\"@{lang}"
            )
        predicates.append(
            f"    career:recommendationReason \"{_ttl_escape(reason)}\"@{lang}"
        )
        lines.append(f"{rec_iri} a career:Recommendation ;")
        lines.append(" ;\n".join(predicates) + " .")
        lines.append(f"<{user}> career:hasRecommendation {rec_iri} .")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _local_suffix(iri: str) -> str:
    local = iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in local)[:40] or "occupation"
