"""Bring-your-own-trace: store an external RAG execution and diagnose it.

The caller's chunk texts are stored on the trace and are exactly what the
judges see; Retrace's own corpus and vector store are never consulted. The
diagnosis runs through the same engine as internal executions.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.metrics import get_metrics
from app.db.models import ExecutionTrace
from app.schemas.traces import TraceRequest
from app.services.diagnosis.engine import diagnose_execution
from app.services.prompts import ABSTENTION_ANSWER
from app.services.retrieval import annotate_injection_flags

logger = get_logger(__name__)

SOURCE_EXTERNAL = "external"
STATUS_COMPLETED = "COMPLETED"
STATUS_ABSTAINED = "ABSTAINED"
# No answer and no abstention: the diagnosis engine treats this as missing (R02).
STATUS_ANSWER_MISSING = "ANSWER_MISSING"

# Refusal phrases recognised when the caller leaves `abstained` unset. Matching
# is case-insensitive and only applies to answers of at most REFUSAL_MAX_CHARS
# characters, so a long answer that merely mentions one of them is not treated
# as an abstention. Set `abstained` explicitly whenever your app knows.
REFUSAL_PHRASES: tuple[str, ...] = (
    "i don't know",
    "i do not know",
    "i cannot answer",
    "i can't answer",
    "i am unable to answer",
    "i'm unable to answer",
    "not enough information to answer",
    "the provided context does not contain",
    "the context does not contain",
    "the documents do not contain",
    "no relevant information",
)
REFUSAL_MAX_CHARS = 300


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def detect_abstention(answer: str | None, explicit: bool | None) -> tuple[bool, str]:
    """Return (abstained, how it was decided).

    Order: the caller's explicit flag, then Retrace's abstention sentinel, then
    the refusal phrase list. A missing answer is not an abstention.
    """
    if explicit is not None:
        return explicit, "explicit"
    if answer is None:
        return False, "none"
    if answer.strip() == ABSTENTION_ANSWER:
        return True, "sentinel"
    norm = _normalize(answer)
    if len(norm) <= REFUSAL_MAX_CHARS:
        for phrase in REFUSAL_PHRASES:
            if phrase in norm:
                return True, f"refusal_phrase:{phrase}"
    return False, "none"


def build_snapshot(req: TraceRequest) -> list[dict[str, Any]]:
    """Chunk list in the same shape as an internal trace's snapshot."""
    snapshot: list[dict[str, Any]] = []
    for position, chunk in enumerate(req.retrieved_chunks, start=1):
        document_id = chunk.document_id
        if document_id is None and ":" in chunk.chunk_id:
            document_id = chunk.chunk_id.split(":", 1)[0] or None
        snapshot.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": document_id,
                "corpus_version_id": None,
                "rank": chunk.rank if chunk.rank is not None else position,
                "retrieval_score": chunk.score,
                "source_name": chunk.source_name,
                "text": chunk.text,
            }
        )
    return snapshot


def _warnings(
    req: TraceRequest,
    snapshot: list[dict[str, Any]],
    abstained: bool,
    flagged: dict[str, list[str]],
) -> list[str]:
    out: list[str] = []
    if not req.gold_chunk_ids:
        out.append(
            "gold_chunk_ids not provided: retrieval-miss detection (rule R11) is unavailable "
            "for this trace."
        )
    if req.answer is None and not abstained:
        out.append("answer is missing: diagnosed as EVAL_MISSING_CONTEXT without running judges.")
    if not snapshot:
        out.append("no retrieved chunks: diagnosed as RETRIEVAL_EMPTY unless the answer is missing.")
    if flagged:
        out.append(
            f"{len(flagged)} chunk(s) matched prompt-injection patterns; see injection_flags. "
            "They were still passed to the judges unchanged."
        )
    return out


class TraceDiagnosisError(AppError):
    """The trace was stored but its diagnosis failed (e.g. the judge model errored)."""

    def __init__(self, execution_id: str, cause: AppError) -> None:
        super().__init__(
            code=cause.code,
            message=f"Trace stored, but diagnosis failed: {cause.message}",
            status_code=cause.status_code,
            details={**(cause.details or {}), "execution_id": execution_id},
        )
        self.execution_id = execution_id


def ingest_trace(
    db: Session,
    req: TraceRequest,
    *,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persist one external trace and, if requested, diagnose it."""
    settings = settings or get_settings()
    snapshot = build_snapshot(req)
    annotate_injection_flags(snapshot, request_id=request_id)
    flagged = {c["chunk_id"]: c["injection_flags"] for c in snapshot if c.get("injection_flags")}
    abstained, detected_by = detect_abstention(req.answer, req.abstained)
    if abstained:
        status = STATUS_ABSTAINED
    elif req.answer is None:
        status = STATUS_ANSWER_MISSING
    else:
        status = STATUS_COMPLETED

    model = (req.metadata or {}).get("model")
    execution_id = str(uuid.uuid4())
    trace = ExecutionTrace(
        id=execution_id,
        request_id=request_id or f"ext-{uuid.uuid4().hex}",
        corpus_version_id=None,
        source=SOURCE_EXTERNAL,
        trace_metadata={
            "metadata": req.metadata,
            "expected_abstention": req.expected_abstention,
            "gold_chunk_ids": req.gold_chunk_ids,
            "abstention_detected_by": detected_by,
        },
        query=req.query,
        retrieval_trace_id=None,
        top_k=len(snapshot),
        retrieved_chunks=snapshot,
        generation_model=model if isinstance(model, str) and len(model) <= 200 else None,
        answer_text=req.answer,
        abstained=abstained,
        status=status,
    )
    db.add(trace)
    db.commit()
    get_metrics().inc("traces.external")
    logger.info(
        "external_trace_stored",
        execution_id=execution_id,
        request_id=trace.request_id,
        chunk_count=len(snapshot),
        status=status,
        abstention_detected_by=detected_by,
        diagnose=req.diagnose,
    )

    diagnosis: dict[str, Any] | None = None
    if req.diagnose:
        try:
            diagnosis = diagnose_execution(
                db,
                execution_id=execution_id,
                gold_chunk_ids=req.gold_chunk_ids,
                settings=settings,
            )
        except AppError as exc:
            db.rollback()
            raise TraceDiagnosisError(execution_id, exc) from exc

    return {
        "execution_id": execution_id,
        "source": SOURCE_EXTERNAL,
        "status": status,
        "abstained": abstained,
        "abstention_detected_by": detected_by,
        "injection_flags": flagged,
        "warnings": _warnings(req, snapshot, abstained, flagged),
        "diagnosis": diagnosis,
    }


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------
@dataclass
class _ParseFailure:
    message: str


class BatchError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code="INVALID_REQUEST", message=message, status_code=400, details=details)


def parse_batch_body(body: bytes, content_type: str, *, max_items: int) -> list[Any]:
    """Parse a JSON array (or {"traces": [...]}) or JSON Lines into raw items.

    A malformed JSON Lines line becomes a per-item failure rather than failing
    the whole batch.
    """
    text = body.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise BatchError("batch is empty")
    ctype = content_type.lower()
    items: list[Any]
    if "ndjson" in ctype or "jsonl" in ctype or "text/plain" in ctype:
        items = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                items.append(_ParseFailure(f"line {line_no}: invalid JSON ({exc.msg})"))
    else:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BatchError(f"body is not valid JSON: {exc.msg}") from exc
        if isinstance(parsed, dict) and isinstance(parsed.get("traces"), list):
            parsed = parsed["traces"]
        if not isinstance(parsed, list):
            raise BatchError('expected a JSON array of traces, {"traces": [...]}, or JSON Lines')
        items = parsed
    if not items:
        raise BatchError("batch is empty")
    if len(items) > max_items:
        raise BatchError(
            f"at most {max_items} traces per batch, got {len(items)}; "
            "use `retrace diagnose --batch traces.jsonl` for larger batches",
            details={"max": max_items, "received": len(items), "cli": "retrace diagnose --batch"},
        )
    return items


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": [str(p) for p in err.get("loc", ())], "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]


def ingest_batch(
    db: Session,
    items: list[Any],
    *,
    request_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Ingest each item independently; one bad trace never fails the batch."""
    settings = settings or get_settings()
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        if isinstance(raw, _ParseFailure):
            results.append(
                {"index": index, "ok": False, "error": {"code": "INVALID_REQUEST", "message": raw.message}}
            )
            continue
        try:
            req = TraceRequest.model_validate(raw)
        except ValidationError as exc:
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Trace failed validation",
                        "details": {"errors": _validation_details(exc)},
                    },
                }
            )
            continue
        item_request_id = f"{request_id}-{index}" if request_id else None
        try:
            out = ingest_trace(db, req, request_id=item_request_id, settings=settings)
            results.append({"index": index, "ok": True, **out})
        except AppError as exc:
            db.rollback()
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "execution_id": getattr(exc, "execution_id", None),
                    "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                }
            )
    ok = sum(1 for r in results if r["ok"])
    return {
        "summary": {"total": len(results), "ok": ok, "failed": len(results) - ok},
        "results": results,
    }
