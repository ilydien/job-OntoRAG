-- Interest activity and keyword vocabulary, linked to RIASEC elements.
SELECT
    'activity' AS kind,
    iri,
    text_en AS label_en,
    text_id AS label_id,
    riasec_local,
    riasec_iri
FROM interest_activities
WHERE text_en IS NOT NULL

UNION ALL

SELECT
    'keyword' AS kind,
    iri,
    keyword_en AS label_en,
    keyword_id AS label_id,
    riasec_local,
    riasec_iri
FROM interest_keywords
WHERE keyword_en IS NOT NULL
