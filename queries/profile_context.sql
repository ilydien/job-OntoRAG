-- Canonical education and Holland vocabularies for profile validation.
SELECT
    'education' AS kind,
    local AS local_name,
    iri,
    label_en,
    label_id,
    level_order AS ord
FROM education_levels
UNION ALL
SELECT
    'holland' AS kind,
    local AS local_name,
    iri,
    label_en,
    label_id,
    NULL AS ord
FROM holland_codes
ORDER BY kind, ord, local_name;
