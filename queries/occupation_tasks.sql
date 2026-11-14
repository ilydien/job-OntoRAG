-- Representative tasks for evidence.
-- Parameters:
--   :occupation_iri  IRI string
--   :limit           integer
SELECT task_iri, task_en, task_id, task_id_text
FROM occupation_tasks
WHERE occupation_iri = :occupation_iri
ORDER BY task_id
LIMIT :limit;
