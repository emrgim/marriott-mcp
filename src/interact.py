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
    for name in ("Accept All", "Accept", "Agree", "Close", "No thanks", "Not now", "OK"):
        loc = p.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I))
        if loc.count() and loc.first.is_visible():
            try:
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


def _pick_room(p, room_pref: str, pay_later: bool) -> bool:
    pref = (room_pref or "").strip()
    cards = p.locator("button, a").filter(has_text=re.compile(r"select|book|reserve", re.I))
    n = min(cards.count(), 20)
    for i in range(n):
        el = cards.nth(i)
        try:
            blob = (el.inner_text() or "")[:400]
        except Exception:
            continue
        if pref and pref.lower() not in blob.lower():
            parent = el.locator("xpath=ancestor::*[self::article or self::li or self::section][1]")
            try:
                blob = (parent.inner_text() or blob)[:500]
            except Exception:
                pass
            if pref.lower() not in blob.lower() and pref.lower() not in ("single", "1"):
                continue
        if pay_later and not re.search(r"pay later|flexible|no prepay|pay at hotel", blob, re.I):
            # still allow if no prepaid language either
            if re.search(r"prepay|non-refundable|pay now", blob, re.I):
                continue
        try:
            el.click(timeout=5000)
            p.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    # last resort: first Select
    btn = p.get_by_role("button", name=re.compile(r"select|book this|reserve", re.I))
    if btn.count():
        try:
            btn.first.click(timeout=5000)
            p.wait_for_timeout(2500)
            return True
        except Exception:
            return False
    return False


def book(
    *,
    destination: str,
    checkin: str,
    checkout: str,
    property: str | None = None,
    property_id: str | None = None,
    adults: int = 1,
    rooms: int = 1,
    room_pref: str = "single",
    pay_later: bool = True,
) -> dict[str, Any]:
    dest = (destination or property or "").strip()
    if not dest or not checkin or not checkout:
        return _err("invalid", "destination, checkin, checkout required")
    snap = ensure_session()
    if not snap.get("signed_in"):
        snap = do_login()
    if not snap.get("signed_in"):
        return _err("login_expired", "Bonvoy session not signed in")
    dismiss_overlays()
    found = search_properties(
        destination=dest,
        checkin=checkin,
        checkout=checkout,
        rooms=rooms,
        adults=adults,
        property_id=property_id or property,
    )
    if not found.get("ok"):
        return {**found, "error": found.get("error") or "search_failed"}
    p = page()
    code = classify(p)
    if code:
        return _err(code, code, search=found)
    needle = (property or dest).strip()
    clicked_hotel = False
    if needle:
        loc = p.get_by_text(re.compile(re.escape(needle), re.I))
        if loc.count():
            try:
                loc.first.click(timeout=6000)
                p.wait_for_timeout(3000)
                clicked_hotel = True
            except Exception:
                clicked_hotel = False
    if not clicked_hotel:
        rates = p.get_by_role("link", name=re.compile(r"view rates|select dates|book", re.I))
        if rates.count():
            try:
                rates.first.click(timeout=6000)
                p.wait_for_timeout(3000)
            except Exception:
                pass
    dismiss_overlays()
    code = classify(p)
    if code in ("sold_out", "akamai_denied", "login_expired"):
        return _err(code, code, url=p.url)
    if not _pick_room(p, room_pref, pay_later):
        ext = extract_page()
        if ext.get("error") == "sold_out" or not ext.get("rooms"):
            return _err("sold_out", "no selectable room", url=p.url, rooms=ext.get("rooms"))
        return _err("not_found", "could not click a room", url=p.url, rooms=ext.get("rooms"))
    p.wait_for_timeout(2000)
    if p.locator('input[autocomplete="cc-number"]').count() or PAY.search(_body(p)[:2500]):
        return _err(
            "payment_required",
            "checkout requires a card; MCP does not fill payment data",
            url=p.url,
        )
    # guest fields if empty — first/last from account first name only
    first = (snap.get("member_first_name") or "")[:40]
    if first:
        for lab in ("first name", "given name"):
            box = p.get_by_label(re.compile(lab, re.I))
            if box.count():
                try:
                    if not (box.first.input_value() or "").strip():
                        box.first.fill(first)
                except Exception:
                    pass
                break
    for name in (
        r"complete reservation",
        r"confirm reservation",
        r"book now",
        r"complete booking",
        r"reserve",
    ):
        btn = p.get_by_role("button", name=re.compile(name, re.I))
        if btn.count() and btn.first.is_visible():
            try:
                btn.first.click(timeout=8000)
                p.wait_for_timeout(5000)
                break
            except Exception:
                continue
    ext = extract_page()
    conf = ext.get("confirmation_number")
    if conf:
        return {
            "ok": True,
            "changed": True,
            "confirmation_number": conf,
            "url": ext.get("url"),
            "session": ext.get("session"),
        }
    code = ext.get("error") or "no_confirmation"
    return {
        "ok": False,
        "changed": False,
        "error": code if code != "no_confirmation" else "no_confirmation",
        "message": "flow ran but no confirmation number on page",
        "url": ext.get("url"),
        "rooms": ext.get("rooms"),
        "buttons": ext.get("buttons"),
    }
