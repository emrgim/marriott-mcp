#!/usr/bin/env python3
"""Dump account pages using the already-logged-in Chrome profile."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, HOME, TRIPS, close_context, goto_account  # noqa: E402


def slim(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "body_excerpt"} | {
        "excerpt_head": (d.get("body_excerpt") or "")[:600]
    }


def main() -> int:
    results = {}
    try:
        results["home"] = slim(goto_account(HOME, name="acct-home"))
        results["trips"] = slim(goto_account(TRIPS, name="acct-trips"))
        results["activity"] = slim(goto_account(ACTIVITY, name="acct-activity"))
        print(json.dumps(results, indent=2))
        ok = bool(results["trips"].get("signed_in") or results["activity"].get("signed_in"))
        return 0 if ok else 2
    finally:
        close_context()


if __name__ == "__main__":
    raise SystemExit(main())
