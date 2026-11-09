"""The abstention sentinel is recognised in the forms models actually write (ADR-047)."""

from __future__ import annotations

import pytest

from app.services.abstention import detect_abstention, exact_sentinel_matching, is_abstention_text, is_sentinel
from app.services.diagnosis.engine import _base_signals
from app.services.prompts import ABSTENTION_ANSWER


@pytest.mark.parametrize(
    "text",
    [
        "INSUFFICIENT_CONTEXT",
        "INSUFFICIENT CONTEXT",
        "insufficient_context",
        "Insufficient context.",
        "  INSUFFICIENT  CONTEXT!\n",
        "insufficient-context",
        '"INSUFFICIENT_CONTEXT"',
        "`INSUFFICIENT_CONTEXT`",
        "**INSUFFICIENT CONTEXT**",
        "INSUFFICIENTCONTEXT",
    ],
)
def test_sentinel_variants_are_abstentions(text: str) -> None:
    assert is_sentinel(text)
    assert is_abstention_text(text)
    assert detect_abstention(text, None) == (True, "sentinel")


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "The context is insufficient to say.",
        "INSUFFICIENT CONTEXT for the second part, but refunds take 30 days.",
        "Insufficient context window",
        "SUFFICIENT CONTEXT",
        "Refunds are available within 30 days.",
    ],
)
def test_other_answers_are_not_the_sentinel(text: str | None) -> None:
    assert not is_sentinel(text)


def test_explicit_flag_still_wins() -> None:
    assert detect_abstention("INSUFFICIENT CONTEXT", False) == (False, "explicit")


def test_exact_mode_reproduces_the_old_behaviour() -> None:
    with exact_sentinel_matching():
        assert is_sentinel(ABSTENTION_ANSWER)
        assert not is_sentinel("INSUFFICIENT CONTEXT")
        assert not is_sentinel("insufficient_context")
    assert is_sentinel("INSUFFICIENT CONTEXT")  # restored on exit


class _Execution:
    """The ExecutionTrace fields _base_signals reads, for a run whose pipeline flag missed the abstention."""

    def __init__(self, answer: str) -> None:
        self.answer_text = answer
        self.abstained = False
        self.status = "COMPLETED"
        self.error_code = None
        self.retrieved_chunks = [{"chunk_id": "doc:c000", "text": "x"}]


def test_diagnosis_sees_the_abstention_when_the_pipeline_flag_missed_it() -> None:
    execution = _Execution("INSUFFICIENT CONTEXT")
    assert _base_signals(execution, None).answer_is_abstention is True  # type: ignore[arg-type]
    with exact_sentinel_matching():
        assert _base_signals(execution, None).answer_is_abstention is False  # type: ignore[arg-type]
