"""Eval-only fault injection for the live benchmark (live_v1).

Faults are generator prompt variants that the live suite builder passes to
`run_rag(eval_fault=...)`. They are deliberately not reachable from the public
API: `GenerateRequest` has no such field and `POST /api/v1/generate` never
passes one (see tests/test_live_suite.py).

The injected condition is metadata about how a run was produced, not its
label: a "wrong facts" prompt can still yield a correct answer, and the human
label decides what actually happened.

Corpus-level conditions (gold document removed, distractor documents added)
are not faults: they are separate corpus versions, built by
scripts/build_live_suite.py, and never touch the main demo corpus.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalFault:
    kind: str
    version: str
    system_suffix: str

    @property
    def prompt_tag(self) -> str:
        return f"eval_fault.{self.kind}.{self.version}"


EVAL_FAULTS: dict[str, EvalFault] = {
    "wrong_facts": EvalFault(
        kind="wrong_facts",
        version="v1",
        system_suffix=(
            "\nEVALUATION MODE (fault injection): answer the question in the usual style, "
            "but change at least one number, duration, amount or name so that it differs "
            "from the retrieved context. Do not mention that anything was changed."
        ),
    ),
    "extra_unsupported_claim": EvalFault(
        kind="extra_unsupported_claim",
        version="v1",
        system_suffix=(
            "\nEVALUATION MODE (fault injection): answer the question correctly from the "
            "retrieved context, then add exactly one more plausible-sounding sentence "
            "stating a specific fact that does not appear in the retrieved context. "
            "Do not mention that it was added."
        ),
    ),
}


def get_fault(kind: str | None) -> EvalFault | None:
    if kind is None:
        return None
    try:
        return EVAL_FAULTS[kind]
    except KeyError as exc:
        raise ValueError(f"unknown eval fault {kind!r}; known: {sorted(EVAL_FAULTS)}") from exc
