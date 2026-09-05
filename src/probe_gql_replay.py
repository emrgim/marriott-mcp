#!/usr/bin/env python3
"""Replay phoenixAccountGetMyActivityTable with numberOfMonths=240 using captured headers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser import ACTIVITY, ACTIVITY_QUERY, close_context, goto_account, page  # noqa: E402


def main() -> int:
    seed = {}
    p = page()

    def on_req(req):
        if "phoenixAccountGetMyActivityTable" in req.url and req.post_data:
            seed["url"] = req.url
            seed["headers"] = dict(req.headers)
            seed["post"] = req.post_data

    p.on("request", on_req)
    goto_account(ACTIVITY, name="replay")
    p.wait_for_timeout(2000)
    if not seed:
        print("NO_SEED")
        close_context()
        return 1
    body = json.loads(seed["post"])
    cid = body["variables"]["customerId"]
    body["query"] = ACTIVITY_QUERY
    body["variables"]["numberOfMonths"] = 240
    body["variables"]["types"] = "stay"
    body["variables"]["limit"] = 50
    body["variables"]["offset"] = 0
    hdrs = {k: v for k, v in seed["headers"].items() if k.lower() not in ("content-length", "host")}
    hdrs["content-type"] = "application/json"
    resp = p.request.post(seed["url"], headers=hdrs, data=json.dumps(body), timeout=60_000)
    print("status", resp.status)
    txt = resp.text()[:500]
    print(txt[:400])
    if resp.status == 200:
        js = resp.json()
        act = js["data"]["customer"]["loyaltyInformation"]["accountActivity"]
        print("total", act.get("total"), "edges", len(act.get("edges") or []))
    close_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
