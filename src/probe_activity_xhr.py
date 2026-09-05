#!/usr/bin/env python3
"""Capture marriott.com XHR when changing Activity filters; try extra ranges."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, close_context, goto_account, page  # noqa: E402


def pick(p, dropdown_id: str, list_id: str, label: str) -> None:
    p.locator(f"#{dropdown_id}").click()
    p.wait_for_timeout(300)
    p.locator(f"#{list_id}").get_by_text(label, exact=True).click()
    p.wait_for_timeout(2000)


def main() -> int:
    hits: list[dict] = []
    p = page()

    def on_request(req):
        u = req.url
        if "marriott.com" not in u:
            return
        if req.resource_type not in ("xhr", "fetch"):
            return
        post = ""
        try:
            post = req.post_data or ""
        except Exception:
            post = ""
        hits.append({"m": req.method, "u": u[:400], "p": post[:1200]})

    p.on("request", on_request)
    goto_account(ACTIVITY, name="xhr-act")
    pick(p, "dropdownactivity-filter", "listbox-activity-filter", "Hotel Stay")
    pick(p, "dropdownduration-filter", "listbox-duration-filter", "Last 24 Months")
    pick(p, "dropdownpage-size", "listbox-page-size", "All")
    years = None
    try:
        loc = p.locator("#dropdownnight-year")
        if loc.count() and loc.first.is_visible():
            loc.click()
            p.wait_for_timeout(400)
            years = p.locator("#listbox-night-year").inner_text()
            p.keyboard.press("Escape")
    except Exception as exc:  # noqa: BLE001
        years = f"skip:{exc}"

    # reservation list
    p.goto("https://www.marriott.com/loyalty/findReservationList.mi", wait_until="domcontentloaded", timeout=60_000)
    p.wait_for_timeout(4000)
    res_ui = p.evaluate(
        """() => ({
          url: location.href,
          title: document.title,
          tabs: Array.from(document.querySelectorAll('[role=tab], a, button')).map(el => (el.innerText||'').trim()).filter(t => /past|upcoming|cancel|activity|stay/i.test(t)).slice(0, 30),
          filters: Array.from(document.querySelectorAll('select, [id*=filter], [id*=duration]')).map(el => ({id: el.id, t: (el.innerText||'').slice(0,200)}))
        })"""
    )

    outp = Path(__file__).resolve().parent.parent / ".session" / "xhr-dump.json"
    outp.write_text(json.dumps({"xhr": hits, "years": years, "res": res_ui}, indent=2), encoding="utf-8")
    print("wrote", outp, "xhr", len(hits))
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
