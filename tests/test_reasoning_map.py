from __future__ import annotations

import unittest
from pathlib import Path

from ontorag.reasoning import PelletReasoner


class ReasoningMapTests(unittest.TestCase):
    def test_output_map_is_declarative(self) -> None:
        reasoner = PelletReasoner(reasoning_map=Path("config/reasoning_map.ttl"))
        output = reasoner._output_map()
        self.assertTrue(output["strong_class"].endswith("EligibleStrong"))
        self.assertTrue(output["eligible_class"].endswith("EligibleOccupation"))
        self.assertEqual(output["strong_tier"], "EligibleStrong")
        self.assertEqual(output["eligible_tier"], "Eligible")
        self.assertEqual(output["not_eligible_tier"], "NotEligible")

    def test_slice_map_is_declarative(self) -> None:
        reasoner = PelletReasoner(reasoning_map=Path("config/reasoning_map.ttl"))
        mapping = reasoner._slice_map()
        self.assertTrue(mapping["education_property"].endswith("hasMinEducationLevel"))
        self.assertTrue(mapping["holland_property"].endswith("hasPrimaryHollandCode"))
        self.assertTrue(mapping["rating_property"].endswith("hasRating"))


if __name__ == "__main__":
    unittest.main()
