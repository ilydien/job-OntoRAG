"""Declarative policy loading (ranking and index policies)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import config, ttl_stream
from .rdf_loader import load_block_map
from .ttl_stream import RDF_TYPE, local_name


@dataclass(frozen=True)
class ScoringComponent:
    iri: str
    name: str
    component_type: str
    weight: float
    order: int


@dataclass(frozen=True)
class ProfileGroup:
    iri: str
    key: str
    label_en: str
    label_id: str
    order: int
    elements: List[str]


@dataclass(frozen=True)
class RequirementCategory:
    iri: str
    key: str
    rating_type: str
    label_en: str
    label_id: str
    order: int
    limit: int


@dataclass
class RankingPolicy:
    iri: str
    name: str
    top_k: int
    candidate_limit: int
    reasoning_candidate_limit: int
    lexical_candidate_limit: int
    require_eligible: bool
    fallback_tier: str
    strong_holland_threshold: float
    strong_element_threshold: float
    tier_order: List[str]
    rule_files: List[Path]
    components: List[ScoringComponent]
    language_default: str
    default_education: str
    default_max_job_zone: int
    score_precision: int
    explanation_limit: int
    task_evidence_limit: int
    job_title_evidence_limit: int
    description_preview_chars: int
    interest_primary: bool
    skill_level_min: float
    skill_level_max: float
    skill_requirement_scale_id: str
    interest_activity_weight: float
    interest_keyword_weight: float
    direct_element_weight: float
    direct_element_min_length: int
    holland_primary_weight: float
    holland_secondary_weight: float
    holland_tertiary_weight: float
    element_aggregation: str
    lexical_normalization: str
    reasoner_default: str
    lexicon_file: Path
    reasoning_map_file: Path
    index_policy_iri: Optional[str] = None
    retrieval_mode: str = "auto"
    semantic_normalization: str = "minmax"
    semantic_candidate_limit: int = 2000
    ontology_normalization: str = "minmax"
    ontology_candidate_limit: int = 2000
    embedding_model: Optional[str] = None
    sparql_endpoint: Optional[str] = None
    sparql_timeout: int = 30
    metadata: Dict[str, object] = field(default_factory=dict)
    requirement_categories: List[RequirementCategory] = field(default_factory=list)
    profile_groups: List[ProfileGroup] = field(default_factory=list)

    @property
    def component_weights(self) -> Dict[str, float]:
        return {component.component_type: component.weight for component in self.components}

    def tier_rank(self, tier: str) -> int:
        try:
            return self.tier_order.index(tier)
        except ValueError:
            return len(self.tier_order)


@dataclass(frozen=True)
class IndexPolicy:
    iri: str
    name: str
    indexed_rating_types: List[str]
    require_complete_data: bool
    min_element_ratings: int
    min_fts_token_length: int
    fts_tokenize: str
    index_version: str
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_batch_size: int = 32
    embedding_max_tasks: int = 8
    embedding_max_elements: int = 12
    embedding_max_job_titles: int = 5
    embedding_card_version: str = "1"
    profile_rating_types: List[str] = field(default_factory=list)
    extra_sources: List[Path] = field(default_factory=list)
    core_task_type: str = "Core"
    task_relevance_scale_id: str = "RT"
    task_frequency_scale_id: str = "FT"

    @property
    def indexed_rating_type_iris(self) -> List[str]:
        return [config.ONET + name for name in self.indexed_rating_types]


def _find_by_type(blocks: Dict[str, Dict[str, list[ttl_stream.Term]]], type_iri: str) -> Optional[str]:
    for subject, predicates in blocks.items():
        for term in predicates.get(RDF_TYPE, []):
            if term.kind == "iri" and term.value == type_iri:
                return subject
    return None


def load_ranking_policy(path: str | Path = config.DEFAULT_POLICY) -> RankingPolicy:
    path = Path(path)
    blocks = load_block_map(path)
    policy_iri = config.CAREER + "DefaultRankingPolicy"
    if policy_iri not in blocks:
        found = _find_by_type(blocks, config.CAREER + "RankingPolicy")
        if not found:
            raise ValueError(f"no career:RankingPolicy found in {path}")
        policy_iri = found
    p = blocks[policy_iri]

    def required_int(predicate: str) -> int:
        value = ttl_stream.numeric_value(p, predicate, None)
        if value is None:
            raise ValueError(f"missing required integer property {predicate} in {path}")
        return int(value)

    def required_float(predicate: str) -> float:
        value = ttl_stream.numeric_value(p, predicate, None)
        if value is None:
            raise ValueError(f"missing required numeric property {predicate} in {path}")
        return float(value)

    def required_string(predicate: str) -> str:
        value = ttl_stream.literal_value(p, predicate, None)
        if value is None:
            raise ValueError(f"missing required string property {predicate} in {path}")
        return value

    def required_bool(predicate: str) -> bool:
        term = ttl_stream.first(p, predicate)
        if term is None:
            raise ValueError(f"missing required boolean property {predicate} in {path}")
        return bool(term.python_value())

    def optional_int(predicate: str, default: int) -> int:
        value = ttl_stream.numeric_value(p, predicate, None)
        return int(value) if value is not None else default

    def optional_string(predicate: str, default: Optional[str] = None) -> Optional[str]:
        value = ttl_stream.literal_value(p, predicate, None)
        return value if value else default

    tier_order = [t.value for t in p.get(config.CAREER + "tierOrder", []) if t.kind == "literal"]
    if not tier_order:
        raise ValueError(f"missing required career:tierOrder values in {path}")

    rule_files: List[Path] = []
    for term in p.get(config.CAREER + "hasRuleFile", []):
        if term.kind == "literal":
            rule_files.append(config.resolve_project_path(term.value))
    if not rule_files:
        raise ValueError(f"missing required career:hasRuleFile values in {path}")

    component_iris = [t.value for t in p.get(config.CAREER + "hasComponent", []) if t.kind == "iri"]
    if not component_iris:
        raise ValueError(f"missing required career:hasComponent values in {path}")
    components: List[ScoringComponent] = []
    for component_iri in component_iris:
        c = blocks.get(component_iri, {})
        component_type = ttl_stream.literal_value(c, config.CAREER + "componentType", "") or ""
        if not component_type:
            raise ValueError(f"component {component_iri} has no career:componentType")
        weight = ttl_stream.numeric_value(c, config.CAREER + "componentWeight", None)
        order = ttl_stream.numeric_value(c, config.CAREER + "componentOrder", None)
        if weight is None or order is None:
            raise ValueError(f"component {component_iri} lacks weight or order")
        label = ttl_stream.literal_value(c, config.CAREER + "label", None)
        # The label predicate is rdfs:label, not career:label.
        label = ttl_stream.literal_value(c, config.RDFS + "label", label) or local_name(component_iri)
        components.append(
            ScoringComponent(
                iri=component_iri,
                name=label,
                component_type=component_type,
                weight=float(weight),
                order=int(order),
            )
        )
    components.sort(key=lambda item: (item.order, item.iri))

    requirement_categories: List[RequirementCategory] = []
    for term in p.get(config.CAREER + "hasRequirementCategory", []):
        if term.kind != "iri":
            continue
        category = blocks.get(term.value, {})
        if not category:
            raise ValueError(f"requirement category {term.value} not found in {path}")
        rating_type = ttl_stream.literal_value(
            category, config.CAREER + "requirementRatingType", None
        )
        order = ttl_stream.numeric_value(
            category, config.CAREER + "requirementCategoryOrder", None
        )
        category_limit = ttl_stream.numeric_value(
            category, config.CAREER + "requirementCategoryLimit", None
        )
        if not rating_type or order is None or category_limit is None:
            raise ValueError(
                f"requirement category {term.value} lacks rating type, order, or limit"
            )
        label_terms_id = ttl_stream.literal_values(
            category, config.RDFS + "label", "id"
        )
        label_terms_en = ttl_stream.literal_values(
            category, config.RDFS + "label", "en"
        )
        fallback = local_name(term.value)
        label_id = label_terms_id[0].value if label_terms_id else fallback
        label_en = label_terms_en[0].value if label_terms_en else fallback
        requirement_categories.append(
            RequirementCategory(
                iri=term.value,
                key=local_name(term.value),
                rating_type=rating_type,
                label_en=label_en,
                label_id=label_id,
                order=int(order),
                limit=int(category_limit),
            )
        )
    requirement_categories.sort(key=lambda item: (item.order, item.iri))

    profile_groups: List[ProfileGroup] = []
    for term in p.get(config.CAREER + "hasProfileGroup", []):
        if term.kind != "iri":
            continue
        group = blocks.get(term.value, {})
        if not group:
            raise ValueError(f"profile group {term.value} not found in {path}")
        order = ttl_stream.numeric_value(
            group, config.CAREER + "profileGroupOrder", None
        )
        elements = [
            item.value
            for item in group.get(config.CAREER + "profileGroupElement", [])
            if item.kind == "iri"
        ]
        if order is None or not elements:
            raise ValueError(f"profile group {term.value} lacks order or elements")
        label_id = ttl_stream.literal_values(group, config.RDFS + "label", "id")
        label_en = ttl_stream.literal_values(group, config.RDFS + "label", "en")
        fallback = local_name(term.value)
        profile_groups.append(
            ProfileGroup(
                iri=term.value,
                key=local_name(term.value),
                label_id=label_id[0].value if label_id else fallback,
                label_en=label_en[0].value if label_en else fallback,
                order=int(order),
                elements=elements,
            )
        )
    profile_groups.sort(key=lambda item: (item.order, item.iri))

    lexicon_path = config.resolve_project_path(
        required_string(config.CAREER + "lexiconFile")
    )
    reasoning_map_path = config.resolve_project_path(
        required_string(config.CAREER + "hasReasoningMap")
    )
    index_policy = ttl_stream.iri_value(p, config.CAREER + "hasIndexPolicy", None)
    if not index_policy:
        raise ValueError(f"missing required career:hasIndexPolicy in {path}")

    return RankingPolicy(
        iri=policy_iri,
        name=ttl_stream.literal_value(p, config.RDFS + "label", local_name(policy_iri))
        or local_name(policy_iri),
        top_k=required_int(config.CAREER + "policyTopK"),
        candidate_limit=required_int(config.CAREER + "candidateLimit"),
        reasoning_candidate_limit=required_int(config.CAREER + "reasoningCandidateLimit"),
        lexical_candidate_limit=required_int(config.CAREER + "lexicalCandidateLimit"),
        require_eligible=required_bool(config.CAREER + "requireEligible"),
        fallback_tier=required_string(config.CAREER + "fallbackTier"),
        strong_holland_threshold=required_float(config.CAREER + "strongHollandThreshold"),
        strong_element_threshold=required_float(config.CAREER + "strongElementThreshold"),
        tier_order=tier_order,
        rule_files=rule_files,
        components=components,
        language_default=required_string(config.CAREER + "languageDefault"),
        default_education=required_string(config.CAREER + "defaultEducation"),
        default_max_job_zone=required_int(config.CAREER + "defaultMaxJobZone"),
        score_precision=required_int(config.CAREER + "scorePrecision"),
        explanation_limit=required_int(config.CAREER + "explanationLimit"),
        task_evidence_limit=required_int(config.CAREER + "taskEvidenceLimit"),
        job_title_evidence_limit=required_int(config.CAREER + "jobTitleEvidenceLimit"),
        description_preview_chars=required_int(config.CAREER + "descriptionPreviewChars"),
        interest_primary=required_bool(config.CAREER + "interestPrimary"),
        skill_level_min=required_float(config.CAREER + "skillLevelMin"),
        skill_level_max=required_float(config.CAREER + "skillLevelMax"),
        skill_requirement_scale_id=required_string(
            config.CAREER + "skillRequirementScaleId"
        ),
        interest_activity_weight=required_float(config.CAREER + "interestActivityWeight"),
        interest_keyword_weight=required_float(config.CAREER + "interestKeywordWeight"),
        direct_element_weight=required_float(config.CAREER + "directElementWeight"),
        direct_element_min_length=required_int(config.CAREER + "directElementMinLength"),
        holland_primary_weight=required_float(config.CAREER + "hollandPrimaryWeight"),
        holland_secondary_weight=required_float(config.CAREER + "hollandSecondaryWeight"),
        holland_tertiary_weight=required_float(config.CAREER + "hollandTertiaryWeight"),
        element_aggregation=required_string(config.CAREER + "elementAggregation"),
        lexical_normalization=required_string(config.CAREER + "lexicalNormalization"),
        reasoner_default=required_string(config.CAREER + "reasonerDefault"),
        lexicon_file=lexicon_path,
        reasoning_map_file=reasoning_map_path,
        index_policy_iri=index_policy,
        requirement_categories=requirement_categories,
        profile_groups=profile_groups,
        retrieval_mode=optional_string(config.CAREER + "retrievalMode", "auto") or "auto",
        semantic_normalization=optional_string(config.CAREER + "semanticNormalization", "minmax") or "minmax",
        semantic_candidate_limit=optional_int(config.CAREER + "semanticCandidateLimit", 2000),
        ontology_normalization=optional_string(config.CAREER + "ontologyNormalization", "minmax") or "minmax",
        ontology_candidate_limit=optional_int(config.CAREER + "ontologyCandidateLimit", 2000),
        embedding_model=optional_string(config.CAREER + "embeddingModel"),
        sparql_endpoint=optional_string(config.CAREER + "sparqlEndpoint"),
        sparql_timeout=optional_int(config.CAREER + "sparqlTimeout", 30),
    )


def load_index_policy(path: str | Path = config.DEFAULT_INDEX_POLICY) -> IndexPolicy:
    path = Path(path)
    blocks = load_block_map(path)
    policy_iri = config.CAREER + "DefaultIndexPolicy"
    if policy_iri not in blocks:
        found = _find_by_type(blocks, config.CAREER + "IndexPolicy")
        if not found:
            raise ValueError(f"no career:IndexPolicy found in {path}")
        policy_iri = found
    p = blocks[policy_iri]
    rating_types = [
        t.value
        for t in p.get(config.CAREER + "indexedRatingType", [])
        if t.kind == "literal"
    ]
    if not rating_types:
        raise ValueError(f"missing required career:indexedRatingType values in {path}")
    require_complete = ttl_stream.first(p, config.CAREER + "requireCompleteData")
    if require_complete is None:
        raise ValueError(f"missing required career:requireCompleteData in {path}")
    min_element_ratings = ttl_stream.numeric_value(
        p, config.CAREER + "minElementRatings", None
    )
    if min_element_ratings is None:
        raise ValueError(f"missing required career:minElementRatings in {path}")
    min_fts_token_length = ttl_stream.numeric_value(
        p, config.CAREER + "minFtsTokenLength", None
    )
    if min_fts_token_length is None:
        raise ValueError(f"missing required career:minFtsTokenLength in {path}")
    fts_tokenize = ttl_stream.literal_value(
        p, config.CAREER + "ftsTokenize", None
    )
    if not fts_tokenize:
        raise ValueError(f"missing required career:ftsTokenize in {path}")
    index_version = ttl_stream.literal_value(
        p, config.CAREER + "indexVersion", None
    )
    if not index_version:
        raise ValueError(f"missing required career:indexVersion in {path}")
    embedding_model = ttl_stream.literal_value(
        p, config.CAREER + "embeddingModel", None
    ) or "intfloat/multilingual-e5-small"
    embedding_batch_size = ttl_stream.numeric_value(
        p, config.CAREER + "embeddingBatchSize", None
    )
    embedding_max_tasks = ttl_stream.numeric_value(
        p, config.CAREER + "embeddingMaxTasks", None
    )
    embedding_max_elements = ttl_stream.numeric_value(
        p, config.CAREER + "embeddingMaxElements", None
    )
    embedding_max_job_titles = ttl_stream.numeric_value(
        p, config.CAREER + "embeddingMaxJobTitles", None
    )
    embedding_card_version = ttl_stream.literal_value(
        p, config.CAREER + "embeddingCardVersion", None
    ) or "1"
    profile_rating_types = [
        t.value
        for t in p.get(config.CAREER + "profileRatingType", [])
        if t.kind == "literal"
    ]
    extra_sources = [
        config.resolve_project_path(t.value)
        for t in p.get(config.CAREER + "extraSource", [])
        if t.kind == "literal"
    ]
    core_task_type = ttl_stream.literal_value(
        p, config.CAREER + "coreTaskType", "Core"
    ) or "Core"
    task_relevance_scale_id = ttl_stream.literal_value(
        p, config.CAREER + "taskRelevanceScaleId", "RT"
    ) or "RT"
    task_frequency_scale_id = ttl_stream.literal_value(
        p, config.CAREER + "taskFrequencyScaleId", "FT"
    ) or "FT"
    return IndexPolicy(
        iri=policy_iri,
        name=ttl_stream.literal_value(p, config.RDFS + "label", local_name(policy_iri)) or local_name(policy_iri),
        indexed_rating_types=rating_types,
        require_complete_data=bool(require_complete.python_value()),
        min_element_ratings=int(min_element_ratings),
        min_fts_token_length=int(min_fts_token_length),
        fts_tokenize=fts_tokenize,
        index_version=index_version,
        embedding_model=embedding_model,
        embedding_batch_size=int(embedding_batch_size) if embedding_batch_size is not None else 32,
        embedding_max_tasks=int(embedding_max_tasks) if embedding_max_tasks is not None else 8,
        embedding_max_elements=int(embedding_max_elements) if embedding_max_elements is not None else 12,
        embedding_max_job_titles=int(embedding_max_job_titles) if embedding_max_job_titles is not None else 5,
        embedding_card_version=embedding_card_version,
        profile_rating_types=profile_rating_types,
        extra_sources=extra_sources,
        core_task_type=core_task_type,
        task_relevance_scale_id=task_relevance_scale_id,
        task_frequency_scale_id=task_frequency_scale_id,
    )
