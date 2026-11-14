from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ontorag import ttl_stream


class TurtleStreamTests(unittest.TestCase):
    def test_prefix_and_block_parsing(self) -> None:
        text = """@prefix : <https://example.org/> .
<https://example.org/s> a :Thing ;
    :name "Example" ;
    :value "12"^^<http://www.w3.org/2001/XMLSchema#integer> ;
    :tags :a, :b .
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.ttl"
            path.write_text(text, encoding="utf-8")
            blocks = list(ttl_stream.iter_blocks(path))
        self.assertEqual(len(blocks), 1)
        subject, predicates = blocks[0]
        self.assertEqual(subject.value, "https://example.org/s")
        self.assertEqual(ttl_stream.literal_value(predicates, "https://example.org/name"), "Example")
        self.assertEqual(ttl_stream.numeric_value(predicates, "https://example.org/value"), 12.0)
        self.assertEqual(
            ttl_stream.iri_values(predicates, "https://example.org/tags"),
            ["https://example.org/a", "https://example.org/b"],
        )

    def test_one_triple_per_line(self) -> None:
        text = """@prefix : <https://example.org/> .
<https://example.org/s> <https://example.org/name> "A" .
<https://example.org/s> <https://example.org/value> "3"^^<http://www.w3.org/2001/XMLSchema#integer> .
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lines.ttl"
            path.write_text(text, encoding="utf-8")
            blocks = list(ttl_stream.iter_blocks(path))
        self.assertEqual(len(blocks), 2)
        self.assertEqual(ttl_stream.literal_value(blocks[0][1], "https://example.org/name"), "A")
        self.assertEqual(ttl_stream.numeric_value(blocks[1][1], "https://example.org/value"), 3.0)

    def test_escaped_literals(self) -> None:
        block = ttl_stream.parse_block(
            '<https://example.org/s> <https://example.org/text> "line\\nnext \\"quoted\\"" .',
            {},
        )
        self.assertIsNotNone(block)
        self.assertEqual(
            ttl_stream.literal_value(block[1], "https://example.org/text"),
            'line\nnext "quoted"',
        )

    def test_blank_nodes_and_collections_are_skipped_but_block_survives(self) -> None:
        block = ttl_stream.parse_block(
            '<https://example.org/s> <https://example.org/list> ( "a" "b" ) ; '
            '<https://example.org/bnode> [ <https://example.org/p> "v" ] .',
            {},
        )
        self.assertIsNotNone(block)
        self.assertNotIn("https://example.org/list", block[1])
        self.assertNotIn("https://example.org/bnode", block[1])

    def test_local_name(self) -> None:
        self.assertEqual(ttl_stream.local_name("https://example.org/a#b"), "b")
        self.assertEqual(ttl_stream.local_name("https://example.org/a/b"), "b")
        self.assertEqual(ttl_stream.local_name("career:S1"), "S1")


if __name__ == "__main__":
    unittest.main()
