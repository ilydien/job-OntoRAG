# OntoRAG Career Recommender

Terminal-first, ontology-grounded recommender for Indonesian free-text career
profiles. It extracts preferences from text, retrieves candidates with SQLite
FTS5/BM25 and optional occupation-card embeddings, reasons over a small
candidate slice with SWRL/Pellet, and returns ranked O*NET occupations with
scores, logical eligibility tiers, evidence, job descriptions, and
explanations.

This repository is the implementation prototype for the OntoRAG project. The
O*NET ABox (`onet_abox.ttl`) and merged ontology (`onet_merged.ttl`) are kept
unchanged; they are data sources, not rewritten artifacts.

## Design summary

- **Ontology-grounded extraction and inference.** Domain vocabulary lives in
  RDF/TTL, not Python keyword lists. Indonesian and English cues live in
  `config/lexicon.ttl`.
- **No hard-coded inference.** Eligibility and tier rules are declarative SWRL
  in `rules/`. Ranking weights, thresholds, defaults, and tier order are in
  `config/ranking_policy.ttl`.
- **Ontology-first retrieval.** SQLite applies hard education/job-zone
  constraints; the default retrieval path traverses the derived ontology
  graph and scores ontology element alignment with SPARQL. FTS5/BM25 and
  occupation-card embeddings remain available as explicit fallback modes
  (`lexical`, `semantic`, `hybrid`, `auto`).
- **Reasoning over a slice.** The full O*NET ABox is never sent to a reasoner.
  The pipeline builds a temporary bundle containing the schema, policy, rules,
  one user profile, and a small set of candidate occupations.
- **Tier then score.** SWRL decides `EligibleStrong`, `Eligible`, or
  `NotEligible`. Python only combines generic component scores and sorts by
  `tier ASC`, then `score DESC`. SWRL never does weighted sums, sorting, or
  top-k.
- **Pure i18n overlay.** `schema/onet_schema_en.ttl` is the English-only app
  schema. Indonesian labels come from the snapshot overlay
  (`i18n-*/onet_i18n_id.ttl`). `onet_abox.ttl` is not modified.

## Requirements

- Python 3.12 or newer.
- SQLite with FTS5 enabled. CPython's bundled SQLite normally has it.
- Java runtime for Pellet (Java 21 was validated with `owlready2==0.48`).
- Optional: `sentence-transformers` and `numpy` for semantic retrieval.

Install dependencies in an isolated environment. With `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Optional: semantic retrieval / build-embeddings
uv pip install -r requirements-embed.txt
```

Or with `venv`/`pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`owlready2` is pinned to `0.48` because its bundled Pellet works with Java 21;
newer owlready2 releases may ship Jena jars that require a newer Java runtime.

## Build the index

The index stores occupation metadata, education/job-zone filters, ratings,
tasks, job titles, related occupations, an FTS5 table, and an element catalogue.
A full build from the 604 MB ABox takes a few minutes and produces roughly
430 MB of SQLite data.

```bash
python -m ontorag.cli build-index --rebuild
```

Useful options:

```bash
python -m ontorag.cli build-index \
  --abox onet_abox.ttl \
  --schema schema/onet_schema_en.ttl \
  --overlay i18n-20261114T035836Z-1-001/onet_i18n_id.ttl \
  --index data/onet_index.sqlite \
  --rebuild
```

Check the build:

```bash
python -m ontorag.cli show-meta
```

### Build semantic embeddings (optional)

Semantic retrieval uses one text card per occupation and the
`intfloat/multilingual-e5-small` model by default. It needs the optional
dependencies:

```bash
uv pip install -r requirements-embed.txt
python -m ontorag.cli build-embeddings --index data/onet_index.sqlite
```

`show-meta` will then expose `embedding.model`, `embedding.dim`, and
`embedding.count`. Without vectors, `--retrieval auto` falls back to FTS5/BM25
without loading the model.

Candidate retrieval excludes occupations whose `data_status` is `NoRatingData`
by default (`config/index_policy.ttl`). The index still contains those
occupations; they are simply not rankable with the current rating-based
components. `show-meta` reports both `ratings` (inserted rows) and
`parsed_ratings` (ratings seen before filtering).

## Extract a profile

```bash
python -m ontorag.cli extract \
  --text "Saya suka riset, analisis data, matematika, dan pemrograman. Saya lulusan S1 dan ingin job zone 4. Saya tidak suka menjual." \
  --format json
```

Use `--format ttl` to inspect the RDF profile that would be sent to the
reasoner:

```bash
python -m ontorag.cli extract --text "Saya lulusan D3, suka mengajar." --format ttl
```

Extraction is declarative. The text cues, negation handling, education aliases,
Holland cues, and element cues come from `config/lexicon.ttl`. Direct O*NET
element names are matched generically from the index catalogue, subject to the
minimum length and weight in the ranking policy. Negated target phrases are
removed from the lexical retrieval text while the raw text is preserved for
audit and display.

## Recommend occupations

```bash
python -m ontorag.cli recommend \
  --text "Saya suka riset, analisis data, matematika, dan pemrograman. Saya lulusan S1 dan ingin job zone 4. Saya tidak suka menjual." \
  --top-k 5
```

The default output is a table plus details, including the occupation
description. Other formats:

```bash
python -m ontorag.cli recommend --text "Saya lulusan D3 dan suka membantu orang." --format json
python -m ontorag.cli recommend --text "Saya lulusan D3 dan suka membantu orang." --format ttl
```

Retrieval selection:

```bash
# Default: graph/ontology traversal
python -m ontorag.cli recommend --text "..." --retrieval ontology

# Optional Jena/Fuseki endpoint for the same graph traversal
python -m ontorag.cli recommend --text "..." --retrieval ontology \
  --sparql-endpoint http://localhost:3030/onet/sparql

# Explicit non-primary retrieval paths
python -m ontorag.cli recommend --text "..." --retrieval auto
python -m ontorag.cli recommend --text "..." --retrieval semantic
python -m ontorag.cli recommend --text "..." --retrieval lexical
python -m ontorag.cli recommend --text "..." --retrieval hybrid
```

### Jena/Fuseki ontology retrieval

The `ontology` mode can use Apache Jena Fuseki as an HTTP SPARQL endpoint. The
endpoint stores a derived graph exported from SQLite, not the raw 600 MB ABox:

```bash
python -m ontorag.cli build-graph \
  --index data/onet_index.sqlite \
  --out data/ontorag_derived.nt \
  --rebuild

# Quick local Fuseki start (in-memory dataset)
fuseki-server --file=data/ontorag_derived.nt --port 3030 /onet

python -m ontorag.cli recommend \
  --text "Saya suka menganalisis data" \
  --retrieval ontology \
  --sparql-endpoint http://localhost:3030/onet/sparql \
  --top-k 5
```

Without `--sparql-endpoint`, `ontology` uses the in-process `rdflib` slice when
available. If neither Fuseki nor `rdflib` is available, the mode fails with a
clear error.

Reasoner selection:

```bash
# Default: try Pellet, then fall back to SQL eligibility
python -m ontorag.cli recommend --text "..." --reasoner auto

# Require Pellet/SWRL
python -m ontorag.cli recommend --text "..." --reasoner pellet

# Fast/no-Java mode: SQL-filtered candidates are marked eligible
python -m ontorag.cli recommend --text "..." --reasoner sql
```

The SQL fallback is conservative: it can produce `Eligible`, but it cannot infer
`EligibleStrong` because that tier requires the SWRL strong-Holland-match rule.

## Profile JSON

A JSON profile can be mixed with free text. `--text` is still used for lexical
retrieval and for supplementary extraction.

```json
{
  "user_iri": "career:user_demo",
  "language": "id",
  "education_level": "S1",
  "max_job_zone": 4,
  "holland": {
    "Investigative": 0.9,
    "Realistic": 0.4
  },
  "elements": {
    "Mathematics/Statistics": 0.8,
    "Programming": 0.7
  }
}
```

Element keys may be O*NET IRIs, English names, or Indonesian labels exposed in
the generated index. Unknown education levels, Holland codes, or elements fail
with an error instead of being silently guessed.

```bash
python -m ontorag.cli recommend --profile profile.json --text "Saya suka data." --top-k 5
```

## Configuration and domain knowledge

| Path | Purpose |
| --- | --- |
| `schema/onet_schema_en.ttl` | English-only app schema; no `@id` labels |
| `i18n-*/onet_i18n_id.ttl` | Pure Indonesian label/comment overlay |
| `config/ranking_policy.ttl` | weights, thresholds, candidate limits, tier order, defaults, description preview length |
| `config/index_policy.ttl` | indexed rating types, completeness policy, FTS tokenizer, embedding settings |
| `config/lexicon.ttl` | Indonesian/English text cues and negation patterns |
| `config/reasoning_map.ttl` | index-row to ontology-slice property mapping and inferred-class/tier output mapping |
| `config/config_vocab.ttl` | lightweight app vocabulary used in profiles/reports |
| `rules/eligibility.swrl.ttl` | education/job-zone eligibility and missing-constraint rules |
| `rules/match_flags.swrl.ttl` | strong Holland match threshold rule |
| `rules/tier.swrl.ttl` | `EligibleStrong` tier rule |
| `queries/*.sql` | candidate filters, FTS lookup, evidence queries |
| `ontorag/*.py` | generic engine, parser, indexer, scorer, output formatting |

The expected final ordering is:

1. `EligibleStrong`
2. `Eligible`
3. `NotEligible` (normally filtered out when `career:requireEligible true`)

Changing weights or thresholds should normally be done in TTL, not Python.

## Tests

The tests are standard-library `unittest` tests. They do not require Java or
network access.

```bash
python -m unittest discover -s tests -v
```

The index test builds a small SQLite index from a local fixture; the full
604 MB ABox is not required for unit tests.

## Validation notes

- `onet_abox.ttl` is 604,608,637 bytes / 8,230,417 triples and was not
  rewritten by this prototype.
- `onet_merged.ttl` was not rewritten.
- App schema: `schema/onet_schema_en.ttl`, 1,555 triples, zero `@id` labels.
- Full index validation: 1,016 occupations, 923 `CompleteData`, 93
  `NoRatingData`, 359,927 indexed rating rows, 18,838 tasks, 54,269 job titles.
- Pellet was validated with `owlready2==0.48` and Java 21 on a small candidate
  slice. A sample profile with S1/job-zone-4 constraints produced
  `EligibleStrong` results through SWRL.
- The test suite currently contains 92 tests. In the system interpreter it
  reports 80 passes and 12 skips (optional rdflib/Jena and Pellet tests); in
  the prepared `.venv` with Java and `owlready2==0.48` it reports 91 passes and
  1 skip.
- HermiT is intended for OWL 2 DL schema validation, not for the runtime SWRL
  built-ins used here; the bundled HermiT reports built-in atoms as unsupported.
  Runtime rule execution therefore uses Pellet, with SQL as the explicit
  fallback.

## Known limitations

- Semantic retrieval requires the optional embedding dependencies and
  `build-embeddings`; without them, the system uses lexical FTS5/BM25.
- Only a shortlist is reasoned over. Candidates outside the shortlist keep the
  SQL eligibility default and therefore do not receive `EligibleStrong`.
- The prototype has no web UI. All output is terminal/file based.
- The current index is rating-centric, so `NoRatingData` occupations are not
  ranked by default.
- If Pellet is unavailable (no Java, incompatible Java, or missing
  `owlready2`), use `--reasoner sql` or let `auto` fall back. The fallback emits
  a warning on stderr.

## Repository layout

```text
ontorag/            Python package and CLI
config/             ranking/index policy, lexicon, app vocabulary
rules/              SWRL rules
queries/            SQL used by the retrieval/evidence layer
schema/             English-only O*NET schema
data/               generated SQLite index and scratch files (ignored)
samples/            small ABox fixtures
benchmark/          gold queries for Recall@k/MRR
tests/              stdlib unittest suite
reports/            validation notes and benchmark output
requirements-embed.txt  optional semantic-retrieval dependencies
```
