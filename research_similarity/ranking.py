"""Encode text and perform exact cosine retrieval."""

from hashlib import blake2b
import json
import math
import re
from urllib.parse import quote

DIMENSIONS = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


class Embedder:
    def __init__(self, mode: str, threads: int = 1):
        self.model = None
        if mode == "minilm":
            import torch
            from sentence_transformers import SentenceTransformer

            torch.set_num_threads(threads)
            torch.set_num_interop_threads(1)
            self.model = SentenceTransformer(
                MODEL_NAME,
                revision=MODEL_REVISION,
                device="cpu",
                model_kwargs={"use_safetensors": True},
            )
        elif mode != "smoke":
            raise ValueError(f"Unknown model mode: {mode}")

    def encode(self, texts: list[str]) -> list[list[float]]:
        if self.model is not None:
            return self.model.encode(
                texts,
                batch_size=16,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()
        return [smoke_embedding(text) for text in texts]


def smoke_embedding(text: str) -> list[float]:
    """Hash token counts into a stable normalized vector for infrastructure tests."""
    tokens = re.findall(r"\w+", text.casefold()) or [text]
    vector = [0.0] * DIMENSIONS
    for token in tokens:
        bucket = int.from_bytes(blake2b(token.encode(), digest_size=4).digest(), "big")
        vector[bucket % DIMENSIONS] += 1
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def search(conn, embedding: list[float], limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT arxiv_id, title, authors, embedding <=> %s::vector AS distance
        FROM papers
        ORDER BY distance, arxiv_id COLLATE "C"
        LIMIT %s
        """,
        (json.dumps(embedding, allow_nan=False), limit),
    ).fetchall()
    return [
        {
            "arxiv_id": row["arxiv_id"],
            "title": row["title"],
            "authors": row["authors"],
            "url": "https://arxiv.org/abs/" + quote(row["arxiv_id"], safe="/"),
            "score": max(-1.0, min(1.0, 1.0 - row["distance"])),
        }
        for row in rows
    ]
