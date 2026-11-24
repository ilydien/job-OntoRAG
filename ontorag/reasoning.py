"""Profile-time SWRL reasoning over a small candidate slice.

The complete O*NET ABox is never sent to a reasoner.  The Pellet path builds a
temporary ontology bundle containing the schema, policy, rules, the user
profile, and a small set of candidate occupations.  The fallback path reports
SQL-filtered candidates as ``Eligible``; it is intentionally conservative.
"""

from __future__ import annotations

import hashlib
import os
import shutil
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


JAVA_ENV = "ONTORAG_JAVA"


def _java_binary(home: str | Path) -> Path:
    home = Path(home).expanduser()
    binary = home / "bin" / ("java.exe" if os.name == "nt" else "java")
    return binary


def _usable_java(path: Optional[Path]) -> Optional[Path]:
    if path is None:
        return None
    try:
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    except OSError:
        return None
    return None


def resolve_java_executable() -> Optional[Path]:
    """Locate the Java runtime used by owlready2/Pellet.

    Priority: explicit ``ONTORAG_JAVA``, ``JAVA_HOME``, the runtime bundled in
    ``environment/jre``, a local ``jre`` folder, then ``java`` on ``PATH``.
    ``ONTORAG_JAVA`` may point either at the ``java`` binary or at a JDK/JRE
    home directory.
    """

    explicit = os.environ.get(JAVA_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_dir():
            candidate = _java_binary(candidate)
        usable = _usable_java(candidate)
        if usable:
            return usable

    home = os.environ.get("JAVA_HOME")
    if home:
        usable = _usable_java(_java_binary(home))
        if usable:
            return usable

    for bundled in (config.BUNDLED_JRE, config.PROJECT_ROOT / "jre"):
        usable = _usable_java(_java_binary(bundled))
        if usable:
            return usable

    found = shutil.which("java")
    return _usable_java(Path(found)) if found else None


def configure_java_environment() -> Optional[Path]:
    """Expose the resolved Java runtime to child processes.

    Both ``JAVA_HOME``/``PATH`` and (later) ``owlready2.JAVA_EXE`` are set so
    the reasoner works across owlready2 versions without relying on a global
    Java installation.
    """

    java = resolve_java_executable()
    if java is None:
        return None
    os.environ.setdefault("JAVA_HOME", str(java.parent.parent))
    bin_dir = str(java.parent)
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    if bin_dir not in parts:
        os.environ["PATH"] = bin_dir + (os.pathsep + path if path else "")
    return java


class ReasoningService(Protocol):
    name: str

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
        skill_requirements: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
    ) -> Dict[str, dict]:
        ...


@dataclass
class SqlReasoner:
    """Fallback reasoner without SWRL.

    Candidate rows already passed the SQL education/job-zone filters.  The
    fallback therefore marks them eligible but cannot infer ``EligibleStrong``.
    """

    fallback_tier: str
    name: str = "sql"

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
        skill_requirements: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
    ) -> Dict[str, dict]:
        return {
            str(row["iri"]): {
                "eligible": True,
                "eligible_strong": False,
                "strong_holland": False,
                "missing_education": False,
                "missing_job_zone": False,
                "skill_ready": False,
                "skill_gap": False,
                "tier": self.fallback_tier,
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
        self._output_map_cache: Optional[Dict[str, str]] = None

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
            "skill_requirement_property": "sliceSkillRequirementProperty",
            "skill_requirement_class": "sliceSkillRequirementClass",
            "skill_requirement_element_property": "sliceSkillRequirementElementProperty",
            "required_skill_level_property": "sliceRequiredSkillLevelProperty",
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

    def _output_map(self) -> Dict[str, str]:
        if self._output_map_cache is not None:
            return self._output_map_cache
        from .rdf_loader import load_block_map

        path = self.reasoning_map or (config.CONFIG_DIR / "reasoning_map.ttl")
        if not path.exists():
            raise ReasoningError(f"reasoning output map not found: {path}")
        blocks = load_block_map(path)
        subject = config.CAREER + "DefaultReasoningOutputMap"
        predicates = blocks.get(subject)
        if not predicates:
            raise ReasoningError(f"no career:DefaultReasoningOutputMap in {path}")
        fields = {
            "eligible_class": ("outputEligibleClass", "iri"),
            "strong_class": ("outputStrongClass", "iri"),
            "strong_holland_class": ("outputStrongHollandClass", "iri"),
            "missing_education_class": ("outputMissingEducationClass", "iri"),
            "missing_job_zone_class": ("outputMissingJobZoneClass", "iri"),
            "skill_ready_class": ("outputSkillReadyClass", "iri"),
            "skill_gap_class": ("outputSkillGapClass", "iri"),
            "strong_tier": ("outputStrongTier", "literal"),
            "eligible_tier": ("outputEligibleTier", "literal"),
            "not_eligible_tier": ("outputNotEligibleTier", "literal"),
        }
        values: Dict[str, str] = {}
        for key, (local, kind) in fields.items():
            predicate = config.CAREER + local
            if kind == "iri":
                value = ttl_stream.iri_value(predicates, predicate, None)
            else:
                value = ttl_stream.literal_value(predicates, predicate, None)
            if not value:
                raise ReasoningError(f"missing {predicate} in {path}")
            values[key] = value
        self._output_map_cache = values
        return values

    def _candidate_slice(
        self,
        candidates: Sequence[dict],
        skill_requirements: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
    ) -> str:
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
            for index, requirement in enumerate(
                (skill_requirements or {}).get(occ, ())
            ):
                element_iri = requirement.get("element_iri")
                required_level = requirement.get("value")
                if not element_iri or required_level is None:
                    continue
                digest = hashlib.sha1(
                    f"{occ}:{element_iri}:{index}".encode("utf-8")
                ).hexdigest()[:10]
                req_iri = f"career:slice_skill_requirement_{digest}"
                lines.extend(
                    [
                        f"<{occ}> <{slice_map['skill_requirement_property']}> {req_iri} .",
                        f"{req_iri} a <{slice_map['skill_requirement_class']}> ;",
                        f"    <{slice_map['skill_requirement_element_property']}> <{element_iri}> ;",
                        f"    <{slice_map['required_skill_level_property']}> \"{float(required_level):.6f}\"^^xsd:decimal .",
                        "",
                    ]
                )
        return "\n".join(lines) + "\n"

    def _bundle(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        skill_requirements: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
    ) -> str:
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
        graph.parse(
            data=self._candidate_slice(candidates, skill_requirements),
            format="turtle",
        )
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
        skill_requirements: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
    ) -> Dict[str, dict]:
        java = configure_java_environment()
        try:
            import owlready2
            from owlready2 import World, sync_reasoner_pellet
        except Exception as exc:  # pragma: no cover - depends on optional package
            java_hint = (
                f"java={java}"
                if java
                else "no Java runtime found; set ONTORAG_JAVA or install a JRE"
            )
            raise ReasoningUnavailable(
                f"owlready2/Pellet is not available: {exc} ({java_hint})"
            ) from exc
        if java is not None:
            # owlready2 versions differ in how they spawn Java; the module
            # attribute covers those that read it, while JAVA_HOME/PATH above
            # covers the subprocess-based versions.
            setattr(owlready2, "JAVA_EXE", str(java))

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        bundle_text = self._bundle(profile, candidates, skill_requirements)
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
        output = self._output_map()
        eligible = self._class_instances(world, output["eligible_class"])
        strong = self._class_instances(world, output["strong_class"])
        strong_holland = self._class_instances(world, output["strong_holland_class"])
        missing_education = self._class_instances(world, output["missing_education_class"])
        missing_job_zone = self._class_instances(world, output["missing_job_zone_class"])
        skill_ready = self._class_instances(world, output["skill_ready_class"])
        skill_gap = self._class_instances(world, output["skill_gap_class"])
        result: Dict[str, dict] = {}
        for row in candidates:
            iri = str(row["iri"])
            is_strong = iri in strong
            is_eligible = iri in eligible or is_strong
            tier = (
                output["strong_tier"]
                if is_strong
                else (output["eligible_tier"] if is_eligible else output["not_eligible_tier"])
            )
            result[iri] = {
                "eligible": is_eligible,
                "eligible_strong": is_strong,
                "strong_holland": iri in strong_holland,
                "missing_education": iri in missing_education,
                "missing_job_zone": iri in missing_job_zone,
                "skill_ready": iri in skill_ready and iri not in skill_gap,
                "skill_gap": iri in skill_gap,
                "tier": tier,
                "source": "pellet",
            }
        return result


class AutoReasoner:
    name = "auto"

    def __init__(self, pellet: PelletReasoner, fallback: ReasoningService) -> None:
        self.pellet = pellet
        self.fallback = fallback

    def infer(
        self,
        profile: Profile,
        candidates: Sequence[dict],
        policy: RankingPolicy,
        skill_requirements: Optional[Mapping[str, Sequence[Mapping[str, object]]]] = None,
    ) -> Dict[str, dict]:
        try:
            return self.pellet.infer(
                profile, candidates, policy, skill_requirements
            )
        except (ReasoningUnavailable, ReasoningError) as exc:
            print(f"[ontorag] Pellet unavailable, using SQL eligibility fallback: {exc}", file=sys.stderr)
            return self.fallback.infer(
                profile, candidates, policy, skill_requirements
            )


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
        return SqlReasoner(policy.fallback_tier)
    return AutoReasoner(pellet, SqlReasoner(policy.fallback_tier))
