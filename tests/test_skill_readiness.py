from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from ontorag.extraction import ElementCatalog, Profile
from ontorag.index import build_index
from ontorag.ontology import Ontology
from ontorag.policy import load_ranking_policy
from ontorag.query_engine import Index
from tests.fixtures import write_skill_fixture

OCCUPATION = "https://example.org/occupation/skill-role"
ELEMENT = "https://example.org/element/programming"


class SkillReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_skill_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "skill.sqlite"
        build_index(
            abox=cls.abox,
            overlay=cls.overlay,
            index=cls.index_path,
            verbose=False,
        )
        with Index(cls.index_path) as index:
            cls.catalog = ElementCatalog.from_rows(index.element_catalog_rows())
        cls.ontology = Ontology()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_scale_and_level_requirement_are_indexed(self) -> None:
        with Index(self.index_path) as index:
            requirements = index.skill_requirements_for_many(
                [OCCUPATION], [ELEMENT], ["KnowledgeRating"], "LV"
            )
            payload = index.requirements_for(
                OCCUPATION,
                load_ranking_policy().requirement_categories,
            )
        self.assertEqual(requirements[OCCUPATION][0]["scale_id"], "LV")
        self.assertEqual(requirements[OCCUPATION][0]["value"], 5.0)
        knowledge = next(
            item
            for item in payload["requirements"]
            if item["rating_type"] == "KnowledgeRating"
        )
        self.assertEqual(knowledge["items"][0]["level"], 5.0)
        self.assertEqual(knowledge["items"][0]["scales"][0]["name"], "Level")

    def test_profile_skill_levels_and_proficiency_ttl(self) -> None:
        profile = Profile.from_json(
            {
                "user_iri": "urn:test:skill-user",
                "education_level": "S1",
                "max_job_zone": 4,
                "skills": {"Programming": 4.5},
            },
            self.ontology,
            self.catalog,
        )
        self.assertEqual(profile.skill_levels[ELEMENT], 4.5)
        ttl = profile.to_ttl(self.ontology)
        self.assertIn("career:hasElementProficiency", ttl)
        self.assertIn("career:proficiencyLevel \"4.500000\"", ttl)
        self.assertIn(f"career:proficiencyElement <{ELEMENT}>", ttl)

    @unittest.skipUnless(
        importlib.util.find_spec("owlready2") is not None,
        "owlready2/Pellet is not installed",
    )
    def test_pellet_infers_skill_ready_and_gap(self) -> None:
        from ontorag.reasoning import PelletReasoner

        policy = load_ranking_policy()
        with Index(self.index_path) as index:
            candidate_profile = Profile.from_json(
                {
                    "user_iri": "urn:test:skill-user",
                    "education_level": "S1",
                    "max_job_zone": 4,
                    "holland": {"Investigative": 1.0},
                },
                self.ontology,
                self.catalog,
            )
            candidates = index.candidates(candidate_profile, policy)
            requirements = index.skill_requirements_for_many(
                [OCCUPATION],
                [ELEMENT],
                ["KnowledgeRating"],
                "LV",
            )
        ready = Profile.from_json(
            {
                "user_iri": "urn:test:skill-user-ready",
                "education_level": "S1",
                "max_job_zone": 4,
                "holland": {"Investigative": 1.0},
                "skills": {"Programming": 6.0},
            },
            self.ontology,
            self.catalog,
        )
        ready_flags = PelletReasoner(rule_files=policy.rule_files).infer(
            ready, candidates, policy, requirements
        )
        self.assertTrue(ready_flags[OCCUPATION]["skill_ready"])
        self.assertFalse(ready_flags[OCCUPATION]["skill_gap"])

        gap = Profile.from_json(
            {
                "user_iri": "urn:test:skill-user-gap",
                "education_level": "S1",
                "max_job_zone": 4,
                "holland": {"Investigative": 1.0},
                "skills": {"Programming": 4.0},
            },
            self.ontology,
            self.catalog,
        )
        gap_flags = PelletReasoner(rule_files=policy.rule_files).infer(
            gap, candidates, policy, requirements
        )
        self.assertFalse(gap_flags[OCCUPATION]["skill_ready"])
        self.assertTrue(gap_flags[OCCUPATION]["skill_gap"])

    def test_pipeline_exposes_skill_gap_details(self) -> None:
        from ontorag.pipeline import Pipeline

        profile = Profile.from_json(
            {
                "user_iri": "urn:test:skill-gap-detail",
                "education_level": "S1",
                "max_job_zone": 4,
                "holland": {"Investigative": 1.0},
                "skills": {"Programming": 4.0},
                "text": "skill role",
            },
            self.ontology,
            self.catalog,
        )
        with Pipeline.from_paths(
            index_path=self.index_path,
            overlay_path=self.overlay,
            reasoner_mode="sql",
            retrieval="lexical",
        ) as pipeline:
            recommendations = pipeline.recommend(profile, top_k=1)
        self.assertTrue(recommendations)
        gaps = recommendations[0].reasoning_flags.get("skill_gaps") or []
        self.assertTrue(gaps)
        self.assertEqual(gaps[0]["label"], "Programming")
        self.assertEqual(gaps[0]["required_level"], 5.0)

    def test_invalid_skill_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Profile.from_json(
                {"skills": {"Programming": 8}},
                self.ontology,
                self.catalog,
                skill_level_max=7,
            )


if __name__ == "__main__":
    unittest.main()
