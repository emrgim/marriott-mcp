"""Agent-filed bugs, stored on the MCP host. Secrets stripped."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BUGS_DIR = ROOT / ".session" / "bugs"

_SECRET = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|bearer|authorization|marriott_password)"
    r"([\"']?\s*[:=]\s*[\"']?)([^\s\"']+)"
)
_TOKENISH = re.compile(r"(?i)\b(am_[a-z0-9_]{16,}|sk-[a-z0-9]{16,}|ghp_[a-zA-Z0-9]{20,})\b")


def _redact(text: str) -> str:
    text = _SECRET.sub(r"\1\2[REDACTED]", text)
    return _TOKENISH.sub("[REDACTED]", text)


def _clip(val: Any, n: int = 8000) -> str:
    if val is None:
        return ""
    if not isinstance(val, str):
        try:
            val = json.dumps(val, ensure_ascii=False, default=str)
        except TypeError:
            val = str(val)
    val = _redact(val)
    return val if len(val) <= n else val[:n] + "\n…[truncated]"


def save_bug(
    *,
    title: str,
    what_happened: str = "",
    expected: str = "",
    tool: str = "",
    arguments: Any = None,
    log: str = "",
    url: str = "",
    client: str = "",
) -> dict[str, Any]:
    title = _clip(title, 200).strip() or "untitled"
    BUGS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    bid = f"BUG-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    rec = {
        "id": bid,
        "created_at": now.isoformat(),
        "title": title,
        "what_happened": _clip(what_happened),
        "expected": _clip(expected, 4000),
        "tool": _clip(tool, 80),
        "arguments": _clip(arguments, 4000),
        "log": _clip(log, 20000),
        "url": _clip(url, 500),
        "client": _clip(client, 80),
    }
    path = BUGS_DIR / f"{bid}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = BUGS_DIR / f"{bid}.md"
    md.write_text(
        f"# {bid} — {title}\n\n"
        f"- created: {rec['created_at']}\n"
        f"- tool: {rec['tool'] or '—'}\n"
        f"- url: {rec['url'] or '—'}\n"
        f"- client: {rec['client'] or '—'}\n\n"
        f"## What happened\n\n{rec['what_happened'] or '—'}\n\n"
        f"## Expected\n\n{rec['expected'] or '—'}\n\n"
        f"## Arguments\n\n```\n{rec['arguments'] or '—'}\n```\n\n"
        f"## Log\n\n```\n{rec['log'] or '—'}\n```\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "id": bid,
        "path": str(path),
        "title": title,
    }


def list_bugs(limit: int = 20) -> dict[str, Any]:
    if not BUGS_DIR.is_dir():
        return {"ok": True, "count": 0, "bugs": []}
    files = sorted(BUGS_DIR.glob("BUG-*.json"), reverse=True)
    bugs = []
    for fp in files[: max(1, min(int(limit or 20), 100))]:
        try:
            rec = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        bugs.append(
            {
                "id": rec.get("id"),
                "created_at": rec.get("created_at"),
                "title": rec.get("title"),
                "tool": rec.get("tool"),
                "path": str(fp),
            }
        )
    return {"ok": True, "count": len(bugs), "bugs": bugs}


def get_bug(bug_id: str) -> dict[str, Any]:
    bid = (bug_id or "").strip()
    path = BUGS_DIR / f"{bid}.json"
    if not path.is_file():
        return {"ok": False, "error": f"unknown bug {bid}"}
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["ok"] = True
    rec["path"] = str(path)
    return rec
