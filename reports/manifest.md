# Artefact manifest

## Deliverable ontology files

| File | Role | Size | Triples / axioms | SHA-256 |
|---|---|---:|---:|---|
| `onet_schema.ttl` | TBox/RBox reasoning target | 56,291 B | 1,628 triples | `6f811fa4e0126ba0d5c171b1f8a3fc1cc80e75ef2a3b82536eccd28a5849d464` |
| `onet_abox.ttl` | Normalised ABox | 604,608,637 B | 8,230,417 triples | `23c414c455c49f66a4464c2187e8c9c265ea401d0ff8e1dfa76ae5b75f2123aa` |
| `onet_all.ttl` | Combined import wrapper | 751 B | — | `7efbb1c349037dd1228624adbee9642cc40a0cd919da53734c71c0920edf5aee` |
| `catalog-v001.xml` | Local import catalog | 377 B | — | `f576fcc82470897f938c48d30a5097d590b10795a6d8b017d593885e0e5edf0a` |
| `onet_merged.ttl` | Original source, unchanged | 434,017,563 B | 6,981,173 triples | `2e53fbf2e50ea258c018f4f34db419a3ec20b4e71cb8c35ed6c8aa8cf882df24` |

Source statistics: 708,527 data subjects, 27 O*NET classes, 57 O*NET
predicates. Generated ABox statistics: 708,528 subjects.

## Reasoning samples

| File | Role | Size | SHA-256 |
|---|---|---:|---|
| `samples/onet_demo_consistent.ttl` | Fully typed consistent demonstration ABox | 2,538 B | `d51269c9e03e3f7d62e4b180d524c8c65fe6bd248b59eaac57b7e1735154a790` |
| `samples/onet_user_profile_consistent.ttl` | Consistent OntoRAG user-profile and recommendation ABox | 1,726 B | `6f39b536560bbb5d14f83556741dba5a021402e51eda7fda2b2d8cbf8e47914d` |
| `samples/probe_d3_s1_inconsistent.ttl` | Deliberate D3+S1 inconsistency probe | 887 B | `bebe1d5adebb79db2967779323fcdad6e4ee445195e111bffcfc18184040bcb1` |
| `samples/onet_sample_1occ.ttl` | Bounded real sample, 1 occupation | 37,544,044 B | `28b757f03cfbc0a6ca76cbf0684820fff188c082cec1b1673f6a36413d9912d2` |
| `samples/onet_sample_3occ.ttl` | Bounded real sample, 3 occupations | 46,386,221 B | `8413f0511f1fd7455c7220de9e5ca9eb0f5f5d1fcd5c102e08a2fd8cc62789db` |
| `samples/onet_sample_20occ.ttl` | Experimental sample, not used as validation evidence | 126,051,370 B | `1368566156430280e26872f566bda35c8c04c7045b05c850bef9bdc17fd50830` |
| `samples/mini_ok.ttl` | Earlier minimal consistent sample | 2,271 B | `3f0d9e7c6650544075f95d8409ca81975dbba153ccc8a9f2c06bcf12db63b425` |

The 1-occupation and 3-occupation samples were consistent under the schema
before the additive OntoRAG profile vocabulary; they were not rerun afterward
because the 1-occupation retry exceeded the available 15-minute window. The
20-occupation sample was not validated because full classification exceeded
the available memory; see `reports/validation.md`.

## Validation reports

| File | Content |
|---|---|
| `reports/profile-validation.txt` | OWL 2 DL profile result |
| `reports/abox-datatypes.txt` | Complete ABox datatype audit |
| `reports/hermit-consistency-onet_schema.log` | Historical schema consistency (pre-profile vocabulary) |
| `reports/hermit-consistency-onet_demo_consistent.log` | Historical demo ABox consistency |
| `reports/hermit-consistency-1occ.log` | Historical 1-occupation sample consistency |
| `reports/hermit-consistency-3occ.log` | Historical 3-occupation sample consistency |
| `reports/hermit-consistency-probe_d3_s1_inconsistent.log` | Expected inconsistency probe |
| `reports/analysis.md` | Design and modelling analysis |
| `reports/expressivity.md` | SROIQ(D) construct inventory |
| `reports/validation.md` | Validation narrative and limitations |
| `reports/archive/README.md` | Explanation of archived pre-fix logs |

## Important limitations

- `onet_merged.ttl` is unchanged.
- The complete ABox is not reasoned over with HermiT; it is checked structurally
  and by bounded samples.
- `samples/onet_sample_20occ.ttl` is retained as an experimental artefact only.
