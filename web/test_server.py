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
    skill_levels: dict = {}
    skill_labels: dict = {}


class _Index:
    _CATALOG = [
        {
            "iri": "occ:data",
            "soc": "15-2051.00",
            "title_en": "Data Scientist",
            "title_id": "Ilmuwan Data",
        },
        {
            "iri": "occ:nurse-icu",
            "soc": "29-1141.01",
            "title_en": "ICU Nurse",
            "title_id": "Perawat ICU",
        },
        {
            "iri": "occ:nurse-child",
            "soc": "29-1141.02",
            "title_en": "Pediatric Nurse",
            "title_id": "Perawat Anak",
        },
    ]

    def meta(self) -> dict:
        return {"occupations": "3"}

    def summary(self, occupation_iri: str):
        row = next(
            (item for item in self._CATALOG if item["iri"] == occupation_iri), None
        )
        return row or self._CATALOG[0]

    def occupation_catalog(self) -> list:
        return self._CATALOG

    def requirements_for(self, occupation_iri, categories, language="id"):
        return {
            "education": {"local": "S1", "label": "Gelar Sarjana", "order": 6},
            "job_zone": {"value": 4, "name": "Persiapan tinggi"},
            "requirements": [],
        }


class _Ontology:
    def education_levels(self) -> list:
        return []


class _Policy:
    score_precision = 4
    requirement_categories: list = []
    profile_groups: list = []


class _Reasoner:
    pass


class _Pipeline:
    retrieval_mode = "ontology"
    index = _Index()
    ontology = _Ontology()
    policy = _Policy()
    index_policy = None
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

    def test_ask_interest_falls_back_to_recommend(self) -> None:
        data = asyncio.run(server.ask(server.AskRequest(text="Saya suka data")))
        self.assertEqual(data["mode"], "recommend")
        self.assertEqual(data["recommendations"], [])

    def test_ask_question_answers_from_index(self) -> None:
        data = asyncio.run(
            server.ask(
                server.AskRequest(
                    text="Apa pendidikan minimum pekerjaan Ilmuwan Data?"
                )
            )
        )
        self.assertEqual(data["mode"], "answer")
        self.assertEqual(data["intent"], "education_min")
        self.assertEqual(data["occupation"]["soc"], "15-2051.00")
        self.assertIn("Gelar Sarjana", data["answer"]["summary"])

    def test_occupation_search(self) -> None:
        data = asyncio.run(server.occupation_search(q="ilmuwan data"))
        self.assertEqual(data["items"][0]["soc"], "15-2051.00")

    def test_ask_ambiguous_name_returns_suggestions(self) -> None:
        data = asyncio.run(
            server.ask(server.AskRequest(text="Apa pendidikan minimum pekerjaan Perawat?"))
        )
        self.assertEqual(data["mode"], "disambiguate")
        self.assertEqual(data["occupation_match"], "ambiguous")
        ir_is = {item["iri"] for item in data["suggestions"]}
        self.assertEqual(ir_is, {"occ:nurse-icu", "occ:nurse-child"})

    def test_ask_explicit_choice_keeps_suggestions(self) -> None:
        data = asyncio.run(
            server.ask(
                server.AskRequest(
                    text="Apa pendidikan minimum pekerjaan Perawat?",
                    occupation="occ:nurse-icu",
                )
            )
        )
        self.assertEqual(data["mode"], "answer")
        self.assertEqual(data["occupation_match"], "explicit")
        self.assertEqual(data["occupation"]["iri"], "occ:nurse-icu")
        self.assertIn("occ:nurse-icu", [item["iri"] for item in data["suggestions"]])

    def test_ask_exact_name_has_no_suggestions(self) -> None:
        data = asyncio.run(
            server.ask(
                server.AskRequest(text="Apa pendidikan minimum pekerjaan Ilmuwan Data?")
            )
        )
        self.assertEqual(data["occupation_match"], "exact")
        self.assertEqual(data["suggestions"], [])


if __name__ == "__main__":
    unittest.main()