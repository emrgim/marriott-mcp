#!/usr/bin/env python3
"""Discover how to walk Activity beyond 24 months (years, history link, XHR)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, close_context, goto_account, page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / ".session" / "shots"


def main() -> int:
    reqs: list[dict] = []
    p = page()

    def on_request(req):
        u = req.url
        if any(k in u.lower() for k in ("activity", "graphql", "loyalty", "stay", "history", "aries")):
            post = None
            try:
                post = req.post_data
            except Exception:
                post = None
            reqs.append({"method": req.method, "url": u[:500], "post": (post or "")[:800]})

    p.on("request", on_request)
    goto_account(ACTIVITY, name="hist-start")

    # Nights Detail / year dropdown
    years = p.evaluate(
        """() => {
          const ul = document.querySelector('#listbox-night-year');
          return ul ? ul.innerText : null;
        }"""
    )
    hist = p.evaluate(
        """() => Array.from(document.querySelectorAll('a')).map(a => ({
            t: (a.innerText||'').trim(), href: a.href
          })).filter(x => /history|folio|past|archive|year|night/i.test(x.t+' '+x.href)).slice(0, 40)"""
    )

    # Click See Activity History if present
    link = p.get_by_text("See Activity History", exact=False)
    extra = {}
    if link.count():
        href = link.first.get_attribute("href")
        extra["see_history_href"] = href
        try:
            link.first.click()
            p.wait_for_timeout(4000)
            extra["after_history_url"] = p.url
            extra["after_history_title"] = p.title()
            extra["after_history_years"] = p.evaluate(
                """() => Array.from(document.querySelectorAll('select, [id*=year], [id*=duration], [id*=filter]')).map(el => ({
                  id: el.id, text: (el.innerText||'').slice(0,300)
                }))"""
            )
            p.screenshot(path=str(SHOTS / "see-history.png"))
        except Exception as exc:  # noqa: BLE001
            extra["see_history_err"] = str(exc)

    print(
        json.dumps(
            {
                "years_ui": years,
                "historyish_links": hist,
                "extra": extra,
                "reqs": reqs[-25:],
            },
            indent=2,
        )[:15000]
    )
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
