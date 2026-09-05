"""Compare local clone to GitHub main. First tools/call may elicit an update."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ.get("MARRIOTT_UPDATE_REPO", "emrgim/marriott-mcp")
BRANCH = os.environ.get("MARRIOTT_UPDATE_BRANCH", "main")

_asked = False
_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at = 0.0


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def local_sha() -> str:
    r = _git("rev-parse", "HEAD", timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def remote_info() -> tuple[str, str]:
    if os.environ.get("MARRIOTT_FAKE_UPDATE") == "1":
        return "deadbeef" * 5, "fake update (MARRIOTT_FAKE_UPDATE=1)"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/commits/{BRANCH}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "marriott-mcp",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.load(resp)
    sha = str(data.get("sha") or "")
    msg = str(((data.get("commit") or {}).get("message") or "")).split("\n", 1)[0][:120]
    return sha, msg


def peek() -> dict[str, Any] | None:
    global _cache, _cache_at
    if os.environ.get("MARRIOTT_SKIP_UPDATE_CHECK") == "1":
        return None
    now = time.time()
    if _cache is not None and now - _cache_at < 300:
        return _cache
    try:
        local = local_sha()
        if not local:
            _cache, _cache_at = None, now
            return None
        remote, message = remote_info()
        if not remote:
            return None
        info = {
            "behind": local.lower() != remote.lower(),
            "local": local[:12],
            "remote": remote[:12],
            "message": message,
            "repo": REPO,
        }
        if os.environ.get("MARRIOTT_FAKE_UPDATE") == "1":
            info["behind"] = True
        _cache, _cache_at = info, now
        return info
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def should_elicit() -> dict[str, Any] | None:
    global _asked
    with _lock:
        if _asked:
            return None
        info = peek()
        if not info or not info.get("behind"):
            _asked = True
            return None
        return info


def mark_asked() -> None:
    global _asked
    with _lock:
        _asked = True


def pull() -> dict[str, Any]:
    before = local_sha()
    r = _git("pull", "--ff-only", "origin", BRANCH, timeout=60)
    after = local_sha()
    ok = r.returncode == 0
    return {
        "ok": ok,
        "changed": bool(ok and after and after != before),
        "before": before[:12],
        "after": after[:12],
        "stdout": (r.stdout or "")[-500:],
        "stderr": (r.stderr or "")[-400:],
    }


def message_for(info: dict[str, Any]) -> str:
    return (
        f"Marriott MCP update on GitHub ({info.get('repo')} {BRANCH}).\n"
        f"Local {info.get('local')} → {info.get('remote')}: {info.get('message')}\n"
        "Update this server now? Confirm = git pull --ff-only. Cancel = skip until restart."
    )
