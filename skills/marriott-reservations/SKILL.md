---
name: marriott-reservations
description: Use when creating, modifying, or cancelling a Marriott reservation via Marriott Dash MCP. Writes always pause on elicitation/create.
version: 1.0.0
---

# Marriott reservations (writes)

Companion skill for the write tools. Tools and this manual ship together.

## Tools

- `marriott_reservation_create` — destination, checkin, checkout required
- `marriott_reservation_modify` — confirmation_number required
- `marriott_reservation_cancel` — confirmation_number required

## Hard rule (elicitation)

Every write **must** go through MCP `elicitation/create`. The tool stays paused until the user hits **Conferma** or **Annulla**.

Execute Playwright **only** if the elicitation result is `action=accept` and `content.confirm=true`.

On decline, cancel, timeout, or `confirm=false`: `changed=false`, `executed=false`. Do not retry the write without a new elicitation.

Never skip elicitation. Never pass `confirm=true` as a tool argument to bypass it — that is not how this server works.

See `references/elicitation.md`.

## Payment

Do not collect cards, CVV, or passwords via elicitation (MCP spec). If checkout shows a card form, stop.

## Read first

Upcoming trips: `marriott_trips`. History: `skill://marriott-stays/SKILL.md`.
