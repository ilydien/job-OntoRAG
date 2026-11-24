-- Level-scale requirements for a user's declared O*NET skills in one occupation.
-- Parameters are formatted by Index.skill_requirements_for_many:
--   occupation IRI, scale id, rating type IN-list, element IN-list
SELECT
    r.occupation_iri,
    r.rating_type,
    r.element_iri,
    r.element_name_en,
    r.element_name_id,
    r.value,
    r.norm_value,
    r.scale_iri,
    s.scale_id,
    s.name_en AS scale_name
FROM occupation_ratings AS r
JOIN scales AS s ON s.iri = r.scale_iri
WHERE r.occupation_iri = ?
  AND s.scale_id = ?
  AND r.rating_type IN ({rating_types})
  AND r.element_iri IN ({elements})
ORDER BY r.element_iri, r.value DESC;
