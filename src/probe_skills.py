#!/usr/bin/env python3
"""SEP-2640 skills/list, skills/get, skill:// read, fallback tools."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.probe_grok_http import main as _unused  # noqa: F401
from src.probe_grok_http import BASE, NoRedirect, b64url  # noqa: E402
import hashlib as _h
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request


def oauth(opener):
    verifier = secrets.token_urlsafe(48)
    challenge = b64url(_h.sha256(verifier.encode()).digest())
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

    init = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
    ext = (
        ((init.get("result") or {}).get("capabilities") or {})
        .get("extensions")
        or {}
    ).get("io.modelcontextprotocol/skills")
    listed = rpc("skills/list", {}, 2)
    skills = (listed.get("result") or {}).get("skills") or []
    uris = [s.get("uri") for s in skills]
    stays = next((s for s in skills if s.get("uri") == "skill://marriott-stays/SKILL.md"), None)
    got = rpc("skills/get", {"uri": "skill://marriott-reservations/SKILL.md"}, 3)
    skill = (got.get("result") or {}).get("skill") or {}
    unknown = rpc("skills/get", {"uri": "skill://nope/SKILL.md"}, 4)
    read = rpc("resources/read", {"uri": "skill://marriott-stays/SKILL.md"}, 5)
    text = ((read.get("result") or {}).get("contents") or [{}])[0].get("text") or ""
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    rec = next(
        (r for r in (stays or {}).get("resources") or [] if r.get("uri", "").endswith("/SKILL.md")),
        {},
    )
    ddir = rpc("resources/directory/read", {"uri": "skill://marriott-reservations"}, 6)
    children = [c.get("name") for c in (ddir.get("result") or {}).get("resources") or []]
    fb = rpc(
        "tools/call",
        {"name": "marriott_skills_list", "arguments": {}},
        7,
    )
    fb_text = ((fb.get("result") or {}).get("content") or [{}])[0].get("text") or ""
    out = {
        "ext": ext,
        "list_type": (listed.get("result") or {}).get("resultType"),
        "uris": uris,
        "get_name": (skill.get("frontmatter") or {}).get("name"),
        "unknown_code": (unknown.get("error") or {}).get("code"),
        "digest_match": rec.get("digest") == digest and rec.get("size") == len(text.encode("utf-8")),
        "dir_children": children,
        "fallback_has_stays": "marriott-stays" in fb_text,
        "read_has_tools": "marriott_stays" in text,
    }
    print(json.dumps(out, indent=2))
    ok = (
        ext == {"directoryRead": True}
        and out["list_type"] == "complete"
        and "skill://marriott-stays/SKILL.md" in uris
        and "skill://marriott-reservations/SKILL.md" in uris
        and out["get_name"] == "marriott-reservations"
        and out["unknown_code"] == -32602
        and out["digest_match"]
        and "SKILL.md" in children
        and "references" in children
        and out["fallback_has_stays"]
        and out["read_has_tools"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
