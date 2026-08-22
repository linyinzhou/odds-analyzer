from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.jobs.refresh_adhoc_match import _find_match, refresh_adhoc_match
from odds_analyzer.models import AsianHandicapOdds, ThreeWayOdds
from odds_analyzer.sources import FootballDataFixture, OddsApiEvent, WeatherBatch
from odds_analyzer.sources.football_data import fetch_fixtures_for_beijing_date


class AdhocReportTest(unittest.TestCase):
    def test_beijing_date_fixture_fetch_filters_utc_boundary(self):
        payload = {
            "matches": [
                {
                    "id": 1,
                    "competition": {"code": "DED", "name": "Eredivisie"},
                    "utcDate": "2026-08-22T16:30:00Z",
                    "status": "TIMED",
                    "homeTeam": {"id": 10, "name": "NEC Nijmegen"},
                    "awayTeam": {"id": 20, "name": "SC Telstar"},
                },
                {
                    "id": 2,
                    "competition": {"code": "DED", "name": "Eredivisie"},
                    "utcDate": "2026-08-21T15:00:00Z",
                    "status": "TIMED",
                    "homeTeam": {"id": 30, "name": "Earlier FC"},
                    "awayTeam": {"id": 40, "name": "Away FC"},
                },
            ]
        }
        with patch("odds_analyzer.sources.football_data._get_json", return_value=payload) as get_json:
            fixtures = fetch_fixtures_for_beijing_date("key", "2026-08-23")

        self.assertEqual([fixture.match_id for fixture in fixtures], [1])
        get_json.assert_called_once_with(
            "/matches",
            "key",
            {"dateFrom": "2026-08-22", "dateTo": "2026-08-23"},
            20,
        )

    def test_team_match_requires_home_and_away_orientation(self):
        fixtures = (
            FootballDataFixture(
                match_id=1,
                competition_code="DED",
                competition_name="Eredivisie",
                utc_date="2026-08-22T18:00:00Z",
                kickoff_time="2026-08-23 02:00",
                home_team_id=10,
                home_team="NEC Nijmegen",
                away_team_id=20,
                away_team="SC Telstar",
                matchday=1,
                stage="REGULAR_SEASON",
                status="TIMED",
            ),
        )
        teams = lambda item: (item.home_team, item.away_team)
        self.assertIsNotNone(_find_match(fixtures, "NEC", "Telstar", teams))
        self.assertIsNone(_find_match(fixtures, "Telstar", "NEC", teams))

    def test_refresh_upserts_adhoc_history_without_changing_daily_lists(self):
        project_root = Path(__file__).resolve().parents[1]
        existing = json.loads(
            (project_root / "dashboard" / "data" / "daily_matches.json").read_text(encoding="utf-8")
        )
        preserved = {
            key: existing.get(key)
            for key in ("current_matches", "mismatch_history", "checker_history", "next_matchday")
        }
        fixture = FootballDataFixture(
            match_id=101,
            competition_code="DED",
            competition_name="Eredivisie",
            utc_date="2026-08-22T18:00:00Z",
            kickoff_time="2026-08-23 02:00",
            home_team_id=10,
            home_team="NEC Nijmegen",
            away_team_id=20,
            away_team="SC Telstar",
            matchday=1,
            stage="REGULAR_SEASON",
            status="TIMED",
            venue="Goffertstadion",
        )

        def odds(home_price: float) -> OddsApiEvent:
            return OddsApiEvent(
                event_id="odds-101",
                sport_key="soccer_netherlands_eredivisie",
                commence_time="2026-08-22T18:00:00Z",
                home_team="NEC Nijmegen",
                away_team="SC Telstar",
                bookmaker="Pinnacle",
                bookmaker_key="pinnacle",
                updated_at="2026-08-22T10:00:00Z",
                european_odds=ThreeWayOdds(home=home_price, draw=4.0, away=5.0),
                asian_handicap=AsianHandicapOdds(
                    handicap=-1.0,
                    home_odds=1.95,
                    away_odds=1.95,
                    provider="Pinnacle",
                ),
            )

        with tempfile.TemporaryDirectory() as directory:
            payload_path = Path(directory) / "daily_matches.json"
            payload_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
            with (
                patch.dict(
                    os.environ,
                    {"FOOTBALL_DATA_API_KEY": "football-key", "THE_ODDS_API_KEY": "odds-key"},
                    clear=True,
                ),
                patch(
                    "odds_analyzer.jobs.refresh_adhoc_match.fetch_fixtures_for_beijing_date",
                    return_value=(fixture,),
                ),
                patch(
                    "odds_analyzer.jobs.refresh_adhoc_match.fetch_odds_api_events",
                    side_effect=([odds(1.70)], [odds(1.75)]),
                ),
                patch(
                    "odds_analyzer.jobs.refresh_adhoc_match.fetch_official_sporttery_matches",
                    return_value=[],
                ),
                patch(
                    "odds_analyzer.jobs.refresh_adhoc_match.fetch_fixture_weather",
                    return_value=WeatherBatch(forecasts={}),
                ),
            ):
                first = refresh_adhoc_match(
                    payload_path,
                    "2026-08-23",
                    "NEC",
                    "Telstar",
                    "荷甲",
                    odds_sport_key="soccer_netherlands_eredivisie",
                )
                second = refresh_adhoc_match(
                    payload_path,
                    "2026-08-23",
                    "NEC",
                    "Telstar",
                    "荷甲",
                    odds_sport_key="soccer_netherlands_eredivisie",
                )

        self.assertEqual(len(first["adhoc_history"]), 1)
        self.assertEqual(len(second["adhoc_history"]), 1)
        report = second["adhoc_history"][0]
        self.assertEqual(report["european_odds"]["home"], 1.75)
        self.assertEqual(report["request"]["home_team"], "NEC")
        self.assertIn("NEC Nijmegen vs SC Telstar", report["report_zh"])
        self.assertIn("NEC Nijmegen vs SC Telstar", report["report_en"])
        for key, value in preserved.items():
            self.assertEqual(second.get(key), value)

    def test_workflow_and_dashboard_expose_adhoc_report(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github" / "workflows" / "manual-report.yml").read_text(encoding="utf-8")
        index = (project_root / "dashboard" / "index.html").read_text(encoding="utf-8")
        app = (project_root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn("- adhoc-report", workflow)
        self.assertIn("home_team:", workflow)
        self.assertIn("refresh_adhoc_match", workflow)
        self.assertIn('data-view="adhoc"', index)
        self.assertIn("renderAdhocView", app)
        self.assertIn("payload.adhoc_history", app)


if __name__ == "__main__":
    unittest.main()
