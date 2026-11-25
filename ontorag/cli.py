"""Command-line interface for the OntoRAG terminal prototype."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

from . import config
from .index import build_index
from .output import recommendations_json, recommendations_table, recommendations_ttl
from .pipeline import Pipeline


def _add_common_data_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    parser.add_argument("--schema", default=None, help="English O*NET schema TTL")
    parser.add_argument("--overlay", default=None, help="Indonesian i18n overlay TTL")
    parser.add_argument("--policy", default=str(config.DEFAULT_POLICY), help="ranking policy TTL")
    parser.add_argument("--index-policy", default=str(config.DEFAULT_INDEX_POLICY), help="index policy TTL")
    parser.add_argument("--lexicon", default=None, help="lexicon TTL")


def _pipeline(args: argparse.Namespace, reasoner_mode: str, retrieval: Optional[str] = None) -> Pipeline:
    return Pipeline.from_paths(
        index_path=args.index,
        schema_path=args.schema,
        overlay_path=args.overlay,
        policy_path=args.policy,
        index_policy_path=args.index_policy,
        lexicon_path=args.lexicon,
        reasoner_mode=reasoner_mode,
        retrieval=retrieval or getattr(args, "retrieval", None),
        embedding_model=getattr(args, "embedding_model", None),
        sparql_endpoint=getattr(args, "sparql_endpoint", None),
        sparql_timeout=getattr(args, "sparql_timeout", None),
    )


def _parse_skills(values: Optional[Sequence[str]]) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"skill must use Name=Level syntax: {raw}")
        name, level = raw.rsplit("=", 1)
        result[name.strip()] = float(level)
    return result


def cmd_build_index(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    if index_path.exists() and not args.rebuild:
        print(f"Index already exists: {index_path}", file=sys.stderr)
        print("Use --rebuild to replace it.", file=sys.stderr)
        return 2
    build_index(
        abox=args.abox,
        schema=args.schema,
        overlay=args.overlay,
        index=index_path,
        index_policy=args.index_policy,
        extra_sources=args.extra_source,
        verbose=not args.quiet,
    )
    if args.with_embeddings:
        from .embeddings import CardLimits, build_embeddings
        from .policy import load_index_policy

        policy = load_index_policy(args.index_policy)
        build_embeddings(
            index_path=index_path,
            model_name=args.embedding_model or policy.embedding_model,
            batch_size=policy.embedding_batch_size,
            limits=CardLimits(
                max_tasks=policy.embedding_max_tasks,
                max_elements=policy.embedding_max_elements,
                max_job_titles=policy.embedding_max_job_titles,
            ),
            verbose=not args.quiet,
        )
    return 0


def cmd_build_graph(args: argparse.Namespace) -> int:
    from .graph_export import export_graph

    target = Path(args.out)
    if target.exists() and not args.rebuild:
        print(f"Derived graph already exists: {target}", file=sys.stderr)
        print("Use --rebuild to replace it.", file=sys.stderr)
        return 2
    export_graph(args.index, target, verbose=not args.quiet)
    return 0


def cmd_build_embeddings(args: argparse.Namespace) -> int:
    from .embeddings import CardLimits, build_embeddings
    from .policy import load_index_policy

    policy = load_index_policy(args.index_policy)
    meta = build_embeddings(
        index_path=args.index,
        model_name=args.model or policy.embedding_model,
        batch_size=args.batch_size or policy.embedding_batch_size,
        rebuild=args.rebuild,
        limits=CardLimits(
            max_tasks=policy.embedding_max_tasks,
            max_elements=policy.embedding_max_elements,
            max_job_titles=policy.embedding_max_job_titles,
        ),
        verbose=not args.quiet,
    )
    for key in ("model", "dim", "count", "built_at", "index_fingerprint"):
        if key in meta:
            print(f"{key}: {meta[key]}")
    return 0


def cmd_show_meta(args: argparse.Namespace) -> int:
    from .query_engine import Index

    with Index(args.index) as index:
        meta = index.meta()
        embedding_meta = index.embedding_meta()
    for key, value in meta.items():
        print(f"{key}: {value}")
    for key, value in sorted(embedding_meta.items()):
        print(f"embedding.{key}: {value}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    reasoner_mode = "sql"
    with _pipeline(args, reasoner_mode, retrieval="lexical") as pipeline:
        if args.profile:
            profile = pipeline.profile_from_json(args.profile, text=args.text, language=args.language)
        else:
            if not args.text:
                print("--text is required when --profile is not used", file=sys.stderr)
                return 2
            profile = pipeline.profile_from_text(
                args.text,
                language=args.language,
                user_iri=args.user_iri,
                education=args.education,
                max_job_zone=args.max_job_zone,
            )
        skills = _parse_skills(getattr(args, "skill", None))
        if skills:
            profile.add_skill_levels(
                skills,
                pipeline.catalog,
                min_level=pipeline.policy.skill_level_min,
                max_level=pipeline.policy.skill_level_max,
            )
        if args.format == "ttl":
            print(profile.to_ttl(pipeline.ontology))
        else:
            payload = {
                "user_iri": profile.user_iri,
                "language": profile.language,
                "education_level": profile.education_local,
                "education_order": profile.education_order,
                "max_job_zone": profile.max_job_zone,
                "holland": profile.holland,
                "elements": profile.element_labels,
                "element_weights": profile.elements,
                "skills": {
                    profile.skill_labels.get(iri, iri): level
                    for iri, level in profile.skill_levels.items()
                },
                "skill_levels": profile.skill_levels,
                "evidence": profile.evidence,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    if not args.text and not args.profile:
        print("provide --text and/or --profile", file=sys.stderr)
        return 2
    if getattr(args, "java", None):
        from .reasoning import JAVA_ENV

        os.environ[JAVA_ENV] = str(args.java)
    with _pipeline(args, args.reasoner) as pipeline:
        if args.profile:
            profile = pipeline.profile_from_json(
                args.profile, text=args.text, language=args.language
            )
        else:
            profile = pipeline.profile_from_text(
                args.text,
                language=args.language,
                user_iri=args.user_iri,
                education=args.education,
                max_job_zone=args.max_job_zone,
            )
        skills = _parse_skills(getattr(args, "skill", None))
        if skills:
            profile.add_skill_levels(
                skills,
                pipeline.catalog,
                min_level=pipeline.policy.skill_level_min,
                max_level=pipeline.policy.skill_level_max,
            )
        recommendations = pipeline.recommend(profile, top_k=args.top_k)
        output_language = args.language or profile.language or pipeline.policy.language_default
        if args.format == "json":
            text = recommendations_json(
                recommendations,
                profile=profile,
                language=output_language,
                precision=pipeline.policy.score_precision,
            )
        elif args.format == "ttl":
            text = recommendations_ttl(
                profile,
                recommendations,
                pipeline.ontology,
                language=output_language,
                description_limit=pipeline.policy.description_preview_chars,
            )
        else:
            text = recommendations_table(
                recommendations,
                language=output_language,
                precision=pipeline.policy.score_precision,
            )
            if recommendations:
                details = []
                for item in recommendations:
                    details.append("")
                    details.append(
                        f"{item.rank}. {item.display_title(output_language)} "
                        f"[{item.tier}, {item.score:.{pipeline.policy.score_precision}f}]"
                    )
                    if item.explanation:
                        details.append(f"   {item.explanation}")
                    description = item.display_description(
                        output_language,
                        limit=pipeline.policy.description_preview_chars,
                    )
                    if description:
                        details.append(f"   Deskripsi: {description}")
                    for evidence in item.evidence[: pipeline.policy.explanation_limit]:
                        detail = evidence.get("detail")
                        label = evidence.get("label")
                        if label and detail:
                            details.append(f"   - {label}: {detail}")
                        elif label:
                            details.append(f"   - {label}")
                text += "\n" + "\n".join(details)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    from .policy import load_index_policy, load_ranking_policy
    from .query_engine import Index

    policy = load_ranking_policy(args.policy)
    index_policy = load_index_policy(args.index_policy)
    with Index(args.index) as index:
        payload = index.occupation_profile(
            args.occupation,
            language=args.language or "id",
            groups=policy.profile_groups,
            core_task_type=index_policy.core_task_type,
            relevance_scale_id=index_policy.task_relevance_scale_id,
            frequency_scale_id=index_policy.task_frequency_scale_id,
        )
    if payload is None:
        print(f"unknown occupation: {args.occupation}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    occupation = payload["occupation"]
    print(f"{occupation.get('title_id') or occupation.get('title_en')} [{occupation.get('soc') or '-'}]")
    tasks = payload.get("tasks") or []
    print("\nTugas inti:")
    for task in tasks[:10]:
        suffix = f" ({task['frequency']}, {task['frequency_percent']:.1f}%)" if task.get("frequency") and task.get("frequency_percent") is not None else ""
        print(f"- {task['task']}{suffix}")
    for section in payload.get("profile_sections") or []:
        print(f"\n{section['key']}:")
        for element in section.get("elements") or []:
            print(f"- {element.get('label')}")
            for item in (element.get("items") or [])[:5]:
                print(f"  - {item.get('label') or item.get('category')}: {item.get('value')}")
    return 0


def cmd_requirements(args: argparse.Namespace) -> int:
    from .policy import load_ranking_policy
    from .query_engine import Index

    policy = load_ranking_policy(args.policy)
    with Index(args.index) as index:
        payload = index.requirements_for(
            args.occupation,
            policy.requirement_categories,
            language=args.language or policy.language_default,
        )
    if payload is None:
        print(f"unknown occupation: {args.occupation}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    occupation = payload["occupation"]
    education = payload["education"]
    zone = payload["job_zone"]
    print(f"{occupation.get('title') or occupation.get('title_en')} [{occupation.get('soc') or '-'}]")
    print(f"Pendidikan minimum: {education.get('label') or education.get('local') or '-'}")
    zone_name = zone.get("name")
    print(f"Job zone: {zone.get('value') if zone.get('value') is not None else '-'}" + (f" ({zone_name})" if zone_name else ""))
    for category in payload["requirements"]:
        if not category["items"]:
            continue
        print(f"\n{category['label']}:")
        for item in category["items"]:
            scale_bits = []
            if item.get("level") is not None:
                scale_bits.append(f"level {float(item['level']):.2f}")
            if item.get("importance") is not None:
                scale_bits.append(f"importance {float(item['importance']):.2f}")
            detail = ", ".join(scale_bits) or f"score {float(item['normalized'] or 0):.3f}"
            print(f"- {item['label']} ({detail})")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .policy import load_index_policy, load_ranking_policy
    from .query_engine import Index
    from .questions import EVIDENCE_INTENTS, QuestionRouter

    policy = load_ranking_policy(args.policy)
    index_policy = load_index_policy(args.index_policy)
    with Index(args.index) as index:
        router = QuestionRouter(index, policy, index_policy)
        decision = router.decide(
            args.text, language=args.language or "id", occupation=args.occupation
        )
        if decision["mode"] == "recommend":
            print("mode: recommend (teks ini dianggap deskripsi minat, bukan pertanyaan)")
            return 0
        if decision["mode"] != "answer":
            print(f"mode: {decision['mode']}")
            if decision.get("message"):
                print(decision["message"])
            for candidate in decision.get("candidates", []):
                print(f"- {candidate.get('title')} [{candidate.get('soc')}] {candidate.get('iri')}")
            return 0
        if decision["intent"] in EVIDENCE_INTENTS:
            print(f"{decision.get('label')}: butuh konteks pencarian; jawab lewat web UI.")
            return 0
        answer = router.answer(decision["intent"], decision["occupation"], args.language or "id")
    if args.format == "json":
        print(json.dumps(
            {
                "intent": decision["intent"],
                "occupation": decision["occupation"],
                "answer": answer,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    occupation = decision["occupation"]
    print(f"{decision.get('label')} · {occupation.get('title')} [{occupation.get('soc') or '-'}]")
    print(answer["heading"])
    print(answer["summary"])
    for fact in answer["facts"]:
        print(f"- {fact['label']}: {fact['value']}")
    for item in answer["items"]:
        print(f"- {item['title']}" + (f": {item['detail']}" if item.get("detail") else ""))
    for group in answer["groups"]:
        print(f"\n{group['heading']}:")
        for item in group["items"]:
            print(f"- {item['title']}" + (f": {item['detail']}" if item.get("detail") else ""))
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from .benchmark import BenchmarkResult, evaluate, load_gold_set
    from .reasoning import JAVA_ENV

    gold = load_gold_set(args.queries)
    if not gold.queries:
        print(f"no gold queries in {args.queries}", file=sys.stderr)
        return 2
    if getattr(args, "java", None):
        os.environ[JAVA_ENV] = str(args.java)

    default_education = args.education or gold.default_education or "S3"
    if args.max_job_zone is not None:
        default_job_zone = args.max_job_zone
    elif gold.default_max_job_zone is not None:
        default_job_zone = gold.default_max_job_zone
    else:
        default_job_zone = 5

    modes = [mode.strip() for mode in args.retrieval.split(",") if mode.strip()]
    allowed = {"auto", "ontology", "semantic", "lexical", "hybrid"}
    unknown = [mode for mode in modes if mode not in allowed]
    if unknown:
        print(f"unknown retrieval mode(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    results = []
    for mode in modes:
        try:
            with _pipeline(args, args.reasoner, retrieval=mode) as pipeline:

                def recommend(query, pipeline=pipeline):
                    profile = pipeline.profile_from_text(
                        query.text,
                        language=query.language,
                        education=query.education or default_education,
                        max_job_zone=(
                            query.max_job_zone
                            if query.max_job_zone is not None
                            else default_job_zone
                        ),
                    )
                    return pipeline.recommend(profile, top_k=args.k, text=query.text)

                results.append(evaluate(mode, recommend, gold.queries, k=args.k))
        except Exception as exc:  # keep the remaining modes usable
            results.append(
                BenchmarkResult(
                    mode=mode,
                    k=args.k,
                    query_count=len(gold.queries),
                    recall_at_k=0.0,
                    mrr=0.0,
                    latency_seconds=0.0,
                    error=str(exc),
                )
            )

    if args.format == "json":
        print(
            json.dumps(
                [result.as_dict() for result in results],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    header = f"{'mode':<10} {'k':>3} {'queries':>7} {'recall@k':>9} {'MRR':>6} {'latency(s)':>10}"
    print(header)
    print("-" * len(header))
    for result in results:
        if result.error:
            print(f"{result.mode:<10} {result.k:>3} {result.query_count:>7} {'n/a':>9} {'n/a':>6} {'n/a':>10}  {result.error}")
        else:
            print(
                f"{result.mode:<10} {result.k:>3} {result.query_count:>7} "
                f"{result.recall_at_k:>9.3f} {result.mrr:>6.3f} {result.latency_seconds:>10.2f}"
            )
    if args.verbose:
        for result in results:
            if result.error:
                continue
            print(f"\n[{result.mode}]")
            for score in result.per_query:
                marker = "hit" if score.recall_at_k > 0 else "MISS"
                print(
                    f"  {marker:>4} R@k={score.recall_at_k:.2f} RR={score.reciprocal_rank:.2f} "
                    f"{score.text}"
                )
                print(f"       expected: {', '.join(score.expected_soc)}")
                print(f"       ranked:   {', '.join(score.ranked_soc) or '-'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ontorag.cli",
        description="Ontology-grounded career recommender (terminal prototype).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-index", help="build the SQLite FTS5 index from onet_abox.ttl")
    build.add_argument("--abox", default=str(config.ABOX), help="O*NET ABox TTL")
    build.add_argument("--schema", default=None, help="English schema TTL")
    build.add_argument("--overlay", default=None, help="Indonesian i18n overlay TTL")
    build.add_argument("--index", default=str(config.DEFAULT_INDEX), help="output SQLite index")
    build.add_argument("--index-policy", default=str(config.DEFAULT_INDEX_POLICY), help="index policy TTL")
    build.add_argument("--rebuild", action="store_true", help="replace an existing index")
    build.add_argument(
        "--extra-source",
        action="append",
        default=None,
        help="additional Turtle source for profile ratings (repeatable)",
    )
    build.add_argument("--quiet", action="store_true", help="suppress progress output")
    build.add_argument(
        "--with-embeddings",
        action="store_true",
        help="build occupation-card embeddings after the index",
    )
    build.add_argument("--embedding-model", default=None, help="sentence-transformers model id")
    build.set_defaults(func=cmd_build_index)

    graph = sub.add_parser(
        "build-graph",
        help="export the derived RDF graph for Jena/Fuseki SPARQL retrieval",
    )
    graph.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    graph.add_argument(
        "--out",
        default=str(config.DATA_DIR / "ontorag_derived.nt"),
        help="output N-Triples file",
    )
    graph.add_argument("--rebuild", action="store_true", help="replace an existing graph file")
    graph.add_argument("--quiet", action="store_true", help="suppress progress output")
    graph.set_defaults(func=cmd_build_graph)

    embeddings = sub.add_parser(
        "build-embeddings", help="embed occupation cards into the SQLite index"
    )
    embeddings.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    embeddings.add_argument("--index-policy", default=str(config.DEFAULT_INDEX_POLICY), help="index policy TTL")
    embeddings.add_argument("--model", default=None, help="sentence-transformers model id")
    embeddings.add_argument("--batch-size", type=int, default=None, help="embedding batch size")
    embeddings.add_argument("--rebuild", action="store_true", help="recompute all vectors")
    embeddings.add_argument("--quiet", action="store_true", help="suppress progress output")
    embeddings.set_defaults(func=cmd_build_embeddings)

    meta = sub.add_parser("show-meta", help="show index metadata")
    meta.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    meta.set_defaults(func=cmd_show_meta)

    extract = sub.add_parser("extract", help="extract a structured profile from free text")
    extract.add_argument("--text", default=None, help="free-text career profile")
    extract.add_argument("--profile", default=None, help="profile JSON")
    extract.add_argument("--education", default=None, help="education level (e.g. S1)")
    extract.add_argument("--max-job-zone", type=int, default=None, help="maximum job zone (1-5)")
    extract.add_argument("--language", choices=["id", "en"], default=None)
    extract.add_argument("--user-iri", default=None)
    extract.add_argument("--skill", action="append", default=None, help="declared skill as Name=Level")
    extract.add_argument("--format", choices=["json", "ttl"], default="json")
    _add_common_data_args(extract)
    extract.set_defaults(func=cmd_extract)

    recommend = sub.add_parser("recommend", help="rank occupations for a profile")
    recommend.add_argument("--text", default=None, help="free-text career profile")
    recommend.add_argument("--profile", default=None, help="profile JSON")
    recommend.add_argument("--education", default=None, help="education level (e.g. S1)")
    recommend.add_argument("--max-job-zone", type=int, default=None, help="maximum job zone (1-5)")
    recommend.add_argument("--top-k", type=int, default=None, help="number of results")
    recommend.add_argument("--format", choices=["table", "json", "ttl"], default="table")
    recommend.add_argument("--language", choices=["id", "en"], default=None)
    recommend.add_argument("--reasoner", choices=["auto", "pellet", "sql"], default=None)
    recommend.add_argument(
        "--retrieval",
        choices=["auto", "ontology", "semantic", "lexical", "hybrid"],
        default=None,
        help="candidate retrieval mode (default: ranking policy)",
    )
    recommend.add_argument("--embedding-model", default=None, help="sentence-transformers model id")
    recommend.add_argument(
        "--sparql-endpoint",
        default=None,
        help="Jena/Fuseki SPARQL endpoint for --retrieval ontology",
    )
    recommend.add_argument(
        "--sparql-timeout",
        type=int,
        default=None,
        help="SPARQL request timeout in seconds",
    )
    recommend.add_argument(
        "--java",
        default=None,
        help="Java executable or JAVA_HOME for Pellet (default: auto-detect)",
    )
    recommend.add_argument("--user-iri", default=None)
    recommend.add_argument("--skill", action="append", default=None, help="declared skill as Name=Level")
    recommend.add_argument("--out", default=None, help="write output to a file")
    _add_common_data_args(recommend)
    recommend.set_defaults(func=cmd_recommend)

    profile = sub.add_parser(
        "profile",
        help="show tasks, qualifications, and work context for one occupation",
    )
    profile.add_argument("--occupation", required=True, help="occupation IRI")
    profile.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    profile.add_argument("--policy", default=str(config.DEFAULT_POLICY), help="ranking policy TTL")
    profile.add_argument("--index-policy", default=str(config.DEFAULT_INDEX_POLICY), help="index policy TTL")
    profile.add_argument("--language", choices=["id", "en"], default=None)
    profile.add_argument("--format", choices=["table", "json"], default="table")
    profile.set_defaults(func=cmd_profile)

    requirements = sub.add_parser(
        "requirements",
        help="show education, job zone, and top O*NET requirements for one occupation",
    )
    requirements.add_argument("--occupation", required=True, help="occupation IRI")
    requirements.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    requirements.add_argument("--policy", default=str(config.DEFAULT_POLICY), help="ranking policy TTL")
    requirements.add_argument("--language", choices=["id", "en"], default=None)
    requirements.add_argument("--format", choices=["table", "json"], default="table")
    requirements.set_defaults(func=cmd_requirements)

    ask = sub.add_parser(
        "ask",
        help="route a free-text question about one occupation to an answer",
    )
    ask.add_argument("--text", required=True, help="question, e.g. 'Apa pendidikan minimum pekerjaan Ilmuwan Data?'")
    ask.add_argument("--occupation", default=None, help="explicit occupation IRI, skipping name matching")
    ask.add_argument("--index", default=str(config.DEFAULT_INDEX), help="SQLite index path")
    ask.add_argument("--policy", default=str(config.DEFAULT_POLICY), help="ranking policy TTL")
    ask.add_argument("--index-policy", default=str(config.DEFAULT_INDEX_POLICY), help="index policy TTL")
    ask.add_argument("--language", choices=["id", "en"], default=None)
    ask.add_argument("--format", choices=["table", "json"], default="table")
    ask.set_defaults(func=cmd_ask)

    benchmark = sub.add_parser(
        "benchmark",
        help="measure Recall@k/MRR of retrieval over the gold query set",
    )
    benchmark.add_argument(
        "--queries",
        default=str(config.DEFAULT_BENCHMARK_QUERIES),
        help="gold query JSON file",
    )
    benchmark.add_argument("--k", type=int, default=10, help="cut-off for Recall@k")
    benchmark.add_argument(
        "--retrieval",
        default="lexical,semantic,hybrid",
        help="comma-separated retrieval modes to compare",
    )
    benchmark.add_argument("--reasoner", choices=["auto", "pellet", "sql"], default=None)
    benchmark.add_argument("--education", default=None, help="override default education")
    benchmark.add_argument(
        "--max-job-zone", type=int, default=None, help="override default max job zone"
    )
    benchmark.add_argument("--format", choices=["table", "json"], default="table")
    benchmark.add_argument("--verbose", action="store_true", help="per-query scores")
    benchmark.add_argument("--embedding-model", default=None, help="sentence-transformers model id")
    benchmark.add_argument(
        "--sparql-endpoint",
        default=None,
        help="Jena/Fuseki SPARQL endpoint for --retrieval ontology",
    )
    benchmark.add_argument(
        "--sparql-timeout",
        type=int,
        default=None,
        help="SPARQL request timeout in seconds",
    )
    benchmark.add_argument(
        "--java",
        default=None,
        help="Java executable or JAVA_HOME for Pellet (default: auto-detect)",
    )
    _add_common_data_args(benchmark)
    benchmark.set_defaults(func=cmd_benchmark)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "reasoner", None) is None:
        args.reasoner = "auto"
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
