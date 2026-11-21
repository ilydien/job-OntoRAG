from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from ontorag.extraction import Profile
from ontorag.graph_search import RELATED_DECAY, related_sparql_query, sparql_query
from ontorag.graph_search import scores as graph_scores
from ontorag.index import build_index
from ontorag.pipeline import Pipeline
from tests.fixtures import write_semantic_fixture

DATA_IRI = "https://example.org/occupation/data-scientist"
FIRE_IRI = "https://example.org/occupation/fire-inspector"

RDFLIB = importlib.util.find_spec("rdflib") is not None


@unittest.skipUnless(RDFLIB, "rdflib is required for the SPARQL retriever")
class OntologyGraphSearchTests(unittest.TestCase):
    def test_direct_match_and_one_hop_related(self) -> None:
        element_rows = {
            "urn:occ:direct": [
                {"element_iri": "urn:element:programming", "norm_value": 0.9}
            ],
            "urn:occ:related": [],
        }
        related_rows = {"urn:occ:direct": ["urn:occ:related"]}
        weights = {"urn:element:programming": 1.0}

        scores = graph_scores(element_rows, related_rows, weights)

        self.assertAlmostEqual(scores["urn:occ:direct"], 0.9, places=6)
        self.assertAlmostEqual(
            scores["urn:occ:related"], 0.9 * RELATED_DECAY, places=6
        )
        self.assertGreater(scores["urn:occ:direct"], scores["urn:occ:related"])

    def test_no_matching_element_returns_nothing(self) -> None:
        element_rows = {
            "urn:occ:direct": [
                {"element_iri": "urn:element:programming", "norm_value": 0.9}
            ]
        }
        scores = graph_scores(element_rows, {}, {"urn:element:other": 1.0})
        self.assertEqual(scores, {})

    def test_empty_weights_returns_nothing(self) -> None:
        self.assertEqual(graph_scores({"urn:occ:a": []}, {}, {}), {})

    def test_query_is_sparql_over_element_individuals(self) -> None:
        query = sparql_query({"urn:element:programming": 1.0}, limit=5)
        self.assertIn("PREFIX", query)
        self.assertIn("SELECT", query)
        self.assertIn("career:hasElementRating", query)
        self.assertIn("career:ratedElement", query)

    def test_hop_query_traverses_related_occupations(self) -> None:
        query = related_sparql_query({"urn:occ:direct": 0.9}, limit=5)
        self.assertIn("VALUES (?seed ?seedScore)", query)
        self.assertIn("career:relatedOccupation", query)


@unittest.skipUnless(RDFLIB, "rdflib is required for the SPARQL retriever")
class OntologyPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_semantic_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "ontology.sqlite"
        build_index(abox=cls.abox, overlay=cls.overlay, index=cls.index_path, verbose=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_default_retrieval_mode_is_ontology(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
        ) as pipeline:
            self.assertEqual(pipeline.retrieval_mode, "ontology")

    def test_ontology_without_elements_returns_empty_with_warning(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
        ) as pipeline:
            profile = Profile(
                user_iri="urn:test:no-elements",
                education_local="S1",
                education_order=pipeline.ontology.education_order("S1"),
                max_job_zone=4,
                raw_text="Saya suka sesuatu yang tidak terdefinisi",
                lexical_text="Saya suka sesuatu yang tidak terdefinisi",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                recommendations = pipeline.recommend(profile, top_k=5)
        self.assertEqual(recommendations, [])
        self.assertIn("found no profile elements", stderr.getvalue())

    def test_ontology_mode_adds_sparql_component(self) -> None:
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            retrieval="ontology",
        ) as pipeline:
            self.assertEqual(pipeline.retrieval_mode, "ontology")
            profile = pipeline.profile_from_text("Saya suka pemrograman", language="id")
            recommendations = pipeline.recommend(profile, top_k=2)
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].occupation_iri, DATA_IRI)
        self.assertIn("ontology", recommendations[0].component_scores)
        kinds = [item["kind"] for item in recommendations[0].evidence]
        self.assertIn("ontology", kinds)


if __name__ == "__main__":
    unittest.main()
