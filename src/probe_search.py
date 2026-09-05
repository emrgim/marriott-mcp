#!/usr/bin/env python3
"""BUG-015: search tools exist; dates are MM/DD/YYYY; properties returned."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.probe_grok_http import BASE, NoRedirect, b64url  # noqa: E402


def oauth(opener):
    verifier = secrets.token_urlsafe(48)
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    qs = urllib.parse.urlencode(
        {
            "client_id": "grok",
            "redirect_uri": "http://127.0.0.1/cb",
            "response_type": "code",
            "scope": "mcp:tools",
            "state": "s1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    html = opener.open(f"{BASE}/oauth/authorize?{qs}").read().decode()
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    csrf = m.group(1) if m else ""
    req = urllib.request.Request(
        f"{BASE}/oauth/authorize",
        data=urllib.parse.urlencode({"csrf": csrf}).encode(),
        method="POST",
    )
    try:
        opener.open(req)
        raise SystemExit("expected 302")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") or ""
    code = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["code"][0]
    tok = json.loads(
        opener.open(
            urllib.request.Request(
                f"{BASE}/oauth/token",
                data=urllib.parse.urlencode(
                    {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": "http://127.0.0.1/cb",
                        "code_verifier": verifier,
                        "client_id": "grok",
                    }
                ).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        ).read()
    )
    return tok["access_token"]


def parse_rpc(raw: str) -> dict:
    if raw.startswith("event:"):
        for line in raw.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
    return json.loads(raw)


def main() -> int:
    opener = urllib.request.build_opener(NoRedirect)
    access = oauth(opener)

    def rpc(method: str, params=None, rid=1):
        payload = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        r = opener.open(
            urllib.request.Request(
                f"{BASE}/",
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": f"Bearer {access}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                method="POST",
            )
        )
        return parse_rpc(r.read().decode())

    listed = rpc("tools/list", {}, 1)
    names = [t["name"] for t in listed["result"]["tools"]]
    res = rpc(
        "tools/call",
        {
            "name": "marriott_search",
            "arguments": {
                "destination": "Dubai",
                "checkin": "2026-11-10",
                "checkout": "2026-11-13",
            },
        },
        2,
    )
    sc = (res.get("result") or {}).get("structuredContent") or {}
    if not sc:
        text = ((res.get("result") or {}).get("content") or [{}])[0].get("text") or "{}"
        try:
            sc = json.loads(text)
        except json.JSONDecodeError:
            sc = {"error": text[:400]}
    first = (sc.get("properties") or [None])[0]
    out = {
        "tools": [n for n in names if n.startswith("marriott_search") or n.startswith("marriott_availability")],
        "ok": sc.get("ok"),
        "signed_in": (sc.get("session") or {}).get("signed_in"),
        "checkin": (sc.get("dates") or {}).get("checkin"),
        "applied": (sc.get("dates") or {}).get("applied_on_site"),
        "from_url": (sc.get("dates") or {}).get("fromDate_in_url"),
        "count": sc.get("count"),
        "first_id": (first or {}).get("property_id") if isinstance(first, dict) else None,
        "first_url": (first or {}).get("url") if isinstance(first, dict) else None,
        "error": sc.get("error"),
    }
    print(json.dumps(out, indent=2))
    ok = (
        "marriott_search" in names
        and "marriott_availability" in names
        and sc.get("ok")
        and (sc.get("dates") or {}).get("checkin") == "11/10/2026"
        and (sc.get("count") or 0) >= 1
        and bool((first or {}).get("url"))
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
