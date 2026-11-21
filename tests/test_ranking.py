"""Ranking checks, including an opt-in PostgreSQL/pgvector oracle test."""

import os

import numpy as np
import pytest

from research_similarity.ranking import Embedder, search


def test_smoke_embeddings_are_deterministic_unit_vectors():
    model = Embedder("smoke")
    texts = ["Dense retrieval encodes documents and queries.", "Machine translation with attention."]
    first = np.asarray(model.encode(texts))
    assert first.shape == (2, 384)
    np.testing.assert_allclose(np.linalg.norm(first, axis=1), np.ones(2), atol=1e-6)
    np.testing.assert_array_equal(first, model.encode(texts))
    assert not np.allclose(first[0], first[1])


@pytest.mark.skipif(
    not os.environ.get("APP_TEST_DATABASE_URL"),
    reason="Set APP_TEST_DATABASE_URL to run the pgvector integration check.",
)
def test_pgvector_top_ten_matches_numpy():
    import psycopg
    from psycopg.rows import dict_row

    rng = np.random.default_rng(41)
    vectors = rng.normal(size=(25, 384)).astype("float32")
    query = rng.normal(size=384).astype("float32")
    scores = (vectors @ query) / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(query))
    expected = sorted(range(len(vectors)), key=lambda i: (-scores[i], str(i)))[:10]

    with psycopg.connect(os.environ["APP_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # PostgreSQL searches the temporary schema first in this session.
        conn.execute(
            """CREATE TEMP TABLE papers (
                 arxiv_id text PRIMARY KEY, title text, authors text, abstract text,
                 categories text[], embedding vector(384)
               ) ON COMMIT DROP"""
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO papers VALUES (
                     %s, %s, 'Test author', 'Test abstract', ARRAY['cs.LG'], %s::vector
                   )""",
                [(str(i), f"Paper {i}", str(vector.tolist())) for i, vector in enumerate(vectors)],
            )
        actual = search(conn, query.tolist())

    assert [row["arxiv_id"] for row in actual] == [str(i) for i in expected]
    np.testing.assert_allclose([row["score"] for row in actual], scores[expected], atol=1e-6)
