"""Nested elicitation/create for write tools.

The tool does not run until the client answers the JSON-RPC request
(or the user clicks Conferma/Annulla on /confirm/{id}).
"""

from __future__ import annotations

import json
import os
import re
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
        self.execution: dict[str, Any] | None = None
        self.status = "pending"


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
    url = confirm_url(eid)
    msg = message_for(tool, args, url=url)
    with _lock:
        _pending[eid] = PendingElicit(tool, args, msg)
    rpc = {
        "jsonrpc": "2.0",
        "id": eid,
        "method": "elicitation/create",
        "params": {
            "mode": "url",
            "message": msg,
            "url": url,
            "elicitationId": eid,
            "requestedSchema": CONFIRM_SCHEMA,
        },
    }
    return eid, rpc


_YES = re.compile(
    r"(?i)\b(sì|si|yes|ok|okay|confermo|conferma|procedi|va bene|go ahead)\b",
)
_NO = re.compile(r"\b(no|annulla|cancel|non confermo|stop)\b", re.I)


def human_confirmed(user_said: str, user_confirmed: Any) -> bool:
    flag = user_confirmed is True or str(user_confirmed).strip().lower() in (
        "true",
        "1",
        "yes",
        "si",
        "sì",
    )
    said = (user_said or "").strip()
    if not flag or not said:
        return False
    if _NO.search(said) and not _YES.search(said):
        return False
    return bool(_YES.search(said))


def chat_confirm_payload(eid: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    ask = message_for(tool, args)
    return {
        "ok": False,
        "error": "needs_user_chat_confirm",
        "executed": False,
        "changed": False,
        "confirm_token": eid,
        "tool": tool,
        "summary": summarize(tool, args),
        "ask_the_user": ask,
        "message": (
            "Grok chat has no MCP Confirm button. Ask the human this question in the Grok UI. "
            "If they reply sì/confermo/yes, call the SAME tool again with "
            "confirm_token, user_confirmed=true, and user_said set to their exact reply. "
            "Never set user_confirmed without that reply."
        ),
    }


def prepare_write(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """'ask' + payload, or 'run' + original args."""
    token = str(args.get("confirm_token") or args.get("confirm_id") or "").strip()
    if token:
        rec = get(token)
        if rec is None or rec.tool != name:
            eid, _ = start(name, args)
            payload = chat_confirm_payload(eid, name, args)
            payload["error"] = "invalid_or_expired_confirm_token"
            return "ask", payload
        if human_confirmed(str(args.get("user_said") or ""), args.get("user_confirmed")):
            rec.status = "accepted"
            rec.result = {
                "action": "accept",
                "content": {"confirm": True, "user_said": args.get("user_said")},
            }
            rec.event.set()
            return "run", rec.args
        return "ask", chat_confirm_payload(token, rec.tool, rec.args)
    eid, _ = start(name, args)
    return "ask", chat_confirm_payload(eid, name, args)


def set_execution(eid: str, payload: dict[str, Any]) -> None:
    with _lock:
        p = _pending.get(str(eid))
        if p is None:
            return
        p.execution = payload
        p.status = "done" if payload.get("ok") else "error"
        p.event.set()


def status_of(eid: str) -> dict[str, Any]:
    rec = get(eid)
    if rec is None:
        return {"ok": False, "error": "unknown or expired confirm_id"}
    if rec.execution is not None:
        return {
            "ok": True,
            "status": rec.status,
            "confirm_id": eid,
            "result": rec.execution,
        }
    if rec.event.is_set() and not accepted(rec.result):
        return {
            "ok": True,
            "status": "declined",
            "confirm_id": eid,
            "executed": False,
            "changed": False,
        }
    return {
        "ok": True,
        "status": rec.status,
        "confirm_id": eid,
        "confirm_url": confirm_url(eid),
        "tool": rec.tool,
        "summary": summarize(rec.tool, rec.args),
        "message": "Waiting for Conferma on confirm_url.",
    }


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
