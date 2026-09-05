"""Page interaction: extract, click, fill, dismiss overlays, book after elicitation.

Does not solve captchas or bypass Akamai. Cards/passwords are never filled.
"""

from __future__ import annotations

import re
from typing import Any

from src.browser import do_login, goto, open_context, page, snapshot
from src.search import ensure_session, search_properties, session_view

CAPTCHA = re.compile(
    r"pardon our interruption|access denied|cf-challenge|recaptcha|akamai|bot manager",
    re.I,
)
SOLD_OUT = re.compile(r"sold out|no rooms? available|not available for these dates", re.I)
PAY = re.compile(r"card number|credit card|cvv|debit card", re.I)
LOGIN = re.compile(r"sign in|please enter the password", re.I)
CONFIRM_RE = re.compile(
    r"(?:confirmation(?:\s+number)?|conferma)[:\s#]*([A-Z0-9]{6,14})",
    re.I,
)
BAD_FILL = re.compile(r"password|card|cvv|cc-number|credit|cvv2|cvc", re.I)


def _err(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message, **extra}


def _body(p) -> str:
    try:
        return p.inner_text("body")
    except Exception:
        return ""


def classify(p) -> str | None:
    text = _body(p)
    title = ""
    try:
        title = p.title()
    except Exception:
        title = ""
    blob = f"{title}\n{text[:4000]}"
    if CAPTCHA.search(blob) or "akamaighost" in blob.lower():
        return "akamai_denied"
    if SOLD_OUT.search(blob):
        return "sold_out"
    if PAY.search(blob) and p.locator('input[autocomplete="cc-number"]').count():
        return "payment_required"
    if "sign-in" in (p.url or "").lower() and LOGIN.search(blob):
        return "login_expired"
    return None


def dismiss_overlays() -> dict[str, Any]:
    open_context()
    p = page()
    clicked = []
    for sel in (
        "#onetrust-accept-btn-handler",
        "#onetrust-reject-all-handler",
        "button#onetrust-accept-btn-handler",
    ):
        loc = p.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=2000)
                clicked.append(sel)
                p.wait_for_timeout(400)
            except Exception:
                pass
    for name in (
        "Accept All",
        "Accept Cookies",
        "Accept",
        "Agree",
        "Confirm My Choices",
        "Close",
        "No thanks",
        "Not now",
        "OK",
        "Got it",
    ):
        loc = p.get_by_role("button", name=re.compile(rf"{re.escape(name)}", re.I))
        if loc.count():
            try:
                if loc.first.is_visible():
                    loc.first.click(timeout=2000)
                    clicked.append(name)
                    p.wait_for_timeout(400)
            except Exception:
                continue
    snap = snapshot(p, "mcp-dismiss")
    code = classify(p)
    return {
        "ok": code is None,
        "error": code,
        "clicked": clicked,
        "url": snap.get("url"),
        "session": session_view(snap),
    }


def extract_page() -> dict[str, Any]:
    open_context()
    p = page()
    snap = snapshot(p, "mcp-page")
    code = classify(p)
    body = snap.get("body_excerpt") or ""
    conf = None
    m = CONFIRM_RE.search(body)
    if m:
        conf = m.group(1).upper()
    rooms = p.evaluate(
        """() => {
          const out = [];
          const seen = new Set();
          const nodes = Array.from(document.querySelectorAll(
            '[class*="room"], [class*="rate"], article, li, section'
          )).slice(0, 80);
          for (const n of nodes) {
            const t = (n.innerText || '').replace(/\\s+/g, ' ').trim();
            if (t.length < 20 || t.length > 400) continue;
            const key = t.slice(0, 80);
            if (seen.has(key)) continue;
            const money = t.match(/\\$\\s?[\\d,]+|AED\\s?[\\d,]+|EUR\\s?[\\d,]+/);
            const pts = t.match(/([\\d,]+)\\s*points/i);
            const bed = (t.match(/\\b(king|queen|twin|double|single|sofa)\\b/i) || [])[1];
            if (!money && !pts && !/select|book|room/i.test(t)) continue;
            seen.add(key);
            out.push({
              text: t.slice(0, 220),
              bed: bed || null,
              rate: money ? money[0] : null,
              points: pts ? pts[1] : null,
              pay_later: /pay later|no prepay|pay at hotel|flexible/i.test(t),
            });
            if (out.length >= 15) break;
          }
          return out;
        }"""
    )
    buttons = p.evaluate(
        """() => Array.from(document.querySelectorAll('button, a[role="button"], input[type="submit"]'))
          .map(el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim())
          .filter(t => t && t.length < 80)
          .slice(0, 25)"""
    )
    return {
        "ok": code not in ("akamai_denied", "login_expired"),
        "error": code,
        "session": session_view(snap),
        "url": snap.get("url"),
        "title": snap.get("title"),
        "confirmation_number": conf,
        "rooms": rooms,
        "buttons": buttons,
        "denied": bool(snap.get("denied")),
    }


def click(target: str) -> dict[str, Any]:
    name = (target or "").strip()
    if not name:
        return _err("invalid", "target required")
    open_context()
    p = page()
    loc = p.get_by_role("button", name=re.compile(name, re.I))
    if not loc.count():
        loc = p.get_by_role("link", name=re.compile(name, re.I))
    if not loc.count():
        loc = p.get_by_text(re.compile(name, re.I))
    if not loc.count():
        return _err("not_found", f"no control matching {name!r}", url=p.url)
    try:
        loc.first.click(timeout=8000)
    except Exception as exc:
        return _err("timeout", str(exc).split("\n", 1)[0][:240], url=p.url)
    p.wait_for_timeout(2500)
    data = extract_page()
    data["clicked"] = name
    return data


def fill(field: str, value: str) -> dict[str, Any]:
    label = (field or "").strip()
    val = value if value is not None else ""
    if not label:
        return _err("invalid", "field required")
    if BAD_FILL.search(label) or BAD_FILL.search(str(val)):
        return _err("forbidden", "MCP never fills password or card fields")
    open_context()
    p = page()
    box = p.get_by_label(re.compile(label, re.I))
    if not box.count():
        box = p.get_by_placeholder(re.compile(label, re.I))
    if not box.count():
        return _err("not_found", f"no field matching {label!r}", url=p.url)
    try:
        box.first.fill(str(val), timeout=8000)
    except Exception as exc:
        return _err("timeout", str(exc).split("\n", 1)[0][:240], url=p.url)
    return {"ok": True, "filled": label, "url": p.url}



def book(**kwargs):
    from src.book_flow import book as _book
    return _book(**kwargs)
