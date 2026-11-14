"""Read-only access to the generated SQLite FTS5 index."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from . import config
from .extraction import Profile
from .policy import RankingPolicy


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

    def summary(self, occupation_iri: str) -> Optional[dict]:
        rows = self.query(
            "occupation_summary.sql",
            {"occupation_iri": occupation_iri},
        )
        return dict(rows[0]) if rows else None

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

    def element_catalog_rows(self) -> List[dict]:
        return [dict(row) for row in self.query("element_catalog.sql")]
