from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ontorag.embeddings import build_embeddings
from ontorag.extraction import Profile
from ontorag.index import build_index
from ontorag.pipeline import Pipeline
from ontorag.query_engine import Index
from ontorag.retrieval import EmbeddingIndexMismatch, SemanticRetriever
from tests.fake_backend import KeywordBackend, MismatchedBackend
from tests.fixtures import write_semantic_fixture

DATA_IRI = "https://example.org/occupation/data-scientist"
FIRE_IRI = "https://example.org/occupation/fire-inspector"


class SemanticRetrieverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_semantic_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "retrieval.sqlite"
        build_index(abox=cls.abox, overlay=cls.overlay, index=cls.index_path, verbose=False)
        build_embeddings(cls.index_path, backend=KeywordBackend(), verbose=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_scores_rank_semantically_matching_occupation(self) -> None:
        with Index(self.index_path) as index:
            retriever = SemanticRetriever(index, KeywordBackend())
            scores = retriever.scores("Saya menganalisis data dan membuat model statistik")
        self.assertEqual(set(scores), {DATA_IRI, FIRE_IRI})
        self.assertGreater(scores[DATA_IRI], scores[FIRE_IRI])

        with Index(self.index_path) as index:
            retriever = SemanticRetriever(index, KeywordBackend())
            fire = retriever.scores("Inspect buildings for fire safety")
        self.assertGreater(fire[FIRE_IRI], fire[DATA_IRI])

    def test_candidate_filter_and_limit(self) -> None:
        with Index(self.index_path) as index:
            retriever = SemanticRetriever(index, KeywordBackend())
            only_fire = retriever.scores("data analysis", candidate_iris=[FIRE_IRI])
            limited = retriever.scores("data analysis", limit=1)
        self.assertEqual(set(only_fire), {FIRE_IRI})
        self.assertEqual(len(limited), 1)

    def test_empty_query_returns_nothing(self) -> None:
        with Index(self.index_path) as index:
            retriever = SemanticRetriever(index, KeywordBackend())
            self.assertEqual(retriever.scores("   "), {})

    def test_query_vectors_are_cached(self) -> None:
        backend = KeywordBackend()
        with Index(self.index_path) as index:
            retriever = SemanticRetriever(index, backend)
            retriever.scores("data analysis")
            encoded_after_first = backend.encoded
            retriever.scores("data analysis")
        self.assertEqual(backend.encoded, encoded_after_first)
        self.assertEqual(encoded_after_first, 1)

    def test_backend_mismatch_is_reported(self) -> None:
        with Index(self.index_path) as index:
            with self.assertRaises(EmbeddingIndexMismatch):
                SemanticRetriever(index, MismatchedBackend())


class PipelineRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_semantic_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "pipeline.sqlite"
        build_index(abox=cls.abox, overlay=cls.overlay, index=cls.index_path, verbose=False)
        build_embeddings(cls.index_path, backend=KeywordBackend(), verbose=False)

        cls.plain_index = Path(cls.tmp.name) / "plain.sqlite"
        build_index(
            abox=cls.abox, overlay=cls.overlay, index=cls.plain_index, verbose=False
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _profile(self, pipeline: Pipeline, text: str) -> Profile:
        return Profile(
            user_iri="urn:test:semantic-user",
            education_local="S1",
            education_order=pipeline.ontology.education_order("S1"),
            max_job_zone=4,
            raw_text=text,
            lexical_text=text,
        )

    def test_semantic_mode_ranks_matching_card_first(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            retrieval="semantic",
            embedding_backend=KeywordBackend(),
        ) as pipeline:
            profile = self._profile(
                pipeline, "Inspect buildings for fire hazards and safety"
            )
            recommendations = pipeline.recommend(profile, top_k=2)
        self.assertEqual(recommendations[0].occupation_iri, FIRE_IRI)
        self.assertIn("semantic", recommendations[0].component_scores)
        self.assertNotIn("lexical", recommendations[0].component_scores)
        self.assertEqual(pipeline.retrieval_mode, "semantic")
        kinds = [item["kind"] for item in recommendations[0].evidence]
        self.assertIn("semantic", kinds)

    def test_lexical_mode_keeps_bm25_component(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            retrieval="lexical",
        ) as pipeline:
            profile = self._profile(pipeline, "Analyze data and build models")
            recommendations = pipeline.recommend(profile, top_k=2)
        self.assertEqual(recommendations[0].occupation_iri, DATA_IRI)
        self.assertIn("lexical", recommendations[0].component_scores)
        self.assertNotIn("semantic", recommendations[0].component_scores)

    def test_auto_falls_back_when_embeddings_are_missing(self) -> None:
        with Pipeline.from_paths(
            index_path=self.plain_index,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            retrieval="auto",
            embedding_backend=KeywordBackend(),
        ) as pipeline:
            self.assertEqual(pipeline.retrieval_mode, "lexical")
            self.assertIsNone(pipeline.retriever)

    def test_explicit_semantic_without_embeddings_raises(self) -> None:
        with self.assertRaises(EmbeddingIndexMismatch):
            Pipeline.from_paths(
                index_path=self.plain_index,
                overlay_path=self.overlay,
                reasoner_mode="sql",
                retrieval="semantic",
                embedding_backend=KeywordBackend(),
            )


if __name__ == "__main__":
    unittest.main()
