"""Find the Retrace API key for helper scripts, or exit with a clear message.

Order: the API_KEY environment variable, then API_KEY in the repo's .env.
There is deliberately no built-in fallback key.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PLACEHOLDERS = {"", "replace-me", "your_api_key_here"}


def _from_dotenv(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def require_api_key() -> str:
    key = os.environ.get("API_KEY")
    source = "the API_KEY environment variable"
    if key is None:
        dotenv = Path(__file__).resolve().parent.parent / ".env"
        key = _from_dotenv(dotenv)
        source = str(dotenv)
    if key is None or key.strip() in PLACEHOLDERS:
        sys.exit(
            f"API_KEY is not set (checked {source}). Set API_KEY in .env "
            "(`make demo` creates one with a generated key) or export API_KEY=<your key>."
        )
    return key.strip()
