"""Bring-your-own-trace API: diagnose traces produced by any RAG app."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import require_api_key
from app.db.session import get_db
from app.schemas.traces import TraceRequest
from app.services.external_traces import ingest_batch, ingest_trace, parse_batch_body

router = APIRouter(
    prefix="/api/v1",
    tags=["traces"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/traces")
def post_trace(body: TraceRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Store one external trace and, unless `diagnose` is false, diagnose it.

    Returns `{execution_id, diagnosis, ...}`; `diagnosis` has the same shape as
    `POST /api/v1/diagnose`.
    """
    return ingest_trace(
        db,
        body,
        request_id=getattr(request.state, "request_id", None),
        settings=get_settings(),
    )


@router.post("/traces/batch")
async def post_trace_batch(request: Request, db: Session = Depends(get_db)) -> dict:
    """Ingest a JSON array (or JSON Lines) of traces; one result per trace.

    Items are validated and diagnosed independently, so one bad trace does not
    fail the batch. Diagnosis runs synchronously; for large batches that need
    LLM judges, prefer `retrace diagnose --batch`.
    """
    settings = get_settings()
    body = await request.body()
    items = parse_batch_body(
        body,
        request.headers.get("content-type", ""),
        max_items=settings.max_trace_batch,
    )
    return await run_in_threadpool(
        ingest_batch,
        db,
        items,
        request_id=getattr(request.state, "request_id", None),
        settings=settings,
    )
