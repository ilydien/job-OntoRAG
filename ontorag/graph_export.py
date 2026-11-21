"""Export the SPARQL-facing graph derived from the SQLite index.

Jena/TDB2 should not receive the complete O*NET ABox for this prototype.  The
ontology search path only needs occupation -> element-rating -> element and
occupation -> related-occupation edges.  This module streams exactly those
triples from the index into N-Triples so they can be loaded into Fuseki or
TDB2 without loading the raw 600 MB ABox.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from . import config


def _iri(value: str) -> str:
    return f"<{value}>"


def _literal(value: object) -> str:
    return f"\"{float(value):.10g}\"^^<{config.XSD}double>"


def export_graph(
    index_path: str | Path = config.DEFAULT_INDEX,
    out_path: str | Path = config.DATA_DIR / "ontorag_derived.nt",
    verbose: bool = True,
) -> Path:
    """Write the derived RDF graph as N-Triples.

    The graph contains:

    - ``rdf:type`` occupation triples;
    - ``career:hasElementRating`` / ``career:ratedElement`` /
      ``career:normalizedValue`` triples;
    - ``career:relatedOccupation`` edges.

    It intentionally does not contain descriptions, tasks, labels, or the raw
    ABox.  Those remain in SQLite and are used by the output layer.
    """

    source = Path(index_path)
    target = Path(out_path)
    if not source.exists():
        raise FileNotFoundError(
            f"index not found: {source}. Run the build-index command first."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    counts = {"occupations": 0, "ratings": 0, "related": 0}

    conn = sqlite3.connect(str(source))
    try:
        conn.execute("PRAGMA query_only=ON")
        with tmp.open("w", encoding="utf-8", newline="\n") as out:
            type_predicate = _iri(config.RDF + "type")
            occupation_class = _iri(config.ONET + "Occupation")
            has_element = _iri(config.CAREER + "hasElementRating")
            rated_element = _iri(config.CAREER + "ratedElement")
            normalized_value = _iri(config.CAREER + "normalizedValue")
            related = _iri(config.CAREER + "relatedOccupation")

            for row in conn.execute("SELECT iri FROM occupations ORDER BY iri"):
                occupation = str(row[0])
                out.write(f"{_iri(occupation)} {type_predicate} {occupation_class} .\n")
                counts["occupations"] += 1

            for row in conn.execute(
                "SELECT occupation_iri, rating_iri, element_iri, norm_value "
                "FROM occupation_ratings "
                "WHERE element_iri IS NOT NULL AND norm_value IS NOT NULL "
                "ORDER BY occupation_iri, rating_iri"
            ):
                occupation, rating, element, value = row
                if not occupation or not rating or not element:
                    continue
                out.write(f"{_iri(str(occupation))} {has_element} {_iri(str(rating))} .\n")
                out.write(f"{_iri(str(rating))} {rated_element} {_iri(str(element))} .\n")
                out.write(f"{_iri(str(rating))} {normalized_value} {_literal(value)} .\n")
                counts["ratings"] += 1

            for row in conn.execute(
                "SELECT occupation_iri, related_iri FROM occupation_related "
                "ORDER BY occupation_iri, related_iri"
            ):
                occupation, related_iri = row
                if not occupation or not related_iri:
                    continue
                out.write(f"{_iri(str(occupation))} {related} {_iri(str(related_iri))} .\n")
                counts["related"] += 1
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    os.replace(tmp, target)
    if verbose:
        print(
            f"Derived graph ready: {target} "
            f"({counts['occupations']:,} occupations, "
            f"{counts['ratings']:,} element ratings, "
            f"{counts['related']:,} related edges)",
            file=sys.stderr,
        )
    return target
