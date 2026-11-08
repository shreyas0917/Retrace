"""Replay context for recorded judge outputs.

Offline suites carry recorded judge outputs per case (`judge_scripts`). While
a case is diagnosed inside `replaying_judges(scripts)`, judges replay those
outputs instead of calling a live model, whatever FAITHFULNESS_BACKEND says:

* `faithfulness`     scripted LLM replies, replayed through the LLM judge path
  (the provider is a ScriptedJudgeLLM), exactly as before the NLI backend.
* `faithfulness_nli` a recorded NLI result (JSON object or string), replayed
  as is. Used for live_v1, which records real NLI outputs and re-diagnoses
  them offline.

Outside the context, judges run live.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_REPLAY: ContextVar[dict[str, Any] | None] = ContextVar("judge_replay", default=None)


def current_replay() -> dict[str, Any] | None:
    return _REPLAY.get()


@contextmanager
def replaying_judges(scripts: dict[str, Any] | None) -> Iterator[None]:
    token = _REPLAY.set(dict(scripts or {}))
    try:
        yield
    finally:
        _REPLAY.reset(token)
