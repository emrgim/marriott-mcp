#!/usr/bin/env python3
"""Save full phoenixAccountGetMyActivityTable request+response."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, close_context, goto_account, page  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".session" / "activity-gql.json"


def main() -> int:
    captured: list[dict] = []
    p = page()

    def on_response(resp):
        if "phoenixAccountGetMyActivityTable" not in resp.url:
            return
        try:
            captured.append(
                {
                    "url": resp.url,
                    "post": resp.request.post_data,
                    "status": resp.status,
                    "body": resp.text()[:200000],
                }
            )
        except Exception as exc:  # noqa: BLE001
            captured.append({"err": str(exc)})

    p.on("response", on_response)
    goto_account(ACTIVITY, name="gql")
    p.locator("#dropdownactivity-filter").click()
    p.wait_for_timeout(300)
    p.locator("#listbox-activity-filter").get_by_text("Hotel Stay", exact=True).click()
    p.wait_for_timeout(1500)
    p.locator("#dropdownduration-filter").click()
    p.wait_for_timeout(300)
    p.locator("#listbox-duration-filter").get_by_text("Last 24 Months", exact=True).click()
    p.wait_for_timeout(2500)
    OUT.write_text(json.dumps(captured, indent=2), encoding="utf-8")
    print("n", len(captured), "wrote", OUT)
    if captured and captured[-1].get("post"):
        print("post_len", len(captured[-1]["post"]))
        print("body_len", len(captured[-1].get("body") or ""))
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
