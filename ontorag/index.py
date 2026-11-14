"""Streaming O*NET ABox -> SQLite FTS5 index builder."""

from __future__ import annotations

import datetime as _dt
import sqlite3
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import config, ttl_stream
from .ontology import Ontology
from .policy import IndexPolicy, load_index_policy
from .ttl_stream import RDF_TYPE, Term, local_name


@dataclass
class OccupationRecord:
    iri: str
    soc: Optional[str] = None
    title_en: Optional[str] = None
    description_en: Optional[str] = None
    data_status: Optional[str] = None
    education_iri: Optional[str] = None
    holland_primary: Optional[str] = None
    holland_secondary: Optional[str] = None
    holland_tertiary: Optional[str] = None
    ratings: List[str] = field(default_factory=list)
    tasks: List[str] = field(default_factory=list)
    job_titles: List[str] = field(default_factory=list)
    related_linkages: List[str] = field(default_factory=list)
    linked_to: List[str] = field(default_factory=list)


@dataclass
class RatingRecord:
    iri: str
    rating_type: str
    value: Optional[float] = None
    element_iri: Optional[str] = None
    scale_iri: Optional[str] = None
    job_zone_iri: Optional[str] = None
    suppressed: bool = False


@dataclass
class ElementRecord:
    iri: str
    name_en: Optional[str] = None
    description_en: Optional[str] = None


@dataclass
class TaskRecord:
    iri: str
    text_en: Optional[str] = None
    task_id: Optional[int] = None


@dataclass
class JobTitleRecord:
    iri: str
    title_en: Optional[str] = None


@dataclass
class JobZoneRecord:
    iri: str
    zone: Optional[int] = None
    name_en: Optional[str] = None


@dataclass
class LinkageRecord:
    iri: str
    related_iri: Optional[str] = None
    tier: Optional[str] = None
    idx: Optional[int] = None


@dataclass
class ParsedABox:
    occupations: Dict[str, OccupationRecord] = field(default_factory=dict)
    ratings: Dict[str, RatingRecord] = field(default_factory=dict)
    elements: Dict[str, ElementRecord] = field(default_factory=dict)
    tasks: Dict[str, TaskRecord] = field(default_factory=dict)
    job_titles: Dict[str, JobTitleRecord] = field(default_factory=dict)
    job_zones: Dict[str, JobZoneRecord] = field(default_factory=dict)
    linkages: Dict[str, LinkageRecord] = field(default_factory=dict)


DROP_PREDICATES = {
    config.ONET + "hasReportedTitle",
    config.ONET + "hasEmergingTask",
    config.ONET + "hasDWA",
    config.ONET + "refersTo",
    config.ONET + "referencedBy",
    config.ONET + "ratingOf",
    config.ONET + "taskOf",
    config.ONET + "jobTitleOf",
    config.ONET + "relatedOccupationOf",
    config.ONET + "memberOf",
    config.ONET + "n",
    config.ONET + "standardError",
    config.ONET + "lowerCIBound",
    config.ONET + "upperCIBound",
    config.ONET + "dateUpdated",
    config.ONET + "domainSource",
    config.ONET + "sources",
    config.ONET + "shortTitle",
    config.ONET + "shownInMyNextMove",
    config.ONET + "incumbentsResponding",
    config.ONET + "taskType",
    config.ONET + "svpRange",
    config.ONET + "experience",
    config.ONET + "education",
    config.ONET + "jobTraining",
    config.ONET + "examples",
    config.ONET + "scaleID",
    config.ONET + "scaleName",
    config.ONET + "minimum",
    config.ONET + "maximum",
    config.ONET + "ratingCategory",
    config.ONET + "elementID",
}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS occupations (
    iri TEXT PRIMARY KEY,
    soc TEXT,
    title_en TEXT,
    title_id TEXT,
    description_en TEXT,
    description_id TEXT,
    data_status TEXT,
    education_iri TEXT,
    education_local TEXT,
    education_label_en TEXT,
    education_label_id TEXT,
    education_order INTEGER,
    job_zone_iri TEXT,
    job_zone INTEGER,
    job_zone_name_en TEXT,
    job_zone_name_id TEXT,
    holland_primary TEXT,
    holland_secondary TEXT,
    holland_tertiary TEXT
);

CREATE TABLE IF NOT EXISTS occupation_ratings (
    occupation_iri TEXT NOT NULL,
    rating_iri TEXT NOT NULL,
    rating_type TEXT,
    element_iri TEXT,
    element_name_en TEXT,
    element_name_id TEXT,
    scale_iri TEXT,
    value REAL,
    norm_value REAL,
    PRIMARY KEY (occupation_iri, rating_iri)
);

CREATE INDEX IF NOT EXISTS idx_ratings_occupation ON occupation_ratings(occupation_iri);
CREATE INDEX IF NOT EXISTS idx_ratings_element ON occupation_ratings(element_iri);

CREATE TABLE IF NOT EXISTS occupation_tasks (
    occupation_iri TEXT NOT NULL,
    task_iri TEXT NOT NULL,
    task_en TEXT,
    task_id INTEGER,
    task_id_text TEXT,
    PRIMARY KEY (occupation_iri, task_iri)
);

CREATE TABLE IF NOT EXISTS occupation_job_titles (
    occupation_iri TEXT NOT NULL,
    job_title_iri TEXT NOT NULL,
    title_en TEXT,
    title_id TEXT,
    PRIMARY KEY (occupation_iri, job_title_iri)
);

CREATE TABLE IF NOT EXISTS occupation_related (
    occupation_iri TEXT NOT NULL,
    related_iri TEXT NOT NULL,
    tier TEXT,
    idx INTEGER,
    PRIMARY KEY (occupation_iri, related_iri)
);

CREATE TABLE IF NOT EXISTS elements (
    iri TEXT PRIMARY KEY,
    name_en TEXT,
    name_id TEXT,
    description_en TEXT,
    description_id TEXT
);

CREATE TABLE IF NOT EXISTS education_levels (
    local TEXT PRIMARY KEY,
    iri TEXT,
    label_en TEXT,
    label_id TEXT,
    level_order INTEGER
);

CREATE TABLE IF NOT EXISTS holland_codes (
    local TEXT PRIMARY KEY,
    iri TEXT,
    label_en TEXT,
    label_id TEXT,
    letter TEXT
);

CREATE TABLE IF NOT EXISTS job_zones (
    iri TEXT PRIMARY KEY,
    zone INTEGER,
    name_en TEXT,
    name_id TEXT
);
"""


class IndexBuilder:
    def __init__(
        self,
        abox: str | Path = config.ABOX,
        schema: str | Path | None = None,
        overlay: str | Path | None = None,
        index: str | Path = config.DEFAULT_INDEX,
        index_policy: str | Path = config.DEFAULT_INDEX_POLICY,
        verbose: bool = True,
    ) -> None:
        self.abox = Path(abox)
        self.schema = Path(schema or (config.SCHEMA_EN if config.SCHEMA_EN.exists() else config.SCHEMA_FALLBACK))
        self.overlay = Path(overlay) if overlay else config.find_overlay()
        self.index = Path(index)
        self.index_policy_path = Path(index_policy)
        self.verbose = verbose

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr, flush=True)

    def build(self) -> Path:
        if not self.abox.exists():
            raise FileNotFoundError(f"ABox not found: {self.abox}")
        if not self.schema.exists():
            raise FileNotFoundError(f"schema not found: {self.schema}")
        policy = load_index_policy(self.index_policy_path)
        self._log(f"Loading ontology vocabulary from {self.schema}")
        ontology = Ontology(self.schema, self.overlay)
        self._log(f"Streaming ABox from {self.abox}")
        parsed = self._parse_abox(policy)
        self._log(
            "Parsed "
            f"{len(parsed.occupations)} occupations, "
            f"{len(parsed.ratings)} ratings, "
            f"{len(parsed.elements)} elements, "
            f"{len(parsed.tasks)} tasks, "
            f"{len(parsed.job_titles)} job titles"
        )
        config.ensure_parent(self.index)
        tmp = self.index.with_suffix(self.index.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        self._log(f"Writing SQLite index to {tmp}")
        conn = sqlite3.connect(str(tmp))
        try:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-200000")
            conn.executescript(SCHEMA_SQL)
            self._create_fts(conn, policy)
            self._insert_vocabularies(conn, ontology)
            self._insert_occupations(conn, parsed, ontology)
            self._insert_ratings(conn, parsed)
            self._insert_tasks(conn, parsed, ontology)
            self._insert_job_titles(conn, parsed, ontology)
            self._insert_related(conn, parsed)
            self._insert_fts(conn, parsed, ontology)
            self._insert_meta(conn, policy, parsed)
            conn.commit()
            conn.execute("PRAGMA optimize")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if self.index.exists():
            self.index.unlink()
        tmp.replace(self.index)
        self._log(f"Index ready: {self.index}")
        return self.index

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_abox(self, policy: IndexPolicy) -> ParsedABox:
        parsed = ParsedABox()
        indexed_types = set(policy.indexed_rating_types)
        types_by_subject: Dict[str, set[str]] = {}
        count = 0
        for subject, predicates in ttl_stream.iter_blocks(
            self.abox, drop_predicates=DROP_PREDICATES
        ):
            if not subject.is_iri:
                continue
            subject_iri = subject.value
            block_types = {
                local_name(t.value)
                for t in predicates.get(RDF_TYPE, [])
                if t.kind == "iri"
            }
            if block_types:
                types_by_subject.setdefault(subject_iri, set()).update(block_types)
            subject_types = types_by_subject.get(subject_iri, set())
            count += 1
            if count % 200000 == 0:
                self._log(f"  parsed {count:,} blocks...")
            if "Occupation" in subject_types:
                record = OccupationRecord(
                    iri=subject_iri,
                    soc=ttl_stream.literal_value(predicates, config.ONET + "onetSOCCode"),
                    title_en=ttl_stream.literal_value(predicates, config.ONET + "title"),
                    description_en=ttl_stream.literal_value(predicates, config.ONET + "description"),
                    data_status=_local_of_iri(
                        ttl_stream.iri_value(predicates, config.CAREER + "hasDataStatus")
                    ),
                    education_iri=ttl_stream.iri_value(
                        predicates, config.CAREER + "hasMinEducationLevel"
                    ),
                    holland_primary=_local_of_iri(
                        ttl_stream.iri_value(predicates, config.CAREER + "hasPrimaryHollandCode")
                    ),
                    holland_secondary=_local_of_iri(
                        ttl_stream.iri_value(predicates, config.CAREER + "hasSecondaryHollandCode")
                    ),
                    holland_tertiary=_local_of_iri(
                        ttl_stream.iri_value(predicates, config.CAREER + "hasTertiaryHollandCode")
                    ),
                    ratings=ttl_stream.iri_values(predicates, config.ONET + "hasRating"),
                    tasks=ttl_stream.iri_values(predicates, config.ONET + "hasTask"),
                    job_titles=ttl_stream.iri_values(predicates, config.ONET + "hasJobTitle"),
                    related_linkages=ttl_stream.iri_values(
                        predicates, config.ONET + "hasRelatedOccupation"
                    ),
                    linked_to=ttl_stream.iri_values(predicates, config.ONET + "linkedTo"),
                )
                parsed.occupations[subject_iri] = _merge_record(
                    parsed.occupations.get(subject_iri), record
                )
            elif "Element" in subject_types:
                record = ElementRecord(
                    iri=subject_iri,
                    name_en=ttl_stream.literal_value(predicates, config.ONET + "elementName"),
                    description_en=ttl_stream.literal_value(predicates, config.ONET + "description"),
                )
                parsed.elements[subject_iri] = _merge_record(
                    parsed.elements.get(subject_iri), record
                )
            elif "Task" in subject_types:
                task_id = ttl_stream.numeric_value(predicates, config.ONET + "taskID", None)
                record = TaskRecord(
                    iri=subject_iri,
                    text_en=ttl_stream.literal_value(predicates, config.ONET + "task"),
                    task_id=int(task_id) if task_id is not None else None,
                )
                parsed.tasks[subject_iri] = _merge_record(
                    parsed.tasks.get(subject_iri), record
                )
            elif "JobTitle" in subject_types:
                record = JobTitleRecord(
                    iri=subject_iri,
                    title_en=ttl_stream.literal_value(predicates, config.ONET + "jobTitle"),
                )
                parsed.job_titles[subject_iri] = _merge_record(
                    parsed.job_titles.get(subject_iri), record
                )
            elif "JobZone" in subject_types:
                zone = ttl_stream.numeric_value(predicates, config.ONET + "jobZone", None)
                record = JobZoneRecord(
                    iri=subject_iri,
                    zone=int(zone) if zone is not None else None,
                    name_en=ttl_stream.literal_value(predicates, config.ONET + "name"),
                )
                parsed.job_zones[subject_iri] = _merge_record(
                    parsed.job_zones.get(subject_iri), record
                )
            elif "RelatedOccupationLinkage" in subject_types:
                idx = ttl_stream.numeric_value(predicates, config.ONET + "relatedIndex", None)
                record = LinkageRecord(
                    iri=subject_iri,
                    related_iri=ttl_stream.iri_value(
                        predicates, config.ONET + "relatedOccupation"
                    ),
                    tier=ttl_stream.literal_value(
                        predicates, config.ONET + "relatednessTier"
                    ),
                    idx=int(idx) if idx is not None else None,
                )
                parsed.linkages[subject_iri] = _merge_record(
                    parsed.linkages.get(subject_iri), record
                )
            else:
                rating_type = next((t for t in subject_types if t in indexed_types), None)
                if rating_type or "JobZoneRating" in subject_types:
                    rated_element = ttl_stream.iri_value(
                        predicates, config.ONET + "ratedElement"
                    )
                    rated_zone = ttl_stream.iri_value(
                        predicates, config.ONET + "ratedJobZone"
                    )
                    value = ttl_stream.numeric_value(
                        predicates, config.ONET + "dataValue", None
                    )
                    suppressed_term = ttl_stream.first(
                        predicates, config.ONET + "recommendSuppress"
                    )
                    suppressed = bool(suppressed_term.python_value()) if suppressed_term else False
                    record = RatingRecord(
                        iri=subject_iri,
                        rating_type=rating_type or "JobZoneRating",
                        value=value,
                        element_iri=rated_element,
                        scale_iri=ttl_stream.iri_value(
                            predicates, config.ONET + "ratingScale"
                        ),
                        job_zone_iri=rated_zone,
                        suppressed=suppressed,
                    )
                    parsed.ratings[subject_iri] = _merge_record(
                        parsed.ratings.get(subject_iri), record
                    )
        self._log(f"  parsed {count:,} total blocks")
        return parsed

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def _create_fts(self, conn: sqlite3.Connection, policy: IndexPolicy) -> None:
        tokenize = policy.fts_tokenize.replace("'", "''")
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS occupation_fts USING fts5("
            "occupation_iri UNINDEXED, title, description, tasks, elements, job_titles, holland, "
            f"tokenize='{tokenize}'"
            ")"
        )

    def _insert_vocabularies(self, conn: sqlite3.Connection, ontology: Ontology) -> None:
        for level in ontology.education_levels():
            conn.execute(
                "INSERT OR REPLACE INTO education_levels(local, iri, label_en, label_id, level_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (level.local, level.iri, level.label_en, level.label_id, level.order),
            )
        for code in ontology.holland_codes():
            conn.execute(
                "INSERT OR REPLACE INTO holland_codes(local, iri, label_en, label_id, letter) "
                "VALUES (?, ?, ?, ?, ?)",
                (code.local, code.iri, code.label_en, code.label_id, code.letter),
            )

    def _insert_occupations(
        self, conn: sqlite3.Connection, parsed: ParsedABox, ontology: Ontology
    ) -> None:
        labels = ontology.labels
        comments = ontology.comments
        for record in parsed.occupations.values():
            education = ontology.education_level(record.education_iri)
            job_zone_iri = None
            for rating_iri in record.ratings:
                rating = parsed.ratings.get(rating_iri)
                if rating and rating.rating_type == "JobZoneRating":
                    job_zone_iri = rating.job_zone_iri
                    break
            job_zone = parsed.job_zones.get(job_zone_iri or "")
            title_id = labels.get(record.iri, {}).get("id")
            description_id = comments.get(record.iri, {}).get("id")
            job_zone_name_id = labels.get(job_zone_iri or "", {}).get("id")
            conn.execute(
                "INSERT OR REPLACE INTO occupations("
                "iri,soc,title_en,title_id,description_en,description_id,data_status,"
                "education_iri,education_local,education_label_en,education_label_id,education_order,"
                "job_zone_iri,job_zone,job_zone_name_en,job_zone_name_id,"
                "holland_primary,holland_secondary,holland_tertiary"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.iri,
                    record.soc,
                    record.title_en,
                    title_id,
                    record.description_en,
                    description_id,
                    record.data_status,
                    record.education_iri,
                    education.local if education else _local_of_iri(record.education_iri),
                    education.label_en if education else _local_of_iri(record.education_iri),
                    education.label_id if education else None,
                    education.order if education else None,
                    job_zone_iri,
                    job_zone.zone if job_zone else None,
                    job_zone.name_en if job_zone else None,
                    job_zone_name_id,
                    record.holland_primary,
                    record.holland_secondary,
                    record.holland_tertiary,
                ),
            )
        for iri, zone in parsed.job_zones.items():
            conn.execute(
                "INSERT OR REPLACE INTO job_zones(iri, zone, name_en, name_id) VALUES (?,?,?,?)",
                (iri, zone.zone, zone.name_en, labels.get(iri, {}).get("id")),
            )
        for iri, element in parsed.elements.items():
            conn.execute(
                "INSERT OR REPLACE INTO elements(iri,name_en,name_id,description_en,description_id) "
                "VALUES (?,?,?,?,?)",
                (
                    iri,
                    element.name_en,
                    labels.get(iri, {}).get("id"),
                    element.description_en,
                    comments.get(iri, {}).get("id"),
                ),
            )

    def _insert_ratings(self, conn: sqlite3.Connection, parsed: ParsedABox) -> None:
        rows: List[Tuple[object, ...]] = []
        stats: Dict[Tuple[str, str, str], List[float]] = {}
        for occupation in parsed.occupations.values():
            for rating_iri in occupation.ratings:
                rating = parsed.ratings.get(rating_iri)
                if not rating or rating.rating_type == "JobZoneRating" or rating.suppressed:
                    continue
                if rating.value is None or not rating.element_iri:
                    continue
                key = (rating.element_iri, rating.rating_type, rating.scale_iri or "")
                stats.setdefault(key, []).append(float(rating.value))
        bounds = {
            key: (min(values), max(values))
            for key, values in stats.items()
            if values
        }
        for occupation in parsed.occupations.values():
            for rating_iri in occupation.ratings:
                rating = parsed.ratings.get(rating_iri)
                if not rating or rating.rating_type == "JobZoneRating" or rating.suppressed:
                    continue
                if rating.value is None or not rating.element_iri:
                    continue
                key = (rating.element_iri, rating.rating_type, rating.scale_iri or "")
                low, high = bounds.get(key, (rating.value, rating.value))
                if high > low:
                    norm = (float(rating.value) - low) / (high - low)
                else:
                    norm = 0.5
                element = parsed.elements.get(rating.element_iri)
                rows.append(
                    (
                        occupation.iri,
                        rating.iri,
                        rating.rating_type,
                        rating.element_iri,
                        element.name_en if element else None,
                        None,
                        rating.scale_iri,
                        float(rating.value),
                        max(0.0, min(1.0, norm)),
                    )
                )
        # Element Indonesian names are filled by a short update after insert.
        conn.executemany(
            "INSERT OR REPLACE INTO occupation_ratings("
            "occupation_iri,rating_iri,rating_type,element_iri,element_name_en,"
            "element_name_id,scale_iri,value,norm_value) VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )

    def _insert_tasks(
        self, conn: sqlite3.Connection, parsed: ParsedABox, ontology: Ontology
    ) -> None:
        labels = ontology.labels
        for occupation in parsed.occupations.values():
            for task_iri in occupation.tasks:
                task = parsed.tasks.get(task_iri)
                if not task:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO occupation_tasks("
                    "occupation_iri,task_iri,task_en,task_id,task_id_text) VALUES (?,?,?,?,?)",
                    (
                        occupation.iri,
                        task_iri,
                        task.text_en,
                        task.task_id,
                        labels.get(task_iri, {}).get("id"),
                    ),
                )

    def _insert_job_titles(
        self, conn: sqlite3.Connection, parsed: ParsedABox, ontology: Ontology
    ) -> None:
        labels = ontology.labels
        for occupation in parsed.occupations.values():
            for title_iri in occupation.job_titles:
                title = parsed.job_titles.get(title_iri)
                if not title:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO occupation_job_titles("
                    "occupation_iri,job_title_iri,title_en,title_id) VALUES (?,?,?,?)",
                    (
                        occupation.iri,
                        title_iri,
                        title.title_en,
                        labels.get(title_iri, {}).get("id"),
                    ),
                )

    def _insert_related(self, conn: sqlite3.Connection, parsed: ParsedABox) -> None:
        for occupation in parsed.occupations.values():
            seen: Set[str] = set()
            for linkage_iri in occupation.related_linkages:
                linkage = parsed.linkages.get(linkage_iri)
                if not linkage or not linkage.related_iri:
                    continue
                seen.add(linkage.related_iri)
                conn.execute(
                    "INSERT OR REPLACE INTO occupation_related("
                    "occupation_iri,related_iri,tier,idx) VALUES (?,?,?,?)",
                    (
                        occupation.iri,
                        linkage.related_iri,
                        linkage.tier,
                        linkage.idx,
                    ),
                )
            for related_iri in occupation.linked_to:
                if related_iri in seen:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO occupation_related("
                    "occupation_iri,related_iri,tier,idx) VALUES (?,?,?,?)",
                    (occupation.iri, related_iri, "linkedTo", None),
                )

    def _insert_fts(
        self, conn: sqlite3.Connection, parsed: ParsedABox, ontology: Ontology
    ) -> None:
        labels = ontology.labels
        comments = ontology.comments
        for occupation in parsed.occupations.values():
            title_parts = [occupation.title_en or "", labels.get(occupation.iri, {}).get("id", "")]
            description_parts = [
                occupation.description_en or "",
                comments.get(occupation.iri, {}).get("id", ""),
            ]
            task_parts: List[str] = []
            element_parts: List[str] = []
            title_job_parts: List[str] = []
            for task_iri in occupation.tasks:
                task = parsed.tasks.get(task_iri)
                if task:
                    task_parts.append(task.text_en or "")
                    task_parts.append(labels.get(task_iri, {}).get("id", ""))
            for rating_iri in occupation.ratings:
                rating = parsed.ratings.get(rating_iri)
                if not rating or rating.rating_type == "JobZoneRating" or not rating.element_iri:
                    continue
                element = parsed.elements.get(rating.element_iri)
                if element:
                    element_parts.append(element.name_en or "")
                    element_parts.append(labels.get(rating.element_iri, {}).get("id", ""))
            for title_iri in occupation.job_titles:
                title = parsed.job_titles.get(title_iri)
                if title:
                    title_job_parts.append(title.title_en or "")
                    title_job_parts.append(labels.get(title_iri, {}).get("id", ""))
            holland_parts: List[str] = []
            for local in (
                occupation.holland_primary,
                occupation.holland_secondary,
                occupation.holland_tertiary,
            ):
                code = ontology.holland_code(local)
                if code:
                    holland_parts.extend([code.label_en, code.label_id or ""])
            conn.execute(
                "INSERT INTO occupation_fts("
                "occupation_iri,title,description,tasks,elements,job_titles,holland"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    occupation.iri,
                    " ".join(part for part in title_parts if part),
                    " ".join(part for part in description_parts if part),
                    " ".join(part for part in task_parts if part),
                    " ".join(part for part in element_parts if part),
                    " ".join(part for part in title_job_parts if part),
                    " ".join(part for part in holland_parts if part),
                ),
            )
        # Backfill Indonesian element labels.
        conn.execute(
            "UPDATE occupation_ratings AS r "
            "SET element_name_id = (SELECT e.name_id FROM elements AS e WHERE e.iri = r.element_iri) "
            "WHERE r.element_name_id IS NULL"
        )

    def _insert_meta(
        self, conn: sqlite3.Connection, policy: IndexPolicy, parsed: ParsedABox
    ) -> None:
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        values = {
            "built_at": now,
            "index_version": policy.index_version,
            "schema": str(self.schema),
            "abox": str(self.abox),
            "abox_size": str(self.abox.stat().st_size),
            "abox_mtime": str(int(self.abox.stat().st_mtime)),
            "overlay": str(self.overlay or ""),
            "occupations": str(len(parsed.occupations)),
            "ratings": str(
                conn.execute("SELECT COUNT(*) FROM occupation_ratings").fetchone()[0]
            ),
            "parsed_ratings": str(len(parsed.ratings)),
            "elements": str(len(parsed.elements)),
            "tasks": str(len(parsed.tasks)),
            "job_titles": str(len(parsed.job_titles)),
            "indexed_rating_types": ",".join(policy.indexed_rating_types),
        }
        conn.executemany(
            "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
            sorted(values.items()),
        )


def _local_of_iri(value: Optional[str]) -> Optional[str]:
    return local_name(value) if value else None


def _merge_record(existing, new):
    """Merge two records of the same dataclass shape.

    The full ABox uses one subject block per record, while validation samples
    use one triple per line.  Merging makes the builder work with both.
    """
    if existing is None:
        return new
    for item in fields(existing):
        old_value = getattr(existing, item.name)
        new_value = getattr(new, item.name)
        if isinstance(new_value, list):
            if not isinstance(old_value, list):
                setattr(existing, item.name, list(new_value))
                continue
            for value in new_value:
                if value not in old_value:
                    old_value.append(value)
        elif old_value is None and new_value is not None:
            setattr(existing, item.name, new_value)
    return existing


def build_index(
    abox: str | Path = config.ABOX,
    schema: str | Path | None = None,
    overlay: str | Path | None = None,
    index: str | Path = config.DEFAULT_INDEX,
    index_policy: str | Path = config.DEFAULT_INDEX_POLICY,
    verbose: bool = True,
) -> Path:
    return IndexBuilder(
        abox=abox,
        schema=schema,
        overlay=overlay,
        index=index,
        index_policy=index_policy,
        verbose=verbose,
    ).build()
