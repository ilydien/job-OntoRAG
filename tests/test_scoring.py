from __future__ import annotations

import unittest

from ontorag.extraction import Profile
from ontorag.policy import load_ranking_policy
from ontorag.scoring import element_score, holland_score, normalize_lexical, score_candidates


class FakeIndex:
    def elements_for(self, iri: str):
        return [
            {
                "element_iri": "urn:element:programming",
                "element_name_en": "Programming",
                "norm_value": 0.9,
                "rating_type": "KnowledgeRating",
            }
        ]


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_ranking_policy()
        cls.profile = Profile(
            user_iri="urn:test:user",
            holland={"Investigative": 1.0},
            elements={"urn:element:programming": 1.0},
            element_labels={"urn:element:programming": "Programming"},
        )

    def test_holland_score_weights_primary_secondary_tertiary(self) -> None:
        row = {
            "holland_primary": "Investigative",
            "holland_secondary": "Conventional",
            "holland_tertiary": "Realistic",
        }
        self.assertAlmostEqual(holland_score(self.profile, row, self.policy), 1.0)
        row["holland_primary"] = "Realistic"
        row["holland_tertiary"] = "Investigative"
        self.assertAlmostEqual(holland_score(self.profile, row, self.policy), 0.30)

    def test_element_score_uses_policy_aggregation(self) -> None:
        score, matches = element_score(
            self.profile,
            [
                {"element_iri": "urn:element:programming", "norm_value": 0.25, "element_name_en": "Programming"},
                {"element_iri": "urn:element:programming", "norm_value": 0.75, "element_name_en": "Programming"},
            ],
            self.policy,
        )
        self.assertAlmostEqual(score, 0.75)
        self.assertEqual(matches[0]["normalized_rating"], 0.75)

    def test_prefetched_element_rows_are_used(self) -> None:
        rows = [
            {
                "iri": "urn:occupation:a",
                "title_en": "Occupation A",
                "holland_primary": "Investigative",
            },
            {
                "iri": "urn:occupation:b",
                "title_en": "Occupation B",
                "holland_primary": "Investigative",
            },
        ]
        prefetched = {
            "urn:occupation:a": [
                {
                    "element_iri": "urn:element:programming",
                    "element_name_en": "Programming",
                    "norm_value": 0.8,
                    "rating_type": "KnowledgeRating",
                }
            ],
            "urn:occupation:b": [],
        }
        recommendations = score_candidates(
            FakeIndex(),
            self.profile,
            self.policy,
            rows,
            element_rows=prefetched,
            top_k=2,
        )
        by_iri = {item.occupation_iri: item for item in recommendations}
        self.assertAlmostEqual(by_iri["urn:occupation:a"].component_scores["element"], 0.8)
        self.assertAlmostEqual(by_iri["urn:occupation:b"].component_scores["element"], 0.0)

    def test_profile_without_elements_skips_element_component(self) -> None:
        profile = Profile(user_iri="urn:test:user", holland={"Investigative": 1.0})
        rows = [
            {
                "iri": "urn:occupation:a",
                "title_en": "Occupation A",
                "holland_primary": "Investigative",
            }
        ]
        recommendations = score_candidates(
            FakeIndex(), profile, self.policy, rows, top_k=1
        )
        self.assertNotIn("element", recommendations[0].component_scores)

    def test_normalize_lexical(self) -> None:
        normalized = normalize_lexical({"a": 1.0, "b": 3.0}, ["a", "b", "c"])
        self.assertAlmostEqual(normalized["a"], 0.0)
        self.assertAlmostEqual(normalized["b"], 1.0)
        self.assertAlmostEqual(normalized["c"], 0.0)
        self.assertEqual(normalize_lexical({"a": 2.0}, ["a"]), {"a": 0.5})

    def test_semantic_scores_add_normalised_component(self) -> None:
        rows = [
            {
                "iri": "urn:occupation:a",
                "title_en": "Occupation A",
                "holland_primary": "Investigative",
            },
            {
                "iri": "urn:occupation:b",
                "title_en": "Occupation B",
                "holland_primary": "Investigative",
            },
        ]
        recommendations = score_candidates(
            FakeIndex(),
            self.profile,
            self.policy,
            rows,
            semantic_scores={"urn:occupation:a": 0.9, "urn:occupation:b": 0.5},
            top_k=2,
        )
        by_iri = {item.occupation_iri: item for item in recommendations}
        self.assertAlmostEqual(by_iri["urn:occupation:a"].component_scores["semantic"], 1.0)
        self.assertAlmostEqual(by_iri["urn:occupation:b"].component_scores["semantic"], 0.0)
        self.assertGreater(
            by_iri["urn:occupation:a"].score, by_iri["urn:occupation:b"].score
        )

    def test_semantic_and_lexical_can_coexist_for_hybrid(self) -> None:
        rows = [
            {
                "iri": "urn:occupation:a",
                "title_en": "Occupation A",
                "holland_primary": "Investigative",
            }
        ]
        recommendations = score_candidates(
            FakeIndex(),
            self.profile,
            self.policy,
            rows,
            lexical_scores={"urn:occupation:a": 0.4},
            semantic_scores={"urn:occupation:a": 0.8},
            top_k=1,
        )
        self.assertIn("lexical", recommendations[0].component_scores)
        self.assertIn("semantic", recommendations[0].component_scores)

    def test_tier_sorting_precedes_score(self) -> None:
        rows = [
            {
                "iri": "urn:occupation:strong",
                "title_en": "Strong Occupation",
                "holland_primary": "Investigative",
                "holland_secondary": "",
                "holland_tertiary": "",
            },
            {
                "iri": "urn:occupation:eligible",
                "title_en": "Eligible Occupation",
                "holland_primary": "Investigative",
                "holland_secondary": "",
                "holland_tertiary": "",
            },
            {
                "iri": "urn:occupation:not-eligible",
                "title_en": "Not Eligible Occupation",
                "holland_primary": "Investigative",
                "holland_secondary": "",
                "holland_tertiary": "",
            },
        ]
        flags = {
            "urn:occupation:strong": {"tier": "EligibleStrong"},
            "urn:occupation:eligible": {"tier": "Eligible"},
            "urn:occupation:not-eligible": {"tier": "NotEligible"},
        }
        recommendations = score_candidates(
            FakeIndex(),
            self.profile,
            self.policy,
            rows,
            lexical_scores={
                "urn:occupation:strong": 0.1,
                "urn:occupation:eligible": 1.0,
                "urn:occupation:not-eligible": 2.0,
            },
            reasoning_flags=flags,
            top_k=3,
        )
        self.assertEqual([item.occupation_iri for item in recommendations], [
            "urn:occupation:strong",
            "urn:occupation:eligible",
        ])
        self.assertEqual(recommendations[0].tier, "EligibleStrong")
        self.assertGreater(recommendations[1].score, recommendations[0].score)
        self.assertEqual([item.rank for item in recommendations], [1, 2])


if __name__ == "__main__":
    unittest.main()
