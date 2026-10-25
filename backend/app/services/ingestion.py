"""Corpus ingestion orchestration."""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, EmbeddingError, NotFoundError
from app.core.logging import get_logger
from app.db.models import Chunk, Corpus, CorpusVersion, Document
from app.services import chroma as chroma_service
from app.services.chunking import (
    chunk_text,
    make_chunk_id,
    normalize_chunking_config,
)
from app.services.embeddings import embed_texts, embedding_revision
from app.services.hashing import (
    compute_chunking_config_hash,
    compute_corpus_hash,
    compute_document_text_hash,
    sha256_text,
)

logger = get_logger(__name__)

STATUS_CREATED = "CREATED"
STATUS_INGESTING = "INGESTING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"


def create_corpus(db: Session, *, corpus_id: str, title: str) -> Corpus:
    existing = db.get(Corpus, corpus_id)
    if existing:
        return existing
    corpus = Corpus(id=corpus_id, title=title)
    db.add(corpus)
    db.commit()
    db.refresh(corpus)
    logger.info("corpus_created", corpus_id=corpus_id)
    return corpus


def get_corpus(db: Session, corpus_id: str) -> Corpus:
    corpus = db.get(Corpus, corpus_id)
    if not corpus:
        raise NotFoundError(f"Corpus not found: {corpus_id}")
    return corpus


def find_version_by_identity(
    db: Session,
    *,
    corpus_id: str,
    corpus_hash: str,
    chunking_config_hash: str,
    embedding_model: str,
    embedding_rev: str,
) -> CorpusVersion | None:
    stmt = select(CorpusVersion).where(
        CorpusVersion.corpus_id == corpus_id,
        CorpusVersion.corpus_hash == corpus_hash,
        CorpusVersion.chunking_config_hash == chunking_config_hash,
        CorpusVersion.embedding_model == embedding_model,
        CorpusVersion.embedding_revision == embedding_rev,
    )
    return db.execute(stmt).scalars().first()


def _clear_version_children(db: Session, version_id: str) -> None:
    db.execute(delete(Chunk).where(Chunk.corpus_version_id == version_id))
    db.execute(delete(Document).where(Document.corpus_version_id == version_id))
    chroma_service.delete_collection_if_exists(version_id)


def ingest_corpus_version(
    db: Session,
    *,
    corpus_id: str,
    documents: Sequence[dict[str, Any]],
    chunking_config: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> CorpusVersion:
    """Create (or reuse) an immutable READY corpus version.

    Flow: hash → chunk → embed → Chroma → Postgres → READY.
    On failure: status=FAILED and raise.
    """
    settings = settings or get_settings()
    get_corpus(db, corpus_id)

    if not documents:
        raise ConflictError("At least one document is required")

    prepared: list[dict[str, Any]] = []
    pairs: list[tuple[str, str]] = []
    for doc in documents:
        doc_id = str(doc.get("id", "")).strip()
        text = doc.get("text")
        if text is None or str(text).strip() == "":
            raise ConflictError(
                "Document text must be non-empty",
                details={"document_id": doc_id or None},
            )
        text = str(text)
        source_name = str(doc.get("source_name") or doc.get("source_uri") or doc_id)
        prepared.append(
            {
                "id": doc_id,
                "text": text,
                "source_name": source_name,
                "source_uri": doc.get("source_uri"),
                "text_hash": compute_document_text_hash(text),
            }
        )
        pairs.append((doc_id, text))

    try:
        corpus_hash = compute_corpus_hash(pairs)
        normalized_chunking = normalize_chunking_config(chunking_config)
        chunking_hash = compute_chunking_config_hash(normalized_chunking)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc

    emb_model = settings.embedding_model
    emb_rev = embedding_revision()

    existing = find_version_by_identity(
        db,
        corpus_id=corpus_id,
        corpus_hash=corpus_hash,
        chunking_config_hash=chunking_hash,
        embedding_model=emb_model,
        embedding_rev=emb_rev,
    )
    if existing and existing.status == STATUS_READY:
        logger.info(
            "corpus_ingest_idempotent_hit",
            corpus_id=corpus_id,
            corpus_version_id=existing.id,
            corpus_hash=corpus_hash,
        )
        return existing

    if existing:
        version_id = existing.id
        _clear_version_children(db, version_id)
        existing.status = STATUS_INGESTING
        existing.status_message = None
        existing.document_count = 0
        existing.chunk_count = 0
        db.commit()
        version = existing
        logger.info(
            "corpus_ingest_retry",
            corpus_version_id=version_id,
            previous_status=existing.status,
        )
    else:
        version_id = uuid.uuid4().hex
        collection = chroma_service.collection_name_for_corpus_version(version_id)
        version = CorpusVersion(
            id=version_id,
            corpus_id=corpus_id,
            corpus_hash=corpus_hash,
            chunking_config=normalized_chunking,
            chunking_config_hash=chunking_hash,
            embedding_model=emb_model,
            embedding_revision=emb_rev,
            vector_collection=collection,
            status=STATUS_INGESTING,
            document_count=0,
            chunk_count=0,
        )
        db.add(version)
        db.commit()
        db.refresh(version)

    logger.info(
        "ingestion_started",
        corpus_id=corpus_id,
        corpus_version_id=version_id,
        document_count=len(prepared),
    )

    try:
        chunk_rows: list[dict[str, Any]] = []
        for doc in prepared:
            db.add(
                Document(
                    id=doc["id"],
                    corpus_version_id=version_id,
                    source_uri=doc.get("source_uri") or doc["source_name"],
                    source_name=doc["source_name"],
                    text_hash=doc["text_hash"],
                    raw_text=doc["text"],
                )
            )

            pieces = chunk_text(
                doc["text"],
                chunk_size=int(normalized_chunking["chunk_size"]),
                chunk_overlap=int(normalized_chunking["chunk_overlap"]),
            )
            if not pieces:
                raise ConflictError(
                    "Document produced zero chunks",
                    details={"document_id": doc["id"]},
                )

            for piece in pieces:
                chunk_id = make_chunk_id(doc["id"], piece.ordinal)
                chunk_rows.append(
                    {
                        "id": chunk_id,
                        "document_id": doc["id"],
                        "ordinal": piece.ordinal,
                        "text": piece.text,
                        "source_name": doc["source_name"],
                    }
                )
                db.add(
                    Chunk(
                        id=chunk_id,
                        corpus_version_id=version_id,
                        document_id=doc["id"],
                        ordinal=piece.ordinal,
                        text=piece.text,
                        text_hash=f"sha256:{sha256_text(piece.text)}",
                        char_start=piece.char_start,
                        char_end=piece.char_end,
                        chunk_metadata={
                            "source_name": doc["source_name"],
                            "document_id": doc["id"],
                            "chunk_index": piece.ordinal,
                        },
                    )
                )

        db.flush()

        logger.info(
            "embedding_started",
            corpus_version_id=version_id,
            chunk_count=len(chunk_rows),
        )
        vectors = embed_texts([c["text"] for c in chunk_rows], settings=settings)

        chroma_service.upsert_chunks(
            version_id,
            ids=[c["id"] for c in chunk_rows],
            documents=[c["text"] for c in chunk_rows],
            embeddings=vectors,
            metadatas=[
                {
                    "chunk_id": c["id"],
                    "document_id": c["document_id"],
                    "corpus_version_id": version_id,
                    "chunk_index": c["ordinal"],
                    "source_name": c["source_name"],
                }
                for c in chunk_rows
            ],
        )

        version.status = STATUS_READY
        version.status_message = None
        version.document_count = len(prepared)
        version.chunk_count = len(chunk_rows)
        db.commit()
        db.refresh(version)

        logger.info(
            "ingestion_completed",
            corpus_id=corpus_id,
            corpus_version_id=version_id,
            document_count=version.document_count,
            chunk_count=version.chunk_count,
            corpus_hash=corpus_hash,
        )
        return version

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ingestion_failed",
            corpus_version_id=version_id,
            error=str(exc),
        )
        db.rollback()
        failed = db.get(CorpusVersion, version_id)
        if failed:
            failed.status = STATUS_FAILED
            failed.status_message = str(exc)[:1000]
            db.commit()
        try:
            chroma_service.delete_collection_if_exists(version_id)
        except Exception:  # noqa: BLE001
            pass
        if isinstance(exc, (ConflictError, EmbeddingError, NotFoundError)):
            raise
        raise ConflictError(
            "Ingestion failed",
            details={"corpus_version_id": version_id, "error": str(exc)},
        ) from exc
