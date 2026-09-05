---
name: marriott-stays
description: Use when listing Bonvoy stays, elite status, points, or upcoming trips on Marriott Dash MCP. Read-only tools only.
version: 1.0.0
---

# Marriott stays (read-only)

Load this skill together with the Marriott Dash tools. Do not invent extra write tools from this skill.

## Tools

- `marriott_status` — session, signed_in, first name
- `marriott_open` — open marriott.com
- `marriott_login` — only if signed_in is false; prefer server env credentials
- `marriott_me` — account overview (points, elite, nights)
- `marriott_trips` — upcoming reservations (does not cancel)
- `marriott_activity` — activity HTML snapshot
- `marriott_stays` — GraphQL stay history (preferred)
- `marriott_goto` — only for a specific marriott.com URL

## marriott_stays

Default `months=240` (full history, not the site's 24-month cap). `types=stay|all|bonus`. `property_contains` filters one hotel.

Call once, then summarize nights by property. Do not dump member numbers or full PII.

## Safety

This skill is read-only. Create / modify / cancel is a different skill: `skill://marriott-reservations/SKILL.md`.
