"""Free-text and JSON profile extraction.

The extractor contains no Indonesian keyword list.  Keywords, patterns, and
targets come from ``config/lexicon.ttl``.  Element names come from the O*NET
index built from the ABox.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import config
from .lexicon import Lexicon, LexicalMatch
from .ontology import EducationLevel, HollandCode, Ontology
from .ttl_stream import local_name


@dataclass(frozen=True)
class ElementInfo:
    iri: str
    name_en: str
    name_id: Optional[str]

    @property
    def display(self) -> str:
        return self.name_en


@dataclass(frozen=True)
class InterestInfo:
    iri: str
    label_en: str
    label_id: Optional[str]
    kind: str
    riasec_local: Optional[str]
    riasec_iri: Optional[str]

    @property
    def display(self) -> str:
        return self.label_en


class InterestCatalog:
    """Interest activity/keyword lookup derived from the generated index."""

    def __init__(self, items: Iterable[InterestInfo]) -> None:
        self.by_iri: Dict[str, InterestInfo] = {}
        self.by_label: Dict[str, InterestInfo] = {}
        for item in items:
            self.by_iri[item.iri] = item
            if item.label_en:
                self.by_label.setdefault(item.label_en.lower(), item)
            if item.label_id:
                self.by_label.setdefault(item.label_id.lower(), item)
        self._names = sorted(
            ((label, item) for label, item in self.by_label.items()),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, object]]) -> "InterestCatalog":
        items: List[InterestInfo] = []
        for row in rows:
            iri = str(row.get("iri") or "")
            label_en = str(row.get("label_en") or "")
            label_id = str(row["label_id"]) if row.get("label_id") is not None else None
            kind = str(row.get("kind") or "")
            riasec_local = (
                str(row["riasec_local"]) if row.get("riasec_local") is not None else None
            )
            riasec_iri = (
                str(row["riasec_iri"]) if row.get("riasec_iri") is not None else None
            )
            if iri and label_en:
                items.append(
                    InterestInfo(
                        iri=iri,
                        label_en=label_en,
                        label_id=label_id,
                        kind=kind,
                        riasec_local=riasec_local,
                        riasec_iri=riasec_iri,
                    )
                )
        return cls(items)

    def direct_matches(
        self,
        text: str,
        min_length: int,
        activity_weight: float,
        keyword_weight: float,
    ) -> List[Tuple[InterestInfo, str, int, int, float]]:
        if not text:
            return []
        found: List[Tuple[InterestInfo, str, int, int, float]] = []
        occupied: List[Tuple[int, int]] = []
        for label, item in self._names:
            # O*NET activity labels are full sentences and usually end with a
            # period.  Match the phrase without requiring the user to reproduce
            # that trailing punctuation.
            term = label.rstrip(" .!?,;:")
            if len(term) < min_length:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                if any(not (end <= a or start >= b) for a, b in occupied):
                    continue
                occupied.append((start, end))
                weight = keyword_weight if item.kind == "keyword" else activity_weight
                found.append((item, match.group(0), start, end, weight))
        return sorted(found, key=lambda item: (item[2], item[3]))


class ElementCatalog:
    """Element label lookup derived from the generated index."""

    def __init__(self, elements: Iterable[ElementInfo]) -> None:
        self.by_iri: Dict[str, ElementInfo] = {}
        self.by_label: Dict[str, ElementInfo] = {}
        for item in elements:
            self.by_iri[item.iri] = item
            self.by_label.setdefault(item.name_en.lower(), item)
            if item.name_id:
                self.by_label.setdefault(item.name_id.lower(), item)
        self._names = sorted(
            ((label, item) for label, item in self.by_label.items()),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    @classmethod
    def from_rows(cls, rows: Iterable[Sequence[object]]) -> "ElementCatalog":
        items: List[ElementInfo] = []
        for row in rows:
            if isinstance(row, Mapping):
                iri = str(row.get("iri") or "")
                name_en = str(row.get("name_en") or "")
                name_id = str(row["name_id"]) if row.get("name_id") is not None else None
            else:
                iri = str(row[0])
                name_en = str(row[1] or "")
                name_id = str(row[2]) if len(row) > 2 and row[2] is not None else None
            if iri and name_en:
                items.append(ElementInfo(iri=iri, name_en=name_en, name_id=name_id))
        return cls(items)

    def resolve(self, key: Optional[str]) -> Optional[ElementInfo]:
        if not key:
            return None
        key = key.strip()
        if key in self.by_iri:
            return self.by_iri[key]
        lower = key.lower()
        if lower in self.by_label:
            return self.by_label[lower]
        # Accept a local name / suffix when unique.
        for item in self.by_iri.values():
            if local_name(item.iri).lower() == lower:
                return item
        matches = [
            item
            for label, item in self.by_label.items()
            if lower in label or label in lower
        ]
        unique = {item.iri: item for item in matches}
        if len(unique) == 1:
            return next(iter(unique.values()))
        return None

    def direct_matches(
        self,
        text: str,
        min_length: int,
        weight: float,
    ) -> List[Tuple[ElementInfo, str, int, int, float]]:
        """Find O*NET element names directly in text.

        Longer names win over overlapping shorter names.  This is generic
        catalogue matching, not a hard-coded domain lexicon.
        """

        if not text:
            return []
        found: List[Tuple[ElementInfo, str, int, int, float]] = []
        occupied: List[Tuple[int, int]] = []
        for label, item in self._names:
            # O*NET activity labels are full sentences and usually end with a
            # period.  Match the phrase without requiring the user to reproduce
            # that trailing punctuation.
            term = label.rstrip(" .!?,;:")
            if len(term) < min_length:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                if any(not (end <= a or start >= b) for a, b in occupied):
                    continue
                occupied.append((start, end))
                found.append((item, match.group(0), start, end, weight))
        return sorted(found, key=lambda item: (item[2], item[3]))


@dataclass
class Profile:
    user_iri: str
    language: str = "id"
    education_local: Optional[str] = None
    education_order: Optional[int] = None
    max_job_zone: Optional[int] = None
    holland: Dict[str, float] = field(default_factory=dict)
    elements: Dict[str, float] = field(default_factory=dict)
    element_labels: Dict[str, str] = field(default_factory=dict)
    skill_levels: Dict[str, float] = field(default_factory=dict)
    skill_labels: Dict[str, str] = field(default_factory=dict)
    raw_text: str = ""
    lexical_text: str = ""
    evidence: List[dict] = field(default_factory=list)
    notes: str = ""

    def merged_with(self, other: "Profile") -> "Profile":
        """Merge two profiles, keeping the stronger signal per target."""

        result = Profile(
            user_iri=self.user_iri or other.user_iri,
            language=self.language or other.language,
            education_local=self.education_local or other.education_local,
            education_order=self.education_order,
            max_job_zone=max(
                [value for value in (self.max_job_zone, other.max_job_zone) if value is not None],
                default=None,
            ),
            holland=dict(self.holland),
            elements=dict(self.elements),
            element_labels=dict(self.element_labels),
            skill_levels=dict(self.skill_levels),
            skill_labels=dict(self.skill_labels),
            raw_text="\n".join(part for part in (self.raw_text, other.raw_text) if part),
            lexical_text="\n".join(
                part for part in (self.lexical_text, other.lexical_text) if part
            ),
            evidence=list(self.evidence) + list(other.evidence),
            notes="\n".join(part for part in (self.notes, other.notes) if part),
        )
        for code, weight in other.holland.items():
            result.holland[code] = max(result.holland.get(code, 0.0), weight)
        for iri, weight in other.elements.items():
            result.elements[iri] = max(result.elements.get(iri, 0.0), weight)
        for iri, label in other.element_labels.items():
            result.element_labels.setdefault(iri, label)
        for iri, level in other.skill_levels.items():
            result.skill_levels[iri] = max(result.skill_levels.get(iri, 0.0), level)
        for iri, label in other.skill_labels.items():
            result.skill_labels.setdefault(iri, label)
        if other.education_order is not None:
            if result.education_order is None or other.education_order > result.education_order:
                result.education_local = other.education_local
                result.education_order = other.education_order
        return result

    def to_ttl(self, ontology: Ontology) -> str:
        user = normalize_iri(self.user_iri)
        lines: List[str] = [
            "@prefix : <https://www.onetcenter.org/rdf/schema/onet/> .",
            "@prefix career: <https://example.org/career#> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
            f"<{user}> a career:User ;",
        ]
        body: List[str] = []
        education = ontology.education_level(self.education_local)
        if education:
            body.append(f"    career:hasEducationLevel <{education.iri}>")
        if self.max_job_zone is not None:
            body.append(f"    career:maxJobZone \"{int(self.max_job_zone)}\"^^xsd:integer")
        if not body:
            lines.append(f"<{user}> a career:User .")
        else:
            lines.append("\n    ;\n".join(body) + " .")

        user_local = local_name(user) or "user"
        for code, weight in sorted(self.holland.items()):
            holland = ontology.holland_code(code)
            if not holland:
                continue
            pref = f"career:{sanitize_local(user_local)}_holland_{sanitize_local(holland.local)}"
            lines.extend(
                [
                    "",
                    f"{pref} a career:HollandPreference ;",
                    f"    career:preferenceHollandCode <{holland.iri}> ;",
                    f"    career:preferenceWeight \"{format_decimal(weight)}\"^^xsd:decimal .",
                    f"<{user}> career:hasHollandPreference {pref} .",
                ]
            )

        for iri, weight in sorted(self.elements.items()):
            pref = (
                f"career:{sanitize_local(user_local)}_element_"
                f"{sanitize_local(local_name(iri) or hashlib.sha1(iri.encode()).hexdigest()[:8])}"
            )
            lines.extend(
                [
                    "",
                    f"{pref} a career:ElementPreference ;",
                    f"    career:preferenceElement <{iri}> ;",
                    f"    career:preferenceWeight \"{format_decimal(weight)}\"^^xsd:decimal .",
                    f"<{user}> career:hasElementPreference {pref} .",
                ]
            )

        for iri, level in sorted(self.skill_levels.items()):
            proficiency = (
                f"career:{sanitize_local(user_local)}_skill_"
                f"{sanitize_local(local_name(iri) or hashlib.sha1(iri.encode()).hexdigest()[:8])}"
            )
            lines.extend(
                [
                    "",
                    f"{proficiency} a career:ElementProficiency ;",
                    f"    career:proficiencyElement <{iri}> ;",
                    f"    career:proficiencyLevel \"{float(level):.6f}\"^^xsd:decimal .",
                    f"<{user}> career:hasElementProficiency {proficiency} .",
                ]
            )
        return "\n".join(lines) + "\n"

    @classmethod
    def from_json(
        cls,
        data: dict,
        ontology: Ontology,
        catalog: ElementCatalog,
        language: Optional[str] = None,
        skill_level_min: float = 0.0,
        skill_level_max: float = 7.0,
    ) -> "Profile":
        user_iri = normalize_iri(str(data.get("user_iri") or "user_profile"))
        language = language or str(data.get("language") or "id")
        education_key = data.get("education_level") or data.get("education")
        education = ontology.education_level(str(education_key)) if education_key else None
        if education_key and not education:
            raise ValueError(f"unknown education level: {education_key}")
        max_job_zone = data.get("max_job_zone", data.get("job_zone"))
        if max_job_zone is not None:
            max_job_zone = int(max_job_zone)
            if not 1 <= max_job_zone <= 5:
                raise ValueError("max_job_zone must be between 1 and 5")

        holland: Dict[str, float] = {}
        for key, value in (data.get("holland") or {}).items():
            code = ontology.holland_code(str(key))
            if not code:
                raise ValueError(f"unknown Holland code: {key}")
            weight = float(value)
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"Holland weight out of range for {key}")
            holland[code.local] = max(holland.get(code.local, 0.0), weight)

        elements: Dict[str, float] = {}
        element_labels: Dict[str, str] = {}
        for key, value in (data.get("elements") or {}).items():
            item = catalog.resolve(str(key))
            if not item:
                raise ValueError(f"unknown O*NET element: {key}")
            weight = float(value)
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"element weight out of range for {key}")
            elements[item.iri] = max(elements.get(item.iri, 0.0), weight)
            element_labels[item.iri] = item.display

        skill_levels: Dict[str, float] = {}
        skill_labels: Dict[str, str] = {}
        for key, value in (data.get("skills") or data.get("skill_levels") or {}).items():
            item = catalog.resolve(str(key))
            if not item:
                raise ValueError(f"unknown O*NET element: {key}")
            level = float(value)
            if not skill_level_min <= level <= skill_level_max:
                raise ValueError(
                    f"skill level out of range for {key}: "
                    f"{skill_level_min}..{skill_level_max}"
                )
            skill_levels[item.iri] = max(skill_levels.get(item.iri, 0.0), level)
            skill_labels[item.iri] = item.display

        return cls(
            user_iri=user_iri,
            language=language,
            education_local=education.local if education else None,
            education_order=education.order if education else None,
            max_job_zone=max_job_zone,
            holland=holland,
            elements=elements,
            element_labels=element_labels,
            skill_levels=skill_levels,
            skill_labels=skill_labels,
            raw_text=str(data.get("text") or ""),
            lexical_text=str(data.get("text") or ""),
            evidence=[],
            notes=str(data.get("notes") or ""),
        )

    def add_skill_levels(
        self,
        values: Mapping[str, object],
        catalog: ElementCatalog,
        min_level: float = 0.0,
        max_level: float = 7.0,
    ) -> None:
        for key, value in values.items():
            item = catalog.resolve(str(key))
            if not item:
                raise ValueError(f"unknown O*NET element: {key}")
            level = float(value)
            if not min_level <= level <= max_level:
                raise ValueError(
                    f"skill level out of range for {key}: {min_level}..{max_level}"
                )
            self.skill_levels[item.iri] = max(
                self.skill_levels.get(item.iri, 0.0), level
            )
            self.skill_labels[item.iri] = item.display
            self.evidence.append(
                {
                    "kind": "skill_level",
                    "text": str(key),
                    "target": item.display,
                    "value": level,
                    "source": "profile",
                }
            )

    @classmethod
    def load(
        cls,
        path: str,
        ontology: Ontology,
        catalog: ElementCatalog,
        language: Optional[str] = None,
        skill_level_min: float = 0.0,
        skill_level_max: float = 7.0,
    ) -> "Profile":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("profile JSON must be an object")
        return cls.from_json(
            data,
            ontology,
            catalog,
            language=language,
            skill_level_min=skill_level_min,
            skill_level_max=skill_level_max,
        )


def normalize_iri(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if ":" in value:
        prefix, local = value.split(":", 1)
        namespace = config.PREFIXES.get(prefix)
        if namespace:
            return namespace + local
    return config.CAREER + value


def sanitize_local(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value)
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "item"
    if cleaned[0].isdigit():
        return "n_" + cleaned
    return cleaned


def format_decimal(value: float) -> str:
    return f"{max(0.0, min(1.0, float(value))):.6f}"


def _add(dictionary: Dict[str, float], key: str, value: float) -> None:
    dictionary[key] = min(1.0, dictionary.get(key, 0.0) + value)


def extract_from_text(
    text: str,
    ontology: Ontology,
    lexicon: Lexicon,
    catalog: ElementCatalog,
    language: str = "id",
    user_iri: Optional[str] = None,
    default_education: Optional[str] = None,
    default_max_job_zone: Optional[int] = None,
    direct_element_weight: Optional[float] = None,
    direct_element_min_length: Optional[int] = None,
    interest_catalog: Optional[InterestCatalog] = None,
    interest_activity_weight: Optional[float] = None,
    interest_keyword_weight: Optional[float] = None,
    interest_primary: Optional[bool] = None,
) -> Profile:
    """Extract a profile from free text using the declarative lexicon."""

    if direct_element_weight is None or direct_element_min_length is None:
        raise ValueError(
            "direct_element_weight and direct_element_min_length must come from policy"
        )
    if interest_catalog is not None and (
        interest_activity_weight is None
        or interest_keyword_weight is None
        or interest_primary is None
    ):
        raise ValueError(
            "interest_primary, interest_activity_weight, and "
            "interest_keyword_weight must come from policy"
        )
    matches = lexicon.find(text)

    # Resolve grounded interest cues first.  When the policy makes interest the
    # primary source, oral/lexicon Holland cues are used only if no O*NET
    # activity or keyword matched at all.  Non-interest lexicon cues (education,
    # job zone, elements, negation) remain active in both modes.
    interest_hits: List[Tuple[InterestInfo, str, int, int, float, HollandCode]] = []
    negation_spans = lexicon.negation_spans(text) if interest_catalog else []
    if interest_catalog is not None:
        for item, matched_text, start, end, weight in interest_catalog.direct_matches(
            text,
            min_length=direct_element_min_length,
            activity_weight=interest_activity_weight,
            keyword_weight=interest_keyword_weight,
        ):
            if not item.riasec_local:
                continue
            if any(
                0 <= start - negated_end <= lexicon.negation_window
                for _, negated_end in negation_spans
            ):
                continue
            code = ontology.holland_code(item.riasec_local)
            if code:
                interest_hits.append((item, matched_text, start, end, weight, code))
    use_lexicon_holland = not (interest_primary and interest_hits)
    holland: Dict[str, float] = {}
    elements: Dict[str, float] = {}
    element_labels: Dict[str, str] = {}
    education: Optional[EducationLevel] = ontology.education_level(default_education)
    max_job_zone = default_max_job_zone
    evidence: List[dict] = []

    for match in matches:
        if match.negated:
            continue
        if match.kind in {"holland", "holland_code"} and not use_lexicon_holland:
            continue
        if match.kind == "holland" and match.target:
            code = ontology.holland_code(match.target)
            if code:
                _add(holland, code.local, match.weight)
                evidence.append(
                    {
                        "kind": "holland",
                        "text": match.text,
                        "target": code.local,
                        "weight": match.weight,
                        "start": match.start,
                        "end": match.end,
                        "source": "lexicon",
                    }
                )
        elif match.kind == "holland_code" and match.capture:
            for letter in match.capture.upper():
                code = ontology.holland_code(letter)
                if code:
                    _add(holland, code.local, match.weight)
                    evidence.append(
                        {
                            "kind": "holland_code",
                            "text": match.text,
                            "target": code.local,
                            "weight": match.weight,
                            "start": match.start,
                            "end": match.end,
                            "source": "lexicon",
                        }
                    )
        elif match.kind == "element" and match.target:
            item = catalog.resolve(match.target)
            if item:
                _add(elements, item.iri, match.weight)
                element_labels[item.iri] = item.display
                evidence.append(
                    {
                        "kind": "element",
                        "text": match.text,
                        "target": item.display,
                        "weight": match.weight,
                        "start": match.start,
                        "end": match.end,
                        "source": "lexicon",
                    }
                )
        elif match.kind == "education" and match.target:
            code = ontology.education_level(match.target)
            if code:
                if education is None or code.order > education.order:
                    education = code
                evidence.append(
                    {
                        "kind": "education",
                        "text": match.text,
                        "target": code.local,
                        "weight": match.weight,
                        "start": match.start,
                        "end": match.end,
                        "source": "lexicon",
                    }
                )
        elif match.kind == "job_zone" and match.capture:
            try:
                value = int(match.capture)
            except ValueError:
                continue
            if 1 <= value <= 5:
                max_job_zone = max(max_job_zone or 0, value)
                evidence.append(
                    {
                        "kind": "job_zone",
                        "text": match.text,
                        "target": value,
                        "weight": match.weight,
                        "start": match.start,
                        "end": match.end,
                        "source": "lexicon",
                    }
                )

    for item, matched_text, start, end, weight, code in interest_hits:
        _add(holland, code.local, weight)
        evidence.append(
            {
                "kind": f"interest_{item.kind}",
                "text": matched_text,
                "target": code.local,
                "interest_iri": item.iri,
                "weight": weight,
                "start": start,
                "end": end,
                "source": "interest_catalog",
            }
        )

    element_spans = [
        (item["start"], item["end"])
        for item in evidence
        if item.get("kind") == "element"
    ]
    for item, matched_text, start, end, weight in catalog.direct_matches(
        text,
        min_length=direct_element_min_length,
        weight=direct_element_weight,
    ):
        if any(not (end <= a or start >= b) for a, b in element_spans):
            continue
        _add(elements, item.iri, weight)
        element_labels.setdefault(item.iri, item.display)
        evidence.append(
            {
                "kind": "element",
                "text": matched_text,
                "target": item.display,
                "weight": weight,
                "start": start,
                "end": end,
                "source": "catalog",
            }
        )

    if education is None:
        education = ontology.education_level(default_education)
    if user_iri is None:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        user_iri = f"career:user_{digest}"

    # Keep negated target phrases out of lexical retrieval.  The raw text is
    # preserved for display and audit, while the FTS query uses this masked
    # version.
    masked = list(text)
    for match in matches:
        if not match.negated:
            continue
        for index in range(max(0, match.start), min(len(masked), match.end)):
            masked[index] = " "
    lexical_text = "".join(masked)

    return Profile(
        user_iri=normalize_iri(user_iri),
        language=language,
        education_local=education.local if education else None,
        education_order=education.order if education else None,
        max_job_zone=max_job_zone,
        holland=holland,
        elements=elements,
        element_labels=element_labels,
        raw_text=text,
        lexical_text=lexical_text,
        evidence=evidence,
    )
