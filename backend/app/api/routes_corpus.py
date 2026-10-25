"""Corpus and ingestion API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.models import Corpus, CorpusVersion
from app.db.session import get_db
from app.schemas.corpus import (
    CorpusDetailResponse,
    CorpusResponse,
    CorpusVersionResponse,
    CreateCorpusRequest,
    IngestVersionRequest,
)
from app.services.ingestion import create_corpus, get_corpus, ingest_corpus_version

router = APIRouter(
    prefix="/api/v1",
    tags=["corpus"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/corpora", response_model=CorpusResponse)
def post_corpus(
    body: CreateCorpusRequest,
    db: Session = Depends(get_db),
) -> Corpus:
    return create_corpus(db, corpus_id=body.id, title=body.title)


@router.get("/corpora", response_model=list[CorpusResponse])
def list_corpora(db: Session = Depends(get_db)) -> list[Corpus]:
    return list(db.execute(select(Corpus).order_by(Corpus.created_at)).scalars())


@router.get("/corpora/{corpus_id}", response_model=CorpusDetailResponse)
def get_corpus_detail(corpus_id: str, db: Session = Depends(get_db)) -> dict:
    corpus = get_corpus(db, corpus_id)
    versions = list(
        db.execute(
            select(CorpusVersion)
            .where(CorpusVersion.corpus_id == corpus_id)
            .order_by(CorpusVersion.created_at.desc())
        ).scalars()
    )
    return {
        "id": corpus.id,
        "title": corpus.title,
        "created_at": corpus.created_at,
        "versions": versions,
    }


@router.post(
    "/corpora/{corpus_id}/versions",
    response_model=CorpusVersionResponse,
)
def post_corpus_version(
    corpus_id: str,
    body: IngestVersionRequest,
    db: Session = Depends(get_db),
) -> CorpusVersion:
    docs = [d.model_dump() for d in body.documents]
    chunking = body.chunking_config.model_dump() if body.chunking_config else None
    return ingest_corpus_version(
        db,
        corpus_id=corpus_id,
        documents=docs,
        chunking_config=chunking,
    )


@router.get(
    "/corpora/{corpus_id}/versions/{version_id}",
    response_model=CorpusVersionResponse,
)
def get_version(
    corpus_id: str,
    version_id: str,
    db: Session = Depends(get_db),
) -> CorpusVersion:
    get_corpus(db, corpus_id)
    version = db.get(CorpusVersion, version_id)
    if not version or version.corpus_id != corpus_id:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Corpus version not found: {version_id}")
    return version
