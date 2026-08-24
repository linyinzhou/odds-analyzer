from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.jobs.refresh_evening_slate import build_evening_slate_batch
from odds_analyzer.sources import (
    FootballDataSnapshot,
    WeatherSnapshot,
    fetch_fixture_weather,
    parse_football_data_fixtures,
    team_city_query,
)


def fixture_snapshot() -> FootballDataSnapshot:
    payload = {
        "competition": {"code": "PL", "name": "Premier League"},
        "matches": [
            {
                "id": 1001,
                "utcDate": "2026-08-22T14:00:00Z",
                "status": "TIMED",
                "matchday": 1,
                "venue": "Hill Dickinson Stadium",
                "homeTeam": {"id": 62, "name": "Everton FC"},
                "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
            }
        ],
    }
    return FootballDataSnapshot(
        fixtures=parse_football_data_fixtures(payload, "PL"),
        standings={},
        forms={},
    )


class WeatherSourceTest(unittest.TestCase):
    def test_team_city_query_uses_controlled_overrides_and_generic_cleanup(self):
        self.assertEqual(team_city_query("Everton FC"), "Liverpool")
        self.assertEqual(team_city_query("Athletic Club"), "Bilbao")
        self.assertEqual(team_city_query("RCD Espanyol de Barcelona"), "Barcelona")
        self.assertEqual(team_city_query("Valencia CF"), "Valencia")
        self.assertEqual(team_city_query("Udinese Calcio"), "Udine")
        self.assertEqual(team_city_query("Manchester United FC"), "Manchester")
        self.assertEqual(team_city_query("Hull City AFC"), "Hull")
        self.assertEqual(team_city_query("Olympique Lyonnais"), "Lyon")

    def test_fetch_geocodes_once_and_samples_nearest_kickoff_hour(self):
        geocode = {
            "results": [
                {
                    "name": "Liverpool",
                    "latitude": 53.41,
                    "longitude": -2.98,
                    "country_code": "GB",
                }
            ]
        }
        forecast = {
            "hourly": {
                "time": ["2026-08-22T13:00", "2026-08-22T14:00", "2026-08-22T15:00"],
                "temperature_2m": [17.0, 16.0, 15.0],
                "precipitation_probability": [30, 70, 60],
                "weather_code": [3, 61, 61],
                "wind_speed_10m": [12.0, 20.0, 18.0],
                "wind_gusts_10m": [30.0, 50.0, 45.0],
            }
        }

        with patch("odds_analyzer.sources.weather._get_json", side_effect=[geocode, forecast]) as get_json:
            batch = fetch_fixture_weather(fixture_snapshot().fixtures)

        self.assertEqual(get_json.call_count, 2)
        self.assertFalse(batch.errors)
        weather = batch.forecasts[1001]
        self.assertEqual(weather.location, "Liverpool")
        self.assertEqual(weather.forecast_time, "2026-08-22T14:00")
        self.assertEqual(weather.temperature_c, 16.0)
        self.assertEqual(weather.precipitation_probability, 70.0)

    def test_dashboard_batch_includes_weather_snapshot_and_risk(self):
        existing = {}
        weather = WeatherSnapshot(
            match_id=1001,
            location="Liverpool",
            latitude=53.41,
            longitude=-2.98,
            forecast_time="2026-08-22T14:00",
            temperature_c=16.0,
            precipitation_probability=70.0,
            weather_code=61,
            wind_speed_kmh=20.0,
            wind_gusts_kmh=50.0,
        )

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            football_data_snapshot=fixture_snapshot(),
            football_data_source="football-data.org",
            weather_forecasts={1001: weather},
            weather_source="Open-Meteo: 1 forecasts",
        )
        everton = next(
            match
            for match in batch["current_matches"]
            if (match.get("football_data_snapshot") or {}).get("match_id") == 1001
        )

        self.assertEqual(batch["slate"]["weather_source"], "Open-Meteo: 1 forecasts")
        self.assertIn("有雨", everton["weather"])
        self.assertEqual(everton["weather_snapshot"]["source"], "Open-Meteo")
        self.assertIn("Open-Meteo", everton["sources"])
        self.assertTrue(any("降水概率" in risk for risk in everton["risks"]))
        self.assertTrue(any("阵风" in risk for risk in everton["risks"]))


if __name__ == "__main__":
    unittest.main()
