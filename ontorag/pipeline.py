"""End-to-end recommendation pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from . import config
from .extraction import ElementCatalog, Profile, extract_from_text
from .lexicon import Lexicon
from .ontology import Ontology
from .policy import IndexPolicy, RankingPolicy, load_index_policy, load_ranking_policy
from .query_engine import Index
from .reasoning import ReasoningService, SqlReasoner, make_reasoner
from .scoring import Recommendation, score_candidates


class Pipeline:
    def __init__(
        self,
        index: Index,
        ontology: Ontology,
        lexicon: Lexicon,
        policy: RankingPolicy,
        index_policy: IndexPolicy,
        reasoner: ReasoningService | None = None,
    ) -> None:
        self.index = index
        self.ontology = ontology
        self.lexicon = lexicon
        self.policy = policy
        self.index_policy = index_policy
        self.reasoner = reasoner or SqlReasoner()
        self.catalog = ElementCatalog.from_rows(index.element_catalog_rows())

    @classmethod
    def from_paths(
        cls,
        index_path: str | Path = config.DEFAULT_INDEX,
        schema_path: str | Path | None = None,
        overlay_path: str | Path | None = None,
        policy_path: str | Path = config.DEFAULT_POLICY,
        index_policy_path: str | Path = config.DEFAULT_INDEX_POLICY,
        lexicon_path: str | Path | None = None,
        reasoner_mode: str = "auto",
        temp_dir: str | Path = config.DATA_DIR,
    ) -> "Pipeline":
        policy = load_ranking_policy(policy_path)
        index_policy = load_index_policy(index_policy_path)
        resolved_schema = schema_path or (
            config.SCHEMA_EN if config.SCHEMA_EN.exists() else config.SCHEMA_FALLBACK
        )
        resolved_overlay = overlay_path or config.find_overlay()
        ontology = Ontology(resolved_schema, resolved_overlay)
        lexicon = Lexicon.load(lexicon_path or policy.lexicon_file)
        index = Index(index_path)
        reasoner = make_reasoner(
            reasoner_mode,
            policy,
            schema=resolved_schema,
            overlay=resolved_overlay,
            policy_file=policy_path,
            temp_dir=temp_dir,
        )
        return cls(index, ontology, lexicon, policy, index_policy, reasoner)

    def close(self) -> None:
        self.index.close()

    def __enter__(self) -> "Pipeline":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def profile_from_text(
        self,
        text: str,
        language: Optional[str] = None,
        user_iri: Optional[str] = None,
        education: Optional[str] = None,
        max_job_zone: Optional[int] = None,
    ) -> Profile:
        profile = extract_from_text(
            text,
            self.ontology,
            self.lexicon,
            self.catalog,
            language=language or self.policy.language_default,
            user_iri=user_iri,
            default_education=education,
            default_max_job_zone=max_job_zone,
            direct_element_weight=self.policy.direct_element_weight,
            direct_element_min_length=self.policy.direct_element_min_length,
        )
        return profile

    def profile_from_json(
        self,
        path: str | Path,
        text: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Profile:
        profile = Profile.load(str(path), self.ontology, self.catalog, language=language)
        if text:
            extracted = self.profile_from_text(
                text,
                language=language or profile.language,
                user_iri=profile.user_iri,
                education=profile.education_local,
                max_job_zone=profile.max_job_zone,
            )
            profile = profile.merged_with(extracted)
        return profile

    def recommend(
        self,
        profile: Profile,
        top_k: Optional[int] = None,
        text: Optional[str] = None,
    ) -> List[Recommendation]:
        if not profile.education_local:
            profile.education_local = self.policy.default_education
            profile.education_order = self.ontology.education_order(profile.education_local)
        if profile.max_job_zone is None:
            profile.max_job_zone = self.policy.default_max_job_zone

        candidates = self.index.candidates(
            profile,
            self.policy,
            require_complete=self.index_policy.require_complete_data,
            limit=self.policy.candidate_limit,
        )
        if not candidates:
            return []

        query_text = text if text is not None else (profile.lexical_text or profile.raw_text)
        lexical_scores = self.index.lexical_scores(
            query_text or "",
            self.policy.lexical_candidate_limit,
            self.index_policy.min_fts_token_length,
        )

        # Reason only over a shortlist.  Preliminary scores use the same
        # generic scorer, but no reasoning flags.
        shortlist = score_candidates(
            self.index,
            profile,
            self.policy,
            candidates,
            lexical_scores=lexical_scores,
            top_k=self.policy.reasoning_candidate_limit,
        )
        shortlist_rows = [recommendation.row for recommendation in shortlist]
        reasoning_flags: Dict[str, dict] = {}
        if shortlist_rows:
            reasoning_flags = self.reasoner.infer(profile, shortlist_rows, self.policy)

        recommendations = score_candidates(
            self.index,
            profile,
            self.policy,
            candidates,
            lexical_scores=lexical_scores,
            reasoning_flags=reasoning_flags,
            top_k=top_k or self.policy.top_k,
        )
        for recommendation in recommendations:
            self._enrich(recommendation, profile)
        return recommendations

    # ------------------------------------------------------------------
    # Evidence and language surface
    # ------------------------------------------------------------------

    def _enrich(self, recommendation: Recommendation, profile: Profile) -> None:
        language = profile.language or self.policy.language_default
        summary = self.index.summary(recommendation.occupation_iri) or recommendation.row
        evidence: List[dict] = []

        holland_pairs = [
            (code, weight)
            for code, weight in profile.holland.items()
            if code in {
                summary.get("holland_primary"),
                summary.get("holland_secondary"),
                summary.get("holland_tertiary"),
            }
        ]
        if holland_pairs:
            evidence.append(
                {
                    "kind": "holland",
                    "label": self._t(
                        language,
                        "Kesesuaian Holland",
                        "Holland alignment",
                    ),
                    "detail": ", ".join(
                        f"{self.ontology.holland_label(code, language)} ({weight:.2f})"
                        for code, weight in sorted(holland_pairs, key=lambda item: -item[1])
                    ),
                    "value": recommendation.component_scores.get("holland"),
                }
            )

        for match in recommendation.element_matches[: self.policy.explanation_limit]:
            evidence.append(
                {
                    "kind": "element",
                    "label": match["element_name"],
                    "detail": self._t(
                        language,
                        f"preferensi {match['preference_weight']:.2f}; rating ternormalisasi {match['normalized_rating']:.2f}",
                        f"preference {match['preference_weight']:.2f}; normalized rating {match['normalized_rating']:.2f}",
                    ),
                    "value": match["normalized_rating"],
                }
            )

        if "lexical" in recommendation.component_scores:
            evidence.append(
                {
                    "kind": "lexical",
                    "label": self._t(language, "Kemiripan leksikal FTS5/BM25", "FTS5/BM25 lexical similarity"),
                    "detail": self._t(
                        language,
                        "teks profil cocok dengan judul, deskripsi, tugas, elemen, atau gelar jabatan",
                        "profile text matches title, description, tasks, elements, or job titles",
                    ),
                    "value": recommendation.component_scores["lexical"],
                }
            )

        education_label = summary.get("education_label_id") or summary.get("education_label_en")
        if education_label:
            evidence.append(
                {
                    "kind": "education",
                    "label": self._t(language, "Pendidikan minimum", "Minimum education"),
                    "detail": str(education_label),
                    "value": summary.get("education_order"),
                }
            )
        if summary.get("job_zone") is not None:
            evidence.append(
                {
                    "kind": "job_zone",
                    "label": self._t(language, "Zona kerja", "Job zone"),
                    "detail": str(
                        summary.get("job_zone_name_id")
                        or summary.get("job_zone_name_en")
                        or summary.get("job_zone")
                    ),
                    "value": summary.get("job_zone"),
                }
            )

        tasks = self.index.tasks(recommendation.occupation_iri, self.policy.explanation_limit)
        if tasks:
            task_text = [
                str(task.get("task_id_text") or task.get("task_en") or "")
                for task in tasks
                if task.get("task_id_text") or task.get("task_en")
            ]
            evidence.append(
                {
                    "kind": "tasks",
                    "label": self._t(language, "Tugas representatif", "Representative tasks"),
                    "detail": "; ".join(task_text[:3]),
                    "value": len(task_text),
                }
            )

        titles = self.index.job_titles(recommendation.occupation_iri, 3)
        if titles:
            title_text = [
                str(title.get("title_id") or title.get("title_en") or "")
                for title in titles
                if title.get("title_id") or title.get("title_en")
            ]
            evidence.append(
                {
                    "kind": "job_titles",
                    "label": self._t(language, "Gelar jabatan terkait", "Related job titles"),
                    "detail": "; ".join(title_text),
                    "value": len(title_text),
                }
            )

        recommendation.evidence = evidence
        recommendation.explanation = self._explain(recommendation, profile, language)

    def _explain(self, recommendation: Recommendation, profile: Profile, language: str) -> str:
        parts: List[str] = []
        tier_label = {
            "EligibleStrong": self._t(language, "memenuhi syarat dan sangat cocok", "eligible with a strong match"),
            "Eligible": self._t(language, "memenuhi syarat", "eligible"),
            "NotEligible": self._t(language, "belum memenuhi syarat", "not yet eligible"),
        }.get(recommendation.tier, recommendation.tier)
        parts.append(
            self._t(
                language,
                f"Tier logis: {recommendation.tier} ({tier_label}).",
                f"Logical tier: {recommendation.tier} ({tier_label}).",
            )
        )
        if recommendation.component_scores:
            component_text = ", ".join(
                f"{name}={value:.3f}" for name, value in sorted(recommendation.component_scores.items())
            )
            parts.append(
                self._t(
                    language,
                    f"Skor komponen: {component_text}.",
                    f"Component scores: {component_text}.",
                )
            )
        holland_codes = [
            code
            for code in (
                recommendation.row.get("holland_primary"),
                recommendation.row.get("holland_secondary"),
                recommendation.row.get("holland_tertiary"),
            )
            if code
        ]
        if holland_codes:
            parts.append(
                self._t(
                    language,
                    "Kode Holland: " + ", ".join(self.ontology.holland_label(code, language) for code in holland_codes) + ".",
                    "Holland codes: " + ", ".join(self.ontology.holland_label(code, language) for code in holland_codes) + ".",
                )
            )
        return " ".join(parts)

    @staticmethod
    def _t(language: str, indonesian: str, english: str) -> str:
        return indonesian if (language or "id").lower() == "id" else english
