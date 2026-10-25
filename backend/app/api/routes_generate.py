"""RAG generation API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import require_api_key
from app.db.models import ExecutionTrace
from app.db.session import get_db
from app.schemas.generate import ExecutionTraceResponse, GenerateRequest, GenerateResponse
from app.services.rag import run_rag

router = APIRouter(
    prefix="/api/v1",
    tags=["generation"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/generate", response_model=GenerateResponse)
def post_generate(
    body: GenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    request_id = getattr(request.state, "request_id", None)
    return run_rag(
        db,
        corpus_version_id=body.corpus_version_id,
        query=body.query,
        top_k=body.top_k,
        request_id=request_id,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionTraceResponse)
def get_execution(execution_id: str, db: Session = Depends(get_db)) -> ExecutionTrace:
    row = db.get(ExecutionTrace, execution_id)
    if not row:
        raise NotFoundError(f"Execution not found: {execution_id}")
    return row
