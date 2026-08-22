from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.jobs.refresh_evening_slate import build_evening_slate_batch
from odds_analyzer.sources.api_football import (
    BEIJING,
    ApiFootballMatchNews,
    ConfirmedLineup,
    PlayerAbsence,
    TeamNews,
    fetch_evening_api_football_news,
)


class ApiFootballSourceTest(unittest.TestCase):
    def test_fetches_date_injuries_and_near_kickoff_confirmed_lineups(self):
        fixture_payload = {
            "response": [
                {
                    "fixture": {"id": 9001, "date": "2026-08-22T11:30:00Z"},
                    "league": {"id": 39},
                    "teams": {
                        "home": {"id": 10, "name": "Everton"},
                        "away": {"id": 20, "name": "Crystal Palace"},
                    },
                }
            ]
        }
        injury_payload = {
            "response": [
                {
                    "fixture": {"id": 9001},
                    "team": {"id": 10, "name": "Everton"},
                    "player": {
                        "id": 100,
                        "name": "Home Player",
                        "type": "Injury",
                        "reason": "Hamstring",
                    },
                }
            ]
        }
        lineup_payload = {
            "response": [
                {
                    "team": {"id": 10, "name": "Everton"},
                    "formation": "4-3-3",
                    "startXI": [{"player": {"name": f"Home {index}"}} for index in range(1, 12)],
                },
                {
                    "team": {"id": 20, "name": "Crystal Palace"},
                    "formation": "3-4-2-1",
                    "startXI": [{"player": {"name": f"Away {index}"}} for index in range(1, 12)],
                },
            ]
        }
        responses = [
            (fixture_payload, 98),
            ({"response": []}, 97),
            (injury_payload, 96),
            ({"response": []}, 95),
            (lineup_payload, 94),
        ]

        with patch("odds_analyzer.sources.api_football._get_json", side_effect=responses) as get_json:
            batch = fetch_evening_api_football_news(
                "key",
                "2026-08-22",
                ("PL",),
                now=datetime(2026, 8, 22, 18, 30, tzinfo=BEIJING),
            )

        self.assertEqual(get_json.call_count, 5)
        self.assertEqual(batch.requests_made, 5)
        self.assertEqual(batch.remaining_requests, 94)
        self.assertFalse(batch.errors)
        self.assertEqual(len(batch.matches), 1)
        match = batch.matches[0]
        self.assertEqual(match.home.absences[0].player_name, "Home Player")
        self.assertEqual(match.home.lineup.formation, "4-3-3")
        self.assertEqual(len(match.away.lineup.starting_xi), 11)
        self.assertEqual(match.queried_at, "2026-08-22T18:30:00+08:00")

    def test_skips_lineup_calls_outside_ninety_minute_window(self):
        fixture_payload = {
            "response": [
                {
                    "fixture": {"id": 9001, "date": "2026-08-22T14:00:00Z"},
                    "league": {"id": 39},
                    "teams": {
                        "home": {"id": 10, "name": "Everton"},
                        "away": {"id": 20, "name": "Crystal Palace"},
                    },
                }
            ]
        }
        responses = [
            (fixture_payload, 98),
            ({"response": []}, 97),
            ({"response": []}, 96),
            ({"response": []}, 95),
        ]

        with patch("odds_analyzer.sources.api_football._get_json", side_effect=responses) as get_json:
            batch = fetch_evening_api_football_news(
                "key",
                "2026-08-22",
                ("PL",),
                now=datetime(2026, 8, 22, 18, 0, tzinfo=BEIJING),
            )

        self.assertEqual(get_json.call_count, 4)
        self.assertIsNone(batch.matches[0].home.lineup)


    def test_dashboard_batch_attaches_team_news_and_bilingual_status(self):
        project_root = Path(__file__).resolve().parents[1]
        existing = json.loads(
            (project_root / "dashboard" / "data" / "daily_matches.json").read_text(
                encoding="utf-8"
            )
        )
        news = ApiFootballMatchNews(
            fixture_id=9100,
            competition_code="PD",
            kickoff_time="2026-08-22 23:00",
            home=TeamNews(
                team_id=1,
                team_name="Athletic Bilbao",
                absences=(PlayerAbsence("Home Player", "Injury", "Knee"),),
                lineup=ConfirmedLineup("4-2-3-1", tuple(f"Home {i}" for i in range(1, 12))),
            ),
            away=TeamNews(
                team_id=2,
                team_name="Sevilla FC",
                absences=(),
                lineup=None,
            ),
        )

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            api_football_news=[news],
            team_news_source="API-Football: 1 fixtures; remaining 94",
            analysis_competitions=("PD",),
        )

        match = next(item for item in batch["current_matches"] if item["home_team"] == "Athletic Club")
        self.assertEqual(batch["slate"]["team_news_source"], "API-Football: 1 fixtures; remaining 94")
        self.assertEqual(match["team_news"]["home"]["absences"][0]["player"], "Home Player")
        self.assertEqual(match["team_news"]["home"]["lineup"]["formation"], "4-2-3-1")
        self.assertIn("queried_at", match["team_news"])
        self.assertIn("API-Football", match["sources"])
        self.assertIn("1 条确认缺阵", match["report_zh"])
        self.assertIn("official lineups for 1/2 teams", match["report_en"])

if __name__ == "__main__":
    unittest.main()
