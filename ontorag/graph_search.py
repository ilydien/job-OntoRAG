"""SPARQL retrieval over the O*NET ontology.

The dense (embedding) and sparse (BM25) retrievers score the profile *text*.
This retriever instead matches the profile's ontology individuals - the O*NET
*element* IRIs the lexicon extracted - against the occupations that rate them.
The relevant slice of the ontology is materialised as RDF and answered with
SPARQL:

* a direct match: occupation -> rating -> element -> normalized value, and
* one bounded hop along the ontology's ``relatedOccupation`` edges, so an
  occupation that shares an element with a matched neighbour still scores.
  That traversal is the part the text retrievers cannot express.

The graph is assembled from the generated SQLite index, never the raw ABox,
which is far too large to load into a triplestore per request.  The two
branches run as separate queries: rdflib evaluates the combined JOIN roughly
six times slower than the sum of the parts.
"""

from __future__ import annotations

import importlib.util
from typing import Dict, Mapping, Optional, Sequence

from . import config

CAREER = config.CAREER
ONET = config.ONET
XSD = config.XSD

# One hop over the related-occupation graph adds this fraction of a seed
# occupation's direct alignment to its neighbours.  Kept small: high-degree
# medical hubs have ~20 related occupations, so a large decay lets their summed
# neighbour evidence swamp the direct element signal.
# shortcut: single hop, fixed decay; widen or retune if recall work continues.
RELATED_DECAY = 0.05

_PREFIXES = (
    f"PREFIX : <{ONET}>\n"
    f"PREFIX career: <{CAREER}>\n"
    f"PREFIX xsd: <{XSD}>\n"
)

# Direct ontology match: the profile's element individuals against every
# occupation that rates them, weighted by the profile's preference.
_DIRECT_QUERY_TEMPLATE = _PREFIXES + """
SELECT ?occupation (SUM(?preference * ?value) AS ?score)
WHERE {
    VALUES (?element ?preference) { %(values)s }
    ?occupation career:hasElementRating ?rating .
    ?rating career:ratedElement ?element ;
            career:normalizedValue ?value .
}
GROUP BY ?occupation
ORDER BY DESC(?score)
LIMIT %(limit)d
"""

# One hop along relatedOccupation from every directly-matched seed.  Seeds are
# bound as VALUES so the traversal does not re-scan the element ratings.
_HOP_QUERY_TEMPLATE = _PREFIXES + """
SELECT ?occupation (SUM(?seedScore * %(decay)s) AS ?score)
WHERE {
    VALUES (?seed ?seedScore) { %(seeds)s }
    ?seed career:relatedOccupation ?occupation .
}
GROUP BY ?occupation
ORDER BY DESC(?score)
LIMIT %(limit)d
"""

_DEFAULT_LIMIT = 100000


class GraphSearchUnavailable(RuntimeError):
    """rdflib is not installed, so the SPARQL retriever cannot run."""


def ontology_available() -> bool:
    """True when the SPARQL engine (rdflib) is importable."""

    return importlib.util.find_spec("rdflib") is not None


def _require_rdflib():
    if not ontology_available():  # pragma: no cover - depends on the environment
        raise GraphSearchUnavailable(
            "rdflib is required for ontology (SPARQL) retrieval"
        )
    import rdflib

    return rdflib


def _values_block(weights: Mapping[str, float]) -> str:
    # xsd:double literals ("...e0") so the multiplication stays float*float;
    # mixing xsd:decimal VALUES with xsd:double ratings raises in rdflib.
    return " ".join(
        f"(<{iri}> {float(weight):.6f}e0)" for iri, weight in weights.items() if iri
    )


def _seed_values_block(scores: Mapping[str, float]) -> str:
    return " ".join(
        f"(<{iri}> {float(score):.6f}e0)" for iri, score in scores.items() if iri
    )


def scores(
    element_rows: Mapping[str, Sequence[Mapping[str, object]]],
    related_rows: Mapping[str, Sequence[str]],
    element_weights: Mapping[str, float],
    limit: Optional[int] = None,
) -> Dict[str, float]:
    """Return SPARQL ontology-alignment scores keyed by occupation IRI.

    ``element_rows`` maps an occupation IRI to its rating rows for the profile's
    element IRIs (the same shape :meth:`Index.elements_for_many` returns), and
    ``related_rows`` maps an occupation IRI to related-occupation IRIs.
    """

    if not element_weights:
        return {}
    rdflib = _require_rdflib()
    career = rdflib.Namespace(CAREER)
    graph = rdflib.Graph()

    candidate_iris = set(element_rows)
    for occupation, rows in element_rows.items():
        for row in rows:
            element = str(row.get("element_iri") or "")
            value = row.get("norm_value")
            if not element or value is None:
                continue
            rating = rdflib.BNode()
            graph.add((rdflib.URIRef(occupation), career.hasElementRating, rating))
            graph.add((rating, career.ratedElement, rdflib.URIRef(element)))
            graph.add((rating, career.normalizedValue, rdflib.Literal(float(value))))

    for occupation, related in related_rows.items():
        for related_iri in related:
            if related_iri in candidate_iris:
                graph.add(
                    (
                        rdflib.URIRef(occupation),
                        career.relatedOccupation,
                        rdflib.URIRef(related_iri),
                    )
                )

    cap = int(limit) if limit is not None else _DEFAULT_LIMIT
    values = _values_block(element_weights)
    if not values:
        return {}
    direct = {
        str(row[0]): float(row[1])
        for row in graph.query(
            _DIRECT_QUERY_TEMPLATE % {"values": values, "limit": cap}
        )
    }
    if not direct or RELATED_DECAY <= 0:
        return direct

    seeds = _seed_values_block(direct)
    hop = {
        str(row[0]): float(row[1])
        for row in graph.query(
            _HOP_QUERY_TEMPLATE
            % {"seeds": seeds, "decay": f"{RELATED_DECAY:.2f}e0", "limit": cap}
        )
    }
    for occupation, bonus in hop.items():
        direct[occupation] = direct.get(occupation, 0.0) + bonus
    return direct


def sparql_query(element_weights: Mapping[str, float], limit: Optional[int] = None) -> str:
    """The direct-match SPARQL query issued for a profile (for audit/tests)."""

    return _DIRECT_QUERY_TEMPLATE % {
        "values": _values_block(element_weights),
        "limit": int(limit) if limit is not None else _DEFAULT_LIMIT,
    }


def related_sparql_query(seed_scores: Mapping[str, float], limit: Optional[int] = None) -> str:
    """The related-occupation hop query issued for a profile (for audit/tests)."""

    return _HOP_QUERY_TEMPLATE % {
        "seeds": _seed_values_block(seed_scores),
        "decay": f"{RELATED_DECAY:.2f}e0",
        "limit": int(limit) if limit is not None else _DEFAULT_LIMIT,
    }
