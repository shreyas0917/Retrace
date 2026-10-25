"""End-to-end RAG execution: retrieve → (optional) generate → persist execution trace."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    GenerationError,
    GenerationTimeoutError,
)
from app.core.logging import bind_correlation, get_logger
from app.core.ops import record_generation
from app.db.models import CorpusVersion, ExecutionTrace
from app.services.generation import generate_answer
from app.services.llm_client import GENERATION_TEMPERATURE
from app.services.prompts import ABSTENTION_ANSWER, PROMPT_VERSION
from app.services.retrieval import retrieve

logger = get_logger(__name__)

STATUS_COMPLETED = "COMPLETED"
STATUS_ABSTAINED = "ABSTAINED"
STATUS_FAILED = "FAILED"
STATUS_GENERATION_TIMEOUT = "GENERATION_TIMEOUT"


def _chunk_snapshot(
    corpus_version_id: str, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compact chunk references stored on the execution trace."""
    snapshot = []
    for item in results:
        snapshot.append(
            {
                "chunk_id": item.get("chunk_id"),
                "document_id": item.get("document_id"),
                "corpus_version_id": corpus_version_id,
                "rank": item.get("rank"),
                "retrieval_score": item.get("score"),
                "source_name": item.get("source_name"),
                "text": item.get("text"),
            }
        )
    return snapshot


def _has_usable_context(results: list[dict[str, Any]]) -> bool:
    if not results:
        return False
    return any((r.get("text") or "").strip() for r in results)


def run_rag(
    db: Session,
    *,
    corpus_version_id: str,
    query: str,
    top_k: int = 5,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Execute retrieve + generate and persist an ExecutionTrace."""
    settings = settings or get_settings()
    request_id = request_id or str(uuid.uuid4())
    execution_id = str(uuid.uuid4())
    total_started = time.perf_counter()
    bind_correlation(
        request_id=request_id,
        execution_id=execution_id,
        corpus_version_id=corpus_version_id,
        operation="rag",
    )

    version = db.get(CorpusVersion, corpus_version_id)
    # retrieve() re-validates READY / existence; we still need version for pins later

    retrieval: dict[str, Any] | None = None
    generation_latency_ms: float | None = None
    answer: str | None = None
    abstained = False
    status = STATUS_COMPLETED
    error_code: str | None = None
    error_message: str | None = None
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    generation_model = settings.model_name

    try:
        retrieval = retrieve(
            db,
            corpus_version_id=corpus_version_id,
            query=query,
            top_k=top_k,
            request_id=request_id,
            settings=settings,
        )
        # reload version pins after successful retrieve
        version = db.get(CorpusVersion, corpus_version_id)
        assert version is not None

        results = retrieval["results"]
        if not _has_usable_context(results):
            # Forced abstention — do not call the LLM (PRD NO_EVIDENCE path).
            abstained = True
            status = STATUS_ABSTAINED
            answer = ABSTENTION_ANSWER
            generation_latency_ms = 0.0
            logger.info(
                "rag_forced_abstention",
                request_id=request_id,
                execution_id=execution_id,
                corpus_version_id=corpus_version_id,
                reason="empty_or_blank_retrieval",
            )
        else:
            llm = generate_answer(
                query=query,
                retrieved_chunks=results,
                settings=settings,
            )
            answer = llm.content
            generation_latency_ms = llm.latency_ms
            generation_model = llm.model
            prompt_tokens = llm.prompt_tokens
            completion_tokens = llm.completion_tokens
            total_tokens = llm.total_tokens
            if answer.strip() == ABSTENTION_ANSWER:
                abstained = True
                status = STATUS_ABSTAINED

    except GenerationTimeoutError as exc:
        status = STATUS_GENERATION_TIMEOUT
        error_code = exc.code
        error_message = exc.message
        logger.error(
            "rag_generation_timeout",
            request_id=request_id,
            execution_id=execution_id,
            error=exc.message,
        )
    except AppError as exc:
        status = STATUS_FAILED
        error_code = exc.code
        error_message = exc.message
        logger.error(
            "rag_execution_failed",
            request_id=request_id,
            execution_id=execution_id,
            error_code=exc.code,
            error=exc.message,
        )
        # Persist partial trace when retrieval already succeeded, then re-raise.
        if retrieval is None:
            raise
    except Exception as exc:  # noqa: BLE001
        status = STATUS_FAILED
        error_code = "EVAL_INTERNAL_ERROR"
        error_message = str(exc)[:1000]
        logger.exception(
            "rag_unexpected_error",
            request_id=request_id,
            execution_id=execution_id,
        )
        if retrieval is None:
            raise GenerationError(
                "RAG execution failed before generation",
                details={"error": str(exc)},
            ) from exc

    total_latency_ms = round((time.perf_counter() - total_started) * 1000, 2)
    retrieval_latency_ms = retrieval["latency_ms"] if retrieval else None
    chunk_refs = (
        _chunk_snapshot(corpus_version_id, retrieval["results"]) if retrieval else []
    )

    # Pins from corpus version when available
    embedding_model = (
        (version.embedding_model if version else None)
        or (retrieval or {}).get("embedding_model")
        or settings.embedding_model
    )
    embedding_revision = (
        (version.embedding_revision if version else None)
        or (retrieval or {}).get("embedding_revision")
    )

    trace = ExecutionTrace(
        id=execution_id,
        request_id=request_id,
        corpus_version_id=corpus_version_id,
        query=query.strip(),
        retrieval_trace_id=(retrieval or {}).get("retrieval_trace_id"),
        top_k=top_k,
        retrieved_chunks=chunk_refs,
        embedding_model=embedding_model,
        embedding_revision=embedding_revision,
        generation_model=generation_model,
        generation_temperature=GENERATION_TEMPERATURE,
        prompt_version=PROMPT_VERSION,
        answer_text=answer,
        abstained=abstained,
        status=status,
        error_code=error_code,
        error_message=error_message,
        retrieval_latency_ms=retrieval_latency_ms,
        generation_latency_ms=generation_latency_ms,
        total_latency_ms=total_latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
    db.add(trace)
    db.commit()

    record_generation(
        status=status,
        latency_ms=generation_latency_ms,
        tokens=total_tokens,
    )
    if retrieval_latency_ms is not None:
        # retrieval already recorded in retrieve(); keep generation-focused here
        pass

    logger.info(
        "rag_execution_completed",
        request_id=request_id,
        execution_id=execution_id,
        corpus_version_id=corpus_version_id,
        status=status,
        abstained=abstained,
        retrieval_latency_ms=retrieval_latency_ms,
        generation_latency_ms=generation_latency_ms,
        total_latency_ms=total_latency_ms,
        model=generation_model,
        operation="rag",
        error_code=error_code,
    )

    if status in {STATUS_FAILED, STATUS_GENERATION_TIMEOUT} and answer is None:
        # Surface failure to the API after persisting the trace.
        if status == STATUS_GENERATION_TIMEOUT:
            raise GenerationTimeoutError(
                error_message or "Generation timed out",
                details={"execution_id": execution_id},
            )
        raise GenerationError(
            error_message or "Generation failed",
            details={"execution_id": execution_id, "error_code": error_code},
        )

    return {
        "request_id": request_id,
        "execution_id": execution_id,
        "corpus_version_id": corpus_version_id,
        "query": query.strip(),
        "answer": answer,
        "abstained": abstained,
        "status": status,
        "retrieval": {
            "retrieval_trace_id": (retrieval or {}).get("retrieval_trace_id"),
            "top_k": top_k,
            "latency_ms": retrieval_latency_ms,
            "results": (retrieval or {}).get("results") or [],
        },
        "generation": {
            "model": generation_model,
            "temperature": GENERATION_TEMPERATURE,
            "prompt_version": PROMPT_VERSION,
            "latency_ms": generation_latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "latency_ms": {
            "retrieval": retrieval_latency_ms,
            "generation": generation_latency_ms,
            "total": total_latency_ms,
        },
    }
