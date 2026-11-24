-- Indexed requirement ratings for one occupation and one O*NET rating type.
-- Parameters:
--   :occupation_iri  IRI string
--   :rating_type     O*NET rating class local name
SELECT
    r.rating_type,
    r.element_iri,
    r.element_name_en,
    r.element_name_id,
    r.value,
    r.norm_value,
    r.scale_iri,
    s.scale_id,
    s.name_en AS scale_name,
    s.minimum AS scale_minimum,
    s.maximum AS scale_maximum
FROM occupation_ratings AS r
LEFT JOIN scales AS s ON s.iri = r.scale_iri
WHERE r.occupation_iri = :occupation_iri
  AND r.rating_type = :rating_type
  AND r.element_iri IS NOT NULL
ORDER BY r.norm_value DESC, r.value DESC, r.element_name_en ASC;
