"""Retrieval API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.schemas.corpus import RetrieveRequest, RetrieveResponse
from app.services.retrieval import retrieve

router = APIRouter(
    prefix="/api/v1",
    tags=["retrieval"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/retrieve", response_model=RetrieveResponse)
def post_retrieve(
    body: RetrieveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    request_id = getattr(request.state, "request_id", None)
    return retrieve(
        db,
        corpus_version_id=body.corpus_version_id,
        query=body.query,
        top_k=body.top_k,
        request_id=request_id,
    )
