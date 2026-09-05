"""Bonvoy credentials: env + .session/bonvoy.json. Never log the password."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREDS_FILE = ROOT / ".session" / "bonvoy.json"


def load_creds() -> None:
    if not CREDS_FILE.is_file():
        return
    try:
        data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    email = str(data.get("MARRIOTT_EMAIL") or "").strip()
    password = str(data.get("MARRIOTT_PASSWORD") or "").strip()
    if email:
        os.environ.setdefault("MARRIOTT_EMAIL", email)
    if password:
        os.environ.setdefault("MARRIOTT_PASSWORD", password)


def save_creds(email: str, password: str) -> None:
    email = (email or "").strip()
    password = (password or "").strip()
    os.environ["MARRIOTT_EMAIL"] = email
    os.environ["MARRIOTT_PASSWORD"] = password
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"MARRIOTT_EMAIL": email, "MARRIOTT_PASSWORD": password})
    tmp = CREDS_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, CREDS_FILE)
    os.chmod(CREDS_FILE, 0o600)


def has_creds() -> bool:
    load_creds()
    return bool(
        os.environ.get("MARRIOTT_EMAIL", "").strip()
        and os.environ.get("MARRIOTT_PASSWORD", "").strip()
    )
