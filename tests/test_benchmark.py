from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontorag.benchmark import (
    evaluate,
    load_gold_queries,
    load_gold_set,
    ranked_socs,
    recall_at_k,
    reciprocal_rank,
)
from ontorag.index import build_index
from ontorag.pipeline import Pipeline
from tests.fixtures import write_fixture


class MetricTests(unittest.TestCase):
    def test_recall_at_k_counts_expected_hits(self) -> None:
        ranked = ["a", "b", "c", "d"]
        self.assertAlmostEqual(recall_at_k(ranked, ["a", "c"], 4), 1.0)
        self.assertAlmostEqual(recall_at_k(ranked, ["a", "c"], 2), 0.5)
        self.assertAlmostEqual(recall_at_k(ranked, ["z"], 4), 0.0)
        self.assertAlmostEqual(recall_at_k(ranked, [], 4), 0.0)

    def test_reciprocal_rank_uses_first_hit(self) -> None:
        self.assertAlmostEqual(reciprocal_rank(["a", "b", "c"], ["c"]), 1 / 3)
        self.assertAlmostEqual(reciprocal_rank(["a", "b", "c"], ["b", "c"]), 1 / 2)
        self.assertAlmostEqual(reciprocal_rank(["a", "b"], ["z"]), 0.0)

    def test_ranked_socs_drops_blanks_and_respects_k(self) -> None:
        class Item:
            def __init__(self, soc):
                self.soc = soc

        self.assertEqual(ranked_socs([Item("a"), Item(None), Item("c")], 3), ["a", "c"])
        self.assertEqual(ranked_socs([Item("a"), Item("b")], 1), ["a"])


class GoldSetTests(unittest.TestCase):
    def test_load_gold_set_reads_defaults_and_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.json"
            path.write_text(
                json.dumps(
                    {
                        "default_education": "S3",
                        "default_max_job_zone": 5,
                        "queries": [
                            {"text": "hello", "expected_soc": ["15-2051.00"]},
                            {"text": "single", "expected": "29-1141.00"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gold = load_gold_set(path)
            self.assertEqual(load_gold_queries(path), gold.queries)
        self.assertEqual(gold.default_education, "S3")
        self.assertEqual(gold.default_max_job_zone, 5)
        self.assertEqual(len(gold.queries), 2)
        self.assertEqual(gold.queries[0].expected_soc, ("15-2051.00",))
        self.assertEqual(gold.queries[1].expected_soc, ("29-1141.00",))

    def test_load_gold_set_rejects_missing_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"queries": [{"expected_soc": ["x"]}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_gold_set(path)


class BenchmarkEndToEndTests(unittest.TestCase):
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

    def test_evaluate_scores_a_perfect_lexical_run(self) -> None:
        from ontorag.benchmark import GoldQuery

        queries = [GoldQuery(text="Analyze data and build models", expected_soc=("15-2051.00",))]
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            retrieval="lexical",
            temp_dir=self.tmp.name,
        ) as pipeline:

            def recommend(query):
                profile = pipeline.profile_from_text(query.text)
                return pipeline.recommend(profile, top_k=10, text=query.text)

            result = evaluate("lexical", recommend, queries, k=10)

        self.assertIsNone(result.error)
        self.assertEqual(result.query_count, 1)
        self.assertAlmostEqual(result.recall_at_k, 1.0)
        self.assertAlmostEqual(result.mrr, 1.0)
        self.assertEqual(result.per_query[0].ranked_soc[0], "15-2051.00")


if __name__ == "__main__":
    unittest.main()
