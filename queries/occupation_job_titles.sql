-- Representative job titles for evidence.
-- Parameters:
--   :occupation_iri  IRI string
--   :limit           integer
SELECT job_title_iri, title_en, title_id
FROM occupation_job_titles
WHERE occupation_iri = :occupation_iri
ORDER BY title_en
LIMIT :limit;
