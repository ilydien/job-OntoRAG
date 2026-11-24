-- Education, training/experience, work-context, and work-style ratings.
-- Parameters: :occupation_iri
SELECT
    pr.rating_type,
    pr.element_iri,
    e.name_en AS element_en,
    e.name_id AS element_id,
    pr.category_iri,
    c.category,
    c.description AS category_description,
    pr.value,
    pr.n
FROM profile_ratings AS pr
LEFT JOIN elements AS e ON e.iri = pr.element_iri
LEFT JOIN categories AS c ON c.iri = pr.category_iri
WHERE pr.occupation_iri = :occupation_iri
ORDER BY pr.rating_type, e.name_en, pr.value DESC;
