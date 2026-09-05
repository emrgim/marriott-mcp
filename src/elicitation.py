"""Nested elicitation/create for write tools.

The tool does not run until the client answers the JSON-RPC request
(or the user clicks Conferma/Annulla on /confirm/{id}).
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from typing import Any

PUBLIC_BASE = os.environ.get("MARRIOTT_PUBLIC_BASE", "http://127.0.0.1:8099")
ELICIT_TIMEOUT_S = int(os.environ.get("MARRIOTT_ELICIT_TIMEOUT", "180"))

CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirm": {
            "type": "boolean",
            "description": (
                "true = esegui l'operazione sulla prenotazione Marriott. "
                "false = non toccare nulla."
            ),
        }
    },
    "required": ["confirm"],
}


class PendingElicit:
    def __init__(self, tool: str, args: dict[str, Any], message: str) -> None:
        self.tool = tool
        self.args = args
        self.message = message
        self.event = threading.Event()
        self.result: dict[str, Any] | None = None
        self.created = time.time()


_lock = threading.Lock()
_pending: dict[str, PendingElicit] = {}


def _eid() -> str:
    return "elicit-" + secrets.token_urlsafe(16)


def confirm_url(eid: str) -> str:
    return f"{PUBLIC_BASE}/confirm/{eid}"


def summarize(tool: str, args: dict[str, Any]) -> str:
    bits = [f"tool={tool}"]
    for k in (
        "confirmation_number",
        "destination",
        "property",
        "property_id",
        "checkin",
        "checkout",
        "adults",
        "rooms",
        "rate",
    ):
        if args.get(k) not in (None, ""):
            bits.append(f"{k}={args[k]}")
    return ", ".join(bits)


def message_for(tool: str, args: dict[str, Any], url: str = "") -> str:
    action = {
        "marriott_reservation_create": "CREARE una prenotazione",
        "marriott_reservation_modify": "MODIFICARE una prenotazione",
        "marriott_reservation_cancel": "CANCELLARE una prenotazione",
    }.get(tool, tool)
    extra = f"\nPagina pulsanti: {url}" if url else ""
    return (
        f"Confermi di {action} su Marriott Bonvoy?\n"
        f"{summarize(tool, args)}\n"
        "Nessuna modifica parte senza il pulsante di conferma."
        f"{extra}"
    )


def login_url(eid: str) -> str:
    return f"{PUBLIC_BASE}/login/{eid}"


def start_login(tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    eid = _eid()
    url = login_url(eid)
    msg = (
        "Sign in to Marriott Bonvoy on this page. Do not type the password in chat.\n"
        f"{url}"
    )
    with _lock:
        rec = PendingElicit(tool, args, msg)
        rec.kind = "login"  # type: ignore[attr-defined]
        _pending[eid] = rec
    rpc = {
        "jsonrpc": "2.0",
        "id": eid,
        "method": "elicitation/create",
        "params": {
            "mode": "url",
            "message": msg,
            "url": url,
            "elicitationId": eid,
            "requestedSchema": {
                "type": "object",
                "properties": {
                    "done": {
                        "type": "boolean",
                        "description": "true after you submitted the login page",
                    }
                },
                "required": ["done"],
            },
        },
    }
    return eid, rpc


def start(tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    eid = _eid()
    msg = message_for(tool, args, url=confirm_url(eid))
    with _lock:
        _pending[eid] = PendingElicit(tool, args, msg)
    rpc = {
        "jsonrpc": "2.0",
        "id": eid,
        "method": "elicitation/create",
        "params": {
            "mode": "form",
            "message": msg,
            "requestedSchema": CONFIRM_SCHEMA,
        },
    }
    return eid, rpc


def get(eid: str) -> PendingElicit | None:
    with _lock:
        return _pending.get(str(eid))


def resolve(eid: str, result: dict[str, Any] | None) -> bool:
    with _lock:
        p = _pending.get(str(eid))
        if p is None:
            return False
        p.result = result if isinstance(result, dict) else {"action": "cancel"}
        p.event.set()
        return True


def wait(eid: str, timeout: float | None = None) -> dict[str, Any] | None:
    p = get(eid)
    if p is None:
        return None
    p.event.wait(ELICIT_TIMEOUT_S if timeout is None else timeout)
    with _lock:
        rec = _pending.pop(str(eid), None)
    if rec is None:
        return None
    if not rec.event.is_set():
        return None
    return rec.result


def accepted(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("action") or "").lower() != "accept":
        return False
    content = result.get("content") or {}
    if not isinstance(content, dict):
        return False
    for key in ("confirm", "done"):
        val = content.get(key)
        if val is True:
            return True
        if isinstance(val, str) and val.strip().lower() in ("true", "1", "yes", "si", "sì"):
            return True
    return False


def cancelled_payload(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "changed": False,
        "executed": False,
        "reason": reason,
    }


def pending_to_json(p: PendingElicit) -> dict[str, Any]:
    return {
        "tool": p.tool,
        "args": p.args,
        "message": p.message,
        "age_s": int(time.time() - p.created),
    }


def dump_pending() -> str:
    with _lock:
        return json.dumps({k: pending_to_json(v) for k, v in _pending.items()})
