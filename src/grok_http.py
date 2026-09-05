#!/usr/bin/env python3
"""Marriott MCP for Grok: Streamable HTTP + OAuth 2.1 PKCE."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# BUG-011: Playwright sync cannot run on uvicorn's asyncio loop.
# One worker thread so the sync Playwright driver stays on a single thread.
_PW_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="marriott-pw")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from src.mcp_server import WRITE_TOOLS, finish_write, handle_rpc, _tool_result
from src import elicitation
from src.browser import do_login
from src.creds import has_creds, save_creds

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("marriott-grok-mcp")

STORE_FILE = str(ROOT / ".session" / "grok-oauth.json")
PUBLIC_BASE = os.environ.get("MARRIOTT_PUBLIC_BASE", "http://127.0.0.1:8099")
CLIENT_ID = "grok"
SCOPE = "mcp:tools"
HOST = os.environ.get("MARRIOTT_GROK_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MARRIOTT_GROK_MCP_PORT", "8099"))
GROK_TOKEN = os.environ.get("GROK_MCP_TOKEN", "").strip()


def _load_store() -> dict:
    try:
        with open(STORE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"codes": {}, "tokens": {}, "refresh": {}}


def _save_store(store: dict) -> None:
    Path(STORE_FILE).parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f)
    os.replace(tmp, STORE_FILE)
    os.chmod(STORE_FILE, 0o600)


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_s256(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


ALLOWED_REDIRECTS = {
    "https://www.cursor.com/agents/mcp/oauth/callback",
    "http://localhost:8787/callback",
    "http://127.0.0.1:8787/callback",
    "http://[::1]:8787/callback",
    "cursor://anysphere.cursor-mcp/oauth/callback",
}


def _redirect_ok(uri: str) -> bool:
    raw = (uri or "").strip()
    if not raw:
        return False
    norm = raw.rstrip("/")
    if norm.lower() in {u.lower() for u in ALLOWED_REDIRECTS}:
        return True
    if norm.lower().startswith("cursor://anysphere.cursor-mcp/oauth/callback"):
        return True
    try:
        p = urlparse(raw)
    except Exception:
        return False
    host = (p.hostname or "").lower()
    if p.scheme == "cursor":
        return "cursor-mcp" in (p.netloc or "").lower()
    if p.scheme == "https" and host:
        return True
    if p.scheme == "http" and host in ("localhost", "127.0.0.1", "::1"):
        return True
    return False


def _as_metadata() -> dict:
    return {
        "issuer": PUBLIC_BASE,
        "authorization_endpoint": f"{PUBLIC_BASE}/oauth/authorize",
        "token_endpoint": f"{PUBLIC_BASE}/oauth/token",
        "registration_endpoint": f"{PUBLIC_BASE}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE, "openid"],
        "service_documentation": PUBLIC_BASE,
    }


def _prm() -> dict:
    return {
        "resource": PUBLIC_BASE,
        "authorization_servers": [PUBLIC_BASE],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
    }


def _cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, Accept, MCP-Session-Id, MCP-Protocol-Version"
    )
    resp.headers["Access-Control-Expose-Headers"] = "Mcp-Session-Id, MCP-Protocol-Version"
    resp.headers["MCP-Protocol-Version"] = "2025-03-26"
    return resp


def _valid_access(token: str) -> bool:
    if not token:
        return False
    if GROK_TOKEN and hmac.compare_digest(token, GROK_TOKEN):
        return True
    store = _load_store()
    rec = store.get("tokens", {}).get(token)
    if not rec:
        return False
    if rec.get("exp", 0) < time.time():
        return False
    return True


async def handle_options(request: Request) -> Response:
    return _cors(Response(status_code=204))


async def well_known_as(request: Request) -> Response:
    return _cors(JSONResponse(_as_metadata()))


async def well_known_prm(request: Request) -> Response:
    return _cors(JSONResponse(_prm()))


async def oauth_register(request: Request) -> Response:
    if request.method == "OPTIONS":
        return await handle_options(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    redirects = body.get("redirect_uris") or []
    return _cors(
        JSONResponse(
            {
                "client_id": CLIENT_ID,
                "client_name": body.get("client_name", "Grok"),
                "redirect_uris": redirects,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "client_id_issued_at": int(time.time()),
            },
            status_code=201,
        )
    )


def _incomplete_auth_page() -> str:
    return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marriott MCP</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}
.card{background:#1c1c1c;padding:28px;border-radius:16px;max-width:440px;width:90%;line-height:1.45}
code{color:#9cf}
</style></head>
<body><div class="card">
<h1>Marriott MCP</h1>
<p>Grok chiede accesso all'account Bonvoy.</p>
<p style="color:#c00">Authorize URL incompleta: manca <code>redirect_uri</code> (bug della connect card, non allowlist).</p>
<p>Grok Bot sta aprendo <code>/oauth/authorize</code> senza query OAuth 2.1 / PKCE. Non si può completare il consenso senza quei parametri.</p>
<p>Per Grok Bot usa un connector con header <code>Authorization: Bearer</code> e il token del host (<code>GROK_MCP_TOKEN</code>). Credenziali Bonvoy restano sul server, non in chat.</p>
</div></body></html>"""


def _auth_page(error: str = "") -> str:
    err = f"<p style='color:#c00'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autorizza Marriott</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#1c1c1c;padding:28px;border-radius:16px;max-width:420px;width:90%}}
button{{background:#fff;color:#111;border:0;padding:12px 18px;border-radius:10px;font-weight:600;cursor:pointer;width:100%}}
</style></head>
<body><div class="card">
<h1>Marriott MCP</h1>
<p>Grok chiede accesso all'account Bonvoy.</p>
{err}
</div></body></html>"""


async def oauth_authorize(request: Request) -> Response:
    if request.method == "OPTIONS":
        return await handle_options(request)
    q = dict(request.query_params)
    client_id = q.get("client_id", "")
    redirect_uri = q.get("redirect_uri", "")
    state = q.get("state", "")
    challenge = q.get("code_challenge", "")
    method = q.get("code_challenge_method", "S256")
    scope = q.get("scope", SCOPE)
    response_type = q.get("response_type", "code")

    if request.method == "GET":
        log.info(
            "OAuth authorize GET qs=%r client_id=%r redirect_uri=%r challenge=%s method=%s state=%r scope=%r",
            str(request.url.query or ""),
            client_id,
            redirect_uri,
            bool(challenge),
            method,
            state,
            scope,
        )
        if not redirect_uri:
            log.warning("OAuth authorize missing redirect_uri qs=%r", str(request.url.query or ""))
            return HTMLResponse(_incomplete_auth_page(), 400)
        if response_type != "code":
            return HTMLResponse(_auth_page("response_type non supportato"), 400)
        if client_id not in (CLIENT_ID, "grok-marriott", "cursor", ""):
            log.warning("OAuth unknown client_id=%s", client_id)
        if not _redirect_ok(redirect_uri):
            log.warning("OAuth rejected redirect_uri=%r", redirect_uri)
            return HTMLResponse(_auth_page("redirect_uri non consentito"), 400)
        if client_id and client_id not in (CLIENT_ID, "grok-marriott", "cursor"):
            # DCR / Cursor may send their own public client id; PKCE still required.
            pass
        if not challenge or method.upper() != "S256":
            return HTMLResponse(_auth_page("Serve PKCE S256"), 400)
        csrf = secrets.token_urlsafe(24)
        store = _load_store()
        store.setdefault("pending", {})[csrf] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "scope": scope,
            "exp": time.time() + 600,
        }
        _save_store(store)
        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autorizza Marriott</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#1c1c1c;padding:28px;border-radius:16px;max-width:420px;width:90%}}
button{{background:#fff;color:#111;border:0;padding:12px 18px;border-radius:10px;font-weight:600;cursor:pointer;width:100%}}
</style></head>
<body><div class="card">
<h1>Marriott MCP</h1>
<p>An MCP client is requesting access to this Bonvoy session on <b>{urlparse(PUBLIC_BASE).hostname or PUBLIC_BASE}</b>.</p>
<form method="post" action="/oauth/authorize">
<input type="hidden" name="csrf" value="{csrf}">
<button type="submit">Autorizza</button>
</form>
</div></body></html>"""
        return HTMLResponse(html)

    form = await request.form()
    csrf = str(form.get("csrf") or "")
    store = _load_store()
    pending = store.get("pending", {}).pop(csrf, None)
    _save_store(store)
    if not pending or pending.get("exp", 0) < time.time():
        return HTMLResponse(_auth_page("Sessione scaduta, riprova da Grok."), 400)
    code = secrets.token_urlsafe(32)
    store = _load_store()
    store.setdefault("codes", {})[code] = {
        "client_id": pending["client_id"],
        "redirect_uri": pending["redirect_uri"],
        "code_challenge": pending["code_challenge"],
        "scope": pending.get("scope", SCOPE),
        "exp": time.time() + 300,
    }
    _save_store(store)
    params = {"code": code}
    if pending.get("state"):
        params["state"] = pending["state"]
    dest = pending["redirect_uri"]
    sep = "&" if urlparse(dest).query else "?"
    log.info("OAuth authorize OK redirect=%s", dest)
    return RedirectResponse(dest + sep + urllib.parse.urlencode(params), status_code=302)


async def oauth_token(request: Request) -> Response:
    if request.method == "OPTIONS":
        return await handle_options(request)
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        data = await request.json()
    else:
        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
    grant = data.get("grant_type")
    store = _load_store()
    if grant == "authorization_code":
        code = data.get("code", "")
        verifier = data.get("code_verifier", "")
        redirect_uri = data.get("redirect_uri", "")
        rec = store.get("codes", {}).pop(code, None)
        _save_store(store)
        if not rec or rec.get("exp", 0) < time.time():
            return _cors(JSONResponse({"error": "invalid_grant"}, status_code=400))
        if redirect_uri and redirect_uri != rec["redirect_uri"]:
            return _cors(
                JSONResponse(
                    {"error": "invalid_grant", "error_description": "redirect_uri"},
                    status_code=400,
                )
            )
        if _pkce_s256(verifier) != rec["code_challenge"]:
            return _cors(
                JSONResponse(
                    {"error": "invalid_grant", "error_description": "pkce"},
                    status_code=400,
                )
            )
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = time.time()
        store = _load_store()
        store.setdefault("tokens", {})[access] = {
            "exp": now + 3600,
            "scope": rec.get("scope", SCOPE),
        }
        store.setdefault("refresh", {})[refresh] = {
            "exp": now + 30 * 86400,
            "scope": rec.get("scope", SCOPE),
        }
        _save_store(store)
        log.info("OAuth token issued")
        return _cors(
            JSONResponse(
                {
                    "access_token": access,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": refresh,
                    "scope": rec.get("scope", SCOPE),
                }
            )
        )
    if grant == "refresh_token":
        old = data.get("refresh_token", "")
        rec = store.get("refresh", {}).pop(old, None)
        _save_store(store)
        if not rec or rec.get("exp", 0) < time.time():
            return _cors(JSONResponse({"error": "invalid_grant"}, status_code=400))
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = time.time()
        store = _load_store()
        store.setdefault("tokens", {})[access] = {
            "exp": now + 3600,
            "scope": rec.get("scope", SCOPE),
        }
        store.setdefault("refresh", {})[refresh] = {
            "exp": rec["exp"],
            "scope": rec.get("scope", SCOPE),
        }
        _save_store(store)
        return _cors(
            JSONResponse(
                {
                    "access_token": access,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": refresh,
                    "scope": rec.get("scope", SCOPE),
                }
            )
        )
    return _cors(JSONResponse({"error": "unsupported_grant_type"}, status_code=400))


def _unauth() -> Response:
    resp = JSONResponse({"error": "unauthorized"}, status_code=401)
    resp.headers["WWW-Authenticate"] = (
        f'Bearer realm="marriott", resource_metadata="{PUBLIC_BASE}/.well-known/oauth-protected-resource"'
    )
    return _cors(resp)


def _rpc_response(msg: Any, accept: str) -> Response:
    payload = json.dumps(msg, ensure_ascii=False)
    if "text/event-stream" in accept:
        body = f"event: message\ndata: {payload}\n\n"
        return _cors(Response(content=body, media_type="text/event-stream"))
    return _cors(Response(content=payload, media_type="application/json"))


def _is_rpc_response(msg: dict) -> bool:
    return "method" not in msg and "id" in msg and ("result" in msg or "error" in msg)


def _sse_line(msg: dict) -> str:
    return f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"


def _confirm_html(eid: str, pending: elicitation.PendingElicit, done: str = "") -> str:
    args = json.dumps(pending.args, ensure_ascii=False, indent=2)
    if done:
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marriott MCP</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#1c1c1c;padding:28px;border-radius:16px;max-width:480px;width:90%}}
</style></head>
<body><div class="card"><h1>Marriott MCP</h1><p>{done}</p></div></body></html>"""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conferma prenotazione</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#1c1c1c;padding:28px;border-radius:16px;max-width:480px;width:90%}}
pre{{white-space:pre-wrap;background:#111;padding:12px;border-radius:8px;font-size:13px}}
form{{display:flex;gap:12px;margin-top:16px}}
button{{border:0;padding:12px 18px;border-radius:10px;font-weight:600;cursor:pointer;flex:1}}
.go{{background:#fff;color:#111}}
.stop{{background:#333;color:#eee}}
</style></head>
<body><div class="card">
<h1>Conferma richiesta</h1>
<p>{pending.message}</p>
<pre>{args}</pre>
<form method="post" action="/confirm/{eid}">
<button class="stop" name="action" value="cancel" type="submit">Annulla</button>
<button class="go" name="action" value="accept" type="submit">Conferma</button>
</form>
</div></body></html>"""


async def confirm_page(request: Request) -> Response:
    eid = request.path_params.get("eid") or ""
    pending = elicitation.get(eid)
    if pending is None:
        return HTMLResponse(
            _confirm_html(
                eid,
                elicitation.PendingElicit("", {}, "Sessione scaduta o già chiusa."),
                done="Sessione scaduta o già chiusa. Nessuna prenotazione è stata toccata.",
            ),
            status_code=404,
        )
    if request.method == "GET":
        return HTMLResponse(_confirm_html(eid, pending))
    form = await request.form()
    action = str(form.get("action") or "cancel")
    if action == "accept":
        elicitation.resolve(eid, {"action": "accept", "content": {"confirm": True}})
        done = "Confermato. L'operazione riprende sul server."
    else:
        elicitation.resolve(eid, {"action": "cancel"})
        done = "Annullato. Nessuna prenotazione è stata toccata."
    return HTMLResponse(_confirm_html(eid, pending, done=done))


def _login_html(error: str = "", done: str = "") -> str:
    err = f"<p style='color:#c00'>{error}</p>" if error else ""
    if done:
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marriott MCP</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#1c1c1c;padding:28px;border-radius:16px;max-width:420px;width:90%}}
</style></head>
<body><div class="card"><h1>Marriott MCP</h1><p>{done}</p></div></body></html>"""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bonvoy sign-in</title>
<style>
body{{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center}}
.card{{background:#1c1c1c;padding:28px;border-radius:16px;max-width:420px;width:90%}}
label{{display:block;margin:12px 0 6px}}
input{{width:100%;padding:10px;border-radius:8px;border:0}}
button{{margin-top:18px;background:#fff;color:#111;border:0;padding:12px 18px;border-radius:10px;font-weight:600;cursor:pointer;width:100%}}
</style></head>
<body><div class="card">
<h1>Marriott Bonvoy</h1>
<p>Sign in here. Do not send the password to Grok.</p>
{err}
<form method="post">
<label>Email or member number</label>
<input type="text" name="email" autocomplete="username" required>
<label>Password</label>
<input type="password" name="password" autocomplete="current-password" required>
<button type="submit">Sign in</button>
</form>
</div></body></html>"""


async def login_page(request: Request) -> Response:
    eid = request.path_params.get("eid") or ""
    pending = elicitation.get(eid)
    if pending is None:
        return HTMLResponse(_login_html(done="Link expired. Ask the agent to sign in again."), 404)
    if request.method == "GET":
        return HTMLResponse(_login_html())
    form = await request.form()
    email = str(form.get("email") or "").strip()
    password = str(form.get("password") or "")
    if not email or not password:
        return HTMLResponse(_login_html(error="Email and password required."), 400)
    save_creds(email, password)
    log.info("Bonvoy login form submitted")
    loop = asyncio.get_running_loop()
    snap = await loop.run_in_executor(_PW_EXEC, do_login)
    if not snap.get("signed_in"):
        return HTMLResponse(_login_html(error="Sign-in failed. Check credentials and retry."), 401)
    elicitation.resolve(eid, {"action": "accept", "content": {"done": True, "confirm": True}})
    name = snap.get("member_first_name") or "Bonvoy"
    return HTMLResponse(_login_html(done=f"Signed in as {name}. Return to the chat."))


def _needs_login_gate(name: str) -> bool:
    if not name.startswith("marriott_"):
        return False
    if name in (
        "marriott_skills_list",
        "marriott_skills_get",
        "marriott_report_bug",
        "marriott_bugs_list",
        "marriott_bugs_get",
    ):
        return False
    return not has_creds()


async def _elicit_login(name: str, args: dict, orig_id: Any, orig_msg: dict) -> Response:
    eid, elicit_rpc = elicitation.start_login(name, args)
    log.info("elicitation/create url-login id=%s tool=%s", eid, name)

    async def gen():
        yield _sse_line(elicit_rpc)
        loop = asyncio.get_running_loop()
        answered = await loop.run_in_executor(None, elicitation.wait, eid)
        if not elicitation.accepted(answered):
            result = _tool_result(
                {
                    "ok": False,
                    "signed_in": False,
                    "error": "Bonvoy login cancelled or timed out. Open the login URL from elicitation.",
                },
                is_error=True,
            )
            yield _sse_line({"jsonrpc": "2.0", "id": orig_id, "result": result})
            return
        if name in WRITE_TOOLS:
            weid, wrpc = elicitation.start(name, args)
            yield _sse_line(wrpc)
            wans = await loop.run_in_executor(None, elicitation.wait, weid)
            result = await loop.run_in_executor(_PW_EXEC, finish_write, name, args, wans)
            yield _sse_line({"jsonrpc": "2.0", "id": orig_id, "result": result})
            return
        resp = await loop.run_in_executor(_PW_EXEC, handle_rpc, orig_msg)
        if isinstance(resp, dict):
            resp.pop("_marriott_elicit", None)
            yield _sse_line(resp)
        else:
            yield _sse_line(
                {
                    "jsonrpc": "2.0",
                    "id": orig_id,
                    "result": _tool_result({"ok": True, "signed_in": True}),
                }
            )

    resp = StreamingResponse(gen(), media_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"
    return _cors(resp)


async def _elicit_write(name: str, args: dict, orig_id: Any) -> Response:
    eid, elicit_rpc = elicitation.start(name, args)
    log.info("elicitation/create id=%s tool=%s", eid, name)

    async def gen():
        yield _sse_line(elicit_rpc)
        loop = asyncio.get_running_loop()
        answered = await loop.run_in_executor(None, elicitation.wait, eid)
        result = await loop.run_in_executor(
            _PW_EXEC, finish_write, name, args, answered
        )
        yield _sse_line({"jsonrpc": "2.0", "id": orig_id, "result": result})

    resp = StreamingResponse(gen(), media_type="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"
    return _cors(resp)


async def handle_mcp(request: Request) -> Response:
    if request.method == "OPTIONS":
        return await handle_options(request)
    auth = request.headers.get("authorization", "").strip()
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
    if not _valid_access(token):
        return _unauth()
    if request.method == "GET":
        return _cors(
            JSONResponse(
                {
                    "name": "Marriott MCP (Grok MCP)",
                    "transport": "streamable-http",
                    "endpoint": "/",
                }
            )
        )
    body = await request.body()
    if not body:
        return _cors(JSONResponse({"error": "empty body"}, status_code=400))
    accept = request.headers.get("accept") or ""
    try:
        msg: Any = json.loads(body)
    except json.JSONDecodeError:
        return _cors(JSONResponse({"error": "invalid json"}, status_code=400))
    loop = asyncio.get_running_loop()
    if isinstance(msg, dict) and _is_rpc_response(msg):
        eid = str(msg.get("id"))
        ok = elicitation.resolve(
            eid,
            msg.get("result") if isinstance(msg.get("result"), dict) else {"action": "cancel"},
        )
        log.info("elicitation response id=%s resolved=%s", eid, ok)
        return _cors(Response(status_code=202))
    if isinstance(msg, dict) and msg.get("method") == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        if _needs_login_gate(name):
            return await _elicit_login(name, args, msg.get("id"), msg)
        if name in WRITE_TOOLS:
            kind, payload = elicitation.prepare_write(name, args)
            if kind != "run":
                return _rpc_response(
                    {
                        "jsonrpc": "2.0",
                        "id": msg.get("id"),
                        "result": _tool_result(payload, is_error=False),
                    },
                    accept,
                )
            result = await loop.run_in_executor(
                _PW_EXEC,
                finish_write,
                name,
                payload,
                {"action": "accept", "content": {"confirm": True}},
            )
            return _rpc_response(
                {"jsonrpc": "2.0", "id": msg.get("id"), "result": result},
                accept,
            )
    if isinstance(msg, list):

        def _batch() -> list:
            out = []
            for item in msg:
                if isinstance(item, dict):
                    r = handle_rpc(item)
                    if r is not None:
                        r.pop("_marriott_elicit", None)
                        out.append(r)
            return out

        out = await loop.run_in_executor(_PW_EXEC, _batch)
        return _rpc_response(out, accept)
    if not isinstance(msg, dict):
        return _cors(JSONResponse({"error": "invalid rpc"}, status_code=400))
    log.info("Grok → Marriott method=%s", msg.get("method"))
    resp = await loop.run_in_executor(_PW_EXEC, handle_rpc, msg)
    if resp is None:
        return _cors(Response(status_code=202))
    if isinstance(resp, dict):
        resp.pop("_marriott_elicit", None)
        if msg.get("method") == "initialize":
            out = _rpc_response(resp, accept)
            out.headers["Mcp-Session-Id"] = secrets.token_urlsafe(18)
            return out
    return _rpc_response(resp, accept)


routes = [
    Route("/", handle_mcp, methods=["GET", "POST", "OPTIONS"]),
    Route("/mcp", handle_mcp, methods=["GET", "POST", "OPTIONS"]),
    Route("/confirm/{eid}", confirm_page, methods=["GET", "POST"]),
    Route("/login/{eid}", login_page, methods=["GET", "POST"]),
    Route("/.well-known/oauth-authorization-server", well_known_as, methods=["GET", "OPTIONS"]),
    Route("/.well-known/openid-configuration", well_known_as, methods=["GET", "OPTIONS"]),
    Route("/.well-known/oauth-protected-resource", well_known_prm, methods=["GET", "OPTIONS"]),
    Route("/.well-known/oauth-protected-resource/", well_known_prm, methods=["GET", "OPTIONS"]),
    Route("/oauth/authorize", oauth_authorize, methods=["GET", "POST", "OPTIONS"]),
    Route("/oauth/token", oauth_token, methods=["POST", "OPTIONS"]),
    Route("/oauth/register", oauth_register, methods=["POST", "OPTIONS"]),
]

app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    log.info("Marriott Grok MCP+OAuth on http://%s:%s/ → %s", HOST, PORT, PUBLIC_BASE)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
