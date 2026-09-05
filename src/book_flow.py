"""Quote rooms, ask in Grok chat, then checkout. No captcha bypass."""

from __future__ import annotations

import re
import secrets
from typing import Any

from src.browser import do_login, open_context, page, snapshot
from src.elicitation import human_confirmed
from src.interact import classify, dismiss_overlays, extract_page, _body, _err
from src.search import ensure_session, search_properties, session_view

PAY = re.compile(r"card number|credit card|cvv|debit card", re.I)
LETTER = re.compile(r"\b([A-H])\b", re.I)
POINTS_ONLY = re.compile(r"points|awards", re.I)

_QUOTES: dict[str, dict[str, Any]] = {}


def _click_named(p, names: list[str], timeout: int = 6000) -> str | None:
    for name in names:
        loc = p.get_by_role("button", name=re.compile(name, re.I))
        if not loc.count():
            loc = p.get_by_role("link", name=re.compile(name, re.I))
        if loc.count():
            try:
                loc.first.click(timeout=timeout)
                p.wait_for_timeout(2000)
                return name
            except Exception:
                continue
    return None


def _open_hotel(p, needle: str) -> None:
    if needle:
        loc = p.get_by_text(re.compile(re.escape(needle), re.I))
        if loc.count():
            try:
                loc.first.click(timeout=6000)
                p.wait_for_timeout(3000)
                return
            except Exception:
                pass
    _click_named(p, [r"view rates", r"select dates", r"book", r"see rooms"])


def _options_from_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    opts = []
    for i, r in enumerate((rooms or [])[:8]):
        lid = chr(65 + i)
        rate = r.get("rate")
        pts = r.get("points")
        bed = r.get("bed")
        text = (r.get("text") or "")[:160]
        label = " · ".join(x for x in (bed, rate, (f"{pts} points" if pts else None), text[:80]) if x)
        opts.append(
            {
                "id": lid,
                "label": label or text or lid,
                "bed": bed,
                "rate": rate,
                "points": pts,
                "pay_later": bool(r.get("pay_later")),
                "text": text,
            }
        )
    return opts


def _ask_list(dest: str, checkin: str, checkout: str, opts: list[dict[str, Any]]) -> str:
    lines = [
        f"Ho trovato queste opzioni per {dest} ({checkin} → {checkout}):",
    ]
    for o in opts:
        lines.append(f"{o['id']}) {o['label']}")
    lines.append("Quale preferisci? Rispondi con la lettera (A, B, C…).")
    lines.append("Se vuoi che prenoti quella, scrivi anche confermo.")
    return "\n".join(lines)


def _ask_price(opt: dict[str, Any]) -> str:
    price = opt.get("rate") or (f"{opt.get('points')} points" if opt.get("points") else "prezzo non letto")
    return (
        f"Ho trovato questa stanza: {opt.get('label')}. Costa {price}. "
        "Continuo con la prenotazione?"
    )


def advance_checkout(p) -> dict[str, Any]:
    """From rateListMenu / reviewDetails toward confirmation. Relogin if session drops."""
    dismiss_overlays()
    url = p.url or ""
    if "rateListMenu" in url or "availability" in url.lower():
        _click_named(
            p,
            [r"select", r"book this", r"reserve", r"continue", r"book now"],
        )
        p.wait_for_timeout(3000)
        dismiss_overlays()
    snap = snapshot(p, "checkout-mid")
    if not snap.get("signed_in"):
        snap = do_login()
        dismiss_overlays()
        if not snap.get("signed_in"):
            return _err("login_expired", "session dropped during checkout", url=p.url)
    if p.locator('input[autocomplete="cc-number"]').count() or (
        PAY.search(_body(p)[:2500]) and p.locator("input[type='password']").count()
    ):
        if p.locator('input[autocomplete="cc-number"]').count():
            return _err(
                "payment_required",
                "checkout requires a card; MCP does not fill payment data",
                url=p.url,
            )
    _click_named(
        p,
        [
            r"complete reservation",
            r"confirm reservation",
            r"book now",
            r"complete booking",
            r"reserve",
            r"confirm my booking",
        ],
    )
    p.wait_for_timeout(4000)
    dismiss_overlays()
    snap = snapshot(p, "checkout-after")
    if not snap.get("signed_in"):
        do_login()
        dismiss_overlays()
        _click_named(p, [r"book now", r"complete reservation", r"confirm reservation"])
        p.wait_for_timeout(4000)
    ext = extract_page()
    conf = ext.get("confirmation_number")
    if conf:
        return {
            "ok": True,
            "changed": True,
            "executed": True,
            "confirmation_number": conf,
            "url": ext.get("url"),
            "session": ext.get("session"),
        }
    code = classify(p)
    if code:
        return _err(code, code, url=p.url, executed=True, changed=False)
    return {
        "ok": False,
        "changed": False,
        "executed": True,
        "error": "no_confirmation",
        "message": "still on checkout; no confirmation number",
        "url": ext.get("url"),
        "title": ext.get("title"),
        "buttons": ext.get("buttons"),
        "rooms": ext.get("rooms"),
    }


def _pick_option(p, opt: dict[str, Any], room_pref: str, pay_later: bool) -> bool:
    needle = (opt.get("bed") or room_pref or "").strip()
    rate = (opt.get("rate") or "").strip()
    cards = p.locator("button, a").filter(has_text=re.compile(r"select|book|reserve", re.I))
    n = min(cards.count(), 24)
    for i in range(n):
        el = cards.nth(i)
        try:
            blob = (el.inner_text() or "")[:400]
            parent = el.locator("xpath=ancestor::*[self::article or self::li or self::section][1]")
            try:
                blob = (parent.inner_text() or blob)[:600]
            except Exception:
                pass
        except Exception:
            continue
        if needle and needle.lower() not in blob.lower() and needle.lower() not in ("single", "1"):
            continue
        if rate and rate.split()[0] not in blob:
            continue
        if pay_later and re.search(r"prepay|non-refundable|pay now", blob, re.I):
            if not re.search(r"pay later|flexible|pay at hotel", blob, re.I):
                continue
        try:
            el.click(timeout=5000)
            p.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    return bool(_click_named(p, [r"select", r"book this", r"reserve"]))


def quote_stay(
    *,
    destination: str,
    checkin: str,
    checkout: str,
    property: str | None = None,
    property_id: str | None = None,
    adults: int = 1,
    rooms: int = 1,
) -> dict[str, Any]:
    dest = (destination or property or "").strip()
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
        return {**found, "error": found.get("error") or "search_failed", "executed": False}
    p = page()
    code = classify(p)
    if code in ("akamai_denied", "login_expired"):
        return _err(code, code, search=found)
    _open_hotel(p, (property or dest).strip())
    dismiss_overlays()
    ext = extract_page()
    raw = ext.get("rooms") or []
    cash = [r for r in raw if r.get("rate")]
    pts = [r for r in raw if r.get("points") and not r.get("rate")]
    if not cash and pts:
        return {
            "ok": False,
            "error": "only_award_rates",
            "message": "No cash/pay-later rate; points/awards only. Ask the user before using points.",
            "rooms": raw,
            "url": ext.get("url"),
            "executed": False,
            "changed": False,
        }
    if not raw or ext.get("error") == "sold_out":
        return _err("sold_out", "no rooms listed", url=ext.get("url"), rooms=raw)
    opts = _options_from_rooms(cash or raw)
    qid = "quote-" + secrets.token_urlsafe(10)
    _QUOTES[qid] = {
        "destination": dest,
        "checkin": checkin,
        "checkout": checkout,
        "property": property,
        "property_id": property_id,
        "adults": adults,
        "rooms": rooms,
        "options": opts,
        "session": session_view(snap),
    }
    ask = _ask_list(dest, checkin, checkout, opts)
    return {
        "ok": True,
        "stage": "choose_room",
        "executed": False,
        "changed": False,
        "quote_id": qid,
        "options": opts,
        "ask_the_user": ask,
        "url": ext.get("url"),
        "session": ext.get("session"),
        "message": "Present options A, B, C… in Grok chat. Do not book until the human picks a letter.",
    }


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
    option_id: str | None = None,
    quote_id: str | None = None,
    user_said: str | None = None,
    user_confirmed: Any = None,
) -> dict[str, Any]:
    dest = (destination or property or "").strip()
    said = (user_said or "").strip()
    oid = (option_id or "").strip().upper()
    qid = (quote_id or "").strip()

    if qid and qid in _QUOTES:
        q = _QUOTES[qid]
        if not oid:
            m = LETTER.search(said)
            oid = m.group(1).upper() if m else ""
        if not oid:
            return {
                "ok": True,
                "stage": "choose_room",
                "executed": False,
                "changed": False,
                "quote_id": qid,
                "options": q["options"],
                "ask_the_user": _ask_list(q["destination"], q["checkin"], q["checkout"], q["options"]),
            }
        opt = next((x for x in q["options"] if x["id"] == oid), None)
        if opt is None:
            return _err("invalid", f"unknown option {oid}", options=q["options"], quote_id=qid)
        confirmed = human_confirmed(said, True if user_confirmed is None else user_confirmed)
        if not confirmed:
            return {
                "ok": True,
                "stage": "confirm_price",
                "executed": False,
                "changed": False,
                "quote_id": qid,
                "option_id": oid,
                "option": opt,
                "ask_the_user": _ask_price(opt),
                "message": "Ask this in Grok chat. Call marriott_book again with quote_id, option_id, user_said.",
            }
        return _execute(q, opt, room_pref, pay_later)

    if not dest or not checkin or not checkout:
        return _err("invalid", "destination, checkin, checkout required")
    return quote_stay(
        destination=dest,
        checkin=checkin,
        checkout=checkout,
        property=property,
        property_id=property_id,
        adults=adults,
        rooms=rooms,
    )


def _execute(
    q: dict[str, Any],
    opt: dict[str, Any],
    room_pref: str,
    pay_later: bool,
) -> dict[str, Any]:
    snap = ensure_session()
    if not snap.get("signed_in"):
        snap = do_login()
    if not snap.get("signed_in"):
        return _err("login_expired", "Bonvoy session not signed in")
    dismiss_overlays()
    found = search_properties(
        destination=q["destination"],
        checkin=q["checkin"],
        checkout=q["checkout"],
        rooms=int(q.get("rooms") or 1),
        adults=int(q.get("adults") or 1),
        property_id=q.get("property_id") or q.get("property"),
    )
    if not found.get("ok"):
        return {**found, "error": found.get("error") or "search_failed"}
    p = page()
    _open_hotel(p, (q.get("property") or q["destination"]).strip())
    dismiss_overlays()
    if not _pick_option(p, opt, room_pref or (opt.get("bed") or ""), pay_later):
        ext = extract_page()
        return _err("not_found", "could not select the chosen room", url=p.url, rooms=ext.get("rooms"))
    return advance_checkout(p)
