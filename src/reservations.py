"""Playwright write ops for Marriott reservations. Call only after elicitation accept."""

from __future__ import annotations

import re
from typing import Any
from src.browser import TRIPS, goto, goto_account, page, snapshot
from src.search import search_url
from src.interact import book as interact_book

LOOKUP = "https://www.marriott.com/reservation/lookupReservation.mi"
SEARCH = "https://www.marriott.com/search/findHotels.mi"


def _body(p) -> str:
    try:
        return p.inner_text("body")
    except Exception:
        return ""


def _click_first(p, names: list[str]) -> bool:
    for name in names:
        btn = p.get_by_role("button", name=re.compile(name, re.I))
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            p.wait_for_timeout(2500)
            return True
        link = p.get_by_role("link", name=re.compile(name, re.I))
        if link.count() and link.first.is_visible():
            link.first.click()
            p.wait_for_timeout(2500)
            return True
    return False


def _has_payment_form(p) -> bool:
    body = _body(p).lower()
    if "card number" in body or "credit card" in body or "cvv" in body:
        return True
    if p.locator('input[autocomplete="cc-number"]').count():
        return True
    return False


def cancel_reservation(confirmation_number: str) -> dict[str, Any]:
    conf = (confirmation_number or "").strip()
    if not conf:
        return {"ok": False, "changed": False, "error": "confirmation_number required"}
    data = goto_account(TRIPS, name="write-cancel-trips")
    p = page()
    text = _body(p)
    if conf.lower() not in text.lower():
        goto(LOOKUP, name="write-cancel-lookup")
        p = page()
        box = p.get_by_label(re.compile(r"confirmation", re.I))
        if box.count():
            box.first.fill(conf)
            _click_first(p, [r"find", r"search", r"look up", r"submit"])
            p.wait_for_timeout(4000)
        text = _body(p)
        if conf.lower() not in text.lower():
            snap = snapshot(p, "write-cancel-missing")
            return {
                "ok": False,
                "changed": False,
                "executed": False,
                "error": "confirmation not found; nothing cancelled",
                "url": snap.get("url"),
            }
    if not _click_first(p, [r"cancel reservation", r"cancel stay", r"^cancel$"]):
        snap = snapshot(p, "write-cancel-no-btn")
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "cancel control not found; nothing cancelled",
            "url": snap.get("url"),
        }
    p.wait_for_timeout(2000)
    _click_first(p, [r"yes, cancel", r"confirm cancel", r"confirm", r"yes"])
    p.wait_for_timeout(5000)
    snap = snapshot(p, "write-cancel-after")
    body = (snap.get("body_excerpt") or "").lower()
    changed = any(
        s in body
        for s in ("cancelled", "canceled", "cancellation confirmed", "has been canceled")
    )
    return {
        "ok": True,
        "changed": changed,
        "executed": True,
        "confirmation_number": conf,
        "url": snap.get("url"),
        "title": snap.get("title"),
    }


def modify_reservation(
    confirmation_number: str,
    checkin: str | None = None,
    checkout: str | None = None,
) -> dict[str, Any]:
    conf = (confirmation_number or "").strip()
    if not conf:
        return {"ok": False, "changed": False, "error": "confirmation_number required"}
    goto_account(TRIPS, name="write-modify-trips")
    p = page()
    if conf.lower() not in _body(p).lower():
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "confirmation not found; nothing modified",
        }
    if not _click_first(p, [r"modify", r"change dates", r"edit reservation"]):
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "modify control not found",
        }
    if checkin:
        cin = p.get_by_label(re.compile(r"check.?in", re.I))
        if cin.count():
            cin.first.fill(checkin)
    if checkout:
        cout = p.get_by_label(re.compile(r"check.?out", re.I))
        if cout.count():
            cout.first.fill(checkout)
    _click_first(p, [r"save", r"update", r"continue", r"search"])
    p.wait_for_timeout(4000)
    if _has_payment_form(p):
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "modify hit payment form; aborted (no card via MCP)",
            "url": p.url,
        }
    snap = snapshot(p, "write-modify-after")
    return {
        "ok": True,
        "changed": True,
        "executed": True,
        "confirmation_number": conf,
        "url": snap.get("url"),
        "title": snap.get("title"),
    }


def create_reservation(
    destination: str,
    checkin: str,
    checkout: str,
    property: str | None = None,
    property_id: str | None = None,
    adults: int = 1,
    rooms: int = 1,
    rate: str | None = None,
) -> dict[str, Any]:
    dest = (destination or "").strip()
    if not dest or not checkin or not checkout:
        return {
            "ok": False,
            "changed": False,
            "error": "destination, checkin, checkout required",
        }
    try:
        url = search_url(
            destination=dest,
            checkin=checkin,
            checkout=checkout,
            rooms=rooms,
            adults=adults,
            property_id=property_id or property,
        )
    except ValueError as exc:
        return {"ok": False, "changed": False, "error": str(exc)}
    goto(url, name="write-create-search")
    p = page()
    needle = (property_id or property or "").strip()
    if needle:
        loc = p.get_by_text(re.compile(re.escape(needle), re.I)).first
        if loc.count():
            loc.click()
            p.wait_for_timeout(3000)
    if not _click_first(p, [r"view rates", r"select room", r"book", r"reserve"]):
        snap = snapshot(p, "write-create-no-rate")
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "no book/rate control; reservation not created",
            "url": snap.get("url"),
        }
    p.wait_for_timeout(3000)
    _click_first(p, [r"select", r"continue", r"book this", r"reserve"])
    p.wait_for_timeout(3000)
    if _has_payment_form(p):
        snap = snapshot(p, "write-create-payment")
        return {
            "ok": False,
            "changed": False,
            "executed": False,
            "error": "checkout requires a card; aborted (MCP never collects payment data)",
            "url": snap.get("url"),
        }
    booked = _click_first(
        p,
        [r"complete reservation", r"confirm reservation", r"book now", r"complete booking"],
    )
    p.wait_for_timeout(5000)
    snap = snapshot(p, "write-create-after")
    body = (snap.get("body_excerpt") or "").lower()
    changed = booked and any(
        s in body for s in ("confirmation", "confirmed", "thank you for booking")
    )
    return {
        "ok": bool(changed),
        "changed": bool(changed),
        "executed": True,
        "destination": dest,
        "checkin": checkin,
        "checkout": checkout,
        "url": snap.get("url"),
        "title": snap.get("title"),
        "note": None if changed else "flow ran but confirmation text not seen",
    }


def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "marriott_reservation_cancel":
            return cancel_reservation(str(args.get("confirmation_number") or ""))
        if name == "marriott_reservation_modify":
            return modify_reservation(
                str(args.get("confirmation_number") or ""),
                args.get("checkin"),
                args.get("checkout"),
            )
        if name == "marriott_reservation_create":
            return create_reservation(
                destination=str(args.get("destination") or ""),
                checkin=str(args.get("checkin") or ""),
                checkout=str(args.get("checkout") or ""),
                property=args.get("property"),
                property_id=args.get("property_id"),
                adults=int(args.get("adults") or 1),
                rooms=int(args.get("rooms") or 1),
                rate=args.get("rate"),
            )
        if name == "marriott_book":
            pl = args.get("pay_later")
            pay_later = True if pl is None else bool(pl)
            if isinstance(pl, str):
                pay_later = pl.strip().lower() not in ("false", "0", "no")
            return interact_book(
                destination=str(args.get("destination") or args.get("property") or ""),
                checkin=str(args.get("checkin") or ""),
                checkout=str(args.get("checkout") or ""),
                property=args.get("property"),
                property_id=args.get("property_id"),
                adults=int(args.get("adults") or 1),
                rooms=int(args.get("rooms") or 1),
                room_pref=str(args.get("room_pref") or "single"),
                pay_later=pay_later,
            )
        return {"ok": False, "changed": False, "error": f"unknown write tool {name}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "changed": False,
            "executed": True,
            "error": str(exc).split("\n", 1)[0][:400],
        }
