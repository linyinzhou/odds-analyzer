from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.fallback_results import apply_fallback_results


QUERY_TIME = "2026-08-22T18:15:00+08:00"


def base_match() -> dict:
    return {
        "id": "match-1",
        "batch_date": "2026-08-22",
        "kickoff_time": "2026-08-22 22:00",
        "competition": "英超 第 1 轮",
        "home_team": "Everton",
        "away_team": "Crystal Palace",
        "venue": "待补",
        "weather": "待补",
        "fundamentals": [{"home": "基本面待补", "away": "基本面待补"}],
        "fundamental_context": {},
        "european_odds": None,
        "asian_handicap": None,
        "chinese_lottery": None,
        "status": "pending",
        "signal_label": "数据待补",
        "sources": [],
        "risks": ["数据待补"],
    }


def queue_request(scope: str = "daily") -> dict:
    return {
        "id": f"{scope}:match-1",
        "scope": scope,
        "status": "pending",
        "match_id": "match-1",
        "batch_date": "2026-08-22",
        "home_team": "Everton",
        "away_team": "Crystal Palace",
        "missing_fields": [
            "fundamentals",
            "european_odds",
            "asian_handicap",
            "sporttery",
        ],
    }


def source(name: str) -> list[dict]:
    return [
        {
            "name": name,
            "url": f"https://example.com/{name.lower().replace(' ', '-')}",
            "tier": "secondary",
            "queried_at": QUERY_TIME,
        }
    ]


def complete_result() -> dict:
    return {
        "request_id": "daily:match-1",
        "home_team": "Everton",
        "away_team": "Crystal Palace",
        "queried_at": QUERY_TIME,
        "fields": {
            "fundamentals": {
                "fundamental_context": {
                    "home": {
                        "position": 8,
                        "played_games": 3,
                        "points": 7,
                        "goal_difference": 3,
                        "form": ["W", "D", "W"],
                    },
                    "away": {
                        "position": 13,
                        "played_games": 3,
                        "points": 4,
                        "goal_difference": -1,
                        "form": ["L", "D", "W"],
                    },
                },
                "fundamentals": [
                    {
                        "home": "埃弗顿排名第8，近3场2胜1平。",
                        "away": "水晶宫排名第13，近3场1胜1平1负。",
                    }
                ],
                "venue": "Hill Dickinson Stadium",
            },
            "european_odds": {"home": 1.88, "draw": 3.55, "away": 4.20},
            "asian_handicap": {
                "provider": "Verified Bookmaker",
                "handicap": -0.5,
                "home_odds": 1.94,
                "away_odds": 1.96,
            },
            "sporttery": {
                "standard": {"home": 1.85, "draw": 3.40, "away": 4.10},
                "handicap": -1,
                "handicap_odds": {"home": 4.50, "draw": 3.55, "away": 1.60},
            },
        },
        "sources": {
            "fundamentals": source("League table"),
            "european_odds": source("Odds source"),
            "asian_handicap": source("Asian source"),
            "sporttery": source("Sporttery source"),
        },
    }


def payload() -> dict:
    return {
        "slate": {"date": "2026-08-22"},
        "current_matches": [base_match()],
        "adhoc_history": [],
        "mismatch_history": [
            {
                "id": "older",
                "batch_date": "2026-08-21",
                "home_team": "Old",
                "away_team": "Match",
            }
        ],
        "checker_history": [],
        "fallback_requests": [queue_request()],
    }


class FallbackResultsTest(unittest.TestCase):
    def apply(self, dashboard: dict, result: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            payload_path = Path(directory) / "daily_matches.json"
            results_path = Path(directory) / "fallback_results.json"
            payload_path.write_text(json.dumps(dashboard, ensure_ascii=False), encoding="utf-8")
            results_path.write_text(
                json.dumps({"results": [result]}, ensure_ascii=False),
                encoding="utf-8",
            )
            return apply_fallback_results(payload_path, results_path)

    def test_complete_result_is_validated_applied_and_reanalyzed(self):
        updated = self.apply(payload(), complete_result())

        match = updated["current_matches"][0]
        request = updated["fallback_requests"][0]
        self.assertEqual(match["venue"], "Hill Dickinson Stadium")
        self.assertEqual(match["european_odds"]["home"], 1.88)
        self.assertEqual(match["asian_handicap"]["handicap"], -0.5)
        self.assertEqual(match["chinese_lottery"]["handicap"], -1)
        self.assertEqual(request["status"], "resolved")
        self.assertEqual(request["missing_fields"], [])
        self.assertEqual(updated["last_fallback_import"]["field_count"], 4)
        self.assertIn("european_odds", match["fallback_research"])
        self.assertIn("report_zh", match)
        self.assertIn("report_en", match)
        self.assertTrue(match.get("recommendation"))
        self.assertTrue(any(item["id"] == "older" for item in updated["mismatch_history"]))
        self.assertIsInstance(updated["checker_history"], list)

    def test_partial_result_keeps_request_pending(self):
        result = complete_result()
        result["fields"] = {"european_odds": result["fields"]["european_odds"]}
        result["sources"] = {"european_odds": result["sources"]["european_odds"]}
        result["unresolved_reason"] = "Other markets could not be verified."

        updated = self.apply(payload(), result)

        request = updated["fallback_requests"][0]
        self.assertEqual(request["status"], "pending")
        self.assertNotIn("european_odds", request["missing_fields"])
        self.assertEqual(request["attempts"], 1)
        self.assertEqual(request["unresolved_reason"], "Other markets could not be verified.")

    def test_swapped_teams_are_rejected(self):
        result = complete_result()
        result["home_team"] = "Crystal Palace"
        result["away_team"] = "Everton"

        with self.assertRaisesRegex(ValueError, "home_team does not match"):
            self.apply(payload(), result)

    def test_existing_api_value_cannot_be_overwritten(self):
        dashboard = payload()
        dashboard["current_matches"][0]["european_odds"] = {
            "home": 1.90,
            "draw": 3.50,
            "away": 4.10,
        }

        with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
            self.apply(dashboard, complete_result())

    def test_invalid_source_url_is_rejected(self):
        result = complete_result()
        result["sources"]["european_odds"][0]["url"] = "not-a-url"

        with self.assertRaisesRegex(ValueError, r"HTTP\(S\) URL"):
            self.apply(payload(), result)

    def test_non_integer_sporttery_handicap_is_rejected(self):
        result = complete_result()
        result["fields"]["sporttery"]["handicap"] = -0.5

        with self.assertRaisesRegex(ValueError, "must be an integer"):
            self.apply(payload(), result)


if __name__ == "__main__":
    unittest.main()
