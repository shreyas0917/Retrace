"""Diagnosis API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import require_api_key
from app.db.models import Diagnosis
from app.db.session import get_db
from app.services.diagnosis.engine import diagnose_execution

router = APIRouter(
    prefix="/api/v1",
    tags=["diagnosis"],
    dependencies=[Depends(require_api_key)],
)


class DiagnoseRequest(BaseModel):
    execution_id: str = Field(..., min_length=1)
    gold_chunk_ids: list[str] | None = None


@router.post("/diagnose")
def post_diagnose(body: DiagnoseRequest, db: Session = Depends(get_db)) -> dict:
    return diagnose_execution(
        db,
        execution_id=body.execution_id,
        gold_chunk_ids=body.gold_chunk_ids,
    )


@router.get("/diagnoses/{diagnosis_id}")
def get_diagnosis(diagnosis_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(Diagnosis, diagnosis_id)
    if not row:
        raise NotFoundError(f"Diagnosis not found: {diagnosis_id}")
    from app.db.models import ExecutionTrace
    from app.services.diagnosis.engine import _to_response

    execution = db.get(ExecutionTrace, row.execution_id) if row.execution_id else None
    if not execution:
        raise NotFoundError("Diagnosis has no linked execution")
    return _to_response(row, execution)
