#!/usr/bin/env python3
"""Regenerate the rule table in docs/concepts.md from rule_catalog.py.

    python scripts/gen_concepts.py           # rewrite the table in place
    python scripts/gen_concepts.py --check   # exit 1 if the doc is out of date (CI)

Only the text between the rule-table markers is generated; the glossary
around it is written by hand. Needs no third-party packages.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.diagnosis.rule_catalog import RULE_TABLE_END, RULE_TABLE_START, render_rule_table  # noqa: E402

DOC = ROOT / "docs" / "concepts.md"


def splice(doc: str, table: str) -> str:
    start = doc.index(RULE_TABLE_START) + len(RULE_TABLE_START)
    end = doc.index(RULE_TABLE_END)
    return doc[:start] + "\n" + table + "\n" + doc[end:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/concepts.md is out of date")
    args = parser.parse_args()
    # Compare with LF endings, whatever the checkout uses.
    current = "\n".join(DOC.read_text(encoding="utf-8").splitlines()) + "\n"
    updated = splice(current, render_rule_table())
    if args.check:
        if updated != current:
            print("docs/concepts.md rule table is out of date: run python scripts/gen_concepts.py", file=sys.stderr)
            return 1
        print("docs/concepts.md rule table matches rule_catalog.py")
        return 0
    DOC.write_text(updated, encoding="utf-8", newline="\n")
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
