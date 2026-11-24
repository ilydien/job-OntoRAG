"""Declarative lexicon loading and free-text matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import config, ttl_stream
from .rdf_loader import load_block_map
from .ttl_stream import RDF_TYPE, local_name


@dataclass(frozen=True)
class LexicalEntry:
    iri: str
    name: str
    keywords: tuple[str, ...]
    patterns: tuple[str, ...]
    target_kind: str
    target: Optional[str]
    weight: float


@dataclass(frozen=True)
class LexicalMatch:
    kind: str
    target: Optional[str]
    weight: float
    text: str
    start: int
    end: int
    negated: bool = False
    capture: Optional[str] = None


class Lexicon:
    """A collection of declarative lexical entries."""

    def __init__(self, entries: Iterable[LexicalEntry], negation_window: int) -> None:
        self.entries = list(entries)
        self.negation_window = negation_window
        self.negation_markers = [
            keyword
            for entry in self.entries
            if entry.target_kind == "negation"
            for keyword in entry.keywords
        ]
        self._keyword_res = {
            (entry.iri, keyword): re.compile(
                r"(?<!\w)" + re.escape(keyword) + r"(?!\w)",
                re.IGNORECASE,
            )
            for entry in self.entries
            for keyword in entry.keywords
        }
        self._pattern_res = {
            (entry.iri, pattern): re.compile(
                pattern,
                0 if entry.target_kind == "holland_code" else re.IGNORECASE,
            )
            for entry in self.entries
            for pattern in entry.patterns
        }

    @classmethod
    def load(cls, path: str | Path = config.DEFAULT_LEXICON) -> "Lexicon":
        blocks = load_block_map(path)
        entries: List[LexicalEntry] = []
        negation_window = 0
        entry_type = config.LEX + "LexicalEntry"
        for subject, predicates in blocks.items():
            subject_types = {t.value for t in predicates.get(RDF_TYPE, []) if t.kind == "iri"}
            if entry_type not in subject_types and not predicates.get(config.LEX + "targetKind"):
                continue
            keywords = tuple(
                dict.fromkeys(
                    t.value
                    for t in predicates.get(config.LEX + "keyword", [])
                    if t.kind == "literal" and t.value.strip()
                )
            )
            patterns = tuple(
                dict.fromkeys(
                    t.value
                    for t in predicates.get(config.LEX + "pattern", [])
                    if t.kind == "literal" and t.value.strip()
                )
            )
            target_kind = ttl_stream.literal_value(
                predicates, config.LEX + "targetKind", ""
            ) or ""
            target = ttl_stream.literal_value(predicates, config.LEX + "target", None)
            weight = ttl_stream.numeric_value(predicates, config.LEX + "weight", 1.0)
            if target_kind == "negation":
                window = ttl_stream.numeric_value(
                    predicates, config.LEX + "negationWindow", None
                )
                if window is None:
                    raise ValueError(f"negation entry {subject} has no lex:negationWindow")
                negation_window = int(window)
            label = ttl_stream.literal_value(predicates, config.RDFS + "label", local_name(subject))
            entries.append(
                LexicalEntry(
                    iri=subject,
                    name=label or local_name(subject),
                    keywords=keywords,
                    patterns=patterns,
                    target_kind=target_kind,
                    target=target,
                    weight=float(weight if weight is not None else 1.0),
                )
            )
        if negation_window <= 0:
            raise ValueError(f"lexicon {path} defines no positive lex:negationWindow")
        return cls(entries, negation_window)

    def negation_spans(self, text: str) -> List[tuple[int, int]]:
        """Return spans for declared negation markers in ``text``.

        This is used by non-lexicon extractors (notably the O*NET interest
        catalogue) so they observe the same negation window as lexicon cues.
        """

        spans: List[tuple[int, int]] = []
        for entry in self.entries:
            if entry.target_kind != "negation":
                continue
            for keyword in entry.keywords:
                regex = self._keyword_res[(entry.iri, keyword)]
                spans.extend((match.start(), match.end()) for match in regex.finditer(text))
            for pattern in entry.patterns:
                regex = self._pattern_res[(entry.iri, pattern)]
                spans.extend((match.start(), match.end()) for match in regex.finditer(text))
        return spans

    def find(self, text: str) -> List[LexicalMatch]:
        """Return all lexicon matches, including negation markers."""

        raw: List[LexicalMatch] = []
        for entry in self.entries:
            for keyword in entry.keywords:
                regex = self._keyword_res[(entry.iri, keyword)]
                for match in regex.finditer(text):
                    raw.append(
                        LexicalMatch(
                            kind=entry.target_kind,
                            target=entry.target,
                            weight=entry.weight,
                            text=match.group(0),
                            start=match.start(),
                            end=match.end(),
                        )
                    )
            for pattern in entry.patterns:
                regex = self._pattern_res[(entry.iri, pattern)]
                for match in regex.finditer(text):
                    capture = None
                    if match.lastindex:
                        capture = match.group(1)
                    raw.append(
                        LexicalMatch(
                            kind=entry.target_kind,
                            target=entry.target,
                            weight=entry.weight,
                            text=match.group(0),
                            start=match.start(),
                            end=match.end(),
                            capture=capture,
                        )
                    )

        # A keyword and a pattern can describe the same span (for example a
        # spelling variant plus its normalized form).  Keep one match per
        # target/span, preferring the stronger weight.
        deduped: Dict[tuple, LexicalMatch] = {}
        for match in raw:
            key = (match.kind, match.target, match.start, match.end, match.capture)
            previous = deduped.get(key)
            if previous is None or match.weight > previous.weight:
                deduped[key] = match
        raw = list(deduped.values())

        # Prefer the longest phrase for the same target.  Without this,
        # "ekplorasi data" would also fire inside the longer match
        # "menganalisis dan ekplorasi data" and inflate the evidence weight.
        ordered = sorted(
            raw,
            key=lambda item: (item.start, -(item.end - item.start), item.end),
        )
        kept: List[LexicalMatch] = []
        for match in ordered:
            overlaps = any(
                previous.kind == match.kind
                and previous.target == match.target
                and not (match.end <= previous.start or match.start >= previous.end)
                for previous in kept
            )
            if not overlaps:
                kept.append(match)
        raw = kept

        negations = [match for match in raw if match.kind == "negation"]
        result: List[LexicalMatch] = []
        for match in raw:
            if match.kind == "negation":
                continue
            negated = False
            for negation in negations:
                # A negation marker immediately before a phrase suppresses it.
                if 0 <= match.start - negation.end <= self.negation_window:
                    negated = True
                    break
            result.append(
                LexicalMatch(
                    kind=match.kind,
                    target=match.target,
                    weight=match.weight,
                    text=match.text,
                    start=match.start,
                    end=match.end,
                    negated=negated,
                    capture=match.capture,
                )
            )
        return sorted(result, key=lambda item: (item.start, item.end, item.kind))
