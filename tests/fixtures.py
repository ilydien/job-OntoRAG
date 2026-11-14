"""Shared fixtures for the stdlib test suite."""

from __future__ import annotations

from pathlib import Path

FIXTURE_ABOX = """@prefix : <https://www.onetcenter.org/rdf/schema/onet/> .
@prefix career: <https://example.org/career#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.org/occupation/data-scientist> a :Occupation ;
    :title "Data Scientist" ;
    :description "Analyze data and build models." ;
    :onetSOCCode "15-2051.00" ;
    career:hasDataStatus career:CompleteData ;
    career:hasMinEducationLevel career:S1 ;
    career:hasPrimaryHollandCode career:Investigative ;
    career:hasSecondaryHollandCode career:Conventional ;
    :hasRating <https://example.org/rating/job-zone>, <https://example.org/rating/programming> ;
    :hasTask <https://example.org/task/build-models> ;
    :hasJobTitle <https://example.org/job-title/data-scientist> ;
    :hasRelatedOccupation <https://example.org/linkage/related> .

<https://example.org/rating/job-zone> a :JobZoneRating ;
    :ratedJobZone <https://example.org/job-zone/4> ;
    :dataValue "4"^^xsd:integer .

<https://example.org/rating/programming> a :KnowledgeRating ;
    :ratedElement <https://example.org/element/programming> ;
    :ratingScale <https://example.org/scale/importance> ;
    :dataValue "4.0"^^xsd:double .

<https://example.org/element/programming> a :Element ;
    :elementName "Programming" .

<https://example.org/job-zone/4> a :JobZone ;
    :jobZone "4"^^xsd:integer .

<https://example.org/task/build-models> a :Task ;
    :task "Build data models" ;
    :taskID 1 .

<https://example.org/job-title/data-scientist> a :JobTitle ;
    :jobTitle "Data Scientist" .

<https://example.org/linkage/related> a :RelatedOccupationLinkage ;
    :relatedOccupation <https://example.org/occupation/data-analyst> ;
    :relatednessTier "Close" ;
    :relatedIndex 1 .
"""


def write_fixture(tmpdir: str | Path) -> tuple[Path, Path]:
    """Write the fixture ABox and an empty overlay; return their paths."""

    root = Path(tmpdir)
    abox = root / "fixture_abox.ttl"
    overlay = root / "empty_overlay.ttl"
    abox.write_text(FIXTURE_ABOX, encoding="utf-8")
    overlay.write_text("", encoding="utf-8")
    return abox, overlay
