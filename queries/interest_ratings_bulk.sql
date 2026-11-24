-- CareerInterestTypesRating rows for a batch of occupations.
-- Parameters: formatted IN-list supplied by Index.interest_ratings_for_many.
SELECT
    occupation_iri,
    rating_type,
    element_iri,
    element_name_en,
    element_name_id,
    norm_value
FROM occupation_ratings
WHERE rating_type = 'CareerInterestTypesRating'
  AND occupation_iri IN ({placeholders})
