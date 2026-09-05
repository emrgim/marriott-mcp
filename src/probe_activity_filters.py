#!/usr/bin/env python3
"""Dump Activity UI controls and XHR so we can implement stay history."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, close_context, goto_account, page  # noqa: E402


def main() -> int:
    p = page()
    xhrs: list[dict] = []

    def on_response(resp):
        u = resp.url
        if any(k in u.lower() for k in ("graphql", "activity", "loyalty", "stay", "history", "transaction", "aries")):
            try:
                xhrs.append({"url": u[:400], "status": resp.status, "type": resp.request.resource_type})
            except Exception:
                pass

    p.on("response", on_response)
    data = goto_account(ACTIVITY, name="act-filters")
    ui = p.evaluate(
        """() => {
          const opts = Array.from(document.querySelectorAll('select, [role="listbox"], [role="combobox"]')).map(el => ({
            tag: el.tagName, id: el.id, name: el.name || null,
            aria: el.getAttribute('aria-label'),
            text: (el.innerText || '').slice(0, 400),
            value: el.value || null,
            options: Array.from(el.querySelectorAll('option')).map(o => ({v: o.value, t: o.textContent.trim(), selected: o.selected}))
          }));
          const buttons = Array.from(document.querySelectorAll('button, a, [role="tab"]')).map(el => ({
            tag: el.tagName, text: (el.innerText || '').trim().slice(0, 80),
            aria: el.getAttribute('aria-label'), href: el.getAttribute('href')
          })).filter(x => /filter|month|year|stay|past|all|page|next|prev|hotel|activity|trip/i.test(
            (x.text||'')+' '+(x.aria||'')+' '+(x.href||'')
          ));
          return {opts, buttons, url: location.href, title: document.title};
        }"""
    )
    print(json.dumps({"page": {k: data.get(k) for k in ("url", "title", "signed_in")}, "ui": ui, "xhrs": xhrs[:40]}, indent=2)[:12000])
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
