from __future__ import annotations

import unittest

from ontorag.policy import load_index_policy, load_ranking_policy


class PolicyTests(unittest.TestCase):
    def test_ranking_policy_defaults(self) -> None:
        policy = load_ranking_policy()
        self.assertEqual(policy.default_education, "S1")
        self.assertEqual(policy.default_max_job_zone, 5)
        self.assertTrue(policy.require_eligible)
        self.assertEqual(policy.tier_order, ["EligibleStrong", "Eligible", "NotEligible"])
        self.assertAlmostEqual(policy.component_weights["holland"], 0.45)
        self.assertAlmostEqual(policy.component_weights["element"], 0.30)
        self.assertAlmostEqual(policy.component_weights["semantic"], 0.25)
        self.assertAlmostEqual(policy.component_weights["lexical"], 0.15)
        self.assertEqual(policy.retrieval_mode, "auto")
        self.assertEqual(policy.semantic_normalization, "minmax")
        self.assertGreater(policy.semantic_candidate_limit, 0)
        # The candidate limit is a safety cap: retrieval must rank the whole
        # hard-filtered pool, so this stays well above the O*NET occupation count.
        self.assertGreaterEqual(policy.candidate_limit, 1000)
        self.assertEqual(len(policy.rule_files), 3)
        self.assertTrue(policy.reasoning_map_file.exists())

    def test_index_policy(self) -> None:
        policy = load_index_policy()
        self.assertTrue(policy.require_complete_data)
        self.assertEqual(policy.min_fts_token_length, 2)
        self.assertIn("KnowledgeRating", policy.indexed_rating_types)
        self.assertIn("AbilitiesRating", policy.indexed_rating_types)
        self.assertEqual(policy.embedding_model, "intfloat/multilingual-e5-small")
        self.assertGreater(policy.embedding_max_tasks, 0)
        self.assertGreater(policy.embedding_max_elements, 0)


if __name__ == "__main__":
    unittest.main()
