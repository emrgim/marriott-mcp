"""Property search + availability. Dates must be MM/DD/YYYY on marriott.com."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from src.browser import do_login, goto, open_context, page, snapshot

SEARCH = "https://www.marriott.com/search/findHotels.mi"
AVAIL = "https://www.marriott.com/reservation/availabilitySearch.mi"


_IT_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def parse_date(value: str) -> datetime:
    raw = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})\s+([A-Za-zàèéìòù]+)\s+(\d{4})$", raw, re.I)
    if m:
        month = _IT_MONTHS.get(m.group(2).lower())
        if month:
            return datetime(int(m.group(3)), month, int(m.group(1)))
    raise ValueError(f"unrecognized date {value!r}; use YYYY-MM-DD or MM/DD/YYYY")


def mmddyyyy(value: str) -> str:
    d = parse_date(value)
    return d.strftime("%m/%d/%Y")


def nights_between(checkin: str, checkout: str) -> int:
    a, b = parse_date(checkin), parse_date(checkout)
    n = (b - a).days
    if n < 1:
        raise ValueError("checkout must be after checkin")
    return n


def search_query(
    *,
    destination: str,
    checkin: str,
    checkout: str,
    rooms: int = 1,
    adults: int = 1,
    property_id: str | None = None,
) -> dict[str, str]:
    frm, to = mmddyyyy(checkin), mmddyyyy(checkout)
    nights = nights_between(checkin, checkout)
    q = {
        "searchType": "InCity",
        "destinationAddress.destination": destination,
        "fromDate": frm,
        "toDate": to,
        "fromDateDefaultFormat": frm,
        "toDateDefaultFormat": to,
        "lengthOfStay": str(nights),
        "numberOfRooms": str(int(rooms or 1)),
        "roomCount": str(int(rooms or 1)),
        "numAdultsPerRoom": str(int(adults or 1)),
        "isInternalSearch": "true",
        "isAdvanceSearch": "true",
        "view": "list",
        "recordsPerPage": "20",
        "deviceType": "desktop-web",
    }
    pid = (property_id or "").strip()
    if pid:
        if re.fullmatch(r"[A-Za-z]{5}", pid):
            q["propertyCode"] = pid.upper()
            q["marriottId"] = pid.upper()
        else:
            q["hotelName"] = pid
    return q


def search_url(**kwargs: Any) -> str:
    return SEARCH + "?" + urlencode(search_query(**kwargs))


def session_view(snap: dict[str, Any]) -> dict[str, Any]:
    acct = snap.get("account") or {}
    return {
        "signed_in": bool(snap.get("signed_in")),
        "member_first_name": snap.get("member_first_name"),
        "elite": acct.get("elite"),
        "points": acct.get("points"),
        "url": snap.get("url"),
    }


def ensure_session() -> dict[str, Any]:
    open_context()
    p = page()
    if "marriott.com" not in (p.url or ""):
        snap = goto("https://www.marriott.com/", name="search-home")
    else:
        snap = snapshot(p, "search-session")
    if not snap.get("signed_in"):
        snap = do_login()
    return snap


def _extract_hotels(p) -> list[dict[str, Any]]:
    return p.evaluate(
        """() => {
          const hotels = [];
          const seen = new Set();
          const anchors = Array.from(document.querySelectorAll('a[href*="/hotels/"]'));
          for (const a of anchors) {
            const href = (a.href || '').split('?')[0];
            const m = href.match(/\\/hotels\\/([a-z0-9-]+)\\//i);
            if (!m) continue;
            const slug = m[1];
            const marsha = (slug.match(/^([a-z]{5})-/i) || [])[1];
            const key = marsha || slug;
            if (seen.has(key)) continue;
            seen.add(key);
            const name = (a.getAttribute('aria-label') || a.innerText || '')
              .trim().split('\\n')[0].slice(0, 120);
            if (!name) continue;
            hotels.push({
              name,
              property_id: (marsha || slug).toUpperCase(),
              slug,
              url: href,
            });
            if (hotels.length >= 20) break;
          }
          return hotels;
        }"""
    )


def _url_dates(url: str) -> dict[str, str | None]:
    frm = re.search(r"fromDate=([^&]+)", url or "")
    to = re.search(r"toDate=([^&]+)", url or "")
    from urllib.parse import unquote

    def dec(m):
        return unquote(m.group(1).replace("+", " ")) if m else None

    return {"fromDate_in_url": dec(frm), "toDate_in_url": dec(to)}


def search_properties(
    *,
    destination: str,
    checkin: str,
    checkout: str,
    rooms: int = 1,
    adults: int = 1,
    property_id: str | None = None,
) -> dict[str, Any]:
    dest = (destination or "").strip()
    if not dest:
        return {"ok": False, "error": "destination required"}
    try:
        q = search_query(
            destination=dest,
            checkin=checkin,
            checkout=checkout,
            rooms=rooms,
            adults=adults,
            property_id=property_id,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    snap = ensure_session()
    url = SEARCH + "?" + urlencode(q)
    page_data = goto(url, name="mcp-search")
    p = page()
    p.wait_for_timeout(3000)
    hotels = _extract_hotels(p)
    applied = _url_dates(p.url)
    dates_ok = (
        applied.get("fromDate_in_url") == q["fromDate"]
        and applied.get("toDate_in_url") == q["toDate"]
    )
    return {
        "ok": True,
        "session": session_view({**snap, **page_data, "url": p.url}),
        "dates": {
            "checkin": q["fromDate"],
            "checkout": q["toDate"],
            "nights": int(q["lengthOfStay"]),
            "applied_on_site": dates_ok,
            **applied,
        },
        "search_url": p.url,
        "count": len(hotels),
        "properties": hotels,
        "note": (
            None
            if hotels
            else "no property cards parsed; use marriott_availability with property_id"
        ),
    }


def property_availability(
    *,
    property_id: str,
    checkin: str,
    checkout: str,
    rooms: int = 1,
    adults: int = 1,
    destination: str | None = None,
) -> dict[str, Any]:
    pid = (property_id or "").strip()
    if not pid:
        return {"ok": False, "error": "property_id required (MARSHA code or slug)"}
    try:
        frm, to = mmddyyyy(checkin), mmddyyyy(checkout)
        nights = nights_between(checkin, checkout)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    snap = ensure_session()
    marsha = pid.split("-")[0].upper() if re.match(r"^[A-Za-z]{5}", pid) else pid
    qs = urlencode(
        {
            "isSearch": "true",
            "propertyCode": marsha,
            "fromDate": frm,
            "toDate": to,
            "fromDateDefaultFormat": frm,
            "toDateDefaultFormat": to,
            "lengthOfStay": str(nights),
            "numberOfRooms": str(int(rooms or 1)),
            "numAdultsPerRoom": str(int(adults or 1)),
        }
    )
    url = f"{AVAIL}?{qs}"
    page_data = goto(url, name="mcp-availability")
    p = page()
    if "error" in (p.url or "").lower() or "findHotels" in (p.url or "") and destination:
        alt = search_properties(
            destination=destination or pid,
            checkin=checkin,
            checkout=checkout,
            rooms=rooms,
            adults=adults,
            property_id=pid,
        )
        alt["availability_url"] = url
        return alt
    hotels = _extract_hotels(p)
    applied = _url_dates(p.url)
    body = ""
    try:
        body = p.inner_text("body")[:2000]
    except Exception:
        body = ""
    rates = []
    for line in body.splitlines():
        if re.search(r"\$\s?\d|points|/night|per night", line, re.I):
            t = " ".join(line.split())
            if 8 < len(t) < 160:
                rates.append(t)
            if len(rates) >= 8:
                break
    overview = None
    mslug = re.search(r"/hotels/([a-z0-9-]+)/", p.url or "", re.I)
    if hotels:
        overview = hotels[0]
    elif mslug:
        slug = mslug.group(1)
        overview = {
            "property_id": slug.split("-")[0].upper(),
            "slug": slug,
            "url": p.url.split("?")[0],
            "name": (page_data.get("title") or slug),
        }
    return {
        "ok": True,
        "session": session_view({**snap, **page_data, "url": p.url}),
        "dates": {
            "checkin": frm,
            "checkout": to,
            "nights": nights,
            "applied_on_site": applied.get("fromDate_in_url") == frm,
            **applied,
        },
        "property": overview,
        "property_url": (overview or {}).get("url") or p.url,
        "availability_url": p.url,
        "rate_lines": rates,
        "properties": hotels,
    }
