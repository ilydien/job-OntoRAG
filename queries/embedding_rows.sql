-- Stored occupation-card vectors (float32 blobs, L2-normalised).
SELECT occupation_iri, dim, vector, card_text, card_hash
FROM occupation_embeddings
ORDER BY occupation_iri;
