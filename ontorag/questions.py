"""Rule-based question routing over the occupation index.

The Indonesian question vocabulary lives in ``config/question_lexicon.ttl``.
This module only applies it.  It answers questions about one occupation, and
falls back to the recommendation pipeline when the text is an interest
description rather than a question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Sequence, Tuple

from . import config, ttl_stream
from .rdf_loader import load_block_map
from .ttl_stream import RDF_TYPE, local_name

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Intents answered from a previous recommendation, not from the occupation
# index alone.  The web layer resolves these with the pipeline.
EVIDENCE_INTENTS = {"why_recommended", "score_components"}

_CONTEXT_GROUPS = {
    "context_indoor_outdoor": "IndoorOutdoorGroup",
    "context_physical": "PhysicalDemandGroup",
    "context_teamwork": "TeamworkGroup",
}

_REQUIREMENT_KEYS = {
    "skills": "RequirementEssentialSkills",
    "knowledge": "RequirementKnowledge",
    "abilities": "RequirementAbilities",
    "work_activities": "RequirementWorkActivities",
}


@dataclass(frozen=True)
class QuestionIntent:
    key: str
    label: str
    keywords: Tuple[str, ...]
    priority: int
    examples: Tuple[str, ...] = ()

    @property
    def references(self) -> Tuple[str, ...]:
        """Strings the similarity fallback compares a question against."""

        return self.keywords + self.examples


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _num(value: object) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text or "0"


class QuestionLexicon:
    """Question intents, stopwords, and question words from one TTL file."""

    def __init__(
        self,
        intents: Sequence[QuestionIntent],
        stopwords: Iterable[str],
        question_words: Iterable[str],
        similarity_threshold: float = 0.55,
    ) -> None:
        self.intents = list(intents)
        self.stopwords = {word.lower() for word in stopwords}
        self.question_words = tuple(dict.fromkeys(word.lower() for word in question_words))
        self.similarity_threshold = float(similarity_threshold)

    @classmethod
    def load(cls, path: str = config.DEFAULT_QUESTION_LEXICON) -> "QuestionLexicon":
        blocks = load_block_map(path)
        intents: List[QuestionIntent] = []
        stopwords: List[str] = []
        question_words: List[str] = []
        threshold: Optional[float] = None
        for subject, predicates in blocks.items():
            types = {t.value for t in predicates.get(RDF_TYPE, []) if t.kind == "iri"}
            words = [
                t.value
                for t in predicates.get(config.QLEX + "stopword", [])
                if t.kind == "literal" and str(t.value).strip()
            ]
            stopwords.extend(words)
            question_words.extend(
                t.value
                for t in predicates.get(config.QLEX + "questionWord", [])
                if t.kind == "literal" and str(t.value).strip()
            )
            if threshold is None:
                threshold = ttl_stream.numeric_value(
                    predicates, config.QLEX + "similarityThreshold", None
                )
            if config.QLEX + "QuestionIntent" not in types:
                continue
            keywords = tuple(
                dict.fromkeys(
                    t.value
                    for t in predicates.get(config.QLEX + "keyword", [])
                    if t.kind == "literal" and str(t.value).strip()
                )
            )
            examples = tuple(
                dict.fromkeys(
                    t.value
                    for t in predicates.get(config.QLEX + "example", [])
                    if t.kind == "literal" and str(t.value).strip()
                )
            )
            priority = ttl_stream.numeric_value(
                predicates, config.QLEX + "priority", 0
            )
            label = ttl_stream.literal_value(
                predicates, config.RDFS + "label", local_name(subject)
            ) or local_name(subject)
            intents.append(
                QuestionIntent(
                    key=local_name(subject),
                    label=label,
                    keywords=keywords,
                    priority=int(priority or 0),
                    examples=examples,
                )
            )
        if not intents:
            raise ValueError(f"question lexicon {path} defines no intents")
        return cls(
            intents,
            stopwords,
            question_words,
            similarity_threshold=0.55 if threshold is None else float(threshold),
        )


class QuestionRouter:
    """Answer questions about one occupation from the index."""

    # A similar intent must beat the runner-up by this much, so an unclear
    # question is not answered with a guess.
    SIMILARITY_MARGIN = 0.1
    # Occupation suggestions offered when the name does not match exactly.
    SUGGESTION_LIMIT = 5
    # Tokens shorter than this must match exactly; fuzzy matching on short
    # Indonesian words produces too many accidental pairs.
    MIN_FUZZY_LENGTH = 4
    FUZZY_RATIO = 0.8

    def __init__(
        self,
        index,
        policy,
        index_policy=None,
        lexicon: Optional[QuestionLexicon] = None,
    ) -> None:
        self.index = index
        self.policy = policy
        self.index_policy = index_policy
        self.lexicon = lexicon or QuestionLexicon.load()
        self._compiled = [
            (
                intent,
                keyword,
                # No trailing boundary: Indonesian and English suffixes
                # (fisiknya, skills) should still match the keyword.
                re.compile(r"(?<!\w)" + re.escape(keyword.lower())),
            )
            for intent in self.lexicon.intents
            for keyword in intent.keywords
        ]
        self._question_res = [
            re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)")
            for word in self.lexicon.question_words
        ]
        self._similarity_refs = [
            (intent, self._content_tokens(reference))
            for intent in self.lexicon.intents
            for reference in intent.references
        ]

    # -- classification ---------------------------------------------------

    def _keyword_intent(self, text: str) -> Optional[QuestionIntent]:
        lowered = (text or "").lower()
        best: Optional[Tuple[int, QuestionIntent]] = None
        for intent, keyword, regex in self._compiled:
            if not regex.search(lowered):
                continue
            score = len(keyword.split()) * 10 + intent.priority
            if best is None or score > best[0]:
                best = (score, intent)
        return best[1] if best else None

    @classmethod
    def _token_close(cls, left: str, right: str) -> bool:
        if left == right:
            return True
        if len(left) < cls.MIN_FUZZY_LENGTH or len(right) < cls.MIN_FUZZY_LENGTH:
            return False
        return SequenceMatcher(None, left, right).ratio() >= cls.FUZZY_RATIO

    @classmethod
    def _similarity(cls, query: Sequence[str], reference: Sequence[str]) -> float:
        """Token F1 between a question and one reference phrase.

        Tokens count as equal when they are equal or fuzzy close, so a typo
        or a morphological variant still matches ("pendidkan", "ketrampilan").
        """

        if not query or not reference:
            return 0.0
        matched_query = sum(
            1
            for token in query
            if any(cls._token_close(token, other) for other in reference)
        )
        if not matched_query:
            return 0.0
        matched_reference = sum(
            1
            for token in reference
            if any(cls._token_close(token, other) for other in query)
        )
        precision = matched_query / len(query)
        recall = matched_reference / len(reference)
        return 2 * precision * recall / (precision + recall)

    def _similar_intents(self, text: str) -> List[Tuple[float, QuestionIntent]]:
        query = self._content_tokens(text)
        if not query:
            return []
        best: dict = {}
        for intent, reference in self._similarity_refs:
            if not reference:
                continue
            score = self._similarity(query, reference)
            current = best.get(intent.key)
            if current is None or score > current[0]:
                best[intent.key] = (score, intent)
        return sorted(
            (item for item in best.values() if item[0] > 0),
            key=lambda item: (-item[0], -item[1].priority),
        )

    def classify(self, text: str) -> Optional[QuestionIntent]:
        intent, _ = self._classify_scored(text)
        return intent

    def _classify_scored(
        self, text: str
    ) -> Tuple[Optional[QuestionIntent], Optional[str]]:
        """Return ``(intent, match)``; ``match`` is ``keyword`` or ``similar``."""

        hit = self._keyword_intent(text)
        if hit is not None:
            return hit, "keyword"
        if not self.looks_like_question(text):
            return None, None
        scored = self._similar_intents(text)
        if not scored:
            return None, None
        best_score, best_intent = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if best_score < self.lexicon.similarity_threshold:
            return None, None
        if best_score - runner_up < self.SIMILARITY_MARGIN:
            return None, None
        return best_intent, "similar"

    def looks_like_question(self, text: str) -> bool:
        if "?" in (text or ""):
            return True
        lowered = (text or "").lower()
        return any(regex.search(lowered) for regex in self._question_res)

    # -- occupation resolution -------------------------------------------

    def _occ(self, row) -> dict:
        return {
            "iri": row.get("iri"),
            "soc": row.get("soc"),
            "title": row.get("title_id") or row.get("title_en") or row.get("iri"),
            "title_en": row.get("title_en"),
            "title_id": row.get("title_id"),
        }

    def _content_tokens(self, text: str) -> List[str]:
        return [
            token
            for token in _tokens(text)
            if token not in self.lexicon.stopwords and token not in self.lexicon.question_words
        ]

    @classmethod
    def _matches(cls, token: str, title_token: str) -> bool:
        if token == title_token:
            return True
        if len(token) >= 3 and title_token.startswith(token):
            return True
        return cls._token_close(token, title_token)

    def _score(self, raw_tokens: Sequence[str], content: Sequence[str], title: str) -> int:
        title_tokens = _tokens(title)
        if not title_tokens:
            return 0
        size = len(title_tokens)
        for start in range(0, len(raw_tokens) - size + 1):
            if list(raw_tokens[start : start + size]) == title_tokens:
                return 1000 + 10 * size
        if not content:
            return 0
        matched = sum(
            1
            for token in content
            if any(self._matches(token, title_token) for title_token in title_tokens)
        )
        if matched == len(content):
            return 500 + 10 * len(content)
        if matched:
            return 100 + int(100 * matched / size) + 20 * matched
        return 0

    def _scored(self, text: str) -> List[Tuple[int, dict]]:
        raw = _tokens(text)
        content = self._content_tokens(text)
        if not raw:
            return []
        best: dict[str, Tuple[int, dict]] = {}
        for row in self.index.occupation_catalog():
            score = max(
                self._score(raw, content, row.get("title_id") or ""),
                self._score(raw, content, row.get("title_en") or ""),
            )
            if score <= 0:
                continue
            current = best.get(str(row.get("iri")))
            if current is None or score > current[0]:
                best[str(row.get("iri"))] = (score, row)
        return sorted(best.values(), key=lambda item: -item[0])

    def search(self, text: str, limit: int = 10) -> List[dict]:
        return [self._occ(row) for _, row in self._scored(text)[:limit]]

    def resolve(self, text: str, occupation_iri: Optional[str] = None) -> dict:
        """Resolve the occupation in ``text`` (or an explicit IRI).

        Returns the chosen occupation, the ranked ``suggestions``, an
        ``occupation_match`` of ``exact``, ``fuzzy``, ``explicit``, or
        ``ambiguous``, and whether the user must choose an ``ambiguous`` match.
        """

        if occupation_iri:
            row = self.index.summary(occupation_iri)
            chosen = self._occ(row) if row else None
            suggestions = [
                self._occ(item[1])
                for item in self._scored(text)[: self.SUGGESTION_LIMIT]
            ]
            if chosen and chosen["iri"] not in {item["iri"] for item in suggestions}:
                suggestions = ([chosen] + suggestions)[: self.SUGGESTION_LIMIT]
            return {
                "occupation": chosen,
                "suggestions": suggestions,
                "occupation_match": "explicit",
                "ambiguous": False,
            }
        scored = self._scored(text)
        if not scored:
            return {
                "occupation": None,
                "suggestions": [],
                "occupation_match": None,
                "ambiguous": False,
            }
        top_score = scored[0][0]
        suggestions = [
            self._occ(item[1]) for item in scored[: self.SUGGESTION_LIMIT]
        ]
        if top_score >= 1000:
            tied = {str(item[1].get("iri")) for item in scored if item[0] == top_score}
            if len(tied) == 1:
                return {
                    "occupation": self._occ(scored[0][1]),
                    "suggestions": [],
                    "occupation_match": "exact",
                    "ambiguous": False,
                }
        runner_up = scored[1][0] if len(scored) > 1 else 0
        if len(scored) == 1 or top_score - runner_up >= 100:
            return {
                "occupation": self._occ(scored[0][1]),
                "suggestions": suggestions,
                "occupation_match": "fuzzy",
                "ambiguous": False,
            }
        return {
            "occupation": None,
            "suggestions": suggestions,
            "occupation_match": "ambiguous",
            "ambiguous": True,
        }

    def decide(
        self,
        text: str,
        language: str = "id",
        occupation: Optional[str] = None,
    ) -> dict:
        intent, match = self._classify_scored(text)
        resolved = self.resolve(text, occupation)
        if intent is None:
            return {"mode": "recommend"}
        base = {
            "intent": intent.key,
            "label": intent.label,
            "match": match,
        }
        chosen = resolved["occupation"]
        if chosen is None:
            if resolved["suggestions"]:
                return {
                    **base,
                    "mode": "disambiguate",
                    "occupation_match": resolved["occupation_match"],
                    "suggestions": resolved["suggestions"],
                }
            if self.looks_like_question(text):
                return {
                    **base,
                    "mode": "need_occupation",
                    "message": (
                        "Nama pekerjaan belum dikenali. Sebutkan nama pekerjaan, "
                        "misalnya 'Ilmuwan Data' atau 'Perawat Terdaftar'."
                    ),
                }
            return {"mode": "recommend"}
        result = {
            **base,
            "mode": "answer",
            "occupation": chosen,
            "occupation_match": resolved["occupation_match"],
        }
        if resolved["occupation_match"] != "exact" and resolved["suggestions"]:
            result["suggestions"] = resolved["suggestions"]
        return result

    # -- answer assembly --------------------------------------------------

    def _profile(self, iri: str, language: str) -> dict:
        return self.index.occupation_profile(
            iri,
            language=language,
            groups=self.policy.profile_groups,
            core_task_type=getattr(self.index_policy, "core_task_type", "Core"),
            relevance_scale_id=getattr(self.index_policy, "task_relevance_scale_id", "RT"),
            frequency_scale_id=getattr(self.index_policy, "task_frequency_scale_id", "FT"),
        )

    def _requirements(self, iri: str, language: str) -> dict:
        return self.index.requirements_for(
            iri, self.policy.requirement_categories, language=language
        )

    @staticmethod
    def _requirement_detail(item: dict) -> str:
        parts: List[str] = []
        if item.get("level") is not None:
            parts.append(f"Level {_num(item['level'])}")
        if item.get("importance") is not None:
            parts.append(f"Importance {_num(item['importance'])}")
        if not parts and item.get("normalized") is not None:
            parts.append(f"Skor {_num(item['normalized'])}")
        return ", ".join(parts)

    @staticmethod
    def _section_rows(section: Optional[dict]) -> List[dict]:
        rows: List[dict] = []
        for element in (section or {}).get("elements", []):
            for item in element.get("items", []):
                title = item.get("label") or item.get("category") or element.get("label")
                detail = f"{_num(item.get('value'))}%"
                if item.get("n") is not None:
                    detail += f" ({_num(item.get('n'))} responden)"
                rows.append({"title": title, "detail": detail})
        return rows

    def answer(self, intent: str, occupation: dict, language: str = "id") -> dict:
        iri = occupation["iri"]
        title = occupation.get("title") or ""
        lang = "id" if (language or "id").lower() == "id" else "en"

        if intent == "education_min":
            data = self._requirements(iri, lang) or {}
            education = data.get("education") or {}
            label = education.get("label") or education.get("local") or "-"
            return {
                "heading": "Pendidikan minimum",
                "summary": f"Pendidikan minimum untuk {title} adalah {label}.",
                "facts": [{"label": "Pendidikan minimum", "value": label}],
                "items": [],
                "groups": [],
            }

        if intent == "job_zone":
            data = self._requirements(iri, lang) or {}
            zone = data.get("job_zone") or {}
            value = zone.get("value")
            name = zone.get("name") or ""
            summary = f"{title} berada pada job zone {value}."
            if name:
                summary += f" {name}."
            return {
                "heading": "Job zone",
                "summary": summary,
                "facts": [
                    {"label": "Job zone", "value": str(value if value is not None else "-")},
                    {"label": "Nama", "value": name or "-"},
                ],
                "items": [],
                "groups": [],
            }

        if intent in _REQUIREMENT_KEYS:
            data = self._requirements(iri, lang) or {}
            key = _REQUIREMENT_KEYS[intent]
            category = next(
                (item for item in data.get("requirements", []) if item.get("key") == key),
                None,
            )
            rows = [
                {"title": item.get("label"), "detail": self._requirement_detail(item)}
                for item in (category or {}).get("items", [])
            ]
            label = (category or {}).get("label") or intent
            if not rows:
                summary = (
                    f"Data {label.lower()} untuk {title} belum tersedia di index ini."
                )
            else:
                summary = f"{label} paling penting untuk {title}."
            return {
                "heading": label,
                "summary": summary,
                "facts": [],
                "items": rows,
                "groups": [],
            }

        if intent == "level_importance":
            data = self._requirements(iri, lang) or {}
            rows: List[dict] = []
            for category in data.get("requirements", []):
                for item in category.get("items", []):
                    detail = self._requirement_detail(item)
                    if not detail:
                        continue
                    rows.append(
                        {
                            "title": f"{category.get('label')}: {item.get('label')}",
                            "detail": detail,
                        }
                    )
            return {
                "heading": "Level dan importance",
                "summary": f"Level dan importance persyaratan untuk {title}.",
                "facts": [],
                "items": rows,
                "groups": [],
            }

        if intent == "description":
            profile = self._profile(iri, lang) or {}
            occupation_data = profile.get("occupation") or {}
            text = (
                occupation_data.get("description_id")
                if lang == "id" and occupation_data.get("description_id")
                else occupation_data.get("description_en")
            ) or occupation_data.get("description_id") or ""
            first = re.split(r"(?<=[.!?])\s+", text.strip())[0] if text else ""
            return {
                "heading": "Deskripsi pekerjaan",
                "summary": first or f"Deskripsi {title} belum tersedia.",
                "facts": [{"label": "Deskripsi", "value": text or "-"}],
                "items": [],
                "groups": [],
            }

        if intent in {"tasks_core", "tasks_relevant", "task_frequency"}:
            profile = self._profile(iri, lang) or {}
            tasks = profile.get("tasks") or []
            if intent == "tasks_core":
                core_type = str(getattr(self.index_policy, "core_task_type", "Core")).lower()
                core = [
                    item
                    for item in tasks
                    if str(item.get("task_type") or "").lower() == core_type
                ]
                chosen = (core or tasks)[:5]
                rows = [
                    {"title": item.get("task"), "detail": item.get("task_type") or ""}
                    for item in chosen
                ]
                summary = f"Lima tugas inti untuk {title}."
            elif intent == "tasks_relevant":
                ranked = sorted(
                    tasks,
                    key=lambda item: -float(item.get("relevance_percent") or 0.0),
                )
                rows = [
                    {
                        "title": item.get("task"),
                        "detail": (
                            f"Relevansi {_num(item.get('relevance_percent'))}%"
                            if item.get("relevance_percent") is not None
                            else ""
                        ),
                    }
                    for item in ranked[:10]
                ]
                summary = f"Tugas yang paling relevan untuk {title}."
            else:
                frequent = [item for item in tasks if item.get("frequency")]
                frequent.sort(
                    key=lambda item: -float(item.get("frequency_percent") or 0.0)
                )
                rows = [
                    {
                        "title": item.get("task"),
                        "detail": f"{item.get('frequency')}"
                        + (
                            f" ({_num(item.get('frequency_percent'))}%)"
                            if item.get("frequency_percent") is not None
                            else ""
                        ),
                    }
                    for item in frequent[:10]
                ]
                summary = f"Frekuensi tugas pada {title}."
            return {
                "heading": "Tugas",
                "summary": summary,
                "facts": [],
                "items": rows,
                "groups": [],
            }

        if intent == "task_dwa":
            profile = self._profile(iri, lang) or {}
            groups: List[dict] = []
            for task in (profile.get("tasks") or []):
                dwa = task.get("dwa") or []
                if not dwa:
                    continue
                groups.append(
                    {
                        "heading": task.get("task"),
                        "items": [
                            {"title": entry.get("label"), "detail": ""} for entry in dwa
                        ],
                    }
                )
                if len(groups) >= 5:
                    break
            return {
                "heading": "DWA di balik tugas",
                "summary": f"Detailed work activity yang terkait dengan tugas {title}.",
                "facts": [],
                "items": [],
                "groups": groups,
            }

        if intent in {"education_distribution", "experience", "training"}:
            profile = self._profile(iri, lang) or {}
            if intent == "education_distribution":
                rows = self._section_rows(profile.get("education"))
                summary = f"Distribusi pendidikan pekerja pada {title}."
            else:
                section = profile.get("training") or {}
                wanted = ("experience",) if intent == "experience" else (
                    "training",
                    "apprentice",
                    "internship",
                )
                elements = [
                    element
                    for element in section.get("elements", [])
                    if any(
                        marker in str(element.get("label_en") or element.get("label") or "").lower()
                        for marker in wanted
                    )
                ]
                rows = self._section_rows({"elements": elements or section.get("elements", [])})
                summary = (
                    f"Pengalaman kerja yang biasanya dibutuhkan {title}."
                    if intent == "experience"
                    else f"Pelatihan dan magang untuk {title}."
                )
            return {
                "heading": "Pendidikan dan pengalaman",
                "summary": summary,
                "facts": [],
                "items": rows,
                "groups": [],
            }

        if intent in _CONTEXT_GROUPS:
            profile = self._profile(iri, lang) or {}
            key = _CONTEXT_GROUPS[intent]
            group = next(
                (item for item in profile.get("context_groups", []) if item.get("key") == key),
                None,
            )
            rows: List[dict] = []
            for element in (group or {}).get("elements", []):
                top = (element.get("items") or [None])[0]
                detail = ""
                if top:
                    detail = top.get("label") or _num(top.get("value"))
                rows.append({"title": element.get("label"), "detail": detail})
            if not rows:
                summary = (
                    "Data konteks kerja belum ada di index ini. Bangun ulang index "
                    "dengan --extra-source WorkContextRating.ttl dan "
                    "WorkContextCategory.ttl."
                )
            else:
                summary = f"Konteks kerja {title}."
            return {
                "heading": (group or {}).get("label") or "Konteks kerja",
                "summary": summary,
                "facts": [],
                "items": rows,
                "groups": [],
            }

        if intent == "tasks_and_titles":
            profile = self._profile(iri, lang) or {}
            task_rows = [
                {"title": item.get("task"), "detail": item.get("task_type") or ""}
                for item in (profile.get("tasks") or [])[:5]
            ]
            title_rows = []
            for row in self.index.job_titles(iri, 8):
                label = row.get("title_id") if lang == "id" and row.get("title_id") else row.get("title_en")
                title_rows.append({"title": label, "detail": ""})
            related_rows = []
            for row in self.index.related(iri, 5):
                related = self.index.summary(str(row.get("related_iri")))
                if not related:
                    continue
                label = (
                    related.get("title_id")
                    if lang == "id" and related.get("title_id")
                    else related.get("title_en")
                )
                related_rows.append(
                    {"title": label, "detail": row.get("tier") or ""}
                )
            return {
                "heading": "Tugas representatif dan jabatan terkait",
                "summary": f"Tugas, jabatan, dan okupasi terkait untuk {title}.",
                "facts": [],
                "items": [],
                "groups": [
                    {"heading": "Tugas representatif", "items": task_rows},
                    {"heading": "Jabatan terkait", "items": title_rows},
                    {"heading": "Okupasi terkait", "items": related_rows},
                ],
            }

        return {
            "heading": "Belum didukung",
            "summary": "Pertanyaan ini belum punya penanganan khusus.",
            "facts": [],
            "items": [],
            "groups": [],
        }