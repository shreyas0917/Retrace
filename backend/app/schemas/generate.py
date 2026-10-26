"""Schemas for RAG generation / execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.corpus import RetrievedChunk, clean_query


class GenerateRequest(BaseModel):
    corpus_version_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        return clean_query(value)


class GenerationInfo(BaseModel):
    model: str | None = None
    temperature: float | None = None
    prompt_version: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    pricing_version: str | None = None


class RetrievalInfo(BaseModel):
    retrieval_trace_id: str | None = None
    top_k: int
    latency_ms: float | None = None
    results: list[RetrievedChunk]


class LatencyInfo(BaseModel):
    retrieval: float | None = None
    generation: float | None = None
    total: float | None = None


class GenerateResponse(BaseModel):
    request_id: str
    execution_id: str
    corpus_version_id: str
    query: str
    answer: str | None
    abstained: bool
    status: str
    retrieval: RetrievalInfo
    generation: GenerationInfo
    latency_ms: LatencyInfo


class ExecutionTraceResponse(BaseModel):
    id: str
    request_id: str
    corpus_version_id: str
    query: str
    retrieval_trace_id: str | None
    top_k: int
    retrieved_chunks: list[dict[str, Any]] | None
    generation_model: str | None
    generation_temperature: float | None
    prompt_version: str | None
    answer_text: str | None
    abstained: bool
    status: str
    error_code: str | None = None
    error_message: str | None = None
    retrieval_latency_ms: float | None = None
    generation_latency_ms: float | None = None
    total_latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    pricing_version: str | None = None

    model_config = {"from_attributes": True}
