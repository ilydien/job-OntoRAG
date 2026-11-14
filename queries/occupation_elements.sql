-- Indexed element ratings for one occupation.
-- Parameters:
--   :occupation_iri  IRI string
SELECT
    r.element_iri,
    r.element_name_en,
    r.element_name_id,
    r.rating_type,
    r.value,
    r.norm_value,
    r.scale_iri
FROM occupation_ratings AS r
WHERE r.occupation_iri = :occupation_iri
ORDER BY r.element_iri, r.rating_type;
