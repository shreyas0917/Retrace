"""Pydantic schemas for corpus ingestion and retrieval."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import get_settings

# Identifiers are used in URLs, Chroma collection names and log fields.
ID_PATTERN = r"^[A-Za-z0-9._-]+$"
MAX_DOCUMENT_CHARS = 2_000_000

# C0/C1 control characters except tab, newline and carriage return.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _max_query_chars() -> int:
    try:
        return int(get_settings().max_query_chars)
    except Exception:  # noqa: BLE001 — settings unavailable outside the app
        return 4000


def clean_query(value: str) -> str:
    """Strip control characters, trim, and enforce the configured length cap."""
    cleaned = _CONTROL_CHARS.sub("", value).strip()
    if not cleaned:
        raise ValueError("query must be non-empty")
    limit = _max_query_chars()
    if len(cleaned) > limit:
        raise ValueError(f"query exceeds maximum length of {limit} characters")
    return cleaned


class CreateCorpusRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=ID_PATTERN)
    title: str = Field(..., min_length=1, max_length=512)


class CorpusDocumentInput(BaseModel):
    id: str = Field(..., min_length=1, max_length=256, pattern=ID_PATTERN)
    text: str = Field(..., min_length=1, max_length=MAX_DOCUMENT_CHARS)
    source_name: str | None = None
    source_uri: str | None = None


class ChunkingConfigInput(BaseModel):
    strategy: str = "recursive_character"
    chunk_size: int = Field(default=512, gt=0)
    chunk_overlap: int = Field(default=64, ge=0)
    tokenizer: str = "char"

    @model_validator(mode="after")
    def overlap_lt_size(self) -> ChunkingConfigInput:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be < chunk_size")
        return self


class IngestVersionRequest(BaseModel):
    documents: list[CorpusDocumentInput] = Field(..., min_length=1)
    chunking_config: ChunkingConfigInput | None = None


class CorpusResponse(BaseModel):
    id: str
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CorpusVersionResponse(BaseModel):
    id: str
    corpus_id: str
    corpus_hash: str
    status: str
    status_message: str | None = None
    chunking_config: dict[str, Any]
    chunking_config_hash: str
    embedding_model: str
    embedding_revision: str
    vector_collection: str
    document_count: int
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CorpusDetailResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    versions: list[CorpusVersionResponse]


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str | None
    text: str | None
    rank: int
    score: float | None
    source_name: str | None = None
    chunk_index: int | None = None
    injection_flags: list[str] = Field(default_factory=list)


class RetrieveRequest(BaseModel):
    corpus_version_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        return clean_query(value)


class RetrieveResponse(BaseModel):
    request_id: str
    retrieval_trace_id: str | None = None
    query: str
    corpus_version_id: str
    top_k: int
    embedding_model: str
    embedding_revision: str | None = None
    latency_ms: float
    results: list[RetrievedChunk]
