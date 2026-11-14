"""Profile-time SWRL reasoning over a small candidate slice.

The complete O*NET ABox is never sent to a reasoner.  The Pellet path builds a
temporary ontology bundle containing the schema, policy, rules, the user
profile, and a small set of candidate occupations.  The fallback path reports
SQL-filtered candidates as ``Eligible``; it is intentionally conservative.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from . import config, ttl_stream
from .extraction import Profile
from .policy import RankingPolicy
from .ttl_stream import local_name


class ReasoningUnavailable(RuntimeError):
    pass


class ReasoningError(RuntimeError):
    pass


class ReasoningService(Protocol):
    name: str

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
    ) -> Dict[str, dict]:
        ...


@dataclass
class SqlReasoner:
    """Fallback reasoner without SWRL.

    Candidate rows already passed the SQL education/job-zone filters.  The
    fallback therefore marks them eligible but cannot infer ``EligibleStrong``.
    """

    name: str = "sql"

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
    ) -> Dict[str, dict]:
        return {
            str(row["iri"]): {
                "eligible": True,
                "eligible_strong": False,
                "strong_holland": False,
                "missing_education": False,
                "missing_job_zone": False,
                "tier": "Eligible",
                "source": "sql",
            }
            for row in candidates
        }


class PelletReasoner:
    name = "pellet"

    def __init__(
        self,
        schema: str | Path | None = None,
        overlay: str | Path | None = None,
        rule_files: Optional[Sequence[str | Path]] = None,
        config_vocab: str | Path = config.DEFAULT_CONFIG_VOCAB,
        policy_file: str | Path = config.DEFAULT_POLICY,
        reasoning_map: str | Path | None = None,
        temp_dir: str | Path = config.DATA_DIR,
    ) -> None:
        self.schema = Path(schema or (config.SCHEMA_EN if config.SCHEMA_EN.exists() else config.SCHEMA_FALLBACK))
        self.overlay = Path(overlay) if overlay else None
        self.rule_files = [Path(path) for path in (rule_files or [])]
        self.config_vocab = Path(config_vocab)
        self.policy_file = Path(policy_file)
        self.reasoning_map = Path(reasoning_map) if reasoning_map else None
        self.temp_dir = Path(temp_dir)
        self._slice_map_cache: Optional[Dict[str, str]] = None

    def _slice_map(self) -> Dict[str, str]:
        if self._slice_map_cache is not None:
            return self._slice_map_cache
        from .rdf_loader import load_block_map

        path = self.reasoning_map or (config.CONFIG_DIR / "reasoning_map.ttl")
        if not path.exists():
            raise ReasoningError(f"reasoning slice map not found: {path}")
        blocks = load_block_map(path)
        subject = config.CAREER + "DefaultReasoningSliceMap"
        predicates = blocks.get(subject)
        if not predicates:
            raise ReasoningError(f"no career:DefaultReasoningSliceMap in {path}")
        fields = {
            "occupation_class": "sliceOccupationClass",
            "job_zone_class": "sliceJobZoneClass",
            "holland_namespace": "sliceHollandNamespace",
            "education_property": "sliceEducationProperty",
            "holland_property": "sliceHollandProperty",
            "rating_property": "sliceRatingProperty",
            "job_zone_rating_class": "sliceJobZoneRatingClass",
            "rated_job_zone_property": "sliceRatedJobZoneProperty",
            "job_zone_property": "sliceJobZoneProperty",
        }
        values: Dict[str, str] = {}
        for key, local in fields.items():
            predicate = config.CAREER + local
            if key == "holland_namespace":
                value = ttl_stream.literal_value(predicates, predicate, None)
            else:
                value = ttl_stream.iri_value(predicates, predicate, None)
            if not value:
                raise ReasoningError(f"missing {predicate} in {path}")
            values[key] = value
        self._slice_map_cache = values
        return values

    def _candidate_slice(self, candidates: Sequence[dict]) -> str:
        slice_map = self._slice_map()
        lines: List[str] = [
            "@prefix : <https://www.onetcenter.org/rdf/schema/onet/> .",
            "@prefix career: <https://example.org/career#> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
        ]
        for row in candidates:
            occ = str(row["iri"])
            parts: List[str] = [f"<{occ}> a <{slice_map['occupation_class']}>"]
            education = row.get("education_iri")
            if education:
                parts.append(f"    <{slice_map['education_property']}> <{education}>")
            primary = row.get("holland_primary")
            if primary:
                parts.append(
                    f"    <{slice_map['holland_property']}> <{slice_map['holland_namespace']}{primary}>"
                )
            lines.append(" ;\n".join(parts) + " .")
            zone_iri = row.get("job_zone_iri")
            zone = row.get("job_zone")
            if zone_iri and zone is not None:
                digest = hashlib.sha1(occ.encode("utf-8")).hexdigest()[:10]
                jzr = f"<{slice_map['holland_namespace']}slice_jobzone_rating_{digest}>"
                lines.extend(
                    [
                        f"<{occ}> <{slice_map['rating_property']}> {jzr} .",
                        f"{jzr} a <{slice_map['job_zone_rating_class']}> ;",
                        f"    <{slice_map['rated_job_zone_property']}> <{zone_iri}> .",
                        f"<{zone_iri}> a <{slice_map['job_zone_class']}> ;",
                        f"    <{slice_map['job_zone_property']}> \"{int(zone)}\"^^xsd:integer .",
                        "",
                    ]
                )
        return "\n".join(lines) + "\n"

    def _bundle(self, profile: Profile, candidates: Sequence[dict]) -> str:
        try:
            from rdflib import Graph
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ReasoningUnavailable(f"rdflib is required for the Pellet bundle: {exc}") from exc

        graph = Graph()
        for path in (
            self.schema,
            self.config_vocab,
            self.policy_file,
            *self.rule_files,
        ):
            if not path.exists():
                raise ReasoningError(f"reasoning input not found: {path}")
            graph.parse(path, format="turtle")
        graph.parse(data=profile.to_ttl(ontology=self._ontology()), format="turtle")
        graph.parse(data=self._candidate_slice(candidates), format="turtle")
        # Owlready2 does not parse Turtle reliably, so hand it RDF/XML.
        return graph.serialize(format="xml")

    def _ontology(self):
        # Avoid an import cycle at module import time.
        from .ontology import Ontology

        return Ontology(self.schema, self.overlay or config.find_overlay())

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
    ) -> Dict[str, dict]:
        try:
            import owlready2
            from owlready2 import World, sync_reasoner_pellet
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise ReasoningUnavailable(f"owlready2/Pellet is not available: {exc}") from exc

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        bundle_text = self._bundle(profile, candidates)
        fd, bundle_name = tempfile.mkstemp(
            prefix="ontorag_reasoning_", suffix=".owl", dir=str(self.temp_dir)
        )
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                fh.write(bundle_text)
            world = World()
            world.get_ontology(Path(bundle_name).as_uri()).load()
            try:
                sync_reasoner_pellet(
                    world,
                    infer_property_values=False,
                    infer_data_property_values=False,
                    debug=0,
                )
            except Exception as exc:
                raise ReasoningError(f"Pellet reasoning failed: {exc}") from exc
            return self._collect_inferred(world, candidates)
        finally:
            Path(bundle_name).unlink(missing_ok=True)

    @staticmethod
    def _class_instances(world, class_iri: str) -> set[str]:
        try:
            cls = world[class_iri]
        except Exception:
            return set()
        if cls is None:
            return set()
        return {str(individual.iri) for individual in cls.instances()}

    def _collect_inferred(
        self,
        world,
        candidates: Sequence[dict],
    ) -> Dict[str, dict]:
        eligible = self._class_instances(world, config.CAREER + "EligibleOccupation")
        strong = self._class_instances(world, config.CAREER + "EligibleStrong")
        strong_holland = self._class_instances(world, config.CAREER + "StrongHollandMatch")
        missing_education = self._class_instances(world, config.CAREER + "MissingEducation")
        missing_job_zone = self._class_instances(world, config.CAREER + "MissingJobZone")
        result: Dict[str, dict] = {}
        for row in candidates:
            iri = str(row["iri"])
            is_strong = iri in strong
            is_eligible = iri in eligible or is_strong
            result[iri] = {
                "eligible": is_eligible,
                "eligible_strong": is_strong,
                "strong_holland": iri in strong_holland,
                "missing_education": iri in missing_education,
                "missing_job_zone": iri in missing_job_zone,
                "tier": "EligibleStrong" if is_strong else ("Eligible" if is_eligible else "NotEligible"),
                "source": "pellet",
            }
        return result


class AutoReasoner:
    name = "auto"

    def __init__(self, pellet: PelletReasoner, fallback: Optional[ReasoningService] = None) -> None:
        self.pellet = pellet
        self.fallback = fallback or SqlReasoner()

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
    ) -> Dict[str, dict]:
        try:
            return self.pellet.infer(profile, candidates, policy)
        except (ReasoningUnavailable, ReasoningError) as exc:
            print(f"[ontorag] Pellet unavailable, using SQL eligibility fallback: {exc}", file=sys.stderr)
            return self.fallback.infer(profile, candidates, policy)


def make_reasoner(
    mode: str,
    policy: RankingPolicy,
    schema: str | Path | None = None,
    overlay: str | Path | None = None,
    policy_file: str | Path = config.DEFAULT_POLICY,
    temp_dir: str | Path = config.DATA_DIR,
) -> ReasoningService:
    mode = (mode or "auto").lower()
    pellet = PelletReasoner(
        schema=schema,
        overlay=overlay,
        rule_files=policy.rule_files,
        policy_file=policy_file,
        reasoning_map=policy.reasoning_map_file,
        temp_dir=temp_dir,
    )
    if mode == "pellet":
        return pellet
    if mode == "sql":
        return SqlReasoner()
    return AutoReasoner(pellet, SqlReasoner())
