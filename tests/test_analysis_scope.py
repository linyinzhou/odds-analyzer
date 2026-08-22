from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.jobs.refresh_evening_slate import (
    ALLOWED_ANALYSIS_COMPETITIONS,
    build_evening_slate_batch,
    parse_analysis_competitions,
    refresh_evening_slate,
)
from odds_analyzer.sources import ApiFootballNewsBatch, FootballDataSnapshot, parse_football_data_fixtures


class AnalysisScopeTest(unittest.TestCase):
    def test_default_is_premier_league_la_liga_serie_a_and_all_enables_every_supported_code(self):
        self.assertEqual(parse_analysis_competitions(None), ("PL", "PD", "SA"))
        self.assertEqual(parse_analysis_competitions(""), ("PL", "PD", "SA"))
        self.assertEqual(parse_analysis_competitions("invalid"), ("PL", "PD", "SA"))
        self.assertEqual(parse_analysis_competitions("PL,PD,PL"), ("PL", "PD"))
        self.assertEqual(parse_analysis_competitions("all"), ALLOWED_ANALYSIS_COMPETITIONS)

    def test_report_lists_are_filtered_but_next_matchday_remains_full(self):
        project_root = Path(__file__).resolve().parents[1]
        existing = json.loads(
            (project_root / "dashboard" / "data" / "daily_matches.json").read_text(encoding="utf-8")
        )
        fixtures = parse_football_data_fixtures(
            {
                "matches": [
                    {
                        "id": 1001,
                        "competition": {"code": "PL", "name": "Premier League"},
                        "utcDate": "2026-08-22T14:00:00Z",
                        "status": "TIMED",
                        "matchday": 1,
                        "homeTeam": {"id": 62, "name": "Everton FC"},
                        "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
                    },
                    {
                        "id": 2001,
                        "competition": {"code": "PD", "name": "Primera Division"},
                        "utcDate": "2026-08-22T15:00:00Z",
                        "status": "TIMED",
                        "matchday": 2,
                        "homeTeam": {"id": 77, "name": "Athletic Club"},
                        "awayTeam": {"id": 78, "name": "Sevilla FC"},
                    },
                ]
            },
            "",
        )
        snapshot = FootballDataSnapshot(fixtures=fixtures, standings={}, forms={})

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            football_data_snapshot=snapshot,
            analysis_competitions=("PL",),
        )

        self.assertEqual(batch["slate"]["analysis_competitions"], ["PL"])
        self.assertTrue(batch["current_matches"])
        self.assertTrue(all(match["competition"].startswith("英超") for match in batch["current_matches"]))
        self.assertTrue(all(match["competition"].startswith("英超") for match in batch["mismatch_history"]))
        self.assertTrue(all(match["competition"].startswith("英超") for match in batch["checker_history"]))
        schedule_names = {item["name"] for item in batch["next_matchday"]["competitions"]}
        self.assertIn("西甲", schedule_names)
        self.assertIn("欧冠", schedule_names)

    def test_refresh_limits_source_calls_to_enabled_default_leagues(self):
        project_root = Path(__file__).resolve().parents[1]
        existing = (project_root / "dashboard" / "data" / "daily_matches.json").read_text(encoding="utf-8")
        empty_snapshot = FootballDataSnapshot(fixtures=(), standings={}, forms={})

        with tempfile.TemporaryDirectory() as directory:
            payload_path = Path(directory) / "daily_matches.json"
            payload_path.write_text(existing, encoding="utf-8")
            with (
                patch.dict(
                    os.environ,
                    {
                        "FOOTBALL_DATA_API_KEY": "football-key",
                        "THE_ODDS_API_KEY": "odds-key",
                        "API_FOOTBALL_API_KEY": "news-key",
                    },
                    clear=True,
                ),
                patch(
                    "odds_analyzer.jobs.refresh_evening_slate.fetch_evening_football_data",
                    return_value=empty_snapshot,
                ) as football_data,
                patch(
                    "odds_analyzer.jobs.refresh_evening_slate.fetch_evening_odds_api_events",
                    return_value=[],
                ) as odds_api,
                patch(
                    "odds_analyzer.jobs.refresh_evening_slate.fetch_evening_api_football_news",
                    return_value=ApiFootballNewsBatch(
                        matches=(),
                        requests_made=0,
                        remaining_requests=100,
                    ),
                ) as api_football,
                patch(
                    "odds_analyzer.jobs.refresh_evening_slate.fetch_official_sporttery_matches",
                    return_value=[],
                ),
            ):
                refresh_evening_slate(payload_path, "2026-08-22")

        football_data.assert_called_once_with(
            "football-key",
            "2026-08-22",
            competition_codes=("PL", "PD", "SA"),
        )
        odds_api.assert_called_once_with(
            "odds-key",
            "2026-08-22",
            sport_keys=("soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a"),
        )
        api_football.assert_called_once_with(
            "news-key",
            "2026-08-22",
            competition_codes=("PL", "PD", "SA"),
        )
    def test_workflow_and_frontend_expose_the_scope_switch(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github" / "workflows" / "manual-report.yml").read_text(encoding="utf-8")
        app = (project_root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn("analysis_competitions:", workflow)
        self.assertNotIn("vars.ANALYSIS_COMPETITIONS", workflow)
        self.assertIn("|| 'PL,PD,SA'", workflow)
        self.assertIn('analysisCompetitionCodes: ["PL", "PD", "SA"]', app)
        self.assertIn('normalized.length ? normalized : ["PL", "PD", "SA"]', app)
        self.assertIn("matchInAnalysisScope", app)
        self.assertIn("renderTeamNews", app)


if __name__ == "__main__":
    unittest.main()
