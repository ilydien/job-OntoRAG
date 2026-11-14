from __future__ import annotations

import unittest

from ontorag.lexicon import Lexicon


class LexiconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lexicon = Lexicon.load()

    def test_matches_are_sorted_and_targeted(self) -> None:
        matches = self.lexicon.find("Saya suka data, matematika, dan pemrograman.")
        kinds = {(match.kind, match.target) for match in matches}
        self.assertIn(("holland", "Investigative"), {(kind, target) for kind, target in kinds if target})
        self.assertIn(("element", "Mathematics/Statistics"), kinds)
        self.assertIn(("element", "Programming"), kinds)
        self.assertEqual(matches, sorted(matches, key=lambda item: (item.start, item.end, item.kind)))

    def test_negation_marks_following_match(self) -> None:
        self.assertEqual(self.lexicon.negation_window, 35)
        matches = self.lexicon.find("Saya tidak suka menjual.")
        selling = [match for match in matches if match.text.lower() == "menjual"]
        self.assertTrue(selling)
        self.assertTrue(all(match.negated for match in selling))

    def test_education_and_job_zone_patterns(self) -> None:
        matches = self.lexicon.find("Saya lulusan S1 dan ingin job zone 4.")
        kinds = {match.kind for match in matches}
        self.assertIn("education", kinds)
        self.assertIn("job_zone", kinds)


if __name__ == "__main__":
    unittest.main()
