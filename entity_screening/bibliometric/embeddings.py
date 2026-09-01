"""Embedding model wrapper for the topic-similarity layer (deferred VSS work).

This is an asymmetric retrieval problem -- a short technology-area description
compared against a long paper abstract -- not symmetric sentence-similarity, so a
general default (e.g. all-MiniLM-L6-v2) is the wrong shape of tool. BAAI/bge-small-
en-v1.5 is built for exactly this query-vs-passage pattern via an instruction prefix
on the query side only. Verified with a real validation run (see
docs/plans/2026-09-01-vss-topic-similarity-layer.md's Finding 4): a real hypersonics
abstract scored highest against "Scaled Hypersonics" (0.70), clearly ahead of every
other category; a real quantum-computing abstract scored highest against "Quantum
and Battlefield Information Dominance" (0.66). Pinned to its exact HuggingFace
revision for reproducibility -- the same discipline as GleifSnapshotManifest
recording dataset versions; an embedding model is exactly the same class of external
dependency whose exact version needs to be part of the reproducibility record.

Install with the CPU-only PyTorch wheel to avoid pulling unneeded CUDA binaries:
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install sentence-transformers
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
EMBEDDING_DIM = 384

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

EmbedFn = Callable[[str], list[float]]

_model: Any = None


def _get_model() -> Any:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)
    return _model


def embed_query(text: str) -> list[float]:
    """Embeds a short technology-area description (the "query" side of the
    asymmetric retrieval pattern) -- applies bge's required instruction prefix."""
    vector = _get_model().encode(QUERY_INSTRUCTION + text, normalize_embeddings=True)
    return vector.tolist()


def embed_passage(text: str) -> list[float]:
    """Embeds a long paper abstract (the "passage" side) -- plain text, no prefix."""
    vector = _get_model().encode(text, normalize_embeddings=True)
    return vector.tolist()
