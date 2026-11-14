# OntoRAG implementation validation

Date: 2026-11-14

## Inputs kept unchanged

| Artifact | SHA-256 | Size |
| --- | --- | --- |
| `onet_abox.ttl` | `23c414c455c49f66a4464c2187e8c9c265ea401d0ff8e1dfa76ae5b75f2123aa` | 604,608,637 B |
| `onet_merged.ttl` | `2e53fbf2e50ea258c018f4f34db419a3ec20b4e71cb8c35ed6c8aa8cf882df24` | 434,017,563 B |
| `schema/onet_schema_en.ttl` | `ae82768885ba67a7bdb5098bdfda97845258acdb6dadbe07fa90c466ec1a32aa` | 56,291 B |
| `i18n-20261114T035836Z-1-001/onet_i18n_id.ttl` | `70673a830b514758b91546dfb21eee641100458c4c0042bab58b9a77c4fac311` | about 20 MB |

The root `onet_schema.ttl` still has 78 `@id` labels and is not loaded by
the application. `schema/onet_schema_en.ttl` has zero `@id` labels and is the
canonical English app schema. The pure Indonesian overlay is loaded separately.

## Index build

Command:

```bash
python3 -m ontorag.cli build-index --rebuild
```

Observed result:

| Table | Rows |
| --- | ---: |
| occupations | 1,016 |
| CompleteData occupations | 923 |
| NoRatingData occupations | 93 |
| occupation_ratings | 359,927 |
| elements | 3,006 |
| occupation_tasks | 18,838 |
| occupation_job_titles | 54,269 |
| occupation_related | 18,460 |
| occupation_fts | 1,016 |

The generated SQLite index is about 429 MB. The build parses 708,528 ABox
blocks with the streaming Turtle reader; the full ABox is never loaded as a
single graph.

`show-meta` reports the source paths, ABox size/mtime, schema, overlay, and
indexed rating types. It reports `parsed_ratings` (367,087) separately from
`ratings` (359,927 inserted rows) because job-zone and suppressed ratings are
not part of `occupation_ratings`. Candidate retrieval excludes `NoRatingData`
occupations by default.

## SWRL and Pellet validation

The index-row to ontology-slice property mapping is declared in
`config/reasoning_map.ttl`, so the profile-time bundle builder does not hold
career-domain field mappings.

Rules:

- `rules/eligibility.swrl.ttl`: education/job-zone eligibility and missing
  constraint flags.
- `rules/match_flags.swrl.ttl`: strong Holland match using
  `career:strongHollandThreshold`.
- `rules/tier.swrl.ttl`: `EligibleStrong` tier.

Runtime bundle contents: English schema, app vocabulary, ranking policy, SWRL
rules, one profile, and a shortlist of candidates. The bundle is serialized to
RDF/XML with `rdflib` because owlready2 does not reliably parse Turtle. Pellet
then runs over that bundle.

Validated with:

- `owlready2==0.48`
- Java 21
- `rdflib>=7`

The corrected SWRL serialization uses `swrl:BuiltinAtom` and
`swrl:builtin`, matching the OWLAPI SWRL vocabulary. Earlier
`swrl:BuiltInAtom`/`swrl:builtIn` spellings caused OWLAPI parse errors.

A sample profile:

```text
Saya suka riset, analisis data, matematika, dan pemrograman.
Saya lulusan S1 dan ingin job zone 4. Saya tidak suka menjual.
```

produced five `EligibleStrong` results with Pellet and five `Eligible` results
with the SQL fallback. The ranking order and scores were identical; only the
logical tier differed, as expected.

The bundled HermiT rejects SWRL built-in atoms as unsupported. It remains
useful for OWL 2 DL/TBox validation, but Pellet is the runtime rule engine.
Existing HermiT validation logs under `reports/` show the schema and small
ABox slices as consistent, while the deliberate D3/S1 disjointness probe is
inconsistent as expected. If Pellet is unavailable, `--reasoner auto` falls
back to SQL and warns on stderr.

## Example top-5 output (Pellet)

| Rank | Tier | Score | Occupation |
| ---: | --- | ---: | --- |
| 1 | EligibleStrong | 0.8046 | Social Science Research Assistants |
| 2 | EligibleStrong | 0.7645 | Remote Sensing Scientists and Technologists |
| 3 | EligibleStrong | 0.7369 | Materials Scientists |
| 4 | EligibleStrong | 0.7291 | Chemists |
| 5 | EligibleStrong | 0.7274 | Hydrologists |

Each result includes:

- logical tier and generic component scores;
- Holland alignment;
- normalized element ratings;
- FTS5/BM25 lexical similarity, explicitly labeled lexical;
- negation-aware lexical retrieval (negated target phrases are masked from the
  FTS query while the audit text is kept);
- minimum education and job zone evidence;
- representative tasks and related job titles;
- an Indonesian explanation when using the default language.

## Latency

Measured on the full index in this workspace, including process startup,
schema/overlay loading, extraction, retrieval, scoring, and output:

| Reasoner | Wall time |
| --- | ---: |
| SQL fallback | about 2.3 s |
| Pellet | about 4.8 s |

The SQL path is the low-latency mode. Pellet is the tier-aware mode.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

- System Python (no owlready2): 26 pass, 1 skipped (Pellet test).
- `owlready2==0.48` environment with Java 21: 27 pass, including the
  end-to-end Pellet/SWRL tier test.

The suite covers the streaming parser, policy loading, lexicon and negation,
profile extraction, SQLite/FTS5 schema and candidate filters, scoring and tier
sorting, SQL fallback, CLI JSON output, and the optional Pellet path.

## Remaining limitations

- Retrieval is lexical (FTS5/BM25), not semantic.
- Only the reasoning shortlist receives explicit SWRL flags. Candidates outside
  the shortlist keep the SQL eligibility default, so they cannot become
  `EligibleStrong`.
- The current index is rating-centric; `NoRatingData` occupations are excluded
  from ranking by default.
- Pellet needs Java. The pinned owlready2 0.48 release is important for Java 21
  compatibility in this workspace.
- No web UI is included; the deliverable is terminal/file based.
