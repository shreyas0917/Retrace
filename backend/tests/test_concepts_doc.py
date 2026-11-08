"""docs/concepts.md: the rule table must match rule_catalog.py exactly."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.diagnosis.rule_catalog import RULE_TABLE_END, RULE_TABLE_START, list_rules, render_rule_table


def _doc_table() -> str:
    for candidate in (Path("/docs/concepts.md"), Path(__file__).resolve().parents[2] / "docs" / "concepts.md"):
        if candidate.is_file():
            text = "\n".join(candidate.read_text(encoding="utf-8").splitlines())  # LF, whatever the checkout uses
            start = text.index(RULE_TABLE_START) + len(RULE_TABLE_START)
            return text[start : text.index(RULE_TABLE_END)].strip()
    pytest.skip("docs/concepts.md is not mounted")


def test_rule_table_matches_the_catalog() -> None:
    assert _doc_table() == render_rule_table(), "run: python scripts/gen_concepts.py"


def test_every_rule_appears_once_in_order() -> None:
    ids = [line.split("|")[1].strip() for line in _doc_table().splitlines()[2:]]
    assert ids == [r["rule_id"] for r in list_rules()]


def test_rendered_table_reflects_catalog_changes(monkeypatch) -> None:
    from app.services.diagnosis import rule_catalog

    changed = {**rule_catalog.RULE_CATALOG["R10"], "summary": "changed summary"}
    monkeypatch.setitem(rule_catalog.RULE_CATALOG, "R10", changed)
    assert "changed summary" in render_rule_table()
