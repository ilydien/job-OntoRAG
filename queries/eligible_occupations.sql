-- Candidate occupations after hard profile constraints.
-- Parameters:
--   :require_complete  0/1
--   :require_eligible  0/1
--   :education_order   integer or NULL
--   :max_job_zone     integer or NULL
--   :limit            integer
SELECT
    iri,
    soc,
    title_en,
    title_id,
    description_en,
    description_id,
    data_status,
    education_iri,
    education_local,
    education_order,
    job_zone_iri,
    job_zone,
    holland_primary,
    holland_secondary,
    holland_tertiary
FROM occupations
WHERE (:require_complete = 0 OR data_status = 'CompleteData')
  AND (
      :require_eligible = 0
      OR (
          education_order IS NOT NULL
          AND job_zone IS NOT NULL
          AND (:education_order IS NULL OR education_order <= :education_order)
          AND (:max_job_zone IS NULL OR job_zone <= :max_job_zone)
      )
  )
ORDER BY iri
LIMIT :limit;
