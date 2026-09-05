---
name: marriott-reservations
description: Use when searching Marriott hotels, checking availability, or creating/modifying/cancelling a reservation. Never web-search hotel URLs. Writes always pause on elicitation/create.
version: 1.1.0
---

# Marriott reservations

Do **not** use web search for property URLs, hotel details, or rates. Those come from MCP.

## Order of tools

1. `marriott_status` — confirm `signed_in`. If false, `marriott_login` (server env).
2. `marriott_search` — destination + checkin + checkout. Returns `properties[].property_id`, `url`, and `dates` actually applied on marriott.com (`MM/DD/YYYY`).
3. `marriott_availability` — one `property_id` + same dates. Returns `property_url` and `rate_lines`.
4. `marriott_reservation_create` — same destination/dates/`property_id`. Pauses on elicitation.

Dates: `YYYY-MM-DD` or `MM/DD/YYYY`. The server always sends Marriott `fromDate`/`toDate` as `MM/DD/YYYY` with `searchType=InCity` and occupancy. Do not pass ISO dates straight into a Marriott URL yourself.

## Write tools

- `marriott_reservation_create`
- `marriott_reservation_modify`
- `marriott_reservation_cancel`

Every write **must** go through `elicitation/create`. Execute only if `action=accept` and `content.confirm=true`.

See `references/elicitation.md`.

## Payment

No cards via elicitation. If checkout shows a card form, stop.
