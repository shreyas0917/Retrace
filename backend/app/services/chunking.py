"""Deterministic text chunking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_CHUNKING_CONFIG: dict[str, Any] = {
    "strategy": "recursive_character",
    "chunk_size": 512,
    "chunk_overlap": 64,
    "tokenizer": "char",
}


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    text: str
    char_start: int
    char_end: int


def normalize_chunking_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(DEFAULT_CHUNKING_CONFIG)
    if config:
        raw.update(dict(config))

    strategy = str(raw.get("strategy", "recursive_character"))
    if strategy != "recursive_character":
        raise ValueError(
            f"unsupported chunking strategy '{strategy}'; "
            "MVP supports only 'recursive_character'"
        )

    chunk_size = int(raw["chunk_size"])
    chunk_overlap = int(raw["chunk_overlap"])
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be < chunk_size")

    return {
        "strategy": strategy,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "tokenizer": str(raw.get("tokenizer", "char")),
    }


def make_chunk_id(document_id: str, ordinal: int) -> str:
    """Stable chunk id: {document_id}:c{ordinal:03d}."""
    return f"{document_id}:c{ordinal:03d}"


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    """Character-window chunking; identical inputs → identical chunks."""
    if not text:
        return []

    chunks: list[TextChunk] = []
    start = 0
    ordinal = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)
        piece = text[start:end]
        chunks.append(
            TextChunk(
                ordinal=ordinal,
                text=piece,
                char_start=start,
                char_end=end,
            )
        )
        ordinal += 1
        if end >= length:
            break
        start = end - chunk_overlap
        if start < 0:
            start = 0
        # Guard against pathological zero-progress loops
        if start >= end:
            start = end

    return chunks
