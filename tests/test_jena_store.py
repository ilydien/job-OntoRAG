from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ontorag.jena_store import JenaStore, JenaUnavailable


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class JenaStoreTests(unittest.TestCase):
    def test_scores_merge_direct_and_hop(self) -> None:
        direct = {
            "head": {"vars": ["occupation", "score"]},
            "results": {
                "bindings": [
                    {"occupation": {"value": "urn:occ:a"}, "score": {"value": "0.9"}}
                ]
            },
        }
        hop = {
            "head": {"vars": ["occupation", "score"]},
            "results": {
                "bindings": [
                    {"occupation": {"value": "urn:occ:b"}, "score": {"value": "0.045"}}
                ]
            },
        }
        store = JenaStore("http://localhost:3030/onet/sparql")
        with patch(
            "ontorag.jena_store.urllib.request.urlopen",
            side_effect=[_Response(direct), _Response(hop)],
        ):
            scores = store.scores({"urn:element:programming": 1.0}, limit=10)
        self.assertAlmostEqual(scores["urn:occ:a"], 0.9)
        self.assertAlmostEqual(scores["urn:occ:b"], 0.045)

    def test_unreachable_endpoint_is_reported(self) -> None:
        from urllib.error import URLError

        store = JenaStore("http://localhost:3030/onet/sparql")
        with patch(
            "ontorag.jena_store.urllib.request.urlopen",
            side_effect=URLError("connection refused"),
        ):
            with self.assertRaises(JenaUnavailable):
                store.query("SELECT * WHERE { ?s ?p ?o } LIMIT 1")


if __name__ == "__main__":
    unittest.main()
