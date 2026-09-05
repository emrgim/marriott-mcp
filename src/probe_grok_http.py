#!/usr/bin/env python3
"""Smoke Grok HTTP MCP: OAuth PKCE + initialize + ping + tools/list + status."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8099"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    opener = urllib.request.build_opener(NoRedirect)
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
            raise SystemExit(f"authorize {e.code} {e.read()[:200]}")
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
    access = tok["access_token"]

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
        raw = r.read().decode()
        if raw.startswith("event:"):
            for line in raw.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
        return json.loads(raw)

    init = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    ping = rpc("ping", {}, 2)
    listed = rpc("tools/list", {}, 3)
    names = [t["name"] for t in listed["result"]["tools"]]
    ann = {t["name"]: t.get("annotations", {}) for t in listed["result"]["tools"]}
    res = rpc("resources/list", {}, 5)
    status = rpc("tools/call", {"name": "marriott_status", "arguments": {}}, 4)
    text = status.get("result", {}).get("content", [{}])[0].get("text", "")
    err = "asyncio loop" in text
    print(
        json.dumps(
            {
                "protocol": init.get("result", {}).get("protocolVersion"),
                "has_instructions": bool(init.get("result", {}).get("instructions")),
                "caps": list((init.get("result", {}) or {}).get("capabilities", {}).keys()),
                "ping_ok": "result" in ping,
                "tools": names,
                "stays_readonly": (ann.get("marriott_stays") or {}).get("readOnlyHint"),
                "cancel_destructive": (ann.get("marriott_reservation_cancel") or {}).get(
                    "destructiveHint"
                ),
                "resources": [r.get("uri") for r in (res.get("result") or {}).get("resources", [])],
                "status_asyncio_error": err,
            },
            indent=2,
        )
    )
    need = {
        "marriott_reservation_create",
        "marriott_reservation_modify",
        "marriott_reservation_cancel",
    }
    return 1 if err or not names or not need.issubset(names) else 0


if __name__ == "__main__":
    raise SystemExit(main())
