from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ontorag.embeddings import (
    CardLimits,
    build_card_text,
    build_embeddings,
    collect_cards,
    unpack_vector,
)
from ontorag.index import build_index
from ontorag.query_engine import Index
from tests.fake_backend import KeywordBackend, MismatchedBackend
from tests.fixtures import write_semantic_fixture

DATA_IRI = "https://example.org/occupation/data-scientist"
FIRE_IRI = "https://example.org/occupation/fire-inspector"


class CardBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_semantic_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "cards.sqlite"
        build_index(abox=cls.abox, overlay=cls.overlay, index=cls.index_path, verbose=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_card_contains_structured_signals(self) -> None:
        with Index(self.index_path) as index:
            cards = collect_cards(index)
        text = cards[DATA_IRI]
        self.assertIn("Data Scientist", text)
        self.assertIn("Analyze data and build statistical models", text)
        self.assertIn("Build statistical models from data", text)
        self.assertIn("Programming", text)
        self.assertIn("Investigative", text)
        self.assertIn("Typical tasks:", text)
        self.assertIn("Knowledge, skills, abilities, and activities:", text)
        self.assertIn("Interests (RIASEC):", text)

    def test_card_limits_are_respected(self) -> None:
        with Index(self.index_path) as index:
            summary = index.summary(DATA_IRI)
            limits = CardLimits(max_tasks=0, max_elements=1, max_job_titles=0)
            text = build_card_text(
                summary,
                index.tasks(DATA_IRI, 5),
                index.elements_for(DATA_IRI),
                index.job_titles(DATA_IRI, 5),
                {},
                limits=limits,
            )
        self.assertNotIn("Typical tasks:", text)
        self.assertNotIn("Also known as:", text)
        self.assertIn("Programming", text)

    def test_card_is_deterministic(self) -> None:
        with Index(self.index_path) as index:
            first = collect_cards(index)
        with Index(self.index_path) as index:
            second = collect_cards(index)
        self.assertEqual(first, second)
        self.assertEqual(set(first), {DATA_IRI, FIRE_IRI})


class EmbeddingBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_semantic_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "embeddings.sqlite"
        build_index(abox=cls.abox, overlay=cls.overlay, index=cls.index_path, verbose=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_build_stores_normalised_vectors_and_meta(self) -> None:
        meta = build_embeddings(
            self.index_path, backend=KeywordBackend(), verbose=False
        )
        self.assertEqual(meta["model"], "fake/keyword")
        self.assertEqual(meta["dim"], "4")
        self.assertEqual(meta["count"], "2")
        self.assertEqual(meta["card_version"], "1")

        with Index(self.index_path) as index:
            rows = index.embedding_rows()
            stored = index.embedding_meta()
        self.assertEqual(len(rows), 2)
        self.assertEqual(stored["model"], "fake/keyword")
        for row in rows:
            vector = unpack_vector(row["vector"])
            self.assertEqual(len(vector), 4)
            self.assertAlmostEqual(sum(value * value for value in vector), 1.0, places=5)
            self.assertTrue(row["card_hash"])

    def test_build_is_idempotent_without_rebuild(self) -> None:
        build_embeddings(self.index_path, backend=KeywordBackend(), verbose=False)
        quiet = KeywordBackend()
        meta = build_embeddings(self.index_path, backend=quiet, verbose=False)
        self.assertEqual(quiet.encoded, 0)
        self.assertEqual(meta["model"], "fake/keyword")

        forced = KeywordBackend()
        build_embeddings(
            self.index_path, backend=forced, rebuild=True, verbose=False
        )
        self.assertEqual(forced.encoded, 2)

    def test_rebuild_detects_model_change(self) -> None:
        build_embeddings(self.index_path, backend=KeywordBackend(), verbose=False)
        build_embeddings(
            self.index_path,
            backend=MismatchedBackend(),
            rebuild=True,
            verbose=False,
        )
        with Index(self.index_path) as index:
            self.assertEqual(index.embedding_meta()["model"], "fake/other-model")


if __name__ == "__main__":
    unittest.main()
