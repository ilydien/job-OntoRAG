-- Full indexed summary for one occupation.
-- Parameters:
--   :occupation_iri  IRI string
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
    education_label_en,
    education_label_id,
    education_order,
    job_zone_iri,
    job_zone,
    job_zone_name_en,
    job_zone_name_id,
    holland_primary,
    holland_secondary,
    holland_tertiary
FROM occupations
WHERE iri = :occupation_iri;
