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
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ontorag import config
from ontorag.graph_search import GraphSearchUnavailable
from ontorag.output import recommendations_json
from ontorag.pipeline import Pipeline

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
    app.state.pipeline = build_pipeline()
    yield
    app.state.pipeline.close()


app = FastAPI(title="OntoRAG", lifespan=lifespan)


class RecommendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = "id"
    education: Optional[str] = None
    max_job_zone: Optional[int] = Field(default=None, ge=1, le=5)
    top_k: int = Field(default=8, ge=1, le=20)


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


@app.post("/api/recommend")
async def recommend(request: RecommendRequest) -> dict:
    pipe: Pipeline = app.state.pipeline
    started = time.perf_counter()
    try:
        profile = pipe.profile_from_text(
            request.text,
            language=request.language,
            education=request.education,
            max_job_zone=request.max_job_zone,
        )
        recommendations = pipe.recommend(profile, top_k=request.top_k)
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
    payload["meta"] = {
        "retrieval": pipe.retrieval_mode,
        "reasoner": type(pipe.reasoner).__name__,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }
    return payload


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