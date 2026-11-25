"""Read-only access to the generated SQLite FTS5 index."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from . import config
from .extraction import Profile
from .policy import RankingPolicy, RequirementCategory


class Index:
    def __init__(self, path: str | Path = config.DEFAULT_INDEX, queries_dir: str | Path = config.QUERIES_DIR) -> None:
        self.path = Path(path)
        self.queries_dir = Path(queries_dir)
        if not self.path.exists():
            raise FileNotFoundError(
                f"index not found: {self.path}. Run the build-index command first."
            )
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self._sql_cache: Dict[str, str] = {}
        if not self._has_fts5():
            raise RuntimeError("this SQLite build does not provide FTS5 support")

    def _has_fts5(self) -> bool:
        try:
            row = self.conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()
            if row and int(row[0]) == 1:
                return True
        except sqlite3.DatabaseError:
            pass
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS temp.__fts5_probe USING fts5(x)"
            )
            self.conn.execute("DROP TABLE temp.__fts5_probe")
            return True
        except sqlite3.DatabaseError:
            return False

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Index":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def sql(self, filename: str) -> str:
        if filename not in self._sql_cache:
            path = self.queries_dir / filename
            self._sql_cache[filename] = path.read_text(encoding="utf-8")
        return self._sql_cache[filename]

    def query(self, filename: str, params: Mapping[str, object] | None = None) -> List[sqlite3.Row]:
        return list(self.conn.execute(self.sql(filename), dict(params or {})))

    def meta(self) -> Dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM meta").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def candidates(
        self,
        profile: Profile,
        policy: RankingPolicy,
        require_complete: bool = True,
        limit: Optional[int] = None,
    ) -> List[dict]:
        rows = self.query(
            "eligible_occupations.sql",
            {
                "require_complete": 1 if require_complete else 0,
                "require_eligible": 1 if policy.require_eligible else 0,
                "education_order": profile.education_order,
                "max_job_zone": profile.max_job_zone,
                "limit": int(limit or policy.candidate_limit),
            },
        )
        return [dict(row) for row in rows]

    @staticmethod
    def fts_query(text: str, min_token_length: int) -> Optional[str]:
        tokens = re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)
        tokens = [token for token in tokens if len(token) >= min_token_length]
        if not tokens:
            return None
        # Deduplicate while preserving order; quote each term so user input
        # cannot inject FTS5 operators.
        seen = set()
        parts: List[str] = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            safe = token.replace('"', '""')
            parts.append(f'"{safe}"')
        return " OR ".join(parts)

    def lexical_scores(self, text: str, limit: int, min_token_length: int) -> Dict[str, float]:
        query = self.fts_query(text, min_token_length)
        if not query:
            return {}
        rows = self.query(
            "lexical_candidates.sql",
            {"query": query, "limit": int(limit)},
        )
        scores: Dict[str, float] = {}
        for row in rows:
            rank = float(row["rank"])
            scores[str(row["occupation_iri"])] = -rank
        return scores

    def elements_for(self, occupation_iri: str) -> List[dict]:
        rows = self.query(
            "occupation_elements.sql",
            {"occupation_iri": occupation_iri},
        )
        return [dict(row) for row in rows]

    def elements_for_many(
        self,
        occupation_iris: Iterable[str],
        element_iris: Optional[Iterable[str]] = None,
    ) -> Dict[str, List[dict]]:
        """Batch-load element ratings for several occupations at once.

        Scoring a whole candidate pool used to issue one query per
        occupation.  Passing the profile's element IRIs keeps the result
        small, so this is the cheap path for large pools.

        Returns a mapping keyed by occupation IRI; occupations with no
        matching rows map to an empty list.
        """

        unique = [str(iri) for iri in dict.fromkeys(occupation_iris) if iri]
        result: Dict[str, List[dict]] = {iri: [] for iri in unique}
        if not unique:
            return result
        elements = [str(iri) for iri in dict.fromkeys(element_iris or ()) if iri]
        template = self.sql("occupation_elements_bulk.sql")
        # Keep combined bind variables below SQLite's default 999 limit.
        chunk_size = 400 if not elements else max(1, 900 - len(elements))
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            if elements:
                element_filter = "AND r.element_iri IN ({})".format(
                    ",".join("?" for _ in elements)
                )
            else:
                element_filter = ""
            sql = template.format(
                placeholders=placeholders, element_filter=element_filter
            )
            params: List[str] = list(chunk)
            if elements:
                params.extend(elements)
            for row in self.conn.execute(sql, params):
                result[str(row["occupation_iri"])].append(dict(row))
        return result

    def related_for_many(self, occupation_iris: Iterable[str]) -> Dict[str, List[str]]:
        """Batch-load related-occupation edges for several occupations at once.

        Returns a mapping keyed by occupation IRI; occupations with no edges
        map to an empty list.
        """

        unique = [str(iri) for iri in dict.fromkeys(occupation_iris) if iri]
        result: Dict[str, List[str]] = {iri: [] for iri in unique}
        if not unique:
            return result
        template = self.sql("occupation_related_bulk.sql")
        chunk_size = 900
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            sql = template.format(placeholders=placeholders)
            for row in self.conn.execute(sql, chunk):
                result[str(row["occupation_iri"])].append(str(row["related_iri"]))
        return result

    def occupation_profile(
        self,
        occupation_iri: str,
        language: str = "id",
        groups: Optional[Iterable[object]] = None,
        core_task_type: str = "Core",
        relevance_scale_id: str = "RT",
        frequency_scale_id: str = "FT",
    ) -> Optional[dict]:
        """Return task, qualification, and work-context facts for one occupation.

        Task frequency ratings are category distributions.  For each task we
        keep the strongest category and expose the full distribution is not
        needed for the usual counselling question.
        """

        summary = self.summary(occupation_iri)
        if not summary:
            return None
        lang = (language or "id").lower()
        task_rows = self.query(
            "occupation_tasks_profile.sql", {"occupation_iri": occupation_iri}
        )
        tasks: Dict[str, dict] = {}
        for row in task_rows:
            task_iri = str(row["task_iri"])
            item = tasks.setdefault(
                task_iri,
                {
                    "iri": task_iri,
                    "task": (
                        row["task_id_text"]
                        if lang == "id" and row["task_id_text"]
                        else row["task_en"]
                    ),
                    "task_en": row["task_en"],
                    "task_id": row["task_id_text"],
                    "task_type": row["task_type"],
                    "frequency": None,
                    "frequency_percent": None,
                    "relevance_percent": None,
                },
            )
            value = row["value"]
            if value is None:
                continue
            if row["rating_scale_id"] == relevance_scale_id:
                if item["relevance_percent"] is None or float(value) > float(
                    item["relevance_percent"]
                ):
                    item["relevance_percent"] = value
            elif row["rating_scale_id"] == frequency_scale_id and (
                item["frequency_percent"] is None
                or float(value) > float(item["frequency_percent"])
            ):
                item["frequency"] = row["category_description"]
                item["frequency_percent"] = value
        dwa_rows = self.query(
            "occupation_task_dwa.sql", {"occupation_iri": occupation_iri}
        )
        dwa_by_task: Dict[str, List[dict]] = {}
        for row in dwa_rows:
            dwa_by_task.setdefault(str(row["task_iri"]), []).append(
                {
                    "iri": row["dwa_element_iri"],
                    "label_en": row["dwa_element_en"],
                    "label_id": row["dwa_element_id"],
                    "label": (
                        row["dwa_element_id"]
                        if lang == "id" and row["dwa_element_id"]
                        else row["dwa_element_en"]
                    ),
                }
            )
        for task_iri, item in tasks.items():
            item["dwa"] = dwa_by_task.get(task_iri, [])
        task_list = sorted(
            tasks.values(),
            key=lambda item: (
                0
                if (item.get("task_type") or "").lower()
                == core_task_type.lower()
                else 1,
                -(
                    float(
                        item.get("relevance_percent")
                        or item.get("frequency_percent")
                        or 0.0
                    )
                ),
                item.get("task") or "",
            ),
        )

        profile_rows = self.query(
            "occupation_profile_ratings.sql", {"occupation_iri": occupation_iri}
        )
        sections: Dict[str, Dict[str, dict]] = {}
        for row in profile_rows:
            rating_type = str(row["rating_type"])
            element_iri = str(row["element_iri"] or "")
            section = sections.setdefault(rating_type, {})
            element = section.setdefault(
                element_iri,
                {
                    "iri": element_iri,
                    "label_en": row["element_en"],
                    "label_id": row["element_id"],
                    "label": (
                        row["element_id"]
                        if lang == "id" and row["element_id"]
                        else row["element_en"]
                    ),
                    "items": [],
                },
            )
            element["items"].append(
                {
                    "category_iri": row["category_iri"],
                    "category": row["category"],
                    "label": row["category_description"],
                    "value": row["value"],
                    "n": row["n"],
                }
            )
        profile_sections = []
        for rating_type in sorted(sections):
            elements = list(sections[rating_type].values())
            elements.sort(key=lambda item: item.get("label") or "")
            profile_sections.append(
                {"key": rating_type, "elements": elements}
            )
        education = next(
            (item for item in profile_sections if item["key"] == "EducationRating"),
            None,
        )
        training = next(
            (
                item
                for item in profile_sections
                if item["key"] == "TrainingAndExperienceRating"
            ),
            None,
        )
        work_context = next(
            (item for item in profile_sections if item["key"] == "WorkContextRating"),
            None,
        )
        work_styles = next(
            (item for item in profile_sections if item["key"] == "WorkStylesRating"),
            None,
        )
        element_lookup: Dict[str, dict] = {}
        for section in profile_sections:
            for element in section["elements"]:
                element_lookup[element["iri"]] = element
        context_groups = []
        for group in groups or ():
            elements = [
                element_lookup[iri]
                for iri in getattr(group, "elements", ())
                if iri in element_lookup
            ]
            context_groups.append(
                {
                    "key": getattr(group, "key", ""),
                    "label": (
                        getattr(group, "label_id", "")
                        if lang == "id"
                        else getattr(group, "label_en", "")
                    ),
                    "label_en": getattr(group, "label_en", ""),
                    "label_id": getattr(group, "label_id", ""),
                    "elements": elements,
                }
            )
        return {
            "occupation": summary,
            "tasks": task_list,
            "education": education,
            "training": training,
            "work_context": work_context,
            "work_styles": work_styles,
            "profile_sections": profile_sections,
            "context_groups": context_groups,
        }

    def skill_requirements_for_many(
        self,
        occupation_iris: Iterable[str],
        element_iris: Iterable[str],
        rating_types: Iterable[str],
        scale_id: str = "LV",
    ) -> Dict[str, List[dict]]:
        """Load O*NET level-scale requirements for the user's declared skills.

        Only requested elements are returned, so the profile-time SWRL bundle
        stays small.  If an element has multiple matching ratings, the highest
        level requirement wins.
        """

        occupations = [str(iri) for iri in dict.fromkeys(occupation_iris) if iri]
        elements = [str(iri) for iri in dict.fromkeys(element_iris) if iri]
        types = [str(item) for item in dict.fromkeys(rating_types) if item]
        result: Dict[str, List[dict]] = {iri: [] for iri in occupations}
        if not occupations or not elements or not types:
            return result
        template = self.sql("occupation_skill_requirements.sql").format(
            rating_types=",".join("?" for _ in types),
            elements=",".join("?" for _ in elements),
        )
        params = [scale_id, *types, *elements]
        try:
            for occupation_iri in occupations:
                for row in self.conn.execute(
                    template, [occupation_iri, *params]
                ):
                    item = dict(row)
                    existing = result[occupation_iri]
                    same = next(
                        (
                            current
                            for current in existing
                            if current["element_iri"] == item["element_iri"]
                        ),
                        None,
                    )
                    if same is None:
                        existing.append(item)
                    elif float(item.get("value") or 0.0) > float(
                        same.get("value") or 0.0
                    ):
                        existing.remove(same)
                        existing.append(item)
        except sqlite3.OperationalError:
            # Older indexes may not have a scales table yet.
            return result
        return result

    def interest_ratings_for_many(
        self, occupation_iris: Iterable[str]
    ) -> Dict[str, List[dict]]:
        """Batch-load graded RIASEC ratings for a set of occupations."""

        unique = [str(iri) for iri in dict.fromkeys(occupation_iris) if iri]
        result: Dict[str, List[dict]] = {iri: [] for iri in unique}
        if not unique:
            return result
        template = self.sql("interest_ratings_bulk.sql")
        chunk_size = 900
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            sql = template.format(placeholders=placeholders)
            for row in self.conn.execute(sql, chunk):
                result[str(row["occupation_iri"])].append(dict(row))
        return result

    def interest_catalog_rows(self) -> List[dict]:
        try:
            return [dict(row) for row in self.query("interest_catalog.sql")]
        except sqlite3.OperationalError:
            # Older indexes predate the interest vocabulary tables.
            return []

    def summary(self, occupation_iri: str) -> Optional[dict]:
        rows = self.query(
            "occupation_summary.sql",
            {"occupation_iri": occupation_iri},
        )
        return dict(rows[0]) if rows else None

    def occupation_catalog(self) -> List[dict]:
        """Return every indexed occupation title for name matching."""

        return [dict(row) for row in self.query("occupation_catalog.sql")]

    def requirements_for(
        self,
        occupation_iri: str,
        categories: Iterable[RequirementCategory],
        language: str = "id",
    ) -> Optional[dict]:
        """Return education, job-zone, and rated requirement categories.

        O*NET often has two rating scales for the same element (for example
        importance and level).  The index does not yet store scale labels, so
        this method keeps the row with the highest normalized value per
        element and exposes the corresponding raw value for audit.
        """

        summary = self.summary(occupation_iri)
        if not summary:
            return None
        lang = (language or "id").lower()
        requirements = []
        for category in sorted(categories, key=lambda item: (item.order, item.iri)):
            try:
                rows = self.query(
                    "occupation_requirements.sql",
                    {
                        "occupation_iri": occupation_iri,
                        "rating_type": category.rating_type,
                    },
                )
            except sqlite3.OperationalError:
                # Older indexes have no scales table.
                rows = []
            grouped: Dict[str, dict] = {}
            for row in rows:
                element_iri = str(row["element_iri"])
                item = grouped.setdefault(
                    element_iri,
                    {
                        "iri": element_iri,
                        "label_en": row["element_name_en"],
                        "label_id": row["element_name_id"],
                        "label": (
                            row["element_name_id"]
                            if lang == "id" and row["element_name_id"]
                            else row["element_name_en"]
                        ),
                        "rating_type": row["rating_type"],
                        "normalized": 0.0,
                        "scales": [],
                    },
                )
                value = row["value"]
                normalized = row["norm_value"]
                if normalized is not None:
                    item["normalized"] = max(item["normalized"], float(normalized))
                scale_entry = {
                    "iri": row["scale_iri"],
                    "id": row["scale_id"],
                    "name": row["scale_name"],
                    "value": value,
                    "normalized": normalized,
                    "minimum": row["scale_minimum"],
                    "maximum": row["scale_maximum"],
                }
                item["scales"].append(scale_entry)
                if row["scale_id"] == "IM":
                    item["importance"] = value
                    item["normalized_importance"] = normalized
                elif row["scale_id"] == "LV":
                    item["level"] = value
                    item["normalized_level"] = normalized
            items = sorted(
                grouped.values(), key=lambda item: item["normalized"], reverse=True
            )[: category.limit]
            requirements.append(
                {
                    "key": category.key,
                    "label": (
                        category.label_id if lang == "id" else category.label_en
                    ),
                    "label_en": category.label_en,
                    "label_id": category.label_id,
                    "rating_type": category.rating_type,
                    "items": items,
                }
            )
        education_label = (
            summary.get("education_label_id")
            if lang == "id"
            else summary.get("education_label_en")
        ) or summary.get("education_label_id") or summary.get("education_label_en")
        zone_name = (
            summary.get("job_zone_name_id")
            if lang == "id"
            else summary.get("job_zone_name_en")
        ) or summary.get("job_zone_name_id") or summary.get("job_zone_name_en")
        title = (
            summary.get("title_id")
            if lang == "id" and summary.get("title_id")
            else summary.get("title_en")
        )
        return {
            "occupation": {
                "iri": summary.get("iri"),
                "soc": summary.get("soc"),
                "title": title,
                "title_en": summary.get("title_en"),
                "title_id": summary.get("title_id"),
                "description_en": summary.get("description_en"),
                "description_id": summary.get("description_id"),
            },
            "education": {
                "local": summary.get("education_local"),
                "label": education_label,
                "order": summary.get("education_order"),
            },
            "job_zone": {
                "value": summary.get("job_zone"),
                "name": zone_name,
            },
            "requirements": requirements,
        }

    def tasks(self, occupation_iri: str, limit: int) -> List[dict]:
        rows = self.query(
            "occupation_tasks.sql",
            {"occupation_iri": occupation_iri, "limit": int(limit)},
        )
        return [dict(row) for row in rows]

    def job_titles(self, occupation_iri: str, limit: int) -> List[dict]:
        rows = self.query(
            "occupation_job_titles.sql",
            {"occupation_iri": occupation_iri, "limit": int(limit)},
        )
        return [dict(row) for row in rows]

    def related(self, occupation_iri: str, limit: int) -> List[dict]:
        rows = self.query(
            "occupation_related.sql",
            {"occupation_iri": occupation_iri, "limit": int(limit)},
        )
        return [dict(row) for row in rows]

    def profile_context(self) -> List[dict]:
        return [dict(row) for row in self.query("profile_context.sql")]

    def embedding_occupations(self) -> List[dict]:
        return [dict(row) for row in self.query("embedding_occupations.sql")]

    def embedding_rows(self) -> List[sqlite3.Row]:
        try:
            return self.query("embedding_rows.sql")
        except sqlite3.OperationalError:
            # Indexes built before semantic retrieval was added have no table.
            return []

    def embedding_meta(self) -> Dict[str, str]:
        try:
            rows = self.query("embedding_meta.sql")
        except sqlite3.OperationalError:
            return {}
        return {str(row["key"]): str(row["value"]) for row in rows}

    def element_catalog_rows(self) -> List[dict]:
        return [dict(row) for row in self.query("element_catalog.sql")]
