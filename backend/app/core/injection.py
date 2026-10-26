"""Conservative prompt-injection pattern scanner for retrieved text.

This is a detector, not a filter: flagged chunks are still passed to the
generator inside ``<retrieved_context>`` (the prompt treats them as untrusted
data), but the flags are surfaced in traces, metrics and logs so operators
can see when a corpus is trying to steer the model.

Patterns are intentionally narrow to keep false positives low on ordinary
documentation. Each entry is ``(name, compiled regex)``:

ignore_instructions      "ignore/forget/disregard/skip (all) (the) previous|prior|above|
                         earlier|original|system instructions|rules|prompt"
disregard_rules          "disregard (all) (the|your) rules|instructions|restrictions"
role_override            "you are now a|an|the|in|free|no longer"
system_prompt_reference  the phrase "system prompt"
reveal_secret            reveal|print|output|show|leak|... <= 60 chars ... api key|password|
                         secret|token|credentials
role_tag                 chat-role markup such as <system>, </assistant>, <|im_start|>
system_line_prefix       a line starting with "SYSTEM:" or "ASSISTANT:"
new_instructions         "new|updated|real|actual|true|hidden instructions:"
developer_mode           "developer|dev|god|DAN|jailbreak mode"
override_rules           "override (all|the|your) rules|instructions|safety|restrictions|guardrails"
hide_from_user           "do not tell|inform|mention|reveal (this to) the user"
base64_blob              a base64-looking run of 200+ characters
"""

from __future__ import annotations

import re

_I = re.IGNORECASE

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(
            r"\b(?:ignore|forget|disregard|skip)\s+(?:all\s+|any\s+|of\s+)?(?:the\s+|your\s+)?"
            r"(?:previous|prior|above|earlier|preceding|original|system)\s+"
            r"(?:instructions?|rules?|directions?|prompts?|guidance|guidelines?)\b",
            _I,
        ),
    ),
    (
        "disregard_rules",
        re.compile(
            r"\bdisregard\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?"
            r"(?:rules?|instructions?|restrictions?|constraints?)\b",
            _I,
        ),
    ),
    (
        "role_override",
        re.compile(r"\byou\s+are\s+now\s+(?:a|an|the|in|free|no\s+longer)\b", _I),
    ),
    ("system_prompt_reference", re.compile(r"\bsystem\s+prompt\b", _I)),
    (
        "reveal_secret",
        re.compile(
            r"\b(?:reveal|print|output|show|leak|display|expose|repeat|dump|exfiltrate)\b"
            r"[^.\n]{0,60}?\b(?:api[\s_-]?key|password|secret|token|credentials?)\b",
            _I,
        ),
    ),
    (
        "role_tag",
        re.compile(
            r"</?\s*(?:system|assistant|user|tool|im_start|im_end)\s*>|<\|im_(?:start|end)\|>",
            _I,
        ),
    ),
    ("system_line_prefix", re.compile(r"(?m)^\s*(?:system|assistant)\s*:", _I)),
    (
        "new_instructions",
        re.compile(r"\b(?:new|updated|real|actual|true|hidden)\s+instructions?\s*:", _I),
    ),
    ("developer_mode", re.compile(r"\b(?:developer|dev|god|dan|jailbreak)\s+mode\b", _I)),
    (
        "override_rules",
        re.compile(
            r"\boverride\s+(?:all\s+|the\s+|your\s+|any\s+)?"
            r"(?:rules?|instructions?|safety|restrictions?|guardrails?)\b",
            _I,
        ),
    ),
    (
        "hide_from_user",
        re.compile(
            r"\bdo\s+not\s+(?:tell|inform|mention|reveal)\s+(?:this\s+to\s+)?(?:the\s+)?user\b",
            _I,
        ),
    ),
    (
        "base64_blob",
        re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{200,}={0,2}(?![A-Za-z0-9+/])"),
    ),
]

PATTERN_NAMES: tuple[str, ...] = tuple(name for name, _ in INJECTION_PATTERNS)

_MAX_SCAN_CHARS = 200_000


def scan_text(text: str | None) -> list[str]:
    """Return the names of injection patterns matched in ``text`` (empty when clean)."""
    if not text:
        return []
    sample = text[:_MAX_SCAN_CHARS]
    return [name for name, pattern in INJECTION_PATTERNS if pattern.search(sample)]
