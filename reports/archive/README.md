# Archived validation artefacts

These files are kept for transparency. They are **not** current validation
results.

## Pre-fix HermiT logs

Before the `taskID` datatype correction, the real ABox samples were reported
as inconsistent. Delta debugging later reduced the failing ABox to a single
`Task` block and showed that the cause was:

```turtle
:taskID "8852"^^xsd:integer .
```

while the schema declared `taskID` with range `xsd:string`. The schema was
corrected to `xsd:integer`, matching the O*NET source. The old logs and the
small explanation file are archived here because they document the diagnosis
process, not the final ontology state.

Archived files include:

- `hermit-sample-1occ.log`, `hermit-sample-3occ.log`, `hermit-sample.log`
- `hermit-sample-1occ-explain.log`, `hermit-sample-3occ-explain.log`
- `hermit-mini-explanation*`, `mini-explanation.md`
- `jfact-sample-1occ.log`
- the older profile report `profile-validation-full.txt`

## Empty/timeout runs

Some `*-fixed.log` files are empty because the ROBOT classification run hit the
time limit before producing output. They were later replaced by the
consistency-only checks in `reports/hermit-consistency-*.log`.

## 20-occupation retry

`hermit-consistency-20occ.log` records an environment/tooling failure:

```text
Error: Could not find or load main class ConsistencyCheck
```

The temporary ROBOT jar and compiled checker had been removed from
`/tmp/opencode` before the retry. This is not an ontology inconsistency result.
The 20-occupation sample is therefore not used as validated evidence.
