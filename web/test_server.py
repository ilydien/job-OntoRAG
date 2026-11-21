from __future__ import annotations

import asyncio
import unittest

from web import server


class _Profile:
    user_iri = "career:test"
    language = "id"
    education_local = "S1"
    max_job_zone = 4
    holland: dict = {}
    element_labels: dict = {}
    elements: dict = {}


class _Index:
    def meta(self) -> dict:
        return {"occupations": "3"}


class _Ontology:
    def education_levels(self) -> list:
        return []


class _Policy:
    score_precision = 4


class _Reasoner:
    pass


class _Pipeline:
    retrieval_mode = "ontology"
    index = _Index()
    ontology = _Ontology()
    policy = _Policy()
    reasoner = _Reasoner()

    def profile_from_text(self, text: str, **kwargs):
        return _Profile()

    def recommend(self, profile, top_k=None) -> list:
        return []


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        server.app.state.pipeline = _Pipeline()

    def test_meta(self) -> None:
        data = asyncio.run(server.meta())
        self.assertEqual(data["occupations"], 3)
        self.assertEqual(data["retrieval"], "ontology")

    def test_recommend_payload(self) -> None:
        data = asyncio.run(
            server.recommend(server.RecommendRequest(text="Saya suka data"))
        )
        self.assertEqual(data["recommendations"], [])
        self.assertEqual(data["meta"]["retrieval"], "ontology")
        self.assertIn("elapsed_ms", data["meta"])
        self.assertEqual(data["profile"]["education_level"], "S1")


if __name__ == "__main__":
    unittest.main()