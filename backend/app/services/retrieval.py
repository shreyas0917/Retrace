"""Dense retrieval against a READY corpus version."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import InvalidStateError, NotFoundError
from app.core.injection import scan_text
from app.core.logging import bind_correlation, get_logger
from app.core.metrics import get_metrics
from app.core.ops import record_retrieval
from app.db.models import CorpusVersion, RetrievalTrace
from app.services import chroma as chroma_service
from app.services.embeddings import embed_query
from app.services.ingestion import STATUS_READY

logger = get_logger(__name__)

INJECTION_METRIC = "retrieval.injection_suspected"


def annotate_injection_flags(
    results: list[dict[str, Any]], *, request_id: str | None = None
) -> int:
    """Scan each result's text for prompt-injection patterns.

    Sets ``injection_flags`` on every result (empty list when clean), bumps the
    ``retrieval.injection_suspected`` counter and logs a warning naming only the
    chunk ids and pattern names, never the chunk text. Returns the flagged count.
    """
    flagged: dict[str, list[str]] = {}
    for item in results:
        flags = scan_text(item.get("text"))
        item["injection_flags"] = flags
        if flags:
            flagged[str(item.get("chunk_id"))] = flags
    if flagged:
        get_metrics().inc(INJECTION_METRIC, len(flagged))
        logger.warning(
            "retrieval_injection_suspected",
            request_id=request_id,
            flagged_count=len(flagged),
            flagged_chunks=flagged,
            operation="retrieval",
        )
    return len(flagged)


def retrieve(
    db: Session,
    *,
    corpus_version_id: str,
    query: str,
    top_k: int = 5,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    query = (query or "").strip()
    if not query:
        raise InvalidStateError("query must be non-empty")
    if top_k < 1 or top_k > 50:
        raise InvalidStateError("top_k must be between 1 and 50")

    version = db.get(CorpusVersion, corpus_version_id)
    if not version:
        raise NotFoundError(f"Corpus version not found: {corpus_version_id}")
    if version.status != STATUS_READY:
        raise InvalidStateError(
            "Corpus version is not READY for retrieval",
            details={
                "corpus_version_id": corpus_version_id,
                "status": version.status,
            },
        )

    request_id = request_id or str(uuid.uuid4())
    started = time.perf_counter()

    query_vec = embed_query(query, settings=settings)
    raw = chroma_service.query_collection(
        corpus_version_id,
        query_embedding=query_vec,
        top_k=top_k,
    )

    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: list[dict[str, Any]] = []
    for rank, chunk_id in enumerate(ids, start=1):
        meta = metadatas[rank - 1] if rank - 1 < len(metadatas) else {}
        distance = distances[rank - 1] if rank - 1 < len(distances) else None
        # Cosine distance → similarity score in [0, 1] approx for normalized vectors
        score = None if distance is None else round(1.0 - float(distance), 6)
        results.append(
            {
                "chunk_id": chunk_id,
                "document_id": (meta or {}).get("document_id"),
                "text": documents[rank - 1] if rank - 1 < len(documents) else None,
                "rank": rank,
                "score": score,
                "source_name": (meta or {}).get("source_name"),
                "chunk_index": (meta or {}).get("chunk_index"),
            }
        )

    annotate_injection_flags(results, request_id=request_id)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    trace = RetrievalTrace(
        id=str(uuid.uuid4()),
        request_id=request_id,
        corpus_version_id=corpus_version_id,
        query=query,
        top_k=top_k,
        retrieved_chunk_ids=[r["chunk_id"] for r in results],
        scores=[r["score"] for r in results],
        latency_ms=latency_ms,
        embedding_model=version.embedding_model,
        result_count=len(results),
    )
    db.add(trace)
    db.commit()

    logger.info(
        "retrieval_completed",
        request_id=request_id,
        corpus_version_id=corpus_version_id,
        top_k=top_k,
        result_count=len(results),
        latency_ms=latency_ms,
        embedding_model=version.embedding_model,
        retrieved_chunk_ids=[r["chunk_id"] for r in results],
        retrieval_trace_id=trace.id,
        operation="retrieval",
    )
    record_retrieval(empty=len(results) == 0, latency_ms=latency_ms)
    bind_correlation(retrieval_trace_id=trace.id, corpus_version_id=corpus_version_id)

    return {
        "request_id": request_id,
        "retrieval_trace_id": trace.id,
        "query": query,
        "corpus_version_id": corpus_version_id,
        "top_k": top_k,
        "embedding_model": version.embedding_model,
        "embedding_revision": version.embedding_revision,
        "latency_ms": latency_ms,
        "results": results,
    }
