"""Deterministic hashing helpers for corpus reproducibility."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex_digest(parts: Sequence[bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.hexdigest()


def compute_document_text_hash(text: str) -> str:
    """Hash of a single document body."""
    return f"sha256:{sha256_text(text)}"


def compute_corpus_hash(documents: Sequence[tuple[str, str]]) -> str:
    """Deterministic corpus hash over (document_id, text) pairs.

    Same IDs + same texts + same set → same hash, independent of input order.
    """
    if not documents:
        raise ValueError("corpus must contain at least one document")

    canonical: list[tuple[str, str]] = []
    seen: set[str] = set()
    for doc_id, text in documents:
        if not doc_id or not doc_id.strip():
            raise ValueError("document id must be non-empty")
        if doc_id in seen:
            raise ValueError(f"duplicate document id: {doc_id}")
        seen.add(doc_id)
        canonical.append((doc_id, text))

    canonical.sort(key=lambda item: item[0])

    h = hashlib.sha256()
    for doc_id, text in canonical:
        text_hash = sha256_text(text)
        h.update(doc_id.encode("utf-8"))
        h.update(b"\0")
        h.update(text_hash.encode("utf-8"))
        h.update(b"\n")
    return f"sha256:{h.hexdigest()}"


def compute_chunking_config_hash(chunking_config: Mapping[str, Any]) -> str:
    """Hash of canonical JSON for chunking configuration."""
    payload = json.dumps(chunking_config, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256_text(payload)}"
