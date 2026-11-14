# O*NET Career Ontology — Expressivity

## 1. Target logic

The schema is designed for **SROIQ(D)** reasoning and is valid under the OWL 2
DL profile. `SROIQ(D)` combines:

- `S` — ALC with transitive roles;
- `R` — role hierarchies and complex role inclusion axioms (property chains);
- `O` — nominals (`owl:oneOf`, `owl:hasValue`);
- `I` — inverse roles;
- `Q` — qualified cardinality restrictions;
- `(D)` — datatypes and datatype restrictions.

The ABox is deliberately outside the reasoning target. HermiT is used for the
schema, a synthetic demonstration ABox, and bounded real samples.

## 2. Constructs used in the schema

### Class expressions

| Construct | OWL 2 syntax | Example |
|---|---|---|
| Union | `owl:unionOf` | Range of `:refersTo`, `:linkedTo`, `:illustratedBy`, `:description` |
| Intersection | `owl:intersectionOf` | `career:RealisticUser`, `career:AssessedOccupation` |
| Enumeration / nominal | `owl:oneOf` | `career:AtLeastD3`, `career:ExactlyS1` |
| Value restriction | `owl:hasValue` | `career:hasHollandCode value career:Realistic` |
| Qualified cardinality | `owl:qualifiedCardinality` | `TaskRating` has exactly one `:refersTo` Task |
| Qualified maximum | `owl:maxQualifiedCardinality` | `Element` has at most one `memberOf` Element |

Qualified minimum cardinality (`owl:minQualifiedCardinality`) is available in
the OWL 2 DL profile but is not needed by the current restrictions.

The threshold classes are nominal classes. For example:

```turtle
career:AtLeastS1 owl:equivalentClass [
    a owl:Class ;
    owl:oneOf ( career:S1 career:Level7_PostBaccalaureateCertificate
                career:S2 career:Level9_PostMasterCertificate
                career:Level10_ProfessionalDoctorate career:S3
                career:Level12_PostDoctoral )
] .
```

### Class axioms

| Axiom | Use |
|---|---|
| `rdfs:subClassOf` | Class hierarchy and threshold ordering |
| `owl:equivalentClass` | Threshold nominals and defined application classes |
| `owl:disjointWith` | D3/S1 separation and other pairwise disjointness |
| `owl:AllDisjointClasses` | Structural and rating-class partitions |
| `owl:AllDifferent` | The 12 education levels and the 6 Holland codes |
| `owl:hasKey` | Stable identifiers for five O*NET classes |

### Object properties

| Axiom | Use |
|---|---|
| `owl:inverseOf` | `hasRating`/`ratingOf`, `hasTask`/`taskOf`, etc. |
| `owl:FunctionalProperty` | `memberOf`, application-layer properties |
| `owl:IrreflexiveProperty` | `memberOf`, `relatedTo` |
| `owl:TransitiveProperty` | `ancestorOf` |
| `owl:propertyChainAxiom` | `hasRatedTask`, `hasRatedElement`, `hasReferent`, etc. |
| `rdfs:subPropertyOf` | Typed references under `refersTo`; `linkedTo` under `relatedTo` |
| `rdfs:domain` / `rdfs:range` | Type constraints and inference support |

### Datatype properties

The datatype layer uses:

| Datatype | Properties |
|---|---|
| `xsd:string` | Codes, titles, descriptions, names, categories, sources |
| `xsd:integer` | `taskID`, `jobZone`, `category`, `relatedIndex`, `anchorValue`, `minimum`, `maximum`, `n`, `incumbentsResponding`, `levelOrder` |
| `xsd:positiveInteger` | `recommendationRank` |
| `xsd:decimal` | `preferenceWeight`, `recommendationScore` |
| `xsd:float` | `dataValue`, `standardError`, `lowerCIBound`, `upperCIBound` |
| `xsd:boolean` | `shownInMyNextMove`, `recommendSuppress`, `notRelevant` |
| `xsd:dateTime` | `dateUpdated` |
| `rdfs:Literal` | `recommendationReason` (may be language-tagged) |

`xsd:date` is not used because it is not in the OWL 2 datatype map. No named
custom datatypes are used because HermiT does not support them. The application
ranges are expressed as inline OWL 2 datatype restrictions instead:

- `preferenceWeight` and `recommendationScore` in `[0.0, 1.0]`;
- `maxJobZone` in `[1, 5]`.

The intended numeric bounds for education percentages and anchor values remain
enforced by the ABox integrity checker.

## 3. Role chains and non-simple properties

The schema uses several property chains:

```turtle
:hasRatedTask owl:propertyChainAxiom ( :hasRating :ratedTask ) .
:hasRatedElement owl:propertyChainAxiom ( :hasRating :ratedElement ) .
:hasRatedScale owl:propertyChainAxiom ( :hasRating :ratingScale ) .
:hasRatedCategory owl:propertyChainAxiom ( :hasRating :ratingCategory ) .
:requiresDWAElement owl:propertyChainAxiom ( :hasDWA :dwaElement ) .
:relatedOccupationDirect owl:propertyChainAxiom ( :hasRelatedOccupation :relatedOccupation ) .
:hasReferent owl:propertyChainAxiom ( :hasRating :refersTo ) .
```

These chains make the ontology more than `SHOIQ(D)`: they introduce complex
role inclusions and therefore place the schema in the `SROIQ(D)` family.

OWL 2 DL imposes a global restriction: a non-simple property must not be used
in a cardinality restriction, and irreflexivity cannot be asserted on a
non-simple property. The schema respects this:

- `ancestorOf` is transitive and is **not** used in cardinality restrictions.
- Irreflexivity is asserted only on the simple `memberOf` and `relatedTo`.
- Cardinality restrictions are placed on the simple `refersTo` and `memberOf`.

This is why the earlier attempt to make `ancestorOf` irreflexive was removed:
it caused an OWL 2 DL profile violation.

## 4. Why the ABox is not a reasoning target

The generated ABox contains 8,230,417 triples and is 577 MiB. It is intended
for loading, SPARQL querying, and application access. Sending the complete ABox
to HermiT would require a very large tableau and is not necessary for the
project’s TBox/RBox goal.

The bounded validation strategy is:

1. Reason over the schema alone.
2. Reason over a fully typed synthetic demonstration ABox.
3. Reason over 1-occupation and 3-occupation real samples.
4. Use a deliberate inconsistent D3+S1 probe to prove that the disjointness
   axiom is active.
5. Use structural and datatype integrity checks for the complete ABox.

## 5. Complexity and practical behaviour

SROIQ is a high-complexity description logic (N2EXPTIME-complete for
satisfiability in the worst case). The schema is small (1,628 triples), so
HermiT handles its consistency and classification quickly. The cost grows with
the number of individuals, inverse roles, keys, and property chains, which is
why the full ABox is excluded from DL reasoning.

The schema was checked with the OWL 2 DL profile validator and with HermiT. The
profile report is in `reports/profile-validation.txt`.
