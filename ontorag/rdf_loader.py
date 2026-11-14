"""Helpers for reading the project's RDF files without a full RDF store."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

from . import ttl_stream
from .ttl_stream import RDFS_COMMENT, RDFS_LABEL, Term

Labels = Dict[str, Dict[str, str]]


def load_labels(path: Optional[str | Path]) -> tuple[Labels, Labels]:
    """Read language-tagged labels and comments from a Turtle file.

    Returns ``(labels, comments)`` where each is ``{subject_iri: {lang: text}}``.
    The i18n overlay is the intended input; the function is generic.
    """

    labels: Labels = {}
    comments: Labels = {}
    if not path:
        return labels, comments
    path = Path(path)
    if not path.exists():
        return labels, comments
    for subject, predicates in ttl_stream.iter_blocks(path):
        if not subject.is_iri:
            continue
        for term in predicates.get(RDFS_LABEL, []):
            if term.kind == "literal":
                lang = (term.lang or "en").lower()
                labels.setdefault(subject.value, {})[lang] = term.value
        for term in predicates.get(RDFS_COMMENT, []):
            if term.kind == "literal":
                lang = (term.lang or "en").lower()
                comments.setdefault(subject.value, {})[lang] = term.value
    return labels, comments


def best_label(
    labels: Mapping[str, Mapping[str, str]],
    subject: str,
    lang: str = "id",
    fallback: Optional[str] = None,
) -> Optional[str]:
    """Return a label in ``lang`` with English fallback."""

    values = labels.get(subject, {})
    return values.get(lang) or values.get("id") or values.get("en") or fallback


def best_comment(
    comments: Mapping[str, Mapping[str, str]],
    subject: str,
    lang: str = "id",
    fallback: Optional[str] = None,
) -> Optional[str]:
    values = comments.get(subject, {})
    return values.get(lang) or values.get("id") or values.get("en") or fallback


def load_block_map(
    path: str | Path,
    drop_predicates: Optional[set[str]] = None,
) -> Dict[str, Dict[str, list[Term]]]:
    """Load a small Turtle file into ``{subject_iri: predicates}``."""

    result: Dict[str, Dict[str, list[Term]]] = {}
    for subject, predicates in ttl_stream.iter_blocks(path, drop_predicates=drop_predicates):
        if subject.is_iri:
            result[subject.value] = predicates
    return result


def iter_iris(path: str | Path) -> Iterable[str]:
    for subject, _ in ttl_stream.iter_blocks(path):
        if subject.is_iri:
            yield subject.value
