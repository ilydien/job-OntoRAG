-- Related occupations for evidence.
-- Parameters:
--   :occupation_iri  IRI string
--   :limit           integer
SELECT related_iri, tier, idx
FROM occupation_related
WHERE occupation_iri = :occupation_iri
ORDER BY idx
LIMIT :limit;
