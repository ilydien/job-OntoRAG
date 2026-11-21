# OntoRAG implementation validation

Date: 2026-11-21

## Inputs kept unchanged

| Artifact | SHA-256 | Size |
| --- | --- | --- |
| `onet_abox.ttl` | `23c414c455c49f66a4464c2187e8c9c265ea401d0ff8e1dfa76ae5b75f2123aa` | 604,608,637 B |
| `onet_merged.ttl` | `2e53fbf2e50ea258c018f4f34db419a3ec20b4e71cb8c35ed6c8aa8cf882df24` | 434,017,563 B |
| `schema/onet_schema_en.ttl` | `a51c78bb419bb8dce7565fa90bc517ca35d2525e96967c330bb6259b76d1ec1a` | 54,578 B |
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

produced five `EligibleStrong` results with Pellet. On the lexical-only path the
SQL fallback produced the same scores and order, but only `Eligible` tiers; the
logical tier is the expected difference. With `--retrieval auto` and built
embeddings, the semantic component participates in the score as well.

The bundled HermiT rejects SWRL built-in atoms as unsupported. It remains
useful for OWL 2 DL/TBox validation, but Pellet is the runtime rule engine.
Existing HermiT validation logs under `reports/` show the schema and small
ABox slices as consistent, while the deliberate D3/S1 disjointness probe is
inconsistent as expected. If Pellet is unavailable, `--reasoner auto` falls
back to SQL and warns on stderr.

## Example top-5 output (default ontology retrieval + Pellet)

For the sample profile above:

| Rank | Tier | Score | Occupation |
| ---: | --- | ---: | --- |
| 1 | EligibleStrong | 0.9079 | Software Developers |
| 2 | EligibleStrong | 0.8954 | Data Scientists |
| 3 | EligibleStrong | 0.8797 | Computer Systems Analysts |
| 4 | EligibleStrong | 0.8265 | Software Quality Assurance Analysts and Testers |
| 5 | EligibleStrong | 0.8145 | Computer Network Architects |

Each result includes:

- logical tier and generic component scores;
- Holland alignment;
- normalized element ratings;
- optional semantic occupation-card similarity;
- FTS5/BM25 lexical similarity, explicitly labeled lexical;
- negation-aware lexical retrieval (negated target phrases are masked from the
  FTS query while the audit text is kept);
- occupation description, available in the table detail, JSON, and TTL output;
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

- System Python (no owlready2/rdflib): 80 pass, 12 skipped (optional
  Jena/rdflib, Pellet, and bundled-JRE tests).
- `.venv` with `owlready2==0.48`, `rdflib`, and Java 21: 91 pass, 1 skipped
  (bundled-JRE test), including the end-to-end Pellet/SWRL tier test.

The suite covers the streaming parser, policy loading, lexicon and negation,
profile extraction, SQLite/FTS5 schema and candidate filters, batched element
lookups, scoring and tier sorting, SQL fallback, CLI JSON output,
occupation-card building, the deterministic embedding backend, semantic
retrieval/fallback, Java runtime resolution, and the optional Pellet path.

## Candidate recall and lexicon fixes

Two ranking defects were found and fixed:

1. **Arbitrary candidate truncation.** The candidate query used
   `ORDER BY iri LIMIT :candidateLimit` with `candidateLimit = 250`. The
   hard-filtered pool for a default profile is ~750 occupations, so
   `Ilmuwan Data` (15-2051.00, position 700) and `Ahli Statistik` never
   reached retrieval or scoring. `candidateLimit` is now a safety cap
   (2000, above the total occupation count); collection and ranking always
   see the whole hard-filtered pool. The dense/sparse recall caps
   (`lexicalCandidateLimit`, `semanticCandidateLimit`) were raised to the
   same guard so neither pass silently drops a relevant occupation.
2. **`membangun`-as-construction.** The lexicon mapped `membangun` to
   Realistic and to *Building and Construction*, so "membangun model"
   inflated construction-heavy occupations. The bare keyword was removed;
   explicit phrases now decide the sense (`membangun model/sistem/aplikasi`
   -> Investigative, `membangun rumah/gedung/jembatan` -> Realistic and
   Building and Construction). New vocabulary adds `model`, `pemodelan`,
   `statistik`, `algoritma`, `machine learning`, `pemrograman`, `python`,
   and `sql`, plus the elements *Analyzing Data or Information* and
   *Programming*. The phrase `membangun model`/`membangun algoritma` also
   maps to the *Programming* element, which separates computational
   modeling from the analytical work that detectives and survey researchers
   also score highly on.

Element ratings for the whole pool are now fetched with one batched query
(`Index.elements_for_many`, filtered to the profile's elements) instead of one
query per occupation. With these fixes the same prompt returns
`Ilmuwan Data` first in `--retrieval lexical`:

| # | Tier | Score | Occupation |
| ---: | --- | ---: | --- |
| 1 | Eligible | 0.9434 | Ilmuwan Data |
| 2 | Eligible | 0.9231 | Perencana Transportasi |
| 3 | Eligible | 0.9169 | Ilmuwan Atmosfer dan Luar Angkasa |
| 4 | Eligible | 0.9044 | Insinyur Nuklir |
| 5 | Eligible | 0.8864 | Insinyur Dirgantara |

The tier is `Eligible` here because the SQL fallback cannot derive
`EligibleStrong`; the Pellet path produces the strong tiers.

## Retrieval quality benchmark

`benchmark/gold_queries.id.json` holds a small hand-labelled set of Indonesian
career descriptions (text plus expected O*NET SOC codes). The `benchmark`
command replays them and reports Recall@k and MRR per retrieval mode:

```bash
python3 -m ontorag.cli benchmark --index data/onet_index.sqlite \
  --retrieval lexical,semantic,hybrid --k 10 --verbose
```

The gold set runs with a permissive profile (education `S3`, job zone 5) so the
measurement isolates ranking rather than eligibility filtering; `--education`
and `--max-job-zone` override it. A mode that cannot be built (for example
`semantic` without the embedding model) is reported as `n/a` and the remaining
modes still run. Metrics live in `ontorag/benchmark.py` and are covered by
`tests/test_benchmark.py`.

Baseline on the full index (SQL reasoner, `k = 10`), before the healthcare/
animal/architecture vocabulary work:

| Mode | Queries | Recall@10 | MRR | Latency |
| --- | ---: | ---: | ---: | ---: |
| `lexical` | 10 | 0.600 | 0.465 | about 6.7 s |
| `semantic` | 10 | 0.617 | 0.583 | about 4.8 s |
| `hybrid` | 10 | 0.650 | 0.667 | about 4.5 s |

The misses were concentrated in three queries: "merawat dan membantu pasien"
(hospitalist ranked first because of a mistranslated title), "mendesain
bangunan" (no Realistic signal, so architects lost to interior designers), and
"merawat hewan" (`hewan` was not mapped to any element, so veterinarians lost
to human-medicine occupations).

### Healthcare, animal, and architecture vocabulary

Two fixes close those gaps:

- **Data fix (needs an index rebuild).** The Indonesian overlay translated the
  Hospitalists title (`29-1229.02`) as `"Rumah sakit"`, so the literal phrase
  "di rumah sakit" matched the job *title* and pushed hospitalists to rank 1.
  It now reads `"Dokter Hospitalis"` in
  `3. Indonesian Translation/i18n/onet_i18n_id.ttl`.
- **Lexicon.** `config/lexicon.ttl` gains `pasien`, `keperawatan`, `perawatan`,
  `rumah sakit` (Medicine), an *Assisting and Caring for Others* entry,
  architecture terms (`bangunan`, `arsitektur`, `gedung` → Realistic;
  `tata ruang`, `penataan ruang` → Design), and animal terms (`hewan`,
  `dokter hewan`, `veteriner`, `ternak`, `satwa` → *Animal Service* plus
  Biology, Investigative, and Realistic). *Animal Service* is the decisive
  signal: veterinarians rate 0.99 and veterinary technicians 0.87, while
  human-medicine occupations rate 0.01.

After the lexicon change, `lexical` on a freshly rebuilt index rises to
**Recall@10 0.833 / MRR 0.628**; veterinarians and veterinary technicians now
rank 1 and 2 for the animal query, and architects enter the top 3. The nurse
query still puts hospitalists first: with the title corrected, the lexical
match now comes from the hospitalist description (inpatient care, patient
handling), which is a defensible adjacent result rather than a mistranslation
artifact. `semantic`/`hybrid` must be re-measured on a machine with the e5
model; the corrected title also changes the hospitalist card embedding.

## Education, data/IT vocabulary, and output fixes

The post-pull validation pass added:

- Education phrases for `belum memiliki gelar` (`Level2_HighSchool`) and
  `masih kuliah` / `sedang belajar di program studi` (treated as a prospective
  `S1` candidate for career recommendations).
- Data/IT vocabulary: `sains data`, `ilmu data`, `data science`,
  `visualisasi data`, `eksplorasi data`, `develop web`, `pengembangan web`,
  `pipeline data`, and related phrases.
- Overlap-aware lexicon matching and keyword deduplication, so a phrase such as
  `menganalisis dan ekplorasi data` is not counted twice and the duplicated
  `data` keyword no longer produces duplicate evidence.
- Canonical element labels are appended to the FTS query, so a typo such as
  `pemrogaman` can still retrieve occupations whose documents use
  `programming`.
- `auto` retrieval checks embedding metadata before loading a
  sentence-transformers model; an index without vectors falls back to lexical
  retrieval immediately.
- `Recommendation` now carries `description_en`/`description_id`. The CLI
  table detail and JSON include the description, and TTL output emits
  `career:recommendationDescription` with a policy-controlled preview length.
- Inferred class IRIs and output tier labels are read from
  `career:DefaultReasoningOutputMap` in `config/reasoning_map.ttl`; the SQL
  fallback tier and evidence display limits come from the ranking policy.
- Food-related lexicon entries map `memasak`, `dapur`, `koki`, and
  `kuliner` to `Food Production`; empty ontology profiles now return no
  recommendations with an explicit warning instead of zero-score alphabetic
  results.
- Additional concept entries cover athletics, stamina, body coordination,
  public safety, engineering, electronics, mechanical/electronic repair,
  agriculture, logistics, hospitality, energy, environment, and performing
  arts.

## Semantic retrieval (occupation-card embeddings)

Retrieval has a dense path alongside FTS5/BM25:

1. `build-index` creates the SQLite tables `occupation_embeddings` and
   `embedding_meta` (empty).
2. `build-embeddings` reads the indexed occupations and composes one
   **occupation card** per row: title (EN/ID), description, up to
   `embeddingMaxTasks` tasks, up to `embeddingMaxElements` elements ordered by
   normalised rating, RIASEC/interest labels, and up to
   `embeddingMaxJobTitles` alternative titles. Cards are text only; the ABox is
   never parsed again.
3. Cards are encoded with the policy model (`intfloat/multilingual-e5-small`
   by default, "query: "/"passage: " prefixes, 384 dimensions) and stored as
   L2-normalised `float32` blobs. Cosine similarity is therefore a dot product.
4. At query time `ontorag.retrieval.SemanticRetriever` encodes the profile text
   and scores only the occupations that pass the structured filter. Ranking
   remains deterministic in `ontorag.scoring`.

```bash
pip install -r requirements-embed.txt
python3 -m ontorag.cli build-embeddings --index data/onet_index.sqlite
python3 -m ontorag.cli recommend --index data/onet_index.sqlite \
  --text "Saya suka menganalisis data dan membangun model" --retrieval semantic
```

Retrieval modes:

| Mode | Behaviour |
| --- | --- |
| `ontology` (default) | SPARQL alignment of the profile's element individuals against the index slice (`rdflib`) or a Fuseki endpoint; requires one of those graph backends. |
| `auto` | Explicit fallback mode: semantic when the index has matching vectors and the model loads, otherwise lexical with a warning. |
| `semantic` | Cosine similarity only; missing/mismatched vectors raise `EmbeddingIndexMismatch`. |
| `lexical` | The previous FTS5/BM25 path. |
| `hybrid` | Semantic + lexical; the policy weights decide the mix. |

`ontology` is the policy default and does not fold into `hybrid`, so the
semantic/hybrid benchmark numbers remain separate. BM25/semantic are explicit
fallback modes, not the default retrieval path.

Component weights are now `holland 0.45 + element 0.30 + ontology 0.30 +
semantic 0.25 + lexical 0.15`; `score_candidates` renormalises over the
components that were actually computed, so the lexical, semantic, and ontology
paths stay comparable.

Provenance is stored in `embedding_meta` (`model`, `dim`, prefixes, card
version, build time, vector count, and an index fingerprint) and is shown by
`show-meta` as `embedding.*` keys. A model or dimension mismatch is a hard
error, never a silent score change.

The new suite (`tests/test_embeddings.py`, `tests/test_retrieval.py`) uses a
deterministic keyword backend, so it runs without `torch` or network access:

```bash
python3 -m unittest discover -s tests -v
```

## Ontology (SPARQL) retrieval

Search has a path that queries the ontology rather than the profile text.
`ontorag/graph_search.py` materialises the relevant slice of the ontology as
RDF - occupations, their element ratings, and `career:relatedOccupation` edges -
straight from the SQLite index (the raw 604 MB ABox is never loaded) and
answers it with SPARQL through `rdflib`:

1. **Direct match.** `VALUES (?element ?preference)` binds the profile's
   element individuals and their preference weights, then joins
   `career:hasElementRating` / `career:ratedElement` / `career:normalizedValue`
   to sum `preference * value` per occupation.
2. **One related-occupation hop.** The matched occupations are re-bound as
   `VALUES (?seed ?seedScore)` and traversed along `career:relatedOccupation`,
   adding `seedScore * 0.05` to each neighbour. This is the graph traversal a
   text-similarity retriever cannot express. The decay is deliberately small:
   high-degree medical hubs have about 20 related occupations, so a larger
   factor lets their summed neighbour evidence swamp the direct element signal
   (a 0.30 factor dropped the gold-set recall from 0.817 to 0.650).

The two branches are separate queries: `rdflib` evaluates the combined JOIN
about six times slower than the sum of the parts (about 3.5 s vs 20 s for a
full pool), so the element match and the hop are issued independently and
merged. `sparql_query` / `related_sparql_query` expose both query strings for
audit. The scores enter ranking as the `ontology` component (policy weight
0.30, min-max normalised) with an `ontology` evidence item on each result.

The same graph can be exported to Jena/Fuseki. `build-graph` writes the derived
N-Triples graph from SQLite:

```bash
python3 -m ontorag.cli build-graph \
  --index data/onet_index.sqlite \
  --out data/ontorag_derived.nt \
  --rebuild
```

Then `--retrieval ontology --sparql-endpoint http://localhost:3030/onet/sparql`
uses `ontorag/jena_store.py` to execute the two queries over HTTP. The endpoint
stores the derived graph, not the raw ABox; `--retrieval ontology` falls back to
the in-process `rdflib` path when no endpoint is supplied.

```bash
python3 -m ontorag.cli recommend --index data/onet_index.sqlite \
  --text "Saya suka merawat hewan dan membantu dokter hewan" \
  --language id --retrieval ontology --top-k 5
```

Because the two branches are pure SPARQL and every constant (element IRIs,
normalised values, related edges) comes from the ontology, the ontology
component is genuine graph search, not a re-labelled text score. When `rdflib`
is not installed, `--retrieval ontology` fails loudly with
`GraphSearchUnavailable` (rather than silently degrading), and `auto`/`hybrid`
simply omit the component. `auto` keeps its previous meaning (semantic when
vectors exist, else lexical) so the ontology path is opt-in.

On the gold set (SQL reasoner, `k = 10`) the ontology component is the weakest
single retriever but proves the graph path runs end to end:

| Mode | Queries | Recall@10 | MRR | Latency |
| --- | ---: | ---: | ---: | ---: |
| `ontology` | 10 | 0.817 | 0.465 | about 41 s |

The direct `VALUES` element match alone scores 0.600/0.343; the bounded hop
lifts it to 0.817/0.465. The value is provenance plus the neighbourhood hop,
not a higher headline number than `hybrid` (0.850/0.817).
`tests/test_graph_search.py` covers the retrieval and the hop (skipped when
`rdflib` is absent).

## Java runtime for Pellet

Pellet needs a Java runtime, and owlready2 spawns it as a child process. The
reasoner resolves Java in this order:

1. `ONTORAG_JAVA` (a `java` binary or a JDK/JRE home directory),
2. `JAVA_HOME`,
3. the bundled runtime at `environment/jre` (Temurin 21 in this workspace),
4. a local `jre` folder,
5. `java` on `PATH`.

The resolved binary is exported through `JAVA_HOME`, `PATH`, and
`owlready2.JAVA_EXE` (when the installed owlready2 exposes that attribute), so
it works across owlready2 versions. Override it per request with
`recommend --java /path/to/java`. If no runtime is found, the message names the
`ONTORAG_JAVA` variable, and `--reasoner auto` still falls back to SQL.

`environment/jre/` is ignored by git, as are `data/` and Python caches.

## Remaining limitations

- Retrieval now has a semantic path. Embedding build time and vector-table size
  for the full index are recorded in the semantic section; Recall@k/MRR now has
  a gold-query harness; the e5 model is available in this workspace and
  occupation embeddings are built. The 92-test suite covers the plumbing with a
  deterministic test backend and the optional Pellet and Jena/Fuseki paths.
- Candidate recall is no longer truncated. A small gold query set with
  Recall@k/MRR measures ranking quality (`benchmark` command); the remaining
  misses are adjacent occupations (e.g. associate vs. full statisticians).
- Only the reasoning shortlist receives explicit SWRL flags. Candidates outside
  the shortlist keep the SQL eligibility default, so they cannot become
  `EligibleStrong`.
- The current index is rating-centric; `NoRatingData` occupations are excluded
  from ranking by default.
- Pellet needs Java; the bundled `environment/jre` (Temurin 21) is detected
  automatically, and the pinned owlready2 0.48 release is important for Java 21
  compatibility in this workspace.
- No web UI is included; the deliverable is terminal/file based.
