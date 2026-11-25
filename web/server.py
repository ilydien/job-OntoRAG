"""FastAPI wrapper around the OntoRAG recommender.

One Pipeline is built at startup and reused.  Endpoints are ``async def`` and
call the blocking pipeline directly, so every request runs on the event-loop
thread and reuses the single SQLite connection safely.
# shortcut: requests are serialised (a slow ontology query blocks others);
# move the pipeline to a dedicated single-thread executor if concurrency is needed.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ontorag import config
from ontorag.graph_search import GraphSearchUnavailable
from ontorag.output import recommendations_json
from ontorag.pipeline import Pipeline
from ontorag.questions import EVIDENCE_INTENTS, QuestionRouter

RETRIEVAL = os.environ.get("ONTORAG_RETRIEVAL", "ontology")
REASONER = os.environ.get("ONTORAG_REASONER", "auto")
SPARQL_ENDPOINT = os.environ.get("ONTORAG_SPARQL_ENDPOINT") or None
INDEX_PATH = os.environ.get("ONTORAG_INDEX") or config.DEFAULT_INDEX
DIST = Path(__file__).resolve().parent / "frontend" / "dist"


def build_pipeline() -> Pipeline:
    try:
        return Pipeline.from_paths(
            index_path=INDEX_PATH,
            reasoner_mode=REASONER,
            retrieval=RETRIEVAL,
            sparql_endpoint=SPARQL_ENDPOINT,
        )
    except GraphSearchUnavailable:
        # shortcut: degrade to lexical instead of refusing to start when
        # rdflib/Jena is missing; swap RETRIEVAL if ontology must be mandatory.
        return Pipeline.from_paths(
            index_path=INDEX_PATH,
            reasoner_mode=REASONER,
            retrieval="lexical",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline = build_pipeline()
    app.state.pipeline = pipeline
    app.state.router = QuestionRouter(pipeline.index, pipeline.policy, pipeline.index_policy)
    yield
    pipeline.close()


app = FastAPI(title="OntoRAG", lifespan=lifespan)


class RecommendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = "id"
    education: Optional[str] = None
    max_job_zone: Optional[int] = Field(default=None, ge=1, le=5)
    skills: Optional[Dict[str, float]] = None
    top_k: int = Field(default=8, ge=1, le=20)


class AskRequest(RecommendRequest):
    context: Optional[str] = Field(default=None, max_length=2000)
    occupation: Optional[str] = None


def _router() -> QuestionRouter:
    router = getattr(app.state, "router", None)
    if router is not None:
        return router
    pipe: Pipeline = app.state.pipeline
    return QuestionRouter(pipe.index, pipe.policy, pipe.index_policy)


@app.get("/api/meta")
async def meta() -> dict:
    pipe: Pipeline = app.state.pipeline
    index_meta = pipe.index.meta()
    levels = [
        {
            "value": level.local,
            "label": level.label_id or level.label_en,
            "order": level.order,
        }
        for level in pipe.ontology.education_levels()
    ]
    return {
        "app": "OntoRAG",
        "retrieval": pipe.retrieval_mode,
        "reasoner": type(pipe.reasoner).__name__,
        "occupations": int(index_meta.get("occupations", 0) or 0),
        "education_levels": levels,
    }


@app.get("/api/occupation/profile")
async def occupation_profile(iri: str, language: str = "id") -> dict:
    pipe: Pipeline = app.state.pipeline
    payload = pipe.index.occupation_profile(
        iri,
        language=language,
        groups=pipe.policy.profile_groups,
        core_task_type=pipe.index_policy.core_task_type,
        relevance_scale_id=pipe.index_policy.task_relevance_scale_id,
        frequency_scale_id=pipe.index_policy.task_frequency_scale_id,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Occupation not found.")
    return payload


@app.get("/api/occupation/requirements")
async def occupation_requirements(iri: str, language: str = "id") -> dict:
    pipe: Pipeline = app.state.pipeline
    payload = pipe.index.requirements_for(
        iri,
        pipe.policy.requirement_categories,
        language=language,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Occupation not found.")
    return payload


def _evidence_answer(
    pipe: Pipeline,
    intent: str,
    occupation: dict,
    context: Optional[str],
    language: str = "id",
) -> dict:
    label = "Alasan rekomendasi" if intent == "why_recommended" else "Komponen skor dan evidence"
    if not context:
        return {
            "heading": label,
            "summary": (
                "Pertanyaan ini butuh konteks pencarian. Cari minat dulu, lalu "
                "tanyakan mengapa pekerjaan itu direkomendasikan."
            ),
            "facts": [],
            "items": [],
            "groups": [],
        }
    try:
        profile = pipe.profile_from_text(context, language=language)
        recommendations = pipe.recommend(profile, top_k=50)
    except Exception as exc:  # surface engine errors in the answer panel
        return {
            "heading": label,
            "summary": f"Gagal menghitung rekomendasi: {exc}",
            "facts": [],
            "items": [],
            "groups": [],
        }
    target = str(occupation.get("iri"))
    recommendation = next(
        (item for item in recommendations if item.occupation_iri == target), None
    )
    if recommendation is None:
        return {
            "heading": label,
            "summary": f"{occupation.get('title')} tidak termasuk rekomendasi untuk konteks itu.",
            "facts": [],
            "items": [],
            "groups": [],
        }
    facts = [
        {"label": "Skor akhir", "value": f"{recommendation.score:.4f}"},
        {"label": "Tier", "value": recommendation.tier},
    ]
    evidence_rows = [
        {
            "title": entry.get("label") or entry.get("kind") or "",
            "detail": entry.get("detail") or "",
        }
        for entry in recommendation.evidence
    ]
    if intent == "why_recommended":
        return {
            "heading": label,
            "summary": recommendation.explanation or "",
            "facts": facts,
            "items": evidence_rows,
            "groups": [],
        }
    component_rows = [
        {"title": key, "detail": f"{float(value):.4f}"}
        for key, value in recommendation.component_scores.items()
    ]
    return {
        "heading": label,
        "summary": f"Komponen skor {occupation.get('title')}.",
        "facts": facts,
        "items": [],
        "groups": [
            {"heading": "Komponen skor", "items": component_rows},
            {"heading": "Evidence", "items": evidence_rows},
        ],
    }


def _recommend_payload(pipe: Pipeline, request: RecommendRequest) -> dict:
    started = time.perf_counter()
    try:
        profile = pipe.profile_from_text(
            request.text,
            language=request.language,
            education=request.education,
            max_job_zone=request.max_job_zone,
            skills=request.skills,
        )
        recommendations = pipe.recommend(profile, top_k=request.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # surface engine errors to the UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = json.loads(
        recommendations_json(
            recommendations,
            profile=profile,
            language=request.language,
            precision=pipe.policy.score_precision,
        )
    )
    # recommendations_json emits IRI -> label; the UI needs label -> weight.
    labels = getattr(profile, "element_labels", {}) or {}
    payload["profile"]["elements"] = [
        {"label": labels.get(iri, iri), "weight": round(float(weight), 4)}
        for iri, weight in (profile.elements or {}).items()
    ]
    skill_labels = getattr(profile, "skill_labels", {}) or {}
    payload["profile"]["skills"] = [
        {"label": skill_labels.get(iri, iri), "level": round(float(level), 2)}
        for iri, level in (profile.skill_levels or {}).items()
    ]
    payload["meta"] = {
        "retrieval": pipe.retrieval_mode,
        "reasoner": type(pipe.reasoner).__name__,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }
    return payload


@app.post("/api/recommend")
async def recommend(request: RecommendRequest) -> dict:
    return _recommend_payload(app.state.pipeline, request)


@app.get("/api/occupation/search")
async def occupation_search(q: str, limit: int = 10) -> dict:
    return {"query": q, "items": _router().search(q, limit=limit)}


@app.post("/api/ask")
async def ask(request: AskRequest) -> dict:
    pipe: Pipeline = app.state.pipeline
    router = _router()
    decision = router.decide(
        request.text,
        language=request.language,
        occupation=request.occupation,
    )
    if decision["mode"] == "recommend":
        payload = _recommend_payload(pipe, request)
        payload["mode"] = "recommend"
        return payload
    if decision["mode"] != "answer":
        return decision
    intent = decision["intent"]
    occupation = decision["occupation"]
    if intent in EVIDENCE_INTENTS:
        answer = _evidence_answer(
            pipe, intent, occupation, request.context, request.language
        )
    else:
        answer = router.answer(intent, occupation, request.language)
    return {
        "mode": "answer",
        "intent": intent,
        "label": decision.get("label"),
        "match": decision.get("match"),
        "occupation": occupation,
        "occupation_match": decision.get("occupation_match"),
        "suggestions": decision.get("suggestions", []),
        "answer": answer,
    }


if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
else:

    @app.get("/")
    async def root() -> dict:
        return {
            "app": "OntoRAG API",
            "docs": "/docs",
            "frontend": "run `npm install && npm run build` in web/frontend",
        }