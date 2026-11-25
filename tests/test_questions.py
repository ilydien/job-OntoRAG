from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ontorag.index import build_index
from ontorag.policy import load_index_policy, load_ranking_policy
from ontorag.questions import QuestionRouter
from ontorag.query_engine import Index
from tests.fixtures import write_fixture

IRI = "https://example.org/occupation/data-scientist"

EXAMPLES = {
    "tasks_core": "Apa 5 tugas inti pekerjaan Data Scientist?",
    "tasks_relevant": "Apa tugas paling relevan untuk Data Scientist?",
    "task_frequency": "Seberapa sering tugas itu dilakukan?",
    "task_dwa": "Apa DWA dari pekerjaan Data Scientist?",
    "education_min": "Apa pendidikan minimum pekerjaan Data Scientist?",
    "job_zone": "Berapa job zone pekerjaan Data Scientist?",
    "education_distribution": "Bagaimana distribusi pendidikan Data Scientist?",
    "experience": "Pengalaman kerja apa yang dibutuhkan?",
    "training": "Apakah ada pelatihan atau magang?",
    "skills": "Apa skill penting untuk Data Scientist?",
    "knowledge": "Pengetahuan apa yang dibutuhkan?",
    "abilities": "Kemampuan apa yang penting?",
    "work_activities": "Aktivitas kerja apa saja?",
    "level_importance": "Berapa level dan importance persyaratannya?",
    "context_indoor_outdoor": "Apakah kerjanya di dalam atau luar ruangan?",
    "context_physical": "Bagaimana tuntutan fisiknya?",
    "context_teamwork": "Apakah butuh kerja tim?",
    "description": "Apa deskripsi pekerjaan Data Scientist?",
    "tasks_and_titles": "Apa tugas representatif dan jabatan terkait?",
    "why_recommended": "Mengapa Data Scientist direkomendasikan?",
    "score_components": "Apa komponen skor dan evidence-nya?",
}


class QuestionRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        abox, overlay = write_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "tiny.sqlite"
        build_index(abox=abox, overlay=overlay, index=cls.index_path, verbose=False)
        cls.policy = load_ranking_policy()
        cls.index_policy = load_index_policy()
        try:
            cls.index = Index(cls.index_path)
            cls.router = QuestionRouter(
                cls.index, cls.policy, cls.index_policy
            )
        except Exception:
            cls.index = None
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.index is not None:
            cls.index.close()
        cls.tmp.cleanup()

    def test_classifies_every_intent(self) -> None:
        for expected, text in EXAMPLES.items():
            with self.subTest(intent=expected):
                intent = self.router.classify(text)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.key, expected)

    def test_interest_text_is_not_a_question(self) -> None:
        text = "Saya suka menganalisis data dan membangun model"
        self.assertIsNone(self.router.classify(text))
        self.assertEqual(self.router.decide(text)["mode"], "recommend")

    def test_lexicon_loads_threshold_and_stopwords(self) -> None:
        # Guards the TTL parse: a bare decimal silently becomes "0".
        self.assertGreater(self.router.lexicon.similarity_threshold, 0.1)
        self.assertIn("pekerjaan", self.router.lexicon.stopwords)

    def test_similarity_fallback_matches_typo_and_morphology(self) -> None:
        for expected, text in {
            "education_min": "Apa pendidkan minimum pekerjaan Data Scientist?",
            "skills": "Apa ketrampilan penting untuk Data Scientist?",
        }.items():
            with self.subTest(intent=expected):
                intent, match = self.router._classify_scored(text)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.key, expected)
                self.assertEqual(match, "similar")

    def test_interest_text_never_uses_similarity(self) -> None:
        # No question mark or question word: the fallback must not run.
        intent, match = self.router._classify_scored("saya suka mengajar anak")
        self.assertIsNone(intent)
        self.assertIsNone(match)

    def test_unrelated_question_gets_no_intent(self) -> None:
        decision = self.router.decide("Apakah besok akan hujan di kota ini?")
        self.assertEqual(decision["mode"], "recommend")

    def test_decide_reports_match_kind(self) -> None:
        keyword = self.router.decide("Apa pendidikan minimum pekerjaan Data Scientist?")
        self.assertEqual(keyword["match"], "keyword")
        similar = self.router.decide("Apa pendidkan minimum pekerjaan Data Scientist?")
        self.assertEqual(similar["mode"], "answer")
        self.assertEqual(similar["intent"], "education_min")
        self.assertEqual(similar["match"], "similar")

    def test_resolves_occupation_name(self) -> None:
        self.assertEqual(self.router.search("data scientist")[0]["iri"], IRI)
        decision = self.router.decide("Apa pendidikan minimum pekerjaan Data Scientist?")
        self.assertEqual(decision["mode"], "answer")
        self.assertEqual(decision["intent"], "education_min")
        self.assertEqual(decision["occupation"]["iri"], IRI)

    def test_question_without_known_occupation_asks_for_name(self) -> None:
        decision = self.router.decide("Apa pendidikan minimum pekerjaan Zzzqqq?")
        self.assertEqual(decision["mode"], "need_occupation")

    def test_explicit_occupation_skips_name_matching(self) -> None:
        decision = self.router.decide(
            "Apa pendidikan minimum pekerjaan ini?", occupation=IRI
        )
        self.assertEqual(decision["mode"], "answer")
        self.assertEqual(decision["occupation"]["iri"], IRI)

    def test_answers_carry_index_data(self) -> None:
        occupation = {"iri": IRI, "title": "Data Scientist"}
        education = self.router.answer("education_min", occupation)
        self.assertEqual(education["heading"], "Pendidikan minimum")
        self.assertIn("S1", education["summary"])

        zone = self.router.answer("job_zone", occupation)
        self.assertTrue(any(fact["value"] == "4" for fact in zone["facts"]))

        tasks = self.router.answer("tasks_core", occupation)
        self.assertEqual(tasks["items"][0]["title"], "Build data models")


class _StubIndex:
    """Catalog stub so name-resolution tests need no SQLite build."""

    def __init__(self, rows) -> None:
        self._rows = rows

    def occupation_catalog(self):
        return self._rows

    def summary(self, iri):
        return next((row for row in self._rows if row["iri"] == iri), None)


def _row(iri: str, title_id: str, soc: str = "00-0000.00") -> dict:
    return {"iri": iri, "soc": soc, "title_id": title_id, "title_en": title_id}


CATALOG = [
    _row("occ:data", "Ilmuwan Data", "15-2051.00"),
    _row("occ:nurse-icu", "Perawat ICU", "29-1141.01"),
    _row("occ:nurse-child", "Perawat Anak", "29-1141.02"),
    _row("occ:vet", "Dokter Hewan", "29-1131.00"),
]


class OccupationSuggestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QuestionRouter(_StubIndex(CATALOG), None)

    def test_exact_name_offers_no_suggestions(self) -> None:
        decision = self.router.decide("Apa pendidikan minimum pekerjaan Ilmuwan Data?")
        self.assertEqual(decision["mode"], "answer")
        self.assertEqual(decision["occupation_match"], "exact")
        self.assertFalse(decision.get("suggestions"))

    def test_typo_name_is_offered_as_a_suggestion(self) -> None:
        decision = self.router.decide("Apa pendidikan minimum pekerjaan Ilmuwan Dta?")
        self.assertEqual(decision["mode"], "answer")
        self.assertEqual(decision["occupation_match"], "fuzzy")
        self.assertEqual(decision["occupation"]["iri"], "occ:data")
        self.assertIn("occ:data", [item["iri"] for item in decision["suggestions"]])

    def test_ambiguous_name_asks_the_user_to_choose(self) -> None:
        decision = self.router.decide("Apa pendidikan minimum pekerjaan Perawat?")
        self.assertEqual(decision["mode"], "disambiguate")
        self.assertIsNone(decision.get("occupation"))
        self.assertEqual(decision["occupation_match"], "ambiguous")
        self.assertGreaterEqual(len(decision["suggestions"]), 2)

    def test_explicit_choice_keeps_suggestions_for_highlighting(self) -> None:
        decision = self.router.decide(
            "Apa pendidikan minimum pekerjaan Perawat?", occupation="occ:nurse-icu"
        )
        self.assertEqual(decision["mode"], "answer")
        self.assertEqual(decision["occupation_match"], "explicit")
        self.assertEqual(decision["occupation"]["iri"], "occ:nurse-icu")
        self.assertIn("occ:nurse-icu", [item["iri"] for item in decision["suggestions"]])

    def test_suggestions_are_capped(self) -> None:
        rows = [_row(f"occ:nurse-{index}", f"Perawat {index}") for index in range(9)]
        router = QuestionRouter(_StubIndex(rows), None)
        decision = router.decide("Apa pendidikan minimum pekerjaan Perawat?")
        self.assertEqual(len(decision["suggestions"]), QuestionRouter.SUGGESTION_LIMIT)


if __name__ == "__main__":
    unittest.main()
