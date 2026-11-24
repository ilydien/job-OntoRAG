-- Tasks and optional frequency ratings for one occupation.
-- Parameters: :occupation_iri
SELECT
    t.occupation_iri,
    t.task_iri,
    t.task_en,
    t.task_id_text,
    t.task_type,
    tr.value,
    tr.category_iri,
    c.description AS category_description,
    s.scale_id AS rating_scale_id
FROM occupation_tasks AS t
LEFT JOIN task_ratings AS tr ON tr.task_iri = t.task_iri
LEFT JOIN categories AS c ON c.iri = tr.category_iri
LEFT JOIN scales AS s ON s.iri = tr.scale_iri
WHERE t.occupation_iri = :occupation_iri
ORDER BY
    CASE WHEN t.task_type = 'Core' THEN 0 ELSE 1 END,
    tr.value DESC,
    t.task_en ASC;
