from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.dashboard_payload import merge_dashboard_payload
from odds_analyzer.fallback_queue import build_fallback_requests, merge_fallback_requests


def complete_match() -> dict:
    return {
        "id": "match-1",
        "batch_date": "2026-08-22",
        "kickoff_time": "2026-08-22 22:00",
        "competition": "英超",
        "home_team": "Everton",
        "away_team": "Crystal Palace",
        "fundamental_context": {
            "home": {"position": 10, "form": ["W", "D"]},
            "away": {"position": 12, "form": ["L", "W"]},
        },
        "european_odds": {"home": 2.0, "draw": 3.3, "away": 3.8},
        "asian_handicap": {"handicap": -0.5, "home_odds": 1.95, "away_odds": 1.95},
        "chinese_lottery": {"handicap": -1},
    }


class FallbackQueueTest(unittest.TestCase):
    def test_complete_match_does_not_create_request(self):
        self.assertEqual(build_fallback_requests([complete_match()], {}, scope="daily"), [])

    def test_missing_market_creates_source_backed_search_task(self):
        match = complete_match()
        match["chinese_lottery"] = None

        requests = build_fallback_requests(
            [match],
            {"sporttery_source": "Sporttery unavailable: HTTPError"},
            scope="daily",
        )

        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request["missing_fields"], ["sporttery"])
        self.assertEqual(request["failure_type"], "source_failure")
        self.assertIn("竞彩", request["search_queries"][0])

    def test_fixture_only_snapshot_is_not_treated_as_fundamentals(self):
        match = complete_match()
        match["football_data_snapshot"] = {"match_id": 1}
        match["fundamental_context"] = {"home": {"team_id": 1}, "away": {"team_id": 2}}

        request = build_fallback_requests([match], {}, scope="adhoc")[0]

        self.assertIn("fundamentals", request["missing_fields"])

    def test_replacing_daily_queue_preserves_adhoc_requests(self):
        existing = [
            {"id": "daily:old", "scope": "daily"},
            {"id": "adhoc:keep", "scope": "adhoc"},
        ]
        fresh = [{"id": "daily:new", "scope": "daily"}]

        merged = merge_fallback_requests(existing, fresh, replace_scope="daily")

        self.assertEqual([item["id"] for item in merged], ["daily:new", "adhoc:keep"])

    def test_dashboard_merge_replaces_only_daily_fallback_tasks(self):
        existing = {
            "current_matches": [],
            "mismatch_history": [],
            "checker_history": [],
            "fallback_requests": [{"id": "adhoc:keep", "scope": "adhoc"}],
        }
        batch = {
            "slate": {"date": "2026-08-22"},
            "current_matches": [],
            "mismatch_history": [],
            "checker_history": [],
            "fallback_requests": [{"id": "daily:new", "scope": "daily"}],
        }

        merged = merge_dashboard_payload(existing, batch)

        self.assertEqual(
            [item["id"] for item in merged["fallback_requests"]],
            ["daily:new", "adhoc:keep"],
        )

    def test_dashboard_exposes_pending_fallback_count(self):
        project_root = Path(__file__).resolve().parents[1]
        index = (project_root / "dashboard" / "index.html").read_text(encoding="utf-8")
        app = (project_root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="fallbackCount"', index)
        self.assertIn("payload.fallback_requests", app)
        self.assertIn("state.fallbackRequests", app)


if __name__ == "__main__":
    unittest.main()
