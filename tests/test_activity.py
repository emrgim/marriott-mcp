import unittest

from src.activity import (
    flatten_activity_node,
    normalize_types,
    parse_account_activity,
    summarize_entries,
)

STAY_NODE = {
    "__typename": "LoyaltyAccountActivity",
    "description": "EL ME'AISAM, DUBAI",
    "endDate": "2026-08-19",
    "postDate": "2026-08-20",
    "properties": [
        {
            "basicInformation": {
                "name": "Element by Marriott Me'aisam, Dubai",
                "brand": {"id": "EL"},
            },
            "id": "DXBEL",
        }
    ],
    "startDate": "2026-07-20",
    "type": {"code": "STAY", "description": "Hotel Stay"},
    "actions": [
        {
            "actionDate": "2026-07-20",
            "totalEarning": 320,
            "type": {"code": "canceled", "description": "Canceled"},
        }
    ],
    "baseEarning": 183,
    "currency": {"code": "HP"},
    "eliteEarning": 137,
    "extraEarning": 0,
    "isQualifyingActivity": True,
    "partner": None,
    "totalEarning": 320,
}

BONUS_NODE = {
    "description": "ENBD MC BASE SPEND",
    "postDate": "2026-09-04",
    "type": {"code": "BONUS", "description": "Bonus"},
    "totalEarning": 57,
    "properties": [],
    "partner": {"type": {"code": "CREDITCARD", "description": "Credit Card"}},
    "currency": {"code": "HP"},
}


class ActivityTests(unittest.TestCase):
    def test_flatten_stay(self):
        rec = flatten_activity_node(STAY_NODE)
        self.assertEqual(rec["type"], "STAY")
        self.assertEqual(rec["property_id"], "DXBEL")
        self.assertEqual(rec["points"], 320)
        self.assertEqual(rec["currency"], "HP")
        self.assertEqual(rec["start"], "2026-07-20")
        self.assertEqual(rec["actions"][0]["type"], "canceled")
        self.assertIsNone(rec["partner"])

    def test_flatten_bonus_partner(self):
        rec = flatten_activity_node(BONUS_NODE)
        self.assertEqual(rec["type"], "BONUS")
        self.assertEqual(rec["partner_code"], "CREDITCARD")
        self.assertEqual(rec["property"], "ENBD MC BASE SPEND")

    def test_parse_and_summarize(self):
        body = {
            "data": {
                "customer": {
                    "loyaltyInformation": {
                        "accountActivity": {
                            "total": 2,
                            "edges": [{"node": STAY_NODE}, {"node": BONUS_NODE}],
                        }
                    }
                }
            }
        }
        edges, total, errs = parse_account_activity(body)
        self.assertEqual(total, 2)
        self.assertIsNone(errs)
        entries = [flatten_activity_node(e["node"]) for e in edges]
        summary = summarize_entries(entries)
        self.assertEqual(summary["type_counts"], {"STAY": 1, "BONUS": 1})
        self.assertEqual(summary["points_total"], 377)

    def test_normalize_types(self):
        self.assertEqual(normalize_types("STAY"), "stay")
        self.assertEqual(normalize_types("nope"), "all")
        self.assertEqual(normalize_types(None), "all")


if __name__ == "__main__":
    unittest.main()
