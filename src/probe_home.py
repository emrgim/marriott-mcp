#!/usr/bin/env python3
"""Probe marriott.com home with persistent Chrome. Prints JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import close_context, goto  # noqa: E402

def main() -> int:
    try:
        data = goto("https://www.marriott.com/", name="home")
        print(json.dumps({k: v for k, v in data.items() if k != "body_excerpt"}, indent=2))
        print("--- excerpt ---")
        print(data.get("body_excerpt", "")[:800])
        return 0 if not data.get("denied") else 2
    finally:
        close_context()


if __name__ == "__main__":
    raise SystemExit(main())
