from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from ontorag.index import build_index
from ontorag.output import recommendations_ttl
from ontorag.pipeline import Pipeline
from ontorag.reasoning import SqlReasoner
from tests.fixtures import write_fixture


class PipelineSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "tiny.sqlite"
        build_index(
            abox=cls.abox,
            overlay=cls.overlay,
            index=cls.index_path,
            verbose=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_end_to_end_sql_fallback(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            temp_dir=self.tmp.name,
        ) as pipeline:
            profile = pipeline.profile_from_text(
                "Saya suka data dan pemrograman. Saya lulusan S1 dan job zone 4."
            )
            self.assertEqual(profile.education_local, "S1")
            self.assertEqual(profile.max_job_zone, 4)
            recommendations = pipeline.recommend(profile, top_k=3)
            ttl = recommendations_ttl(profile, recommendations, pipeline.ontology)
        self.assertIn("career:Recommendation", ttl)
        self.assertIn("career:recommendationScore", ttl)
        self.assertIn("career:recommendationDescription", ttl)
        self.assertEqual(len(recommendations), 1)
        recommendation = recommendations[0]
        self.assertEqual(recommendation.title_en, "Data Scientist")
        self.assertEqual(recommendation.description_en, "Analyze data and build models.")
        self.assertEqual(recommendation.tier, "Eligible")
        self.assertGreater(recommendation.score, 0.0)
        self.assertIn("holland", recommendation.component_scores)
        self.assertIn("element", recommendation.component_scores)
        self.assertTrue(any(item.get("kind") == "education" for item in recommendation.evidence))

    def test_sql_reasoner_marks_sql_candidates_eligible(self) -> None:
        rows = [{"iri": "urn:occupation:one"}, {"iri": "urn:occupation:two"}]
        flags = SqlReasoner("Eligible").infer(None, rows, None)  # type: ignore[arg-type]
        self.assertEqual(set(flags), {"urn:occupation:one", "urn:occupation:two"})
        self.assertTrue(all(item["tier"] == "Eligible" for item in flags.values()))
        self.assertTrue(all(not item["eligible_strong"] for item in flags.values()))


@unittest.skipUnless(
    importlib.util.find_spec("owlready2") is not None and shutil.which("java"),
    "owlready2 and a Java runtime are required for the Pellet test",
)
class PipelinePelletTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "tiny.sqlite"
        build_index(
            abox=cls.abox,
            overlay=cls.overlay,
            index=cls.index_path,
            verbose=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_pellet_swrl_tier(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="pellet",
            temp_dir=self.tmp.name,
        ) as pipeline:
            profile = pipeline.profile_from_text(
                "Saya suka data dan pemrograman. Saya lulusan S1 dan job zone 4."
            )
            recommendations = pipeline.recommend(profile, top_k=3)
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0].tier, "EligibleStrong")


if __name__ == "__main__":
    unittest.main()
