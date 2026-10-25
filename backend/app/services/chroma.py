"""Chroma vector-store client.

PRD / ADR-005: one Chroma collection per corpus_version_id → cv_{id}.
"""

from __future__ import annotations

from typing import Any, Sequence

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from app.core.config import Settings, get_settings
from app.core.errors import DependencyUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: ClientAPI | None = None


def collection_name_for_corpus_version(corpus_version_id: str) -> str:
    """Stable collection naming: one collection per corpus_version_id."""
    safe = corpus_version_id.replace("/", "_").replace(" ", "_")
    return f"cv_{safe}"


def get_chroma_client(settings: Settings | None = None) -> ClientAPI:
    global _client
    if _client is not None:
        return _client
    settings = settings or get_settings()
    _client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    return _client


def reset_chroma_client() -> None:
    """Test helper to clear the cached client."""
    global _client
    _client = None


def check_chroma_connection(settings: Settings | None = None) -> bool:
    """Heartbeat against Chroma; raises DependencyUnavailableError on failure."""
    settings = settings or get_settings()
    try:
        client = get_chroma_client(settings)
        client.heartbeat()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("chroma_unavailable", error=str(exc))
        raise DependencyUnavailableError(
            "Chroma is unavailable",
            details={"host": settings.chroma_host, "port": settings.chroma_port},
        ) from exc


def delete_collection_if_exists(corpus_version_id: str) -> None:
    name = collection_name_for_corpus_version(corpus_version_id)
    client = get_chroma_client()
    try:
        client.delete_collection(name)
        logger.info("chroma_collection_deleted", collection=name)
    except Exception:  # noqa: BLE001 — missing collection is fine
        pass


def get_or_create_collection(corpus_version_id: str) -> Collection:
    client = get_chroma_client()
    name = collection_name_for_corpus_version(corpus_version_id)
    return client.get_or_create_collection(
        name=name,
        metadata={"corpus_version_id": corpus_version_id, "hnsw:space": "cosine"},
    )


def upsert_chunks(
    corpus_version_id: str,
    *,
    ids: Sequence[str],
    documents: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    metadatas: Sequence[dict[str, Any]],
) -> int:
    """Replace collection contents for a corpus version (idempotent rewrite)."""
    if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
        raise ValueError("upsert_chunks length mismatch")

    delete_collection_if_exists(corpus_version_id)
    collection = get_or_create_collection(corpus_version_id)

    # Chroma has practical batch limits; chunk upserts.
    batch_size = 100
    total = 0
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.upsert(
            ids=list(ids[start:end]),
            documents=list(documents[start:end]),
            embeddings=[list(e) for e in embeddings[start:end]],
            metadatas=list(metadatas[start:end]),
        )
        total += end - start

    logger.info(
        "chroma_upsert_complete",
        corpus_version_id=corpus_version_id,
        collection=collection_name_for_corpus_version(corpus_version_id),
        count=total,
    )
    return total


def query_collection(
    corpus_version_id: str,
    *,
    query_embedding: Sequence[float],
    top_k: int,
) -> dict[str, Any]:
    client = get_chroma_client()
    name = collection_name_for_corpus_version(corpus_version_id)
    try:
        collection = client.get_collection(name)
    except Exception as exc:  # noqa: BLE001
        raise DependencyUnavailableError(
            "Chroma collection not found for corpus version",
            details={"corpus_version_id": corpus_version_id, "collection": name},
        ) from exc

    return collection.query(
        query_embeddings=[list(query_embedding)],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )


def collection_count(corpus_version_id: str) -> int:
    client = get_chroma_client()
    name = collection_name_for_corpus_version(corpus_version_id)
    try:
        return int(client.get_collection(name).count())
    except Exception:  # noqa: BLE001
        return 0
