from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from ontorag.graph_export import export_graph
from ontorag.index import build_index
from tests.fixtures import write_fixture

RDFLIB = importlib.util.find_spec("rdflib") is not None


@unittest.skipUnless(RDFLIB, "rdflib is required to inspect the derived graph")
class GraphExportTests(unittest.TestCase):
    def test_export_contains_occupation_rating_and_related_edges(self) -> None:
        from rdflib import Graph, Namespace

        with tempfile.TemporaryDirectory() as tmp:
            abox, overlay = write_fixture(tmp)
            index_path = Path(tmp) / "index.sqlite"
            output = Path(tmp) / "derived.nt"
            build_index(abox=abox, overlay=overlay, index=index_path, verbose=False)
            export_graph(index_path, output, verbose=False)

            self.assertTrue(output.exists())
            graph = Graph()
            graph.parse(output, format="nt")
            career = Namespace("https://example.org/career#")
            onet = Namespace("https://www.onetcenter.org/rdf/schema/onet/")
            self.assertTrue(
                list(
                    graph.subjects(
                        career.hasElementRating,
                        None,
                    )
                )
            )
            self.assertTrue(list(graph.subjects(career.relatedOccupation, None)))
            self.assertTrue(list(graph.triples((None, career.normalizedValue, None))))
            self.assertTrue(list(graph.triples((None, career.ratedElement, None))))
            self.assertTrue(list(graph.triples((None, None, onet.Occupation))))

    def test_export_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            abox, overlay = write_fixture(tmp)
            index_path = Path(tmp) / "index.sqlite"
            first = Path(tmp) / "first.nt"
            second = Path(tmp) / "second.nt"
            build_index(abox=abox, overlay=overlay, index=index_path, verbose=False)
            export_graph(index_path, first, verbose=False)
            export_graph(index_path, second, verbose=False)
            self.assertEqual(first.read_text(), second.read_text())


if __name__ == "__main__":
    unittest.main()
