"""Recognising an abstention ("I don't know") in answer text.

Shared by external-trace ingestion (deciding whether an app abstained) and the
NLI faithfulness judge (dropping refusal sentences, which are not claims).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.services.prompts import ABSTENTION_ANSWER

# Before ADR-047 the sentinel was matched exactly ("INSUFFICIENT_CONTEXT" only).
# Replaying recordings made then, "as recorded", needs that behaviour back;
# nothing else should turn it on.
_EXACT_SENTINEL: ContextVar[bool] = ContextVar("retrace_exact_sentinel", default=False)
# ABSTENTION_ANSWER is "INSUFFICIENT_CONTEXT"; any run of spaces, underscores or hyphens may join the words.
_SENTINEL_RE = re.compile(r"[\s_\-]*".join(re.escape(w) for w in ABSTENTION_ANSWER.split("_")), re.IGNORECASE)
_WRAPPERS = "\"'`*"
_TRAILING = ".!?:;,"


@contextmanager
def exact_sentinel_matching() -> Iterator[None]:
    """Match the abstention sentinel exactly, as the code did before ADR-047."""
    token = _EXACT_SENTINEL.set(True)
    try:
        yield
    finally:
        _EXACT_SENTINEL.reset(token)


def is_sentinel(text: str | None) -> bool:
    """True when the whole answer is the abstention sentinel.

    Tolerant of case, surrounding whitespace, quotes or backticks, trailing
    punctuation, and spaces, underscores or hyphens between the two words:
    "INSUFFICIENT CONTEXT", "insufficient_context", "Insufficient context." all
    match. A longer answer that merely contains the words does not.
    """
    if text is None:
        return False
    if _EXACT_SENTINEL.get():
        return text.strip() == ABSTENTION_ANSWER
    core = text.strip().strip(_WRAPPERS).strip().rstrip(_TRAILING).strip().strip(_WRAPPERS).strip()
    if not core or len(core) > 40:
        return False
    return _SENTINEL_RE.fullmatch(core) is not None


# Matching is case-insensitive and, for whole answers, only applies to
# answers of at most REFUSAL_MAX_CHARS characters, so a long answer that
# merely mentions one of these phrases is not treated as an abstention.
REFUSAL_PHRASES: tuple[str, ...] = (
    "i don't know",
    "i do not know",
    "i cannot answer",
    "i can't answer",
    "i am unable to answer",
    "i'm unable to answer",
    "not enough information to answer",
    "the provided context does not contain",
    "the context does not contain",
    "the documents do not contain",
    "no relevant information",
)
REFUSAL_MAX_CHARS = 300


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def refusal_phrase(text: str) -> str | None:
    """The refusal phrase contained in `text`, or None."""
    norm = normalize(text)
    for phrase in REFUSAL_PHRASES:
        if phrase in norm:
            return phrase
    return None


def is_abstention_text(text: str) -> bool:
    """True when the text is the sentinel or a short refusal."""
    if is_sentinel(text):
        return True
    return len(normalize(text)) <= REFUSAL_MAX_CHARS and refusal_phrase(text) is not None


def detect_abstention(answer: str | None, explicit: bool | None) -> tuple[bool, str]:
    """Return (abstained, how it was decided).

    Order: the caller's explicit flag, then Retrace's abstention sentinel, then
    the refusal phrase list. A missing answer is not an abstention.
    """
    if explicit is not None:
        return explicit, "explicit"
    if answer is None:
        return False, "none"
    if is_sentinel(answer):
        return True, "sentinel"
    if len(normalize(answer)) <= REFUSAL_MAX_CHARS:
        phrase = refusal_phrase(answer)
        if phrase:
            return True, f"refusal_phrase:{phrase}"
    return False, "none"
