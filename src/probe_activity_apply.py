#!/usr/bin/env python3
"""Apply Hotel Stay + Last 24 Months + All, dump table rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, close_context, goto_account, page  # noqa: E402


def pick(p, dropdown_id: str, list_id: str, label: str) -> None:
    p.locator(f"#{dropdown_id}").click()
    p.wait_for_timeout(400)
    p.locator(f"#{list_id}").get_by_text(label, exact=True).click()
    p.wait_for_timeout(2500)


def main() -> int:
    goto_account(ACTIVITY, name="act-before")
    p = page()
    pick(p, "dropdownactivity-filter", "listbox-activity-filter", "Hotel Stay")
    pick(p, "dropdownduration-filter", "listbox-duration-filter", "Last 24 Months")
    pick(p, "dropdownpage-size", "listbox-page-size", "All")
    p.wait_for_timeout(3000)
    rows = p.evaluate(
        """() => {
          const tables = Array.from(document.querySelectorAll('table'));
          const fromTables = tables.map(t => ({
            headers: Array.from(t.querySelectorAll('th')).map(th => th.innerText.trim()),
            rows: Array.from(t.querySelectorAll('tbody tr')).map(tr =>
              Array.from(tr.querySelectorAll('td,th')).map(td => td.innerText.trim().slice(0, 200))
            )
          }));
          const cards = Array.from(document.querySelectorAll('[class*="activity"], [class*="stay"], [class*="transaction"]'))
            .slice(0, 40)
            .map(el => el.innerText.trim().slice(0, 240));
          const duration = document.querySelector('#dropdownduration-filter')?.innerText;
          const atype = document.querySelector('#dropdownactivity-filter')?.innerText;
          const psize = document.querySelector('#dropdownpage-size')?.innerText;
          return {duration, atype, psize, fromTables, bodySlice: document.body.innerText.slice(0, 3500)};
        }"""
    )
    p.screenshot(path=str(Path(__file__).resolve().parent.parent / ".session/shots/act-filtered.png"))
    print(json.dumps(rows, indent=2)[:14000])
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
