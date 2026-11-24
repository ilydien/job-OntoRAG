-- Detailed work activities linked to an occupation's tasks.
-- Parameters: :occupation_iri
SELECT
    t.task_iri,
    e.iri AS dwa_element_iri,
    e.name_en AS dwa_element_en,
    e.name_id AS dwa_element_id
FROM occupation_tasks AS t
JOIN task_dwa AS td ON td.task_iri = t.task_iri
LEFT JOIN elements AS e ON e.iri = td.dwa_element_iri
WHERE t.occupation_iri = :occupation_iri
ORDER BY t.task_iri, e.name_en;
