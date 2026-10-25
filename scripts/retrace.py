#!/usr/bin/env python3
"""Container entry shim: retrace → python -m app.cli.retrace"""

from __future__ import annotations

import sys

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from app.cli.retrace import main

if __name__ == "__main__":
    raise SystemExit(main())
