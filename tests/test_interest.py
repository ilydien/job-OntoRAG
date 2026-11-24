from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ontorag.extraction import InterestCatalog, extract_from_text
from ontorag.index import build_index
from ontorag.lexicon import Lexicon
from ontorag.ontology import Ontology
from ontorag.policy import load_ranking_policy
from ontorag.query_engine import Index
from ontorag.scoring import holland_score

INTEREST_ABOX = """@prefix : <https://www.onetcenter.org/rdf/schema/onet/> .
@prefix career: <https://example.org/career#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.org/element/realistic> a :Element ;
    :elementName "Realistic" ;
    :illustratedBy <https://example.org/activity/build> ;
    :linkedTo <https://example.org/keyword/animals> .

<https://example.org/activity/build> a :InterestsActivity ;
    :activity "Build kitchen cabinets." .

<https://example.org/element/mechanics> a :Element ;
    :elementName "Mechanics/Electronics" ;
    :illustratedBy <https://example.org/activity/repair> ;
    :linkedTo <https://example.org/element/realistic> .

<https://example.org/activity/repair> a :InterestsActivity ;
    :activity "Repair motors and generators." .

<https://example.org/element/enterprising> a :Element ;
    :elementName "Enterprising" ;
    :linkedTo <https://example.org/keyword/selling> .

<https://example.org/keyword/animals> a :InterestsKeyword ;
    :keyword "Animals" ;
    :keywordType "Object" .

<https://example.org/keyword/selling> a :InterestsKeyword ;
    :keyword "Selling" ;
    :keywordType "Activity" .

<https://example.org/scale/interest> a :Scale ;
    :scaleName "Interest" .

<https://example.org/rating/interest> a :CareerInterestTypesRating ;
    :dataValue "6.0"^^xsd:float ;
    :refersTo <https://example.org/element/realistic>, <https://example.org/scale/interest> .

<https://example.org/occupation/builder> a :Occupation ;
    :title "Builder" ;
    :description "Build things." ;
    :onetSOCCode "47-0000.00" ;
    career:hasDataStatus career:CompleteData ;
    career:hasMinEducationLevel career:S1 ;
    career:hasPrimaryHollandCode career:Realistic ;
    :hasRating <https://example.org/rating/interest> .
"""

INTEREST_OVERLAY = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/activity/build>
    rdfs:label "Membangun lemari dapur."@id .
<https://example.org/keyword/animals>
    rdfs:label "Hewan"@id .
<https://example.org/keyword/selling>
    rdfs:label "Menjual"@id .
"""


class InterestFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox = Path(cls.tmp.name) / "interest_abox.ttl"
        cls.overlay = Path(cls.tmp.name) / "interest_overlay.ttl"
        cls.index_path = Path(cls.tmp.name) / "interest.sqlite"
        cls.abox.write_text(INTEREST_ABOX, encoding="utf-8")
        cls.overlay.write_text(INTEREST_OVERLAY, encoding="utf-8")
        build_index(
            abox=cls.abox,
            overlay=cls.overlay,
            index=cls.index_path,
            verbose=False,
        )
        cls.index = Index(cls.index_path)
        cls.ontology = Ontology()
        cls.lexicon = Lexicon.load()
        cls.policy = load_ranking_policy()
        cls.catalog = InterestCatalog.from_rows(cls.index.interest_catalog_rows())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.index.close()
        cls.tmp.cleanup()

    def test_interest_catalog_and_riasec_links_are_indexed(self) -> None:
        rows = self.index.interest_catalog_rows()
        self.assertEqual({row["kind"] for row in rows}, {"activity", "keyword"})
        activities = [row for row in rows if row["kind"] == "activity"]
        self.assertEqual(len(activities), 2)
        self.assertTrue(all(row["riasec_local"] == "Realistic" for row in activities))
        keywords = {row["label_en"]: row["riasec_local"] for row in rows if row["kind"] == "keyword"}
        self.assertEqual(keywords["Animals"], "Realistic")
        self.assertEqual(keywords["Selling"], "Enterprising")
        ratings = self.index.interest_ratings_for_many(
            ["https://example.org/occupation/builder"]
        )
        self.assertEqual(ratings["https://example.org/occupation/builder"][0]["rating_type"], "CareerInterestTypesRating")

    def test_interest_catalog_matches_indonesian_label_to_riasec(self) -> None:
        from ontorag.extraction import ElementCatalog

        elements = ElementCatalog([])
        profile = extract_from_text(
            "Saya suka membangun lemari dapur",
            self.ontology,
            self.lexicon,
            elements,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
            interest_catalog=self.catalog,
            interest_activity_weight=self.policy.interest_activity_weight,
            interest_keyword_weight=self.policy.interest_keyword_weight,
            interest_primary=True,
        )
        self.assertIn("Realistic", profile.holland)
        self.assertTrue(
            any(item.get("kind") == "interest_activity" for item in profile.evidence)
        )

    def _extract(self, text: str, catalog: InterestCatalog):
        from ontorag.extraction import ElementCatalog

        return extract_from_text(
            text,
            self.ontology,
            self.lexicon,
            ElementCatalog([]),
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
            interest_catalog=catalog,
            interest_activity_weight=self.policy.interest_activity_weight,
            interest_keyword_weight=self.policy.interest_keyword_weight,
            interest_primary=True,
        )

    def test_interest_primary_suppresses_lexicon_holland_cues(self) -> None:
        profile = self._extract("Saya suka riset dan membangun lemari dapur", self.catalog)
        self.assertIn("Realistic", profile.holland)
        self.assertNotIn("Investigative", profile.holland)
        self.assertFalse(
            any(
                item.get("kind") in {"holland", "holland_code"}
                for item in profile.evidence
            )
        )

    def test_interest_primary_falls_back_to_lexicon_without_interest_hits(self) -> None:
        profile = self._extract("Saya suka riset.", InterestCatalog([]))
        self.assertIn("Investigative", profile.holland)
        self.assertTrue(
            any(item.get("kind") == "holland" for item in profile.evidence)
        )

    def test_negated_interest_cue_is_ignored(self) -> None:
        profile = self._extract("Saya tidak suka menjual.", self.catalog)
        self.assertNotIn("Enterprising", profile.holland)
        self.assertFalse(
            any(item.get("kind", "").startswith("interest_") for item in profile.evidence)
        )

    def test_graded_riasec_rating_drives_holland_score(self) -> None:
        profile = type(
            "P",
            (),
            {"holland": {"Realistic": 1.0}},
        )()
        rows = self.index.interest_ratings_for_many(
            ["https://example.org/occupation/builder"]
        )
        occupation_rows = rows["https://example.org/occupation/builder"]
        score = holland_score(
            profile,
            {"holland_primary": "Artistic"},
            self.policy,
            interest_rows=occupation_rows,
        )
        self.assertGreater(score, 0.0)
        fallback = holland_score(
            profile,
            {"holland_primary": "Artistic"},
            self.policy,
        )
        self.assertEqual(fallback, 0.0)


if __name__ == "__main__":
    unittest.main()
