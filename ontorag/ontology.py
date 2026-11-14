"""Lightweight access to the canonical education and Holland vocabularies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

from . import config, ttl_stream
from .rdf_loader import Labels, load_labels
from .ttl_stream import RDF_TYPE, RDFS_LABEL, Term, local_name


@dataclass(frozen=True)
class EducationLevel:
    iri: str
    local: str
    label_en: str
    label_id: Optional[str]
    order: int


@dataclass(frozen=True)
class HollandCode:
    iri: str
    local: str
    label_en: str
    label_id: Optional[str]
    letter: str


class Ontology:
    """Vocabulary loaded from ``onet_schema_en.ttl`` plus optional overlay labels."""

    def __init__(
        self,
        schema_path: str | Path | None = None,
        overlay_path: str | Path | None = None,
    ) -> None:
        self.schema_path = Path(schema_path or (config.SCHEMA_EN if config.SCHEMA_EN.exists() else config.SCHEMA_FALLBACK))
        self.overlay_path = Path(overlay_path) if overlay_path else None
        self.labels: Labels = {}
        self.comments: Labels = {}
        self.education: Dict[str, EducationLevel] = {}
        self.holland: Dict[str, HollandCode] = {}
        self._education_by_iri: Dict[str, EducationLevel] = {}
        self._holland_by_iri: Dict[str, HollandCode] = {}
        self._holland_by_letter: Dict[str, HollandCode] = {}
        self._load()

    def _load(self) -> None:
        if self.overlay_path:
            self.labels, self.comments = load_labels(self.overlay_path)

        education_class = config.CAREER + "EducationLevel"
        holland_class = config.CAREER + "HollandCode"
        level_order = config.CAREER + "levelOrder"
        holland_letter = config.CAREER + "hollandLetter"

        for subject, predicates in ttl_stream.iter_blocks(self.schema_path):
            if not subject.is_iri:
                continue
            subject_types = {t.value for t in predicates.get(RDF_TYPE, []) if t.kind == "iri"}
            if education_class in subject_types:
                order_term = ttl_stream.first(predicates, level_order)
                if order_term is None:
                    continue
                order = int(order_term.python_value())
                label_en = self._label(subject.value, "en") or local_name(subject.value)
                local = local_name(subject.value)
                item = EducationLevel(
                    iri=subject.value,
                    local=local,
                    label_en=label_en,
                    label_id=self._label(subject.value, "id"),
                    order=order,
                )
                self.education[local] = item
                self._education_by_iri[subject.value] = item
            elif holland_class in subject_types:
                letter_term = ttl_stream.first(predicates, holland_letter)
                if letter_term is None:
                    continue
                local = local_name(subject.value)
                item = HollandCode(
                    iri=subject.value,
                    local=local,
                    label_en=self._label(subject.value, "en") or local,
                    label_id=self._label(subject.value, "id"),
                    letter=str(letter_term.python_value()).upper(),
                )
                self.holland[local] = item
                self._holland_by_iri[subject.value] = item
                self._holland_by_letter[item.letter] = item

    def _label(self, subject: str, lang: str) -> Optional[str]:
        values = self.labels.get(subject, {})
        return values.get(lang)

    def education_level(self, key: str | None) -> Optional[EducationLevel]:
        if not key:
            return None
        if key in self.education:
            return self.education[key]
        if key in self._education_by_iri:
            return self._education_by_iri[key]
        # Accept a label in either language.
        target = key.strip().lower()
        for item in self.education.values():
            if item.label_en.lower() == target or (item.label_id or "").lower() == target:
                return item
        return None

    def holland_code(self, key: str | None) -> Optional[HollandCode]:
        if not key:
            return None
        if key in self.holland:
            return self.holland[key]
        if key in self._holland_by_iri:
            return self._holland_by_iri[key]
        upper = key.strip().upper()
        if upper in self._holland_by_letter:
            return self._holland_by_letter[upper]
        target = key.strip().lower()
        for item in self.holland.values():
            if item.label_en.lower() == target or (item.label_id or "").lower() == target:
                return item
        return None

    def education_levels(self) -> Iterable[EducationLevel]:
        return sorted(self.education.values(), key=lambda item: item.order)

    def holland_codes(self) -> Iterable[HollandCode]:
        return sorted(self.holland.values(), key=lambda item: item.letter)

    def education_iri(self, key: str) -> Optional[str]:
        item = self.education_level(key)
        return item.iri if item else None

    def holland_iri(self, key: str) -> Optional[str]:
        item = self.holland_code(key)
        return item.iri if item else None

    def education_order(self, key: str) -> Optional[int]:
        item = self.education_level(key)
        return item.order if item else None

    def education_label(self, key: str, lang: str = "id") -> str:
        item = self.education_level(key)
        if not item:
            return key
        if lang == "id" and item.label_id:
            return item.label_id
        return item.label_en

    def holland_label(self, key: str, lang: str = "id") -> str:
        item = self.holland_code(key)
        if not item:
            return key
        if lang == "id" and item.label_id:
            return item.label_id
        return item.label_en
