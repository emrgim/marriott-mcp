"""Parse Bonvoy GraphQL account activity (no Playwright)."""

from __future__ import annotations

from collections import Counter
from typing import Any

ACTIVITY_TYPES = ("all", "stay", "bonus")


def flatten_activity_node(node: dict) -> dict[str, Any]:
    props = node.get("properties") or []
    hotel = (props[0].get("basicInformation") or {}) if props else {}
    typ = node.get("type") or {}
    partner = node.get("partner") or {}
    ptyp = partner.get("type") or {}
    award = node.get("awardType") or {}
    actions = []
    for a in node.get("actions") or []:
        at = a.get("type") or {}
        actions.append(
            {
                "date": a.get("actionDate"),
                "points": a.get("totalEarning"),
                "type": at.get("code"),
                "type_label": at.get("description"),
            }
        )
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
        "currency": (node.get("currency") or {}).get("code"),
        "partner": ptyp.get("description"),
        "partner_code": ptyp.get("code"),
        "award_type": award.get("code"),
        "actions": actions,
    }


def parse_account_activity(js: dict | None) -> tuple[list[dict], int | None, list | None]:
    """Return (edges, total, graphql_errors) from a phoenixAccountGetMyActivityTable body."""
    js = js or {}
    errs = js.get("errors")
    act = (
        ((js.get("data") or {}).get("customer") or {})
        .get("loyaltyInformation", {})
        .get("accountActivity")
        or {}
    )
    total = act.get("total")
    edges = act.get("edges") or []
    return edges, total, errs


def summarize_entries(entries: list[dict]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    points: Counter[str] = Counter()
    for e in entries:
        t = str(e.get("type") or "UNKNOWN")
        counts[t] += 1
        try:
            points[t] += int(e.get("points") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "type_counts": dict(counts),
        "points_by_type": dict(points),
        "points_total": int(sum(points.values())),
    }


def normalize_types(types: str | None) -> str:
    raw = (types or "all").strip().lower()
    if raw not in ACTIVITY_TYPES:
        return "all"
    return raw
