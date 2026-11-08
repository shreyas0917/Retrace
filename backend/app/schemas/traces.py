"""Request schema for bring-your-own-trace (POST /api/v1/traces).

A trace is what someone else's RAG app already produced: the question, the
chunks it retrieved, and the answer it gave. Retrace stores it and diagnoses
it without touching its own corpus or generator. Unknown fields are rejected,
booleans are strict, and every size is capped by a setting.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
)

from app.core.config import get_settings
from app.schemas.corpus import clean_query

# Same character family as corpus/document ids, plus ':' because Retrace's own
# chunk ids look like "employee_handbook:c001", and '/' '#' for path-like ids.
CHUNK_ID_PATTERN = r"^[A-Za-z0-9._:/#-]+$"
_CHUNK_ID_RE = re.compile(CHUNK_ID_PATTERN)
# C0/C1 control characters except tab, newline and carriage return.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

MAX_GOLD_IDS = 50
MAX_METADATA_BYTES = 8192
MAX_METADATA_KEYS = 50


class TraceChunk(BaseModel):
    """One retrieved chunk, exactly as the caller's retriever returned it."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., min_length=1, max_length=256, pattern=CHUNK_ID_PATTERN)
    text: str = Field(..., min_length=1)
    score: float | None = Field(default=None, allow_inf_nan=False)
    rank: int | None = Field(default=None, ge=1)
    source_name: str | None = Field(default=None, max_length=512)
    document_id: str | None = Field(default=None, min_length=1, max_length=256, pattern=CHUNK_ID_PATTERN)

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        cleaned = _CONTROL_CHARS.sub("", value)
        if not cleaned.strip():
            raise ValueError("chunk text must be non-empty")
        limit = get_settings().max_trace_chunk_chars
        if len(cleaned) > limit:
            raise ValueError(f"chunk text exceeds maximum length of {limit} characters")
        return cleaned


class TraceRequest(BaseModel):
    """An external RAG execution to store and, by default, diagnose."""

    model_config = ConfigDict(extra="forbid")

    query: str
    retrieved_chunks: list[TraceChunk] = Field(default_factory=list)
    # null (or blank) means the app produced no answer: diagnosed as missing.
    answer: str | None = None
    # null means "detect it": see app.services.external_traces.detect_abstention.
    abstained: StrictBool | None = None
    # Without gold ids, retrieval-miss detection (rule R11) is unavailable.
    gold_chunk_ids: list[str] | None = None
    # Stored with the trace for your own evaluation; not read by the rules.
    expected_abstention: StrictBool | None = None
    metadata: dict[str, Any] | None = None
    diagnose: StrictBool = True

    @field_validator("query")
    @classmethod
    def _clean_query(cls, value: str) -> str:
        return clean_query(value)

    @field_validator("retrieved_chunks")
    @classmethod
    def _check_chunks(cls, chunks: list[TraceChunk]) -> list[TraceChunk]:
        limit = get_settings().max_trace_chunks
        if len(chunks) > limit:
            raise ValueError(f"at most {limit} retrieved chunks are allowed, got {len(chunks)}")
        ids = [c.chunk_id for c in chunks]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"chunk_id values must be unique; duplicated: {duplicates[:5]}")
        return chunks

    @field_validator("answer")
    @classmethod
    def _clean_answer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _CONTROL_CHARS.sub("", value).strip()
        if not cleaned:
            return None
        limit = get_settings().max_trace_answer_chars
        if len(cleaned) > limit:
            raise ValueError(f"answer exceeds maximum length of {limit} characters")
        return cleaned

    @field_validator("gold_chunk_ids")
    @classmethod
    def _check_gold(cls, ids: list[str] | None) -> list[str] | None:
        if ids is None:
            return None
        if len(ids) > MAX_GOLD_IDS:
            raise ValueError(f"at most {MAX_GOLD_IDS} gold_chunk_ids are allowed")
        bad = [i for i in ids if not isinstance(i, str) or not _CHUNK_ID_RE.match(i) or len(i) > 256]
        if bad:
            raise ValueError(f"invalid gold_chunk_ids: {bad[:5]}")
        # De-duplicate, keeping the caller's order.
        return list(dict.fromkeys(ids))

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > MAX_METADATA_KEYS:
            raise ValueError(f"metadata may have at most {MAX_METADATA_KEYS} keys")
        try:
            size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-serializable") from exc
        if size > MAX_METADATA_BYTES:
            raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} bytes when serialized")
        return value
