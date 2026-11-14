-- Lexical retrieval step.  FTS5 bm25() returns lower-is-better values.
-- Parameters:
--   :query  FTS5 MATCH expression
--   :limit  integer
SELECT
    occupation_iri,
    bm25(occupation_fts) AS rank
FROM occupation_fts
WHERE occupation_fts MATCH :query
ORDER BY rank ASC
LIMIT :limit;
