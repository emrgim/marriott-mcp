#!/usr/bin/env python3
"""Verify write tools pause on elicitation/create and do not execute on decline."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
import time
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
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    req = urllib.request.Request(
        f"{BASE}/oauth/authorize",
        data=urllib.parse.urlencode({"csrf": csrf}).encode(),
        method="POST",
    )
    try:
        opener.open(req)
        raise SystemExit("expected 302")
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise SystemExit(f"authorize {e.code}")
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


def read_sse_message(resp, timeout=30.0) -> dict:
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        try:
            chunk = resp.read(1)
        except Exception:
            time.sleep(0.05)
            continue
        if not chunk:
            time.sleep(0.05)
            continue
        buf += chunk
        if b"\n\n" in buf:
            block, _, buf = buf.partition(b"\n\n")
            for line in block.decode().splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
    raise TimeoutError(f"no SSE message in {timeout}s buf={buf[:200]!r}")


def main() -> int:
    opener = urllib.request.build_opener(NoRedirect)
    access = oauth(opener)

    def post(payload: dict, stream: bool = False):
        req = urllib.request.Request(
            f"{BASE}/",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        return opener.open(req)

    init = {}
    raw = post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"elicitation": {"form": {}}},
            },
        }
    ).read().decode()
    if "data: " in raw:
        for line in raw.splitlines():
            if line.startswith("data: "):
                init = json.loads(line[6:])
                break
    else:
        init = json.loads(raw)

    call = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {
            "name": "marriott_reservation_cancel",
            "arguments": {"confirmation_number": "TEST-NOOP-ELICIT"},
        },
    }
    resp = post(call)
    first = read_sse_message(resp, timeout=20)
    if first.get("method") != "elicitation/create":
        print(json.dumps({"fail": "expected elicitation/create", "got": first}, indent=2))
        return 1
    eid = first["id"]
    schema = (first.get("params") or {}).get("requestedSchema") or {}
    confirm_page = urllib.request.urlopen(f"{BASE}/confirm/{eid}", timeout=10)
    page_html = confirm_page.read().decode()
    has_buttons = "Conferma" in page_html and "Annulla" in page_html

    # Decline — must not execute Marriott write.
    decline = {
        "jsonrpc": "2.0",
        "id": eid,
        "result": {"action": "cancel"},
    }
    try:
        dresp = post(decline)
        dstatus = dresp.status
        dresp.read()
    except urllib.error.HTTPError as e:
        dstatus = e.code
        e.read()

    second = read_sse_message(resp, timeout=30)
    text = json.dumps(second)
    declined_ok = (
        second.get("id") == 99
        and '"changed": false' in text
        and "executed" in text
        and "TEST-NOOP" in json.dumps(first)
    )

    # Accept path with fake confirmation: executes lookup, must not cancel anything.
    resp2 = post(call)
    first2 = read_sse_message(resp2, timeout=20)
    eid2 = first2["id"]
    accept = {
        "jsonrpc": "2.0",
        "id": eid2,
        "result": {"action": "accept", "content": {"confirm": True}},
    }
    try:
        post(accept).read()
    except urllib.error.HTTPError:
        pass
    second2 = read_sse_message(resp2, timeout=90)
    t2 = json.dumps(second2)
    accept_ran = second2.get("id") == 99
    nothing_cancelled = '"changed": false' in t2 or "not found" in t2.lower()

    out = {
        "init_ok": bool((init.get("result") or {}).get("instructions")),
        "elicit_method": first.get("method"),
        "elicit_schema_has_confirm": "confirm" in (schema.get("properties") or {}),
        "confirm_page_buttons": has_buttons,
        "decline_http": dstatus,
        "declined_ok": declined_ok,
        "decline_preview": text[:400],
        "accept_ran": accept_ran,
        "nothing_cancelled": nothing_cancelled,
        "accept_preview": t2[:400],
    }
    print(json.dumps(out, indent=2))
    ok = (
        out["elicit_method"] == "elicitation/create"
        and out["elicit_schema_has_confirm"]
        and out["confirm_page_buttons"]
        and out["declined_ok"]
        and out["accept_ran"]
        and out["nothing_cancelled"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
