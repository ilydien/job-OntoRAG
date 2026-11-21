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
                ElementInfo("urn:element:design", "Design", "Desain"),
                ElementInfo("urn:element:food", "Food Production", "Produksi Pangan"),
                ElementInfo("urn:element:service", "Service Orientation", "Orientasi Pelayanan"),
                ElementInfo("urn:element:athletics", "Athletics", "Atletik"),
                ElementInfo("urn:element:stamina", "Stamina", "Daya Tahan"),
                ElementInfo(
                    "urn:element:body_coordination",
                    "Gross Body Coordination",
                    "Koordinasi Tubuh Kasar",
                ),
                ElementInfo(
                    "urn:element:public_safety",
                    "Public Safety and Security",
                    "Keselamatan dan Keamanan Publik",
                ),
                ElementInfo(
                    "urn:element:engineering",
                    "Engineering and Technology",
                    "Rekayasa dan Teknologi",
                ),
                ElementInfo(
                    "urn:element:electronics",
                    "Computers and Electronics",
                    "Komputer dan Elektronik",
                ),
                ElementInfo(
                    "urn:element:mech_repair",
                    "Repairing and Maintaining Mechanical Equipment",
                    "Memperbaiki dan Memelihara Peralatan Mekanik",
                ),
                ElementInfo("urn:element:agriculture", "Agriculture", "Pertanian"),
                ElementInfo(
                    "urn:element:logistics",
                    "Management of Material Resources",
                    "Pengelolaan Sumber Daya Material",
                ),
                ElementInfo("urn:element:fine_arts", "Fine Arts", "Seni Rupa"),
                ElementInfo(
                    "urn:element:caring",
                    "Assisting and Caring for Others",
                    "Membantu dan Merawat Orang Lain",
                ),
                ElementInfo(
                    "urn:element:medicine",
                    "Medicine and Dentistry",
                    "Kedokteran dan Kedokteran Gigi",
                ),
                ElementInfo("urn:element:biology", "Biology", "Biologi"),
                ElementInfo("urn:element:animal", "Animal Service", "Layanan Hewan"),
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

    def test_patient_care_query_extracts_caring_element(self) -> None:
        profile = extract_from_text(
            "Saya suka merawat dan membantu pasien di rumah sakit.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("Social", profile.holland)
        self.assertIn("urn:element:caring", profile.elements)
        self.assertIn("urn:element:medicine", profile.elements)

    def test_animal_query_extracts_animal_service_and_biology(self) -> None:
        profile = extract_from_text(
            "Saya suka merawat hewan dan membantu dokter hewan.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("urn:element:animal", profile.elements)
        self.assertIn("urn:element:biology", profile.elements)
        self.assertIn("Investigative", profile.holland)
        self.assertIn("Realistic", profile.holland)

    def test_architect_query_extracts_realistic_and_building(self) -> None:
        profile = extract_from_text(
            "Saya suka mendesain bangunan dan tata ruang.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("Realistic", profile.holland)
        self.assertIn("Artistic", profile.holland)
        self.assertIn("urn:element:building", profile.elements)
        self.assertIn("urn:element:design", profile.elements)

    def test_no_degree_maps_to_high_school(self) -> None:
        profile = extract_from_text(
            "Saya suka musik, tetapi saya belum memiliki gelar apapun.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertEqual(profile.education_local, "Level2_HighSchool")
        self.assertTrue(any(item["kind"] == "education" for item in profile.evidence))

    def test_current_student_maps_to_prospective_s1(self) -> None:
        profile = extract_from_text(
            "Saya sedang belajar di program studi Sains Data.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertEqual(profile.education_local, "S1")
        self.assertIn("urn:element:data", profile.elements)
        self.assertIn("urn:element:programming", profile.elements)

    def test_data_science_phrase_does_not_duplicate_data_evidence(self) -> None:
        profile = extract_from_text(
            "Saya suka menganalisis dan eksplorasi data serta visualisasi data.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        data_holland = [
            item
            for item in profile.evidence
            if item.get("kind") == "holland"
            and item.get("target") == "Investigative"
            and item.get("text", "").lower() == "data"
        ]
        spans = {(item["start"], item["end"]) for item in data_holland}
        self.assertEqual(len(spans), len(data_holland))
        self.assertTrue(data_holland)
        self.assertIn("urn:element:data", profile.elements)

    def test_cooking_maps_to_food_production(self) -> None:
        profile = extract_from_text(
            "Saya suka memasak di dapur dan membuat makanan.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("urn:element:food", profile.elements)

    def test_food_service_phrase_maps_to_service_orientation(self) -> None:
        profile = extract_from_text(
            "Saya suka pelayanan makanan dan melayani pelanggan di restoran.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("urn:element:service", profile.elements)

    def test_web_pipeline_phrase_maps_to_programming(self) -> None:
        profile = extract_from_text(
            "Saya suka develop web dan membangun pipeline data.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        self.assertIn("urn:element:programming", profile.elements)
        self.assertNotIn("urn:element:building", profile.elements)

    def test_additional_domains_map_to_elements(self) -> None:
        profile = extract_from_text(
            "Saya suka olahraga, keamanan, teknik mesin, pertanian, logistik, "
            "perhotelan, energi terbarukan, konservasi, dan teater.",
            self.ontology,
            self.lexicon,
            self.catalog,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        for iri in (
            "urn:element:athletics",
            "urn:element:public_safety",
            "urn:element:engineering",
            "urn:element:agriculture",
            "urn:element:logistics",
            "urn:element:service",
            "urn:element:biology",
            "urn:element:fine_arts",
        ):
            self.assertIn(iri, profile.elements)

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
