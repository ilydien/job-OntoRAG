"""Project paths and RDF namespace constants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PARENT_ROOT = PROJECT_ROOT.parent


def _first_existing(candidates, fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return fallback


# The application folder is self-contained in a deployed copy, while the
# workspace keeps the generated artefacts in the sibling phase folders.
SCHEMA_EN = _first_existing(
    (
        PROJECT_ROOT / "schema" / "onet_schema_en.ttl",
        _PARENT_ROOT / "3. Indonesian Translation" / "i18n" / "onet_schema_en.ttl",
    ),
    PROJECT_ROOT / "schema" / "onet_schema_en.ttl",
)
SCHEMA_FALLBACK = _first_existing(
    (
        PROJECT_ROOT / "onet_schema.ttl",
        _PARENT_ROOT / "2. ABox + TRBox" / "onet_schema.ttl",
    ),
    PROJECT_ROOT / "onet_schema.ttl",
)
ABOX = _first_existing(
    (
        PROJECT_ROOT / "onet_abox.ttl",
        _PARENT_ROOT / "2. ABox + TRBox" / "onet_abox.ttl",
    ),
    PROJECT_ROOT / "onet_abox.ttl",
)
DEFAULT_INDEX = PROJECT_ROOT / "data" / "onet_index.sqlite"
CONFIG_DIR = PROJECT_ROOT / "config"
RULES_DIR = PROJECT_ROOT / "rules"
QUERIES_DIR = PROJECT_ROOT / "queries"
DATA_DIR = PROJECT_ROOT / "data"
ENVIRONMENT_DIR = PROJECT_ROOT / "environment"
# Optional bundled Java runtime used as a fallback by the Pellet reasoner.
BUNDLED_JRE = ENVIRONMENT_DIR / "jre"

DEFAULT_POLICY = CONFIG_DIR / "ranking_policy.ttl"
DEFAULT_INDEX_POLICY = CONFIG_DIR / "index_policy.ttl"
DEFAULT_CONFIG_VOCAB = CONFIG_DIR / "config_vocab.ttl"
DEFAULT_LEXICON = CONFIG_DIR / "lexicon.ttl"

ONET = "https://www.onetcenter.org/rdf/schema/onet/"
CAREER = "https://example.org/career#"
LEX = "https://example.org/lex#"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
SWRL = "http://www.w3.org/2003/11/swrl#"
SWRLB = "http://www.w3.org/2003/11/swrlb#"

ONET_ABOX_IRI = "https://example.org/ontology/onet-abox"
ONET_SCHEMA_IRI = "https://example.org/ontology/onet-schema"

PREFIXES = {
    "": ONET,
    "onet": ONET,
    "career": CAREER,
    "lex": LEX,
    "owl": OWL,
    "rdf": RDF,
    "rdfs": RDFS,
    "xsd": XSD,
    "swrl": SWRL,
    "swrlb": SWRLB,
    "dcterms": "http://purl.org/dc/terms/",
}


@dataclass(frozen=True)
class Paths:
    """Resolved project paths for one command invocation."""

    schema: Path = SCHEMA_EN if SCHEMA_EN.exists() else SCHEMA_FALLBACK
    abox: Path = ABOX
    overlay: Optional[Path] = None
    index: Path = DEFAULT_INDEX
    policy: Path = DEFAULT_POLICY
    index_policy: Path = DEFAULT_INDEX_POLICY
    config_vocab: Path = DEFAULT_CONFIG_VOCAB
    lexicon: Path = DEFAULT_LEXICON
    rules_dir: Path = RULES_DIR
    queries_dir: Path = QUERIES_DIR


def find_overlay(explicit: Optional[str | Path] = None) -> Optional[Path]:
    """Locate the pure Indonesian overlay.

    Preference order:
      1. an explicit path,
      2. ``i18n/onet_i18n_id.ttl``,
      3. the newest ``i18n-*/onet_i18n_id.ttl`` snapshot.
    """

    if explicit:
        path = Path(explicit).expanduser()
        return path if path.exists() else None
    stable = PROJECT_ROOT / "i18n" / "onet_i18n_id.ttl"
    if stable.exists():
        return stable
    candidates = sorted(PROJECT_ROOT.glob("i18n-*/onet_i18n_id.ttl"), reverse=True)
    if candidates:
        return candidates[0]
    workspace = (
        PROJECT_ROOT.parent / "3. Indonesian Translation" / "i18n" / "onet_i18n_id.ttl"
    )
    return workspace if workspace.exists() else None


def resolve_project_path(value: str | Path, base: Path = PROJECT_ROOT) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
