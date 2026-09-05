#!/usr/bin/env python3
"""stdio + RPC MCP: Marriott Dash. Reads plus elicited writes."""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.browser import (  # noqa: E402
    ACTIVITY,
    HOME,
    TRIPS,
    close_context,
    do_login,
    fetch_stays,
    goto,
    goto_account,
    open_context,
    page,
    snapshot,
)
from src import elicitation  # noqa: E402
from src import reservations  # noqa: E402
from src import skills_ext  # noqa: E402

VERSION = "0.4.0"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Marriott Dash MCP. Tools and skills ship together. "
    "SEP-2640: skills/list then skills/get, files via resources/read under skill://. "
    "Skills: skill://marriott-stays/SKILL.md (reads), "
    "skill://marriott-reservations/SKILL.md (writes + elicitation). "
    "If the client has no skills/list, call marriott_skills_list / marriott_skills_get. "
    "Writes pause on elicitation/create until Confirm/Cancel. "
    "Self-host with Streamable HTTP + OAuth PKCE."
)
WRITE_TOOLS = {
    "marriott_reservation_create",
    "marriott_reservation_modify",
    "marriott_reservation_cancel",
}

RO = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
SESSION = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
WRITE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}

TOOLS = [
    {
        "name": "marriott_status",
        "title": "Session status",
        "description": (
            "Read-only. Returns signed_in, URL, title, member first name. "
            "Example: call with no arguments after connect."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": RO,
    },
    {
        "name": "marriott_open",
        "title": "Open marriott.com",
        "description": "Opens the persistent Chrome session on marriott.com home. Not destructive.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": SESSION,
    },
    {
        "name": "marriott_login",
        "title": "Sign in Bonvoy",
        "description": (
            "Signs into Bonvoy using MARRIOTT_EMAIL/MARRIOTT_PASSWORD from server env, "
            "or email/password arguments. Does not cancel or delete anything. "
            "Do not pass passwords in chat if env is already set."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Bonvoy email or member number"},
                "password": {"type": "string", "description": "Bonvoy password"},
            },
        },
        "annotations": SESSION,
    },
    {
        "name": "marriott_me",
        "title": "Account overview",
        "description": "Read-only My Account / trips dashboard (points, elite, nights).",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": RO,
    },
    {
        "name": "marriott_trips",
        "title": "Upcoming trips",
        "description": "Read-only upcoming reservations. Never cancels.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": RO,
    },
    {
        "name": "marriott_activity",
        "title": "Activity page",
        "description": "Read-only Activity HTML snapshot. Prefer marriott_stays for structured history.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": RO,
    },
    {
        "name": "marriott_stays",
        "title": "Stay history",
        "description": (
            "Read-only GraphQL stay/activity list. months default 240 (20 years). "
            "types=stay|all|bonus. property_contains filters one hotel. "
            "Paginates until exhausted. Does not delete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1200,
                    "description": "Lookback months. Default 240.",
                },
                "types": {
                    "type": "string",
                    "description": "stay (default), all, or bonus",
                },
                "property_contains": {
                    "type": "string",
                    "description": "Substring of hotel name or MARSHA id",
                },
                "page_size": {"type": "integer"},
            },
        },
        "annotations": RO,
    },
    {
        "name": "marriott_goto",
        "title": "Open Marriott URL",
        "description": "Read-only navigation to a marriott.com URL. Rejects non-marriott hosts. No writes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "https://www.marriott.com/..."}
            },
            "required": ["url"],
        },
        "annotations": RO,
    },
    {
        "name": "marriott_reservation_create",
        "title": "Create reservation",
        "description": (
            "Create a Marriott reservation. ALWAYS pauses on elicitation/create "
            "(Confirm/Cancel). Executes only after accept+confirm=true. "
            "Aborts if checkout asks for a card. destination, checkin, checkout required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "checkin": {"type": "string", "description": "MM/DD/YYYY or YYYY-MM-DD"},
                "checkout": {"type": "string"},
                "property": {"type": "string"},
                "property_id": {"type": "string"},
                "adults": {"type": "integer"},
                "rooms": {"type": "integer"},
                "rate": {"type": "string"},
            },
            "required": ["destination", "checkin", "checkout"],
        },
        "annotations": WRITE,
    },
    {
        "name": "marriott_reservation_modify",
        "title": "Modify reservation",
        "description": (
            "Modify dates on an existing reservation. Pauses on elicitation/create. "
            "Runs only after the confirm button."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirmation_number": {"type": "string"},
                "checkin": {"type": "string"},
                "checkout": {"type": "string"},
            },
            "required": ["confirmation_number"],
        },
        "annotations": WRITE,
    },
    {
        "name": "marriott_reservation_cancel",
        "title": "Cancel reservation",
        "description": (
            "Cancel a reservation. Sends elicitation/create and waits for the "
            "Confirm or Cancel button. Nothing is cancelled on decline/timeout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirmation_number": {"type": "string"},
            },
            "required": ["confirmation_number"],
        },
        "annotations": WRITE,
    },
    {
        "name": "marriott_skills_list",
        "title": "List skills (fallback)",
        "description": (
            "Fallback when the client cannot call skills/list (SEP-2640). "
            "Returns the same catalog: uri, frontmatter, resources with sha256."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": RO,
    },
    {
        "name": "marriott_skills_get",
        "title": "Get skill (fallback)",
        "description": (
            "Fallback when the client cannot call skills/get. "
            "Pass uri like skill://marriott-stays/SKILL.md. "
            "Then resources/read or this result's files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": "skill://<name>/SKILL.md",
                }
            },
            "required": ["uri"],
        },
        "annotations": RO,
    },
]

PROMPTS = [
    {
        "name": "stays_overview",
        "title": "Stay overview",
        "description": "List historical stays and summarize nights by property.",
        "arguments": [
            {
                "name": "property",
                "description": "Optional hotel name substring",
                "required": False,
            }
        ],
    },
    {
        "name": "account_status",
        "title": "Account status",
        "description": "Read elite status, points, and nights. Read-only.",
        "arguments": [],
    },
]

RESOURCES = [
    {
        "uri": "marriott://docs/safety",
        "name": "Safety policy",
        "mimeType": "text/plain",
        "description": "Write policy: elicitation/create required.",
    }
]

DESTRUCTIVE_TOKENS = ("cancel", "delete", "remove", "drop", "void", "erase")


def log(msg: str) -> None:
    print(f"[marriott-mcp] {msg}", file=sys.stderr, flush=True)


def slim(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    excerpt = out.get("body_excerpt") or ""
    out["body_excerpt"] = excerpt[:2500]
    return out


def _refuse_destructive(name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "changed": False,
        "elicitation": {
            "message": (
                f"Refused `{name}`. This MCP never cancels, deletes, or modifies "
                "reservations or loyalty data. Confirm is not enough — the action is not implemented."
            ),
            "requestedSchema": {
                "type": "object",
                "properties": {
                    "ack": {
                        "type": "boolean",
                        "description": "User acknowledges the action will not run",
                    }
                },
                "required": ["ack"],
            },
        },
    }


def dispatch(name: str, args: dict[str, Any]) -> Any:
    if name in WRITE_TOOLS:
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "write tools run only after elicitation/create accept",
        }
    lname = name.lower()
    if any(tok in lname for tok in DESTRUCTIVE_TOKENS):
        return _refuse_destructive(name)
    if name == "marriott_open":
        open_context()
        return slim(goto(HOME, name="mcp-open"))
    if name == "marriott_status":
        open_context()
        p = page()
        if "marriott.com" not in (p.url or ""):
            return slim(goto(HOME, name="mcp-status"))
        return slim(snapshot(p, "mcp-status"))
    if name == "marriott_login":
        return slim(do_login(args.get("email"), args.get("password")))
    if name == "marriott_me":
        return slim(goto_account(TRIPS, name="mcp-me"))
    if name == "marriott_trips":
        return slim(goto_account(TRIPS, name="mcp-trips"))
    if name == "marriott_activity":
        return slim(goto_account(ACTIVITY, name="mcp-activity"))
    if name == "marriott_stays":
        months = int(args.get("months") or 240)
        types = str(args.get("types") or "stay")
        page_size = int(args.get("page_size") or 50)
        return fetch_stays(
            months=months,
            types=types,
            page_size=page_size,
            property_contains=args.get("property_contains"),
        )
    if name == "marriott_goto":
        url = args.get("url") or ""
        if "marriott.com" not in url:
            return {"error": "Solo URL marriott.com", "changed": False}
        return slim(goto(url, name="mcp-goto"))
    if name == "marriott_skills_list":
        return {
            "resultType": "complete",
            "skills": skills_ext.skill_entries(),
        }
    if name == "marriott_skills_get":
        uri = str(args.get("uri") or "")
        entry = skills_ext.get_entry(uri)
        if entry is None:
            return {"error": f"unknown skill {uri}", "ok": False}
        return {"resultType": "complete", "skill": entry}
    return {"error": f"unknown tool {name}"}


def _tool_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {"value": payload}
    text = json.dumps(payload, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _pick_protocol(params: dict) -> str:
    wanted = ""
    if isinstance(params, dict):
        wanted = str(params.get("protocolVersion") or "")
    if wanted in PROTOCOLS:
        return wanted
    return PROTOCOLS[0]


def handle_rpc(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": _pick_protocol(params if isinstance(params, dict) else {}),
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                    "logging": {},
                    "elicitation": {},
                    "extensions": {
                        "io.modelcontextprotocol/skills": {"directoryRead": True},
                    },
                },
                "serverInfo": {
                    "name": "marriott-dash",
                    "title": "Marriott Dash",
                    "version": VERSION,
                    "websiteUrl": "https://github.com/emrgim/marriott-mcp",
                },
                "instructions": INSTRUCTIONS,
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "logging/setLevel":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (params or {}).get("name") or ""
        args = (params or {}).get("arguments") or {}
        if name in WRITE_TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "_marriott_elicit": True,
                "result": None,
            }
        if any(tok in name.lower() for tok in DESTRUCTIVE_TOKENS):
            body = _refuse_destructive(name)
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": _tool_result(body, is_error=True),
            }
        try:
            result = dispatch(name, args)
            err = isinstance(result, dict) and bool(result.get("error") or result.get("ok") is False)
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": _tool_result(result, is_error=err),
            }
        except Exception as exc:  # noqa: BLE001
            log(traceback.format_exc())
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": _tool_result({"error": str(exc), "changed": False}, is_error=True),
            }
    if method == "skills/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"resultType": "complete", "skills": skills_ext.skill_entries()},
        }
    if method == "skills/get":
        uri = (params or {}).get("uri") or ""
        entry = skills_ext.get_entry(str(uri))
        if entry is None:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": f"Unknown skill {uri}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"resultType": "complete", "skill": entry},
        }
    if method == "resources/directory/read":
        uri = (params or {}).get("uri") or ""
        kids = skills_ext.list_directory(str(uri))
        if kids is None:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": f"Not a directory resource {uri}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"resultType": "complete", "resources": kids},
        }
    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"resources": RESOURCES + skills_ext.all_file_resources()},
        }
    if method == "resources/templates/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resourceTemplates": []}}
    if method == "resources/read":
        uri = (params or {}).get("uri") or ""
        if uri == "marriott://docs/safety":
            text = (
                "Marriott Dash MCP writes require elicitation/create.\n"
                "- Create/modify/cancel pause until Accept or Cancel.\n"
                "- Decline, cancel, or timeout → changed=false, nothing executed.\n"
                "- Payment cards are never collected via elicitation.\n"
            )
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "contents": [
                        {"uri": uri, "mimeType": "text/plain", "text": text}
                    ]
                },
            }
        skill_file = skills_ext.read_uri(str(uri))
        if skill_file is None:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": f"Unknown resource {uri}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"contents": [skill_file]},
        }
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"prompts": PROMPTS}}
    if method == "prompts/get":
        name = (params or {}).get("name")
        prop = ((params or {}).get("arguments") or {}).get("property") or ""
        if name == "stays_overview":
            text = (
                "Call marriott_stays with months=240"
                + (f" and property_contains={prop!r}" if prop else "")
                + ". Summarize nights by property. Do not cancel anything."
            )
        elif name == "account_status":
            text = "Call marriott_me then marriott_status. Report elite, points, nights. Read-only."
        else:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32602, "message": f"Unknown prompt {name}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "description": name,
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": text}}
                ],
            },
        }
    if rid is not None:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": str(method)},
        }
    return None


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


_paused: dict[str, dict[str, Any]] = {}


def finish_write(name: str, args: dict[str, Any], elicit_result: Any) -> dict[str, Any]:
    if not elicitation.accepted(elicit_result if isinstance(elicit_result, dict) else None):
        return _tool_result(
            elicitation.cancelled_payload("declined, cancelled, timeout, or confirm=false"),
            is_error=False,
        )
    try:
        payload = reservations.execute(name, args)
        err = bool(payload.get("error")) or payload.get("ok") is False
        return _tool_result(payload, is_error=err)
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        return _tool_result(
            {"error": str(exc), "changed": False, "executed": False},
            is_error=True,
        )


def handle(req: dict) -> None:
    if isinstance(req, dict) and not req.get("method") and "id" in req:
        eid = str(req.get("id"))
        paused = _paused.pop(eid, None)
        elicitation.resolve(
            eid,
            req.get("result") if isinstance(req.get("result"), dict) else {"action": "cancel"},
        )
        if paused is None:
            return
        send(
            {
                "jsonrpc": "2.0",
                "id": paused["id"],
                "result": finish_write(paused["name"], paused["args"], req.get("result")),
            }
        )
        return
    if req.get("method") == "tools/call":
        params = req.get("params") or {}
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        if name in WRITE_TOOLS:
            eid, elicit_rpc = elicitation.start(name, args)
            _paused[eid] = {"id": req.get("id"), "name": name, "args": args}
            send(elicit_rpc)
            return
    resp = handle_rpc(req)
    if resp is not None:
        resp.pop("_marriott_elicit", None)
        send(resp)


def main() -> None:
    log("stdio ready")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(req)
    close_context()


if __name__ == "__main__":
    main()
