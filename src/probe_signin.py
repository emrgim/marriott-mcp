#!/usr/bin/env python3
"""Probe sign-in page: dump input names/ids for login selectors."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import close_context, goto, page  # noqa: E402


def main() -> int:
    data = goto("https://www.marriott.com/sign-in.mi", name="signin")
    p = page()
    fields = p.evaluate(
        """() => Array.from(document.querySelectorAll('input,button')).map(el => ({
            tag: el.tagName,
            type: el.type || null,
            name: el.name || null,
            id: el.id || null,
            placeholder: el.placeholder || null,
            aria: el.getAttribute('aria-label'),
            text: (el.innerText || '').slice(0,80)
        }))"""
    )
    print(json.dumps({k: v for k, v in data.items() if k != "body_excerpt"}, indent=2))
    print("--- fields ---")
    print(json.dumps(fields, indent=2)[:4000])
    print("--- excerpt ---")
    print((data.get("body_excerpt") or "")[:1000])
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
