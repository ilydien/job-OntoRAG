from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ontorag.extraction import Profile
from ontorag.index import build_index
from ontorag.policy import load_ranking_policy
from ontorag.query_engine import Index
from tests.fixtures import write_fixture


class TinyIndexTests(unittest.TestCase):
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
        cls.policy = load_ranking_policy()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_index_schema_and_counts(self) -> None:
        conn = sqlite3.connect(self.index_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM occupations").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM occupation_ratings").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM elements").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM occupation_tasks").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM occupation_job_titles").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM occupation_related").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM occupation_fts").fetchone()[0], 1)
        finally:
            conn.close()

    def test_candidates_apply_education_and_job_zone_filters(self) -> None:
        profile = Profile(
            user_iri="urn:test:user",
            education_local="S1",
            education_order=6,
            max_job_zone=4,
        )
        with Index(self.index_path) as index:
            candidates = index.candidates(profile, self.policy, require_complete=True, limit=10)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title_en"], "Data Scientist")
        self.assertEqual(candidates[0]["job_zone"], 4)

        too_low = Profile(
            user_iri="urn:test:user",
            education_local="D3",
            education_order=5,
            max_job_zone=4,
        )
        with Index(self.index_path) as index:
            self.assertEqual(
                index.candidates(too_low, self.policy, require_complete=True, limit=10),
                [],
            )

    def test_fts_and_evidence_queries(self) -> None:
        with Index(self.index_path) as index:
            scores = index.lexical_scores("data models", 10, 2)
            self.assertTrue(scores)
            iri = next(iter(scores))
            summary = index.summary(iri)
            self.assertEqual(summary["title_en"], "Data Scientist")
            self.assertEqual(summary["education_local"], "S1")
            tasks = index.tasks(iri, 5)
            self.assertEqual(tasks[0]["task_en"], "Build data models")
            titles = index.job_titles(iri, 5)
            self.assertEqual(titles[0]["title_en"], "Data Scientist")
            related = index.related(iri, 5)
            self.assertEqual(related[0]["related_iri"], "https://example.org/occupation/data-analyst")
            elements = index.elements_for(iri)
            self.assertEqual(elements[0]["element_name_en"], "Programming")
            self.assertEqual(len(index.element_catalog_rows()), 1)

    def test_elements_for_many_batches_and_filters(self) -> None:
        with Index(self.index_path) as index:
            iri = next(iter(index.lexical_scores("data models", 10, 2)))
            batched = index.elements_for_many([iri, "urn:missing"])
            self.assertEqual(batched[iri][0]["element_name_en"], "Programming")
            self.assertEqual(batched["urn:missing"], [])
            filtered = index.elements_for_many(
                [iri], element_iris=["https://example.org/element/programming"]
            )
            self.assertEqual(len(filtered[iri]), 1)
            none_match = index.elements_for_many(
                [iri], element_iris=["https://example.org/element/absent"]
            )
            self.assertEqual(none_match[iri], [])

    def test_meta_records_provenance(self) -> None:
        with Index(self.index_path) as index:
            meta = index.meta()
        self.assertEqual(meta["occupations"], "1")
        self.assertEqual(meta["ratings"], "1")
        self.assertEqual(meta["parsed_ratings"], "2")
        self.assertIn("KnowledgeRating", meta["indexed_rating_types"])


if __name__ == "__main__":
    unittest.main()
