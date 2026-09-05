"""Sessione Chrome persistente verso marriott.com (account utente)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / ".session" / "verify-chrome-profile"
SHOTS = ROOT / ".session" / "shots"
STATE = ROOT / ".session" / "state.json"

HOME = "https://www.marriott.com/"
SIGNIN = "https://www.marriott.com/sign-in.mi"
TRIPS = "https://www.marriott.com/loyalty/myAccount/default.mi"
ACTIVITY = "https://www.marriott.com/loyalty/myAccount/activity.mi"

_pw = None
_ctx: BrowserContext | None = None


from src.creds import load_creds  # noqa: E402


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    load_creds()


load_dotenv()


def _ensure_dirs() -> None:
    PROFILE.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)


def open_context() -> BrowserContext:
    global _pw, _ctx
    if _ctx is not None:
        return _ctx
    _ensure_dirs()
    _pw = sync_playwright().start()
    _ctx = _pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="chrome",
        headless=False,
        viewport={"width": 1400, "height": 900},
        locale="en-US",
        args=["--disable-blink-features=AutomationControlled"],
    )
    return _ctx


def close_context() -> None:
    global _pw, _ctx
    if _ctx is not None:
        _ctx.close()
        _ctx = None
    if _pw is not None:
        _pw.stop()
        _pw = None


def page() -> Page:
    ctx = open_context()
    if ctx.pages:
        return ctx.pages[0]
    return ctx.new_page()


def _signed_in(body: str) -> bool:
    """BUG-007/010: remembered 'Sign In, Name'; full session 'Hello, Name'."""
    if re.search(r"sign in,\s+\w+", body, re.I):
        return True
    if re.search(r"hello,\s+\w+", body, re.I):
        return True
    if re.search(r"\bsign out\b", body, re.I):
        return True
    if "lifetime" in body.lower() and "elite" in body.lower():
        return True
    return False


def parse_account(body: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(r"([\d,]+)\s+Points", body, re.I)
    if m:
        out["points"] = int(m.group(1).replace(",", ""))
    m = re.search(r"([\d,]+)\s+nights", body, re.I)
    if m:
        out["nights"] = int(m.group(1).replace(",", ""))
    m = re.search(r"(Lifetime\s+\w+\s+Elite)", body, re.I)
    if m:
        out["lifetime_status"] = m.group(1)
    for status in (
        "Ambassador Elite",
        "Titanium Elite",
        "Platinum Elite",
        "Gold Elite",
        "Silver Elite",
    ):
        if status.lower() in body.lower():
            out["elite"] = status
            break
    m = re.search(r"Hi,\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", body)
    if m:
        out["name"] = m.group(1).strip()
    m = re.search(r"Member Since\s+([A-Za-z]+\s+\d{4})", body, re.I)
    if m:
        out["member_since"] = m.group(1)
    m = re.search(r"\b(\d{8,})\b", body)
    if m:
        out["member_number"] = m.group(1)
    return out


def snapshot(p: Page, name: str) -> dict[str, Any]:
    shot = SHOTS / f"{name}.png"
    try:
        p.screenshot(path=str(shot), full_page=False)
    except Exception as exc:  # noqa: BLE001
        shot = Path(str(shot) + ".fail")
        shot.write_text(str(exc), encoding="utf-8")
    body = ""
    try:
        body = p.inner_text("body")[:8000]
    except Exception:
        body = ""
    title = ""
    try:
        title = p.title()
    except Exception:
        pass
    denied = (
        "access denied" in body.lower()
        or "pardon our interruption" in body.lower()
        or "access denied" in title.lower()
    )
    m = re.search(r"(?:sign in|hello),\s+([A-Za-z][A-Za-z\-']+)", body, re.I)
    data = {
        "url": p.url,
        "title": title,
        "denied": denied,
        "signed_in": _signed_in(body),
        "member_first_name": m.group(1) if m else None,
        "account": parse_account(body),
        "body_excerpt": body[:2500],
        "screenshot": str(shot) if shot.exists() else None,
    }
    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def goto(url: str, name: str = "page") -> dict[str, Any]:
    p = page()
    p.goto(url, wait_until="domcontentloaded", timeout=60_000)
    p.wait_for_timeout(4_000)
    return snapshot(p, name)


def env_creds() -> tuple[str, str]:
    load_dotenv()
    return os.environ.get("MARRIOTT_EMAIL", "").strip(), os.environ.get(
        "MARRIOTT_PASSWORD", ""
    ).strip()


def complete_step_up() -> dict[str, Any]:
    """BUG-008: remembered user still needs password for /loyalty/*."""
    p = page()
    body = ""
    try:
        body = p.inner_text("body")
    except Exception:
        body = ""
    if "please enter the password" not in body.lower():
        return snapshot(p, "no-stepup")
    _, password = env_creds()
    if not password:
        return {"error": "missing password for step-up", "signed_in": False}
    pwd_box = p.locator('input[type="password"]').first
    pwd_box.wait_for(state="visible", timeout=15_000)
    pwd_box.click()
    pwd_box.fill("")
    pwd_box.type(password, delay=40)
    p.wait_for_timeout(400)
    filled_len = len(pwd_box.input_value() or "")
    form = p.locator("form").filter(has_text="Forgot password")
    if form.count():
        form.get_by_role("button", name="Sign In", exact=True).click()
    else:
        pwd_box.press("Enter")
    p.wait_for_timeout(12_000)
    data = snapshot(p, "stepup-after")
    data["password_filled_len"] = filled_len
    return data


def goto_account(url: str, name: str = "account") -> dict[str, Any]:
    data = goto(url, name=name)
    excerpt = (data.get("body_excerpt") or "").lower()
    if "sign-in" in (data.get("url") or "") and "please enter the password" in excerpt:
        data = complete_step_up()
    return data


def do_login(email: str | None = None, password: str | None = None) -> dict[str, Any]:
    """BUG-005/006: aria-label fill, Sign In scoped to form, Enter fallback."""
    e, psw = env_creds()
    email = (email or e).strip()
    password = (password or psw).strip()
    if not email or not password:
        return {"error": "missing credentials", "signed_in": False}
    p = page()
    p.goto(SIGNIN, wait_until="domcontentloaded", timeout=60_000)
    p.wait_for_timeout(2500)
    for label in ("Accept All", "Accept"):
        btn = p.get_by_role("button", name=label, exact=False)
        if btn.count() and btn.first.is_visible():
            btn.first.click()
            p.wait_for_timeout(800)
            break
    email_box = p.get_by_label("email or member number", exact=False)
    email_box.wait_for(state="visible", timeout=20_000)
    email_box.fill(email)
    pwd_box = p.get_by_label("sign in password", exact=False)
    pwd_box.fill(password)
    p.wait_for_timeout(300)
    form = p.locator("form").filter(has_text="Forgot password")
    if form.count():
        form.get_by_role("button", name="Sign In", exact=True).click()
    else:
        pwd_box.press("Enter")
    p.wait_for_timeout(10_000)
    return snapshot(p, "login-after")


ACTIVITY_QUERY = (ROOT / "src" / "queries" / "activity.graphql").read_text()
GQL_ACTIVITY = "https://www.marriott.com/mi/query/phoenixAccountGetMyActivityTable"
USER_DETAILS = "https://www.marriott.com/mi/phoenix-account-auth/v2/userDetails"
_GQL_SEED: dict[str, Any] = {}


def _capture_gql_seed() -> None:
    p = page()

    def on_req(req):
        if "phoenixAccountGetMyActivityTable" not in req.url:
            return
        raw = req.post_data
        if not raw:
            return
        _GQL_SEED["url"] = req.url
        _GQL_SEED["headers"] = dict(req.headers)
        _GQL_SEED["post"] = raw

    p.on("request", on_req)
    goto_account(ACTIVITY, name="gql-seed")
    p.wait_for_timeout(2500)


def customer_id() -> str:
    if not _GQL_SEED.get("post"):
        _capture_gql_seed()
    return json.loads(_GQL_SEED["post"])["variables"]["customerId"]


def flatten_activity_node(node: dict) -> dict[str, Any]:
    props = node.get("properties") or []
    hotel = (props[0].get("basicInformation") or {}) if props else {}
    typ = node.get("type") or {}
    return {
        "posted": node.get("postDate"),
        "start": node.get("startDate"),
        "end": node.get("endDate"),
        "type": typ.get("code"),
        "type_label": typ.get("description"),
        "description": node.get("description"),
        "property": hotel.get("name") or node.get("description"),
        "property_id": props[0].get("id") if props else None,
        "points": node.get("totalEarning"),
        "base": node.get("baseEarning"),
        "elite": node.get("eliteEarning"),
        "extra": node.get("extraEarning"),
        "qualifying": node.get("isQualifyingActivity"),
    }


def fetch_activity_page(
    *,
    months: int,
    types: str,
    offset: int,
    limit: int | None,
    cid: str | None = None,
) -> dict[str, Any]:
    cid = cid or customer_id()
    if not _GQL_SEED.get("url"):
        _capture_gql_seed()
    payload = {
        "operationName": "phoenixAccountGetMyActivityTable",
        "variables": {
            "customerId": cid,
            "numberOfMonths": months,
            "types": types,
            "limit": limit,
            "offset": offset,
            "filter": None,
        },
        "query": ACTIVITY_QUERY,
    }
    hdrs = {
        k: v
        for k, v in (_GQL_SEED.get("headers") or {}).items()
        if k.lower() not in ("content-length", "host")
    }
    hdrs["content-type"] = "application/json"
    resp = page().request.post(
        _GQL_SEED["url"],
        headers=hdrs,
        data=json.dumps(payload),
        timeout=60_000,
    )
    try:
        js = resp.json()
    except Exception:
        js = None
    return {"ok": resp.status == 200, "status": resp.status, "json": js}


def fetch_stays(
    *,
    months: int = 240,
    types: str = "stay",
    page_size: int = 50,
    max_pages: int = 200,
    property_contains: str | None = None,
) -> dict[str, Any]:
    """Paginate GraphQL. months=240 ≈ 20 years; no UI 24-month cap."""
    goto_account(ACTIVITY, name="stays-session")
    cid = customer_id()
    stays: list[dict[str, Any]] = []
    offset = 0
    total = None
    pages = 0
    while pages < max_pages:
        raw = fetch_activity_page(
            months=months, types=types, offset=offset, limit=page_size, cid=cid
        )
        if not raw.get("ok"):
            return {"error": raw, "stays": stays, "count": len(stays)}
        js = raw.get("json") or {}
        act = (
            ((js.get("data") or {}).get("customer") or {})
            .get("loyaltyInformation", {})
            .get("accountActivity")
            or {}
        )
        total = act.get("total")
        edges = act.get("edges") or []
        if not edges:
            break
        for e in edges:
            rec = flatten_activity_node(e.get("node") or {})
            if property_contains:
                blob = f"{rec.get('property') or ''} {rec.get('property_id') or ''}"
                if property_contains.lower() not in blob.lower():
                    continue
            stays.append(rec)
        pages += 1
        if total is not None and offset + len(edges) >= int(total):
            break
        if len(edges) < (page_size or 1):
            break
        offset += len(edges)
    dates = [s.get("start") for s in stays if s.get("start")]
    ends = [s.get("end") for s in stays if s.get("end")]
    return {
        "count": len(stays),
        "reported_total": total,
        "months_requested": months,
        "types": types,
        "pages": pages,
        "earliest_start": min(dates) if dates else None,
        "latest_end": max(ends) if ends else None,
        "stays": stays,
    }


def fetch_activity(
    *,
    months: int = 240,
    types: str = "all",
    page_size: int = 50,
    max_pages: int = 200,
) -> dict[str, Any]:
    """All activity types via GraphQL. months=240 ≈ 20 years; not the UI 3-month filter."""
    raw = fetch_stays(
        months=months,
        types=types,
        page_size=page_size,
        max_pages=max_pages,
    )
    if "stays" in raw:
        raw["entries"] = raw.pop("stays")
    return raw
