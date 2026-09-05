#!/usr/bin/env python3
"""Verify Bonvoy credentials in real headed Chrome (not headless)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = ROOT / ".session" / "shots"
PROFILE = ROOT / ".session" / "verify-chrome-profile"


def load_env() -> tuple[str, str]:
    env_path = ROOT / ".env"
    data = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    email = data.get("MARRIOTT_EMAIL", "")
    password = data.get("MARRIOTT_PASSWORD", "")
    if not email or not password:
        raise SystemExit("missing creds in .env")
    return email, password


def classify(url: str, title: str, body: str) -> str:
    b = body.lower()
    t = title.lower()
    if any(x in b for x in ("incorrect", "doesn't match", "does not match", "invalid password", "we don't recognize")):
        return "bad_credentials"
    if any(x in b for x in ("verification", "one-time", "one time", "two-step", "two step", "enter the code", "security code")):
        return "mfa"
    if "pardon our interruption" in b or "access denied" in b:
        return "akamai"
    if any(x in b for x in ("sign out", "account activity")) or "my trips" in t:
        return "signed_in"
    if "sign-in" in url or "sign in" in t:
        return "still_on_login"
    return "unknown"


def main() -> int:
    email, password = load_env()
    SHOTS.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DISPLAY", ":0")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.marriott.com/sign-in.mi", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)

        # cookie banner if present
        for label in ("Accept All", "Accept", "Agree"):
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1000)
                break

        page.screenshot(path=str(SHOTS / "verify-before-fill.png"))
        fields = page.evaluate(
            """() => Array.from(document.querySelectorAll('input')).map(el => ({
                type: el.type, name: el.name, id: el.id,
                placeholder: el.placeholder, aria: el.getAttribute('aria-label'),
                visible: !!(el.offsetWidth || el.offsetHeight)
            }))"""
        )
        print("FIELDS", json.dumps(fields)[:2000])
        print("URL_BEFORE", page.url, "TITLE", page.title())

        email_box = page.get_by_placeholder("Email or Member Number")
        if not email_box.count():
            email_box = page.get_by_label("email or member number", exact=False)
        if not email_box.count():
            email_box = page.locator('input[type="text"]').first
        email_box.wait_for(state="visible", timeout=15_000)
        email_box.click()
        email_box.fill(email)
        pwd_box = page.get_by_placeholder("Password")
        if not pwd_box.count():
            pwd_box = page.get_by_label("sign in password", exact=False)
        if not pwd_box.count():
            pwd_box = page.locator('input[type="password"]').first
        pwd_box.click()
        pwd_box.fill(password)
        page.wait_for_timeout(500)
        filled = {
            "email_value": email_box.input_value(),
            "password_len": len(pwd_box.input_value() or ""),
        }
        page.screenshot(path=str(SHOTS / "verify-filled.png"))

        form = page.locator("form").filter(has_text="Forgot password")
        if form.count():
            form.get_by_role("button", name="Sign In", exact=True).click()
        else:
            pwd_box.press("Enter")

        page.wait_for_timeout(10_000)
        page.screenshot(path=str(SHOTS / "verify-after.png"))
        body = page.inner_text("body")[:4000]
        result = {
            "email": email,
            "url": page.url,
            "title": page.title(),
            "filled": filled,
            "verdict": classify(page.url, page.title(), body),
            "excerpt": body[:1200],
            "shots": {
                "filled": str(SHOTS / "verify-filled.png"),
                "after": str(SHOTS / "verify-after.png"),
            },
        }
        print(json.dumps(result, indent=2))
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
