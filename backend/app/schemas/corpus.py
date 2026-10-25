"""Pydantic schemas for corpus ingestion and retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateCorpusRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=512)


class CorpusDocumentInput(BaseModel):
    id: str = Field(..., min_length=1, max_length=256)
    text: str = Field(..., min_length=1)
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


class RetrieveRequest(BaseModel):
    corpus_version_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must be non-empty")
        return cleaned


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
