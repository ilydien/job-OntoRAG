"""Dense embedding backend and occupation-card builder.

Semantic retrieval in OntoRAG embeds *occupation cards* built from the
generated SQLite index, never the raw ABox.  The backend is pluggable so the
test suite can run without ``sentence-transformers`` and so another model can
be supplied at build time without touching the pipeline.

Vectors are stored as normalised ``float32`` blobs.  Cosine similarity then
reduces to a dot product.
"""

from __future__ import annotations

import array
import datetime as _dt
import hashlib
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from . import config
from .query_engine import Index

CARD_VERSION = "1"
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_BATCH_SIZE = 32

EMBEDDING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS occupation_embeddings (
    occupation_iri TEXT PRIMARY KEY,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    card_text TEXT,
    card_hash TEXT
);

CREATE TABLE IF NOT EXISTS embedding_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class EmbeddingUnavailable(RuntimeError):
    """Raised when the embedding runtime or model cannot be loaded."""


class EmbeddingBackend(Protocol):
    """Minimal contract shared by real and test embedding backends."""

    name: str
    dim: int
    query_prefix: str
    passage_prefix: str
    normalized: bool

    def encode(self, texts: Sequence[str], kind: str = "passage") -> List[List[float]]:
        ...


@dataclass(frozen=True)
class CardLimits:
    max_tasks: int = 8
    max_elements: int = 12
    max_job_titles: int = 5


def _uses_e5_prefixes(model_name: str) -> bool:
    return "e5" in model_name.lower()


class SentenceTransformerBackend:
    """``sentence-transformers`` backend with e5 query/passage prefixes."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        device: Optional[str] = None,
        max_seq_length: Optional[int] = None,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # ImportError or a broken torch install
            raise EmbeddingUnavailable(
                "sentence-transformers is not installed. "
                "Install it with: pip install -r requirements-embed.txt"
            ) from exc
        self.name = model_name
        self.batch_size = int(batch_size)
        self.normalized = True
        prefixes = _uses_e5_prefixes(model_name)
        self.query_prefix = "query: " if prefixes else ""
        self.passage_prefix = "passage: " if prefixes else ""
        try:
            self._model = SentenceTransformer(model_name, device=device)
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"could not load embedding model {model_name!r}: {exc}"
            ) from exc
        if max_seq_length is not None:
            self._model.max_seq_length = int(max_seq_length)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: Sequence[str], kind: str = "passage") -> List[List[float]]:
        prefix = self.query_prefix if kind == "query" else self.passage_prefix
        prepared = [prefix + (text or "") for text in texts]
        if not prepared:
            return []
        vectors = self._model.encode(
            prepared,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in vectors]


# ---------------------------------------------------------------------------
# Vector packing
# ---------------------------------------------------------------------------

def pack_vector(values: Iterable[float]) -> bytes:
    return array.array("f", [float(value) for value in values]).tobytes()


def unpack_vector(blob: bytes) -> array.array:
    vector = array.array("f")
    vector.frombytes(blob)
    return vector


def normalize_vector(values: Sequence[float]) -> Tuple[float, ...]:
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if norm <= 0.0:
        return tuple(0.0 for _ in values)
    return tuple(float(value) / norm for value in values)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Dot product; inputs are expected to be L2-normalised."""

    return float(sum(float(a) * float(b) for a, b in zip(left, right)))


# ---------------------------------------------------------------------------
# Occupation cards
# ---------------------------------------------------------------------------

def _clean(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _join_unique(values: Iterable[str]) -> str:
    seen: set[str] = set()
    parts: List[str] = []
    for value in values:
        text = _clean(value)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        parts.append(text)
    return ", ".join(parts)


def _element_names(
    elements: Sequence[Mapping[str, object]],
    limit: int,
    language: str,
) -> List[str]:
    best: Dict[str, Tuple[float, str]] = {}
    for row in elements:
        iri = str(row.get("element_iri") or "")
        if not iri:
            continue
        try:
            norm = float(row.get("norm_value")) if row.get("norm_value") is not None else 0.0
        except (TypeError, ValueError):
            norm = 0.0
        name = _clean(
            row.get("element_name_id" if language == "id" else "element_name_en")
            or row.get("element_name_en")
            or row.get("element_name_id")
        )
        if not name:
            continue
        previous = best.get(iri)
        if previous is None or norm > previous[0]:
            best[iri] = (norm, name)
    ordered = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))
    names: List[str] = []
    for _iri, (_norm, name) in ordered:
        if name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def build_card_text(
    summary: Mapping[str, object],
    tasks: Sequence[Mapping[str, object]],
    elements: Sequence[Mapping[str, object]],
    job_titles: Sequence[Mapping[str, object]],
    holland_labels: Mapping[str, Tuple[str, str]],
    limits: CardLimits = CardLimits(),
    language: str = "id",
) -> str:
    """Compose the text document that represents one occupation."""

    lines: List[str] = []

    title_en = _clean(summary.get("title_en"))
    title_id = _clean(summary.get("title_id"))
    if title_en and title_id and title_id.lower() != title_en.lower():
        lines.append(f"Title: {title_en} ({title_id}).")
    elif title_en or title_id:
        lines.append(f"Title: {title_en or title_id}.")

    description_en = _clean(summary.get("description_en"))
    description_id = _clean(summary.get("description_id"))
    if description_en:
        lines.append(f"Description: {description_en}")
    if description_id and description_id != description_en:
        lines.append(f"Deskripsi: {description_id}")

    task_texts: List[str] = []
    for row in tasks[: limits.max_tasks]:
        task_texts.append(
            _clean(row.get("task_id_text") if language == "id" else "")
            or _clean(row.get("task_en"))
            or _clean(row.get("task_id_text"))
        )
    if task_texts:
        lines.append("Typical tasks: " + "; ".join(text for text in task_texts if text) + ".")

    element_names = _element_names(elements, limits.max_elements, language)
    if element_names:
        lines.append("Knowledge, skills, abilities, and activities: " + ", ".join(element_names) + ".")

    holland_parts: List[str] = []
    for key in ("holland_primary", "holland_secondary", "holland_tertiary"):
        code = _clean(summary.get(key))
        if not code:
            continue
        labels = holland_labels.get(code, ("", ""))
        label = labels[1] if language == "id" and labels[1] else labels[0]
        holland_parts.append(_join_unique([code, label]))
    if holland_parts:
        lines.append("Interests (RIASEC): " + "; ".join(holland_parts) + ".")

    title_parts: List[str] = []
    for row in job_titles[: limits.max_job_titles]:
        title_parts.append(_clean(row.get("title_en")))
        title_parts.append(_clean(row.get("title_id")))
    known_as = _join_unique(title_parts)
    if known_as:
        lines.append("Also known as: " + known_as + ".")

    return "\n".join(lines)


def card_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Index-side build
# ---------------------------------------------------------------------------

def _holland_labels(index: Index) -> Dict[str, Tuple[str, str]]:
    labels: Dict[str, Tuple[str, str]] = {}
    for row in index.profile_context():
        if str(row.get("kind") or "") != "holland":
            continue
        local = _clean(row.get("local_name"))
        if local:
            labels[local] = (
                _clean(row.get("label_en")),
                _clean(row.get("label_id")),
            )
    return labels


def _index_fingerprint(meta: Mapping[str, str]) -> str:
    parts = [
        meta.get("built_at", ""),
        meta.get("abox", ""),
        meta.get("abox_size", ""),
        meta.get("abox_mtime", ""),
        meta.get("overlay", ""),
        meta.get("occupations", ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def collect_cards(
    index: Index,
    limits: CardLimits = CardLimits(),
    language: str = "id",
) -> Dict[str, str]:
    """Build one card per indexed occupation."""

    holland = _holland_labels(index)
    cards: Dict[str, str] = {}
    for row in index.embedding_occupations():
        iri = str(row["iri"])
        text = build_card_text(
            row,
            index.tasks(iri, limits.max_tasks),
            index.elements_for(iri),
            index.job_titles(iri, limits.max_job_titles),
            holland,
            limits=limits,
            language=language,
        )
        if text:
            cards[iri] = text
    return cards


def build_embeddings(
    index_path: str | Path = config.DEFAULT_INDEX,
    backend: Optional[EmbeddingBackend] = None,
    model_name: Optional[str] = None,
    batch_size: Optional[int] = None,
    rebuild: bool = False,
    limits: Optional[CardLimits] = None,
    language: str = "id",
    verbose: bool = True,
) -> Dict[str, str]:
    """Embed occupation cards and store them in the index."""

    path = Path(index_path)
    if not path.exists():
        raise FileNotFoundError(
            f"index not found: {path}. Run the build-index command first."
        )
    limits = limits or CardLimits()

    with Index(path) as index:
        index_meta = index.meta()
        existing_meta = index.embedding_meta()
        existing_hashes = {
            str(row["occupation_iri"]): str(row["card_hash"] or "")
            for row in index.embedding_rows()
        }
        cards = collect_cards(index, limits=limits, language=language)

    fingerprint = _index_fingerprint(index_meta)
    model = model_name or (backend.name if backend else DEFAULT_EMBEDDING_MODEL)
    resolved_batch = int(batch_size or (getattr(backend, "batch_size", None) or DEFAULT_BATCH_SIZE))

    if backend is None:
        backend = SentenceTransformerBackend(model, batch_size=resolved_batch)
    if int(backend.dim) <= 0:
        raise EmbeddingUnavailable("embedding backend reported a non-positive dimension")

    hashes = {iri: card_hash(text) for iri, text in cards.items()}
    stale = (
        rebuild
        or not existing_meta
        or existing_meta.get("model") != backend.name
        or existing_meta.get("dim") != str(backend.dim)
        or existing_meta.get("card_version") != CARD_VERSION
        or existing_meta.get("index_fingerprint") != fingerprint
        or existing_hashes != hashes
    )
    if not stale:
        if verbose:
            print(
                f"Embeddings are up to date ({len(cards)} occupations, model {backend.name})",
                file=sys.stderr,
            )
        return dict(existing_meta)

    if verbose:
        print(
            f"Embedding {len(cards)} occupation cards with {backend.name} "
            f"({backend.dim} dimensions, batch {resolved_batch})",
            file=sys.stderr,
        )

    iris = sorted(cards)
    rows: List[Tuple[object, ...]] = []
    for start in range(0, len(iris), resolved_batch):
        batch_iris = iris[start : start + resolved_batch]
        vectors = backend.encode([cards[iri] for iri in batch_iris], kind="passage")
        if len(vectors) != len(batch_iris):
            raise EmbeddingUnavailable(
                f"backend returned {len(vectors)} vectors for {len(batch_iris)} texts"
            )
        for iri, vector in zip(batch_iris, vectors):
            if len(vector) != int(backend.dim):
                raise EmbeddingUnavailable(
                    f"backend returned {len(vector)} dimensions, expected {backend.dim}"
                )
            rows.append(
                (
                    iri,
                    int(backend.dim),
                    pack_vector(normalize_vector(vector)),
                    cards[iri],
                    hashes[iri],
                )
            )
        if verbose:
            print(f"  embedded {min(start + resolved_batch, len(iris))}/{len(iris)}", file=sys.stderr)

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    meta_values = {
        "model": backend.name,
        "dim": str(backend.dim),
        "prefix_query": getattr(backend, "query_prefix", ""),
        "prefix_passage": getattr(backend, "passage_prefix", ""),
        "normalized": "1" if getattr(backend, "normalized", True) else "0",
        "card_version": CARD_VERSION,
        "built_at": now,
        "count": str(len(rows)),
        "index_fingerprint": fingerprint,
    }

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(EMBEDDING_SCHEMA_SQL)
        conn.execute("DELETE FROM occupation_embeddings")
        conn.executemany(
            "INSERT INTO occupation_embeddings"
            "(occupation_iri,dim,vector,card_text,card_hash) VALUES (?,?,?,?,?)",
            rows,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO embedding_meta(key,value) VALUES (?,?)",
            sorted(meta_values.items()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if verbose:
        print(f"Embeddings ready: {path} ({len(rows)} vectors)", file=sys.stderr)
    return meta_values
