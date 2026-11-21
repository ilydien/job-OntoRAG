"""HTTP SPARQL client for the Jena/Fuseki retrieval path.

The Jena path is intentionally narrow: Fuseki stores the derived graph exported
by :mod:`ontorag.graph_export`, and this client executes the same two SPARQL
queries used by the in-memory rdflib fallback.  It does not load or query the
raw O*NET ABox.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, Mapping, Optional, Sequence

from .graph_search import related_sparql_query, sparql_query


class JenaUnavailable(RuntimeError):
    """Fuseki is configured but cannot be queried."""


class JenaStore:
    def __init__(self, endpoint: str, timeout: int = 30) -> None:
        self.endpoint = str(endpoint).strip()
        self.timeout = int(timeout)
        if not self.endpoint:
            raise ValueError("Jena/Fuseki endpoint must not be empty")

    def query(self, sparql: str) -> list[dict[str, str]]:
        payload = sparql.encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/sparql-query; charset=utf-8",
                "Accept": "application/sparql-results+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise JenaUnavailable(f"could not query Fuseki at {self.endpoint}: {exc}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JenaUnavailable(f"invalid SPARQL JSON response from {self.endpoint}") from exc
        bindings = data.get("results", {}).get("bindings", [])
        if not isinstance(bindings, list):
            raise JenaUnavailable(f"unexpected SPARQL response from {self.endpoint}")
        rows: list[dict[str, str]] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            row: dict[str, str] = {}
            for key, value in binding.items():
                if isinstance(value, dict) and "value" in value:
                    row[str(key)] = str(value["value"])
            rows.append(row)
        return rows

    def scores(
        self,
        element_weights: Mapping[str, float],
        limit: Optional[int] = None,
    ) -> Dict[str, float]:
        """Return direct + one-hop ontology scores from Fuseki."""

        if not element_weights:
            return {}
        direct_rows = self.query(sparql_query(element_weights, limit))
        direct = {
            row["occupation"]: float(row["score"])
            for row in direct_rows
            if row.get("occupation") and row.get("score") is not None
        }
        if not direct:
            return {}
        hop_rows = self.query(related_sparql_query(direct, limit))
        for row in hop_rows:
            occupation = row.get("occupation")
            score = row.get("score")
            if not occupation or score is None:
                continue
            direct[occupation] = direct.get(occupation, 0.0) + float(score)
        return direct
