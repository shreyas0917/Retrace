"""Embedding service — PRD-locked model only."""

from __future__ import annotations

from typing import Sequence

from app.core.config import Settings, get_settings
from app.core.errors import EmbeddingError
from app.core.logging import get_logger

logger = get_logger(__name__)

_PRD_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_model = None
_model_revision: str | None = None


def embedding_revision() -> str:
    """Pinned revision string stored with corpus versions."""
    global _model_revision
    if _model_revision:
        return _model_revision
    # Local install pin — not a HuggingFace commit; documented in ADR.
    _model_revision = f"{_PRD_MODEL}@sentence-transformers-local"
    return _model_revision


def get_embedding_model(settings: Settings | None = None):
    """Lazy-load and cache the SentenceTransformer model."""
    global _model
    if _model is not None:
        return _model

    settings = settings or get_settings()
    if settings.embedding_model != _PRD_MODEL:
        raise EmbeddingError(
            f"Refusing to load non-PRD embedding model: {settings.embedding_model}"
        )

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingError(
            "sentence-transformers is not installed",
            details={"hint": "pip install sentence-transformers"},
        ) from exc

    try:
        logger.info("embedding_model_loading", model=_PRD_MODEL)
        _model = SentenceTransformer(_PRD_MODEL)
        logger.info("embedding_model_ready", model=_PRD_MODEL)
        return _model
    except Exception as exc:  # noqa: BLE001
        logger.error("embedding_model_load_failed", error=str(exc))
        raise EmbeddingError(
            "Failed to load embedding model",
            details={"model": _PRD_MODEL, "error": str(exc)},
        ) from exc


def embed_texts(texts: Sequence[str], settings: Settings | None = None) -> list[list[float]]:
    """Embed a batch of texts. Raises EmbeddingError on failure; never skips."""
    if not texts:
        return []

    model = get_embedding_model(settings)
    try:
        vectors = model.encode(
            list(texts),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        result = [vec.tolist() for vec in vectors]
    except Exception as exc:  # noqa: BLE001
        logger.error("embedding_failed", error=str(exc), count=len(texts))
        raise EmbeddingError(
            "Embedding generation failed",
            details={"error": str(exc), "count": len(texts)},
        ) from exc

    if len(result) != len(texts):
        raise EmbeddingError(
            "Embedding count mismatch",
            details={"expected": len(texts), "got": len(result)},
        )
    return result


def embed_query(query: str, settings: Settings | None = None) -> list[float]:
    vectors = embed_texts([query], settings=settings)
    return vectors[0]


def reset_embedding_model() -> None:
    """Test helper."""
    global _model
    _model = None
