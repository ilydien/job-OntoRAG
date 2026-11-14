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
        self.assertAlmostEqual(policy.component_weights["holland"], 0.50)
        self.assertAlmostEqual(policy.component_weights["element"], 0.35)
        self.assertAlmostEqual(policy.component_weights["lexical"], 0.15)
        self.assertEqual(len(policy.rule_files), 3)
        self.assertTrue(policy.reasoning_map_file.exists())

    def test_index_policy(self) -> None:
        policy = load_index_policy()
        self.assertTrue(policy.require_complete_data)
        self.assertEqual(policy.min_fts_token_length, 2)
        self.assertIn("KnowledgeRating", policy.indexed_rating_types)
        self.assertIn("AbilitiesRating", policy.indexed_rating_types)


if __name__ == "__main__":
    unittest.main()
