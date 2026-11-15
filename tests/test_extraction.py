from __future__ import annotations

import unittest

from ontorag.extraction import ElementCatalog, ElementInfo, extract_from_text
from ontorag.lexicon import Lexicon
from ontorag.ontology import Ontology
from ontorag.policy import load_ranking_policy


class ExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ontology = Ontology()
        cls.lexicon = Lexicon.load()
        cls.policy = load_ranking_policy()
        cls.catalog = ElementCatalog(
            [
                ElementInfo("urn:element:math", "Mathematics/Statistics", "Matematika"),
                ElementInfo("urn:element:instructing", "Instructing", "Mengajar"),
                ElementInfo("urn:element:programming", "Programming", "Pemrograman"),
                ElementInfo("urn:element:sales", "Sales and Marketing", "Penjualan"),
                ElementInfo(
                    "urn:element:data",
                    "Analyzing Data or Information",
                    "Menganalisis Data atau Informasi",
                ),
                ElementInfo(
                    "urn:element:building",
                    "Building and Construction",
                    "Bangunan dan Konstruksi",
                ),
            ]
        )

    def test_extracts_education_job_zone_holland_and_elements(self) -> None:
        profile = extract_from_text(
            "Saya lulusan D3, suka membantu orang, mengajar, dan job zone 3. "
            "Saya tidak suka menjual.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertEqual(profile.education_local, "D3")
        self.assertEqual(profile.max_job_zone, 3)
        self.assertIn("Social", profile.holland)
        self.assertNotIn("Enterprising", profile.holland)
        self.assertIn("urn:element:instructing", profile.elements)
        self.assertNotIn("urn:element:sales", profile.elements)
        self.assertNotIn("menjual", profile.lexical_text)
        self.assertIn("mengajar", profile.lexical_text)

    def test_defaults_are_applied_only_when_no_explicit_signal(self) -> None:
        profile = extract_from_text(
            "Saya suka data.",
            self.ontology,
            self.lexicon,
            self.catalog,
            default_education="S1",
            default_max_job_zone=4,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertEqual(profile.education_local, "S1")
        self.assertEqual(profile.max_job_zone, 4)

    def test_build_model_is_investigative_not_construction(self) -> None:
        profile = extract_from_text(
            "Saya suka menganalisis data dan membangun model.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("Investigative", profile.holland)
        self.assertNotIn("Realistic", profile.holland)
        self.assertIn("urn:element:data", profile.elements)
        self.assertIn("urn:element:programming", profile.elements)
        self.assertNotIn("urn:element:building", profile.elements)

    def test_software_keyword_maps_to_programming(self) -> None:
        profile = extract_from_text(
            "Saya suka software dan developer aplikasi.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("urn:element:programming", profile.elements)

    def test_build_house_stays_realistic_and_construction(self) -> None:
        profile = extract_from_text(
            "Saya suka membangun rumah dan jembatan.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("Realistic", profile.holland)
        self.assertIn("urn:element:building", profile.elements)

    def test_bare_membangun_no_longer_means_construction(self) -> None:
        profile = extract_from_text(
            "Saya suka membangun.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertNotIn("Realistic", profile.holland)
        self.assertNotIn("urn:element:building", profile.elements)

    def test_profile_ttl_contains_user_constraints(self) -> None:
        profile = extract_from_text(
            "Saya lulusan D3, suka mengajar, job zone 3.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        ttl = profile.to_ttl(self.ontology)
        self.assertIn("career:User", ttl)
        self.assertIn("https://example.org/career#D3", ttl)
        self.assertIn('career:maxJobZone "3"^^xsd:integer', ttl)
        self.assertIn("career:hasHollandPreference", ttl)


if __name__ == "__main__":
    unittest.main()
