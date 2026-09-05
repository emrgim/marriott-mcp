#!/usr/bin/env python3
"""Mini-server HTTP: visualizza/controlla l'account Marriott via sessione Chrome."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.browser import (
    ACTIVITY,
    HOME,
    TRIPS,
    close_context,
    do_login,
    goto,
    goto_account,
    open_context,
    page,
    snapshot,
)

app = FastAPI(title="Marriott Dash", version="0.1.0")


class LoginBody(BaseModel):
    email: str | None = None
    password: str | None = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "marriott-dash"}


@app.post("/session/open")
def session_open() -> dict:
    open_context()
    return goto(HOME, name="session-open")


@app.post("/session/close")
def session_close() -> dict:
    close_context()
    return {"ok": True}


@app.get("/status")
def status() -> dict:
    open_context()
    p = page()
    if "marriott.com" not in (p.url or ""):
        return goto(HOME, name="status")
    return snapshot(p, "status")


@app.get("/me")
def me() -> dict:
    data = goto_account(TRIPS, name="me")
    if data.get("denied"):
        raise HTTPException(403, "Akamai blocked the page")
    if not data.get("signed_in"):
        raise HTTPException(401, "Not signed in")
    return data


@app.get("/trips")
def trips() -> dict:
    data = goto_account(TRIPS, name="trips")
    if data.get("denied"):
        raise HTTPException(403, "Akamai blocked the page")
    return data


@app.get("/activity")
def activity() -> dict:
    data = goto_account(ACTIVITY, name="activity")
    if data.get("denied"):
        raise HTTPException(403, "Akamai blocked the page")
    return data


@app.post("/login")
def login(body: LoginBody | None = None) -> dict:
    email = body.email if body else None
    password = body.password if body else None
    open_context()
    out = do_login(email, password)
    if out.get("error"):
        raise HTTPException(400, out["error"])
    return out


def main() -> None:
    import uvicorn

    port = int(os.environ.get("MARRIOTT_PORT", "8876"))
    uvicorn.run("src.server:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
