"""Command-line interface for the OntoRAG terminal prototype."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

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
    )


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
                "evidence": profile.evidence,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    if not args.text and not args.profile:
        print("provide --text and/or --profile", file=sys.stderr)
        return 2
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
    build.add_argument("--quiet", action="store_true", help="suppress progress output")
    build.add_argument(
        "--with-embeddings",
        action="store_true",
        help="build occupation-card embeddings after the index",
    )
    build.add_argument("--embedding-model", default=None, help="sentence-transformers model id")
    build.set_defaults(func=cmd_build_index)

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
        choices=["auto", "semantic", "lexical", "hybrid"],
        default=None,
        help="candidate retrieval mode (default: ranking policy)",
    )
    recommend.add_argument("--embedding-model", default=None, help="sentence-transformers model id")
    recommend.add_argument("--user-iri", default=None)
    recommend.add_argument("--out", default=None, help="write output to a file")
    _add_common_data_args(recommend)
    recommend.set_defaults(func=cmd_recommend)

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
