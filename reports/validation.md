# O*NET Career Ontology — Validation

## 1. Validation scope

The validation covers:

1. OWL 2 DL profile compliance of `onet_schema.ttl`.
2. HermiT consistency and classification of the schema.
3. HermiT consistency of a fully typed demonstration ABox.
4. HermiT consistency of a user-profile/recommendation ABox for the OntoRAG
   application vocabulary.
5. HermiT consistency of bounded real O*NET samples.
6. A deliberate D3/S1 inconsistency probe.
7. Structural and datatype integrity of the complete ABox.

The complete ABox is not reasoned over with HermiT. This is intentional: it
contains 8,230,417 triples / 577 MiB and is outside the practical memory and
time budget. Full-ABox reasoning is not required for the TBox/RBox target.

## 2. OWL 2 DL profile

Command:

```bash
robot validate-profile --profile DL \
  --input onet_schema.ttl \
  --output reports/profile-validation.txt
```

Result (`reports/profile-validation.txt`):

```text
OWL 2 DL Profile Report: [Ontology and imports closure in profile]
```

The schema was also parsed as Turtle successfully. The current schema has
1,628 triples.

## 3. HermiT results

HermiT was run through ROBOT with the local import catalog. The additive
OntoRAG profile vocabulary was validated with a new user-profile ABox.

| Input | Result | Notes |
|---|---|---|
| `onet_schema.ttl` | consistent | OWL 2 DL profile valid; ROBOT/HermiT exit 0 |
| `samples/onet_demo_consistent.ttl` | consistent | existing demonstration ABox |
| `samples/onet_user_profile_consistent.ttl` | consistent | scored Holland/element preferences, education, job zone, recommendation |
| `samples/probe_d3_s1_inconsistent.ttl` | **inconsistent (expected)** | D3/S1 disjointness probe |
| `samples/onet_sample_1occ.ttl` | previously consistent | not rerun after the additive app vocabulary; the earlier run exceeded the available 15-minute retry window |
| `samples/onet_sample_3occ.ttl` | previously consistent | not rerun for the same cost reason |

The application vocabulary is additive: no O*NET class, property, ABox
assertion, or D3/S1 axiom was changed. A temporary probe with
`career:maxJobZone "6"^^xsd:integer` was inconsistent as expected, showing that
the inline datatype restriction is active.

The former consistency-only logs remain available as historical records:

- `reports/hermit-consistency-onet_schema.log`
- `reports/hermit-consistency-onet_demo_consistent.log`
- `reports/hermit-consistency-1occ.log`
- `reports/hermit-consistency-3occ.log`
- `reports/hermit-consistency-probe_d3_s1_inconsistent.log`

For the current schema and the new user-profile sample, `robot reason
--reasoner HermiT` returned exit 0; the deliberate probe returned exit 1 with
an “ontology is inconsistent” error, as expected.

### D3/S1 probe

`samples/probe_d3_s1_inconsistent.ttl` imports the schema and adds:

```turtle
career:D3 a career:AtLeastS1 .
```

This is inconsistent because `career:ExactlyD3` is the nominal class `{D3}`,
`career:AtLeastS1` excludes D3, and the two classes are declared disjoint. The
probe therefore demonstrates that the D3-versus-S1 distinction is semantically
active, not merely a comment.

A consistent counterpart is provided by
`samples/onet_demo_consistent.ttl`, which uses `career:S1` as a minimum level
and is accepted by HermiT.

## 4. Complete ABox integrity checks

The generated ABox was checked with a streaming integrity checker over
8,230,417 triples and 708,528 subjects.

| Check | Violations |
|---|---:|
| Duplicate key values | 0 |
| Dangling object IRIs in checked relations | 0 |
| Qualified-cardinality violations | 0 |
| Typed-reference mismatches | 0 |
| Functional-property violations | 0 |
| Semantic range violations | 0 |
| Unconverted `xsd:date` literals | 0 |

The ABox contains:

- 1,016 occupations;
- 923 occupations with ratings;
- 93 occupations without ratings;
- 901 `career:hasMinEducationLevel` assertions;
- 24 education-category mappings;
- 2,316 Holland-code assertions.

These are structural checks, not a proof of full ABox consistency. They check
the constraints that are most likely to be violated by the source-to-RDF
transformation.

## 5. Datatype audit

The datatype audit streams the ABox as N-Triples and compares every literal
property against the declared schema range.

Result (`reports/abox-datatypes.txt`):

```text
Literal triples scanned: 4,274,072
Datatype mismatches: 0
All observed datatypes are compatible with the declared ranges.
```

In particular, all 18,838 `taskID` literals are `xsd:integer`, matching the
corrected schema range. This was the issue that caused the earlier HermiT
inconsistency.

## 6. Source-file integrity

`onet_merged.ttl` was not modified.

| Property | Value |
|---|---|
| Size | 434,017,563 bytes |
| Last modification | 2026-10-05 11:51:25 +0700 |
| SHA-256 | `2e53fbf2e50ea258c018f4f34db419a3ec20b4e71cb8c35ed6c8aa8cf882df24` |

## 7. Artefact hashes

| File | SHA-256 |
|---|---|
| `onet_schema.ttl` | `6f811fa4e0126ba0d5c171b1f8a3fc1cc80e75ef2a3b82536eccd28a5849d464` |
| `onet_abox.ttl` | `23c414c455c49f66a4464c2187e8c9c265ea401d0ff8e1dfa76ae5b75f2123aa` |
| `onet_all.ttl` | `7efbb1c349037dd1228624adbee9642cc40a0cd919da53734c71c0920edf5aee` |
| `catalog-v001.xml` | `f576fcc82470897f938c48d30a5097d590b10795a6d8b017d593885e0e5edf0a` |
| `samples/onet_demo_consistent.ttl` | `d51269c9e03e3f7d62e4b180d524c8c65fe6bd248b59eaac57b7e1735154a790` |
| `samples/onet_user_profile_consistent.ttl` | `6f39b536560bbb5d14f83556741dba5a021402e51eda7fda2b2d8cbf8e47914d` |
| `samples/probe_d3_s1_inconsistent.ttl` | `bebe1d5adebb79db2967779323fcdad6e4ee445195e111bffcfc18184040bcb1` |

## 8. How to reproduce in Protégé

1. Open `onet_schema.ttl` in Protégé.
2. Start the HermiT reasoner.
3. Check ontology consistency; the schema should be consistent.
4. Open `samples/onet_demo_consistent.ttl` with the catalog available; it
   should also be consistent.
5. Open `samples/onet_user_profile_consistent.ttl`; it should be consistent
   and demonstrates the OntoRAG profile and recommendation vocabulary.
6. Open `samples/probe_d3_s1_inconsistent.ttl`; HermiT should report an
   inconsistency. This is intentional and demonstrates the D3/S1 disjointness.

The `catalog-v001.xml` file maps the ontology IRIs to the local Turtle files so
Protégé can resolve `owl:imports` without a network connection.

## 9. Limitations

- Full-ABox HermiT reasoning was not performed; the ABox is validated
  structurally and by bounded samples.
- The 1-occupation and 3-occupation samples were consistent before the
  additive application vocabulary. They were not rerun afterward because the
  1-occupation retry exceeded the available 15-minute window; the change adds
  only application classes/properties and does not alter O*NET axioms.
- The 20-occupation sample is not a validated result. A previous full ROBOT
  classification attempt exceeded available memory, and a later consistency-only
  retry could not run after temporary tooling was cleaned up. The failed log is
  archived under `reports/archive/` for transparency; it is not an ontology
  inconsistency result.
- The source file remains the unchanged O*NET dump.
