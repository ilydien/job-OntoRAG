-- Batched element ratings for a candidate set.
-- Parameters (substituted by Index.elements_for_many):
--   {placeholders}    one ? per occupation IRI
--   {element_filter}  optional "AND element_iri IN (?, ...)" clause
SELECT
    r.occupation_iri,
    r.element_iri,
    r.element_name_en,
    r.element_name_id,
    r.rating_type,
    r.value,
    r.norm_value,
    r.scale_iri
FROM occupation_ratings AS r
WHERE r.occupation_iri IN ({placeholders})
  {element_filter}
ORDER BY r.occupation_iri, r.element_iri, r.rating_type;
