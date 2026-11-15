-- Occupation fields used to compose embedding cards.
SELECT
    iri,
    soc,
    title_en,
    title_id,
    description_en,
    description_id,
    holland_primary,
    holland_secondary,
    holland_tertiary
FROM occupations
ORDER BY iri;
