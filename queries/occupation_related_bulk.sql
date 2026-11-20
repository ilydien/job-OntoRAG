-- Batched related-occupation edges for a candidate set.
-- Parameters (substituted by Index.related_for_many):
--   {placeholders}  one ? per occupation IRI
SELECT occupation_iri, related_iri, tier
FROM occupation_related
WHERE occupation_iri IN ({placeholders})
ORDER BY occupation_iri, related_iri;
