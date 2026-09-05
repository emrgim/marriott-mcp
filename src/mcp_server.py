#!/usr/bin/env python3
"""stdio + RPC MCP: Marriott MCP. Reads plus elicited writes."""

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
    fetch_activity,
    fetch_stays,
    goto,
    goto_account,
    open_context,
    page,
    snapshot,
)
from src import elicitation  # noqa: E402
from src import reservations  # noqa: E402
from src import search as marriott_search  # noqa: E402
from src import interact as marriott_interact  # noqa: E402
from src import skills_ext  # noqa: E402
from src.creds import has_creds  # noqa: E402
from src import bugs as marriott_bugs  # noqa: E402
from src import update_check  # noqa: E402

VERSION = "0.6.3"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Marriott MCP. Never web-search Marriott hotels, URLs, or rates — use tools. "
    "Session: marriott_status / marriott_login (env credentials). "
    "Find hotels: marriott_search then marriott_page (rooms/prices/confirmation). "
    "Interact: marriott_click, marriott_fill, marriott_dismiss. "
    "Book: marriott_book first lists rooms (A, B, C) and ask_the_user. Show that list in Grok chat. "
    "After the human picks a letter, call again with quote_id, option_id or user_said. "
    "If they have not said confermo, ask_the_user is the price question. Only then checkout. "
    "Structured errors: sold_out, payment_required, login_expired, akamai_denied. "
    "Never solve captchas. Never fill cards. "
    "Dates: YYYY-MM-DD or MM/DD/YYYY; the server converts to Marriott MM/DD/YYYY. "
    "Book only via marriott_reservation_create after search; elicitation/create must confirm. "
    "If Bonvoy is not signed in, the server sends a login URL (elicitation mode=url); "
    "never put the password in chat. "
    "If something fails, call marriott_report_bug with title, what_happened, the tool name, arguments, and the raw log. "
    "Skills: skill://marriott-stays/SKILL.md and skill://marriott-reservations/SKILL.md."
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
        "title": "Account activity",
        "description": (
            "Structured Bonvoy activity via GraphQL (not the 3-month HTML filter). "
            "months default 240. types=all|stay|bonus. posted, type, description, property, points."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "months": {"type": "integer", "description": "Lookback months, default 240"},
                "types": {"type": "string", "description": "all | stay | bonus"},
                "page_size": {"type": "integer"},
            },
        },
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
        "name": "marriott_search",
        "title": "Search hotels",
        "description": (
            "Search marriott.com for properties. REQUIRED: destination, checkin, checkout. "
            "Returns session.signed_in, dates actually applied on the site (MM/DD/YYYY), "
            "and properties[{name, property_id, url}]. Do NOT web-search hotels. "
            "Uses the persistent Bonvoy Chrome session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "City or hotel name"},
                "checkin": {"type": "string", "description": "YYYY-MM-DD or MM/DD/YYYY"},
                "checkout": {"type": "string"},
                "adults": {"type": "integer", "default": 1},
                "rooms": {"type": "integer", "default": 1},
                "property_id": {
                    "type": "string",
                    "description": "Optional MARSHA code (5 letters) or hotel name",
                },
            },
            "required": ["destination", "checkin", "checkout"],
        },
        "annotations": RO,
    },
    {
        "name": "marriott_availability",
        "title": "Property availability",
        "description": (
            "Rates and property URL for one hotel. REQUIRED: property_id, checkin, checkout. "
            "Returns session, dates applied, property_url, rate_lines. "
            "Do not invent Marriott URLs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "property_id": {
                    "type": "string",
                    "description": "MARSHA code from marriott_search (e.g. DXBWH)",
                },
                "checkin": {"type": "string"},
                "checkout": {"type": "string"},
                "adults": {"type": "integer"},
                "rooms": {"type": "integer"},
                "destination": {"type": "string"},
            },
            "required": ["property_id", "checkin", "checkout"],
        },
        "annotations": RO,
    },
    {
        "name": "marriott_page",
        "title": "Read page structured",
        "description": (
            "Extract the current marriott.com page: rooms, rates, buttons, "
            "confirmation_number, overlays. Structured errors: sold_out, "
            "payment_required, login_expired, akamai_denied. Does not click."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": RO,
    },
    {
        "name": "marriott_dismiss",
        "title": "Dismiss overlays",
        "description": "Click cookie/consent buttons (Accept All). Does not solve captchas.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": SESSION,
    },
    {
        "name": "marriott_click",
        "title": "Click control",
        "description": "Click a button or link by visible name (Select, View rates, Continue). Not captcha.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
        "annotations": SESSION,
    },
    {
        "name": "marriott_fill",
        "title": "Fill a field",
        "description": (
            "Fill a guest form field by label/placeholder. Refuses password and card fields."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["field", "value"],
        },
        "annotations": SESSION,
    },
    {
        "name": "marriott_reservation_create",
        "title": "Create reservation",
        "description": (
            "Create a Marriott reservation. First call returns ask_the_user + confirm_token "
            "(no hang). Grok must ask that phrase in chat. After the human replies sì/confermo, "
            "call again with confirm_token, user_confirmed=true, user_said=<exact reply>. "
            "Aborts if checkout asks for a card."
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
                "confirm_token": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
                "user_said": {
                    "type": "string",
                    "description": "Exact human reply in Grok chat",
                },
            },
            "required": ["destination", "checkin", "checkout"],
        },
        "annotations": WRITE,
    },
    {
        "name": "marriott_reservation_modify",
        "title": "Modify reservation",
        "description": (
            "Modify dates. First call returns ask_the_user. After the human replies in Grok, "
            "call again with confirm_token, user_confirmed=true, user_said."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirmation_number": {"type": "string"},
                "checkin": {"type": "string"},
                "checkout": {"type": "string"},
                "confirm_token": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
                "user_said": {"type": "string"},
            },
            "required": ["confirmation_number"],
        },
        "annotations": WRITE,
    },
    {
        "name": "marriott_reservation_cancel",
        "title": "Cancel reservation",
        "description": (
            "Cancel a reservation. First call returns ask_the_user. After the human replies in Grok, "
            "call again with confirm_token, user_confirmed=true, user_said. Nothing runs without that."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirmation_number": {"type": "string"},
                "confirm_token": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
                "user_said": {"type": "string"},
            },
            "required": ["confirmation_number"],
        },
        "annotations": WRITE,
    },
    {
        "name": "marriott_book",
        "title": "Book a stay",
        "description": (
            "First call: search and return options A/B/C + ask_the_user. Show the list in Grok chat. "
            "Do not book yet. After the human picks a letter, call again with quote_id and user_said. "
            "If they did not say confermo, ask the price question. Checkout only after that."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "checkin": {"type": "string"},
                "checkout": {"type": "string"},
                "property": {"type": "string"},
                "property_id": {"type": "string"},
                "adults": {"type": "integer"},
                "rooms": {"type": "integer"},
                "room_pref": {"type": "string", "description": "single, king, twin"},
                "pay_later": {"type": "boolean", "default": True},
                "quote_id": {"type": "string"},
                "option_id": {"type": "string", "description": "A, B, C from the quote list"},
                "confirm_token": {"type": "string"},
                "user_confirmed": {"type": "boolean"},
                "user_said": {"type": "string"},
            },
            "required": ["destination", "checkin", "checkout"],
        },
        "annotations": SESSION,
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
    {
        "name": "marriott_report_bug",
        "title": "Report a bug",
        "description": (
            "File a bug on the MCP host. Include title, what happened, expected, "
            "tool name, arguments, and the raw log/traceback. Passwords and API keys "
            "are stripped. Does not need Bonvoy login."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "what_happened": {"type": "string"},
                "expected": {"type": "string"},
                "tool": {"type": "string", "description": "MCP tool that failed"},
                "arguments": {"type": "string", "description": "Tool arguments as JSON text"},
                "log": {"type": "string", "description": "Traceback, tool result, or console log"},
                "url": {"type": "string"},
                "client": {"type": "string", "description": "e.g. grok, claude, cursor"},
            },
            "required": ["title", "what_happened"],
        },
        "annotations": RO,
    },
    {
        "name": "marriott_bugs_list",
        "title": "List filed bugs",
        "description": "List bugs saved on this server. No Bonvoy login.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
        "annotations": RO,
    },
    {
        "name": "marriott_bugs_get",
        "title": "Get a filed bug",
        "description": "Read one bug by id (BUG-...). Includes log. No Bonvoy login.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
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
            out = slim(goto(HOME, name="mcp-status"))
        else:
            out = slim(snapshot(p, "mcp-status"))
        info = update_check.peek()
        if info:
            out["update"] = info
        return out
    if name == "marriott_login":
        return slim(do_login(args.get("email"), args.get("password")))
    if name == "marriott_me":
        return slim(goto_account(TRIPS, name="mcp-me"))
    if name == "marriott_trips":
        return slim(goto_account(TRIPS, name="mcp-trips"))
    if name == "marriott_activity":
        months = int(args.get("months") or 240)
        types = str(args.get("types") or "all")
        page_size = int(args.get("page_size") or 50)
        return fetch_activity(months=months, types=types, page_size=page_size)
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
    if name == "marriott_search":
        return marriott_search.search_properties(
            destination=str(args.get("destination") or ""),
            checkin=str(args.get("checkin") or ""),
            checkout=str(args.get("checkout") or ""),
            rooms=int(args.get("rooms") or 1),
            adults=int(args.get("adults") or 1),
            property_id=args.get("property_id"),
        )
    if name == "marriott_availability":
        return marriott_search.property_availability(
            property_id=str(args.get("property_id") or ""),
            checkin=str(args.get("checkin") or ""),
            checkout=str(args.get("checkout") or ""),
            rooms=int(args.get("rooms") or 1),
            adults=int(args.get("adults") or 1),
            destination=args.get("destination"),
        )
    if name == "marriott_book":
        pl = args.get("pay_later")
        pay_later = True if pl is None else bool(pl)
        if isinstance(pl, str):
            pay_later = pl.strip().lower() not in ("false", "0", "no")
        return marriott_interact.book(
            destination=str(args.get("destination") or args.get("property") or ""),
            checkin=str(args.get("checkin") or ""),
            checkout=str(args.get("checkout") or ""),
            property=args.get("property"),
            property_id=args.get("property_id"),
            adults=int(args.get("adults") or 1),
            rooms=int(args.get("rooms") or 1),
            room_pref=str(args.get("room_pref") or "single"),
            pay_later=pay_later,
            option_id=args.get("option_id"),
            quote_id=args.get("quote_id"),
            user_said=args.get("user_said"),
            user_confirmed=args.get("user_confirmed"),
        )
    if name == "marriott_page":
        return marriott_interact.extract_page()
    if name == "marriott_dismiss":
        return marriott_interact.dismiss_overlays()
    if name == "marriott_click":
        return marriott_interact.click(str(args.get("target") or ""))
    if name == "marriott_fill":
        return marriott_interact.fill(str(args.get("field") or ""), str(args.get("value") or ""))
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
    if name == "marriott_report_bug":
        return marriott_bugs.save_bug(
            title=str(args.get("title") or ""),
            what_happened=str(args.get("what_happened") or ""),
            expected=str(args.get("expected") or ""),
            tool=str(args.get("tool") or ""),
            arguments=args.get("arguments"),
            log=str(args.get("log") or ""),
            url=str(args.get("url") or ""),
            client=str(args.get("client") or ""),
        )
    if name == "marriott_bugs_list":
        return marriott_bugs.list_bugs(limit=int(args.get("limit") or 20))
    if name == "marriott_bugs_get":
        return marriott_bugs.get_bug(str(args.get("id") or ""))
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
                    "title": "Marriott MCP",
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
                "Marriott MCP writes require elicitation/create.\n"
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
        if paused.get("kind") == "login":
            if not elicitation.accepted(
                req.get("result") if isinstance(req.get("result"), dict) else None
            ):
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": paused["id"],
                        "result": _tool_result(
                            {"ok": False, "signed_in": False, "error": "Bonvoy login cancelled"},
                            is_error=True,
                        ),
                    }
                )
                return
            if paused["name"] in WRITE_TOOLS:
                eid2, elicit_rpc = elicitation.start(paused["name"], paused["args"])
                _paused[eid2] = {
                    "id": paused["id"],
                    "name": paused["name"],
                    "args": paused["args"],
                }
                send(elicit_rpc)
                return
            inner = handle_rpc(
                {
                    "jsonrpc": "2.0",
                    "id": paused["id"],
                    "method": "tools/call",
                    "params": {"name": paused["name"], "arguments": paused["args"]},
                }
            )
            if inner is not None:
                inner.pop("_marriott_elicit", None)
                send(inner)
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
        if (
            name.startswith("marriott_")
            and name
            not in (
                "marriott_skills_list",
                "marriott_skills_get",
                "marriott_report_bug",
                "marriott_bugs_list",
                "marriott_bugs_get",
            )
            and not has_creds()
        ):
            eid, elicit_rpc = elicitation.start_login(name, args)
            _paused[eid] = {"id": req.get("id"), "name": name, "args": args, "kind": "login"}
            send(elicit_rpc)
            return
        if name in WRITE_TOOLS:
            kind, payload = elicitation.prepare_write(name, args)
            if kind != "run":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "result": _tool_result(payload, is_error=False),
                    }
                )
                return
            send(
                {
                    "jsonrpc": "2.0",
                    "id": req.get("id"),
                    "result": finish_write(
                        name,
                        payload,
                        {"action": "accept", "content": {"confirm": True}},
                    ),
                }
            )
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
