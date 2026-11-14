# O*NET Career Ontology — Analysis

## 1. Scope

The project transforms the O*NET 31.0 RDF dump `onet_merged.ttl` into a split
**SROIQ(D)** ontology for a knowledge-based career-recommendation scenario.

The target is primarily TBox and RBox reasoning. The complete ABox is **not**
intended to be sent to HermiT: the full ABox has more than eight million
triples, which is far beyond the practical memory budget of the available
machine. The ABox is therefore kept as a separate, loadable/queryable artefact,
while the schema remains the reasoning target.

| Item | Value |
|---|---:|
| Source file | `onet_merged.ttl` |
| Source size | 434,017,563 bytes (about 414 MiB) |
| Source SHA-256 | `2e53fbf2e50ea258c018f4f34db419a3ec20b4e71cb8c35ed6c8aa8cf882df24` |
| Source triples | 6,981,173 |
| Source data subjects | 708,527 |
| O*NET classes in source | 27 |
| O*NET predicates in source | 57 |

The original source file was not modified. All transformations were written to
new files.

## 2. File architecture

| File | Role |
|---|---|
| `onet_schema.ttl` | TBox and RBox, the HermiT/Protégé reasoning target. 1,628 triples, OWL 2 DL profile. |
| `onet_abox.ttl` | Normalised ABox, 577 MiB, 8,230,417 triples. Imports `onet_schema.ttl`. |
| `onet_all.ttl` | Convenience wrapper importing both the schema and the ABox. |
| `catalog-v001.xml` | Local import resolution for Protégé and ROBOT. |
| `samples/` | Bounded reasoning samples and deliberate probes. |

The separation is deliberate:

- The schema contains no O*NET instance data.
- The ABox contains the instance data and the application-layer assertions
  derived from it.
- The wrapper is for loading/querying the complete ontology, not for
  whole-ABox reasoning.

## 3. ABox normalisation

The source overloads the generic `:refersTo` relation. The generated ABox keeps
the original generic triples and adds typed subproperty assertions:

| Typed reference | Triples |
|---|---:|
| `:ratedElement` | 413,314 |
| `:ratingScale` | 579,101 |
| `:ratedTask` | 165,780 |
| `:ratingCategory` | 43,318 |
| `:dwaElement` | 24,087 |
| `:relatedOccupation` | 18,460 |
| `:ratedJobZone` | 923 |

This makes the intended type of each reference explicit while preserving the
source relation for compatibility.

The ABox also contains derived application-layer assertions:

| Derived item | Count |
|---|---:|
| Occupations | 1,016 |
| Occupations with ratings | 923 |
| Occupations without ratings | 93 |
| `career:hasMinEducationLevel` assertions | 901 |
| Education-category to canonical-level mappings | 24 |
| Holland-code assertions (primary/secondary/tertiary) | 2,316 |

Minimum-education distribution:

| Level | Count |
|---|---:|
| Level1_BelowHighSchool | 28 |
| Level2_HighSchool | 290 |
| Level3_PostSecondaryCertificate | 101 |
| Level4_SomeCollege | 54 |
| Associate's Degree | 69 |
| Bachelor's Degree | 208 |
| Level7_PostBaccalaureateCertificate | 9 |
| Master's Degree | 66 |
| Level9_PostMasterCertificate | 2 |
| Level10_ProfessionalDoctorate | 3 |
| Doctoral Degree | 54 |
| Level12_PostDoctoral | 17 |

Holland-code distribution:

| Code | Count |
|---|---:|
| Realistic | 595 |
| Investigative | 375 |
| Artistic | 76 |
| Social | 272 |
| Enterprising | 248 |
| Conventional | 750 |

## 4. Education model and D3/S1 distinction

Twelve canonical education levels are represented as named individuals of
`career:EducationLevel`:

- `career:Level1_BelowHighSchool` through `career:Level4_SomeCollege`
- `career:D3` — Associate's Degree or other 2-year degree
- `career:S1` — Bachelor's Degree
- `career:Level7_PostBaccalaureateCertificate`
- `career:S2` — Master's Degree
- `career:Level9_PostMasterCertificate`
- `career:Level10_ProfessionalDoctorate`
- `career:S3` — Doctoral Degree
- `career:Level12_PostDoctoral`

The display labels use the original O*NET degree names. The internal IRIs keep
the D3/S1/S2/S3 codes because the ABox and samples reference them. The levels
are declared pairwise different with `owl:AllDifferent`, and ordered with
`career:levelOrder`.

Threshold classes are nominals, with the display labels shown in parentheses:

- `career:AtLeastD3` (Associate's Degree or Higher) = {D3, S1, Level7, S2, Level9, Level10, S3, Level12}
- `career:AtLeastS1` (Bachelor's Degree or Higher) = {S1, Level7, S2, Level9, Level10, S3, Level12}
- `career:AtLeastS2` (Master's Degree or Higher) = {S2, Level9, Level10, S3, Level12}
- `career:AtLeastS3` (Doctoral Degree or Higher) = {S3, Level12}

The important distinction is:

```turtle
career:AtLeastS1 rdfs:subClassOf career:AtLeastD3 .
career:ExactlyD3 owl:disjointWith career:AtLeastS1 .
```

Thus `career:D3` (Associate's Degree) is exactly that level and is not an S1
level, while `career:S1` (Bachelor's Degree) is both at least D3 and at least
S1. This captures the D3-versus-S1 distinction without collapsing the two
levels.

`career:hasMinEducationLevel` is functional on occupations, and
`career:educationLevel` is functional on education categories. The education
categories are mapped to the canonical levels before minimum-level reasoning is
performed.

## 5. TBox/RBox modelling decisions

### Structural disjointness

The structural classes are pairwise disjoint:

- Occupation, JobTitle, ReportedJobTitle, Task, EmergingTask, Element, Scale,
  LevelScaleAnchor, Category, JobZone, Linkage, Rating, InterestsActivity,
  InterestsKeyword.
- TaskCategory, EducationCategory, TrainingAndExperienceCategory.
- TaskDWALinkage, RelatedOccupationLinkage.
- The individual rating subclasses.

This prevents a resource from being interpreted simultaneously as, for
example, a Task and an Element.

### Properties

- `:memberOf` is functional and irreflexive; it is the direct element-tree
  parent relation.
- `:ancestorOf` is transitive only. Irreflexivity is **not** asserted on it,
  because OWL 2 DL forbids irreflexivity on a non-simple property.
- `:relatedTo` is irreflexive but deliberately **not symmetric**.
- `:linkedTo` is a subproperty of `:relatedTo`.
- `:revisionFor` has domain `EmergingTask` and range `Task`.
- Inverse properties are provided for the main relations.
- Property chains materialise application-level relations:
  - `hasRatedTask = hasRating ∘ ratedTask`
  - `hasRatedElement = hasRating ∘ ratedElement`
  - `hasRatedScale = hasRating ∘ ratingScale`
  - `hasRatedCategory = hasRating ∘ ratingCategory`
  - `requiresDWAElement = hasDWA ∘ dwaElement`
  - `relatedOccupationDirect = hasRelatedOccupation ∘ relatedOccupation`
  - `hasReferent = hasRating ∘ refersTo`

### Cardinality restrictions

Qualified cardinality restrictions are placed on the simple `refersTo`
relation, for example:

- `TaskRating`: exactly 1 Task, exactly 1 Scale, at most 1 TaskCategory.
- Ability/Work-Activity/Interest/Knowledge/Transferable-Skill/Essential-Skill
  ratings: exactly 1 Element and exactly 1 Scale.
- `EducationRating`: exactly 1 Element, exactly 1 Scale, at most 1
  EducationCategory.
- `TaskDWALinkage`: exactly 1 Element.
- `RelatedOccupationLinkage`: exactly 1 Occupation.
- `EducationCategory` and `TrainingAndExperienceCategory`: exactly 1 Element
  and exactly 1 Scale.
- `TaskCategory`: exactly 1 Scale.
- `Element`: at most 1 `memberOf` parent.

No cardinality restriction is placed on the non-simple `ancestorOf`.

### Keys

`owl:hasKey` is used only where the source really has a stable identifier:

| Class | Key |
|---|---|
| Occupation | `:onetSOCCode` |
| Task | `:taskID` |
| Element | `:elementID` |
| Scale | `:scaleID` |
| JobZone | `:jobZone` |

### OntoRAG profile vocabulary

The schema now includes an application layer for user profiles and ranked
recommendations:

- `career:UserPreference`, with `career:HollandPreference` and
  `career:ElementPreference` as disjoint subclasses.
- `career:hasHollandPreference`, `career:preferenceHollandCode`, and
  `career:preferenceWeight` for scored RIASEC preferences.
- `career:hasElementPreference` and `career:preferenceElement` for preferences
  over O*NET `:Element` individuals. Ability/skill distinctions remain in the
  O*NET element hierarchy rather than being duplicated as new classes.
- `career:hasEducationLevel` and `career:maxJobZone` for user constraints.
- `career:Recommendation` with `career:recommendationFor`,
  `career:recommendedOccupation`, `career:recommendationRank`,
  `career:recommendationScore`, and `career:recommendationReason`.

The classes are application-level and disjoint with `:OnetEntity`. The
existing `career:hasHollandCode` is retained for an optional top-code
assertion; scored profiles use `career:hasHollandPreference`.

### Datatypes

The ontology uses only standard OWL 2 datatypes:

- `xsd:string`
- `xsd:integer`
- `xsd:positiveInteger`
- `xsd:decimal`
- `xsd:float`
- `xsd:boolean`
- `xsd:dateTime`

No **named** user-defined datatypes are used. The profile vocabulary uses
inline OWL 2 datatype restrictions for application ranges:

- preference weights and recommendation scores in `[0.0, 1.0]`;
- `career:maxJobZone` in `[1, 5]`.

These are data-range expressions, not named custom datatypes, and are accepted
by HermiT. Two further intended numeric ranges remain checked by the ABox
validator:

- EducationRating `dataValue` in `[0, 100]`.
- LevelScaleAnchor `anchorValue` in `[0, 7]`.

The source uses `xsd:date` for dates, but `xsd:date` is not in the OWL 2
datatype map. All ABox dates were converted to `xsd:dateTime`
(`YYYY-MM-DDT00:00:00`).

## 6. Inconsistency found during validation

A real 1-occupation sample initially made HermiT report an inconsistency.
Delta debugging over the ABox subjects reduced the failing subset to a **single
Task block**. The cause was:

```turtle
:taskID "8852"^^xsd:integer .
```

while the schema declared:

```turtle
:taskID rdfs:range xsd:string .
```

The O*NET source itself writes task IDs as integer literals, so the schema was
the incorrect side. The range was corrected to `xsd:integer`, and the ABox was
left unchanged. A datatype audit of 4,274,072 literal triples found no
remaining datatype/range mismatch.

After the correction:

- the schema is consistent;
- the demonstration ABox is consistent;
- the 1-occupation sample is consistent;
- the 3-occupation sample is consistent;
- the deliberate D3+S1 probe is inconsistent as intended.

## 7. Limitations

- The complete 577 MiB ABox is not reasoned over with HermiT. This is a
  deliberate resource decision and is consistent with the project requirement.
- Consistency evidence comes from the schema, the synthetic demonstration ABox,
  and bounded real samples. The full ABox is covered by structural and
  datatype integrity checks, not by whole-ABox DL reasoning.
- The 20-occupation sample is not used as a validated result. Earlier attempts
  at full ROBOT classification exceeded the available memory; the sample is
  retained only as an experimental artefact.
