import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.jobs.refresh_evening_slate import _enrich_with_polymarket
from odds_analyzer.slate_analysis import analyze_slate_match
from odds_analyzer.sources import parse_polymarket_events


def polymarket_payload(volume=1_132_624.0):
    common = {
        "gameId": 90114078,
        "eventStartTime": "2026-08-24T19:00:00Z",
        "updatedAt": "2026-08-24T16:05:22Z",
    }
    return [
        {
            **common,
            "id": "primary",
            "slug": "epl-ful-che-2026-08-24",
            "title": "Fulham FC vs. Chelsea FC",
            "volume": volume,
            "liquidity": 4_694_197.0,
            "markets": [
                {
                    "question": "Will Chelsea FC win on 2026-08-24?",
                    "sportsMarketType": "moneyline",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.505", "0.495"]',
                    "gameStartTime": "2026-08-24 19:00:00+00",
                },
                {
                    "question": "Will Fulham FC vs. Chelsea FC end in a draw?",
                    "sportsMarketType": "moneyline",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.255", "0.745"]',
                },
                {
                    "question": "Will Fulham FC win on 2026-08-24?",
                    "sportsMarketType": "moneyline",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.235", "0.765"]',
                },
            ],
        },
        {
            **common,
            "id": "more-markets",
            "slug": "epl-ful-che-2026-08-24-more-markets",
            "title": "Fulham FC vs. Chelsea FC - More Markets",
            "markets": [
                {
                    "question": "Spread: Fulham FC (-1.5)",
                    "sportsMarketType": "spreads",
                    "line": -1.5,
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.085", "0.915"]',
                    "volumeNum": 1_013.0,
                },
                {
                    "question": "Spread: Chelsea FC (-1.5)",
                    "sportsMarketType": "spreads",
                    "line": -1.5,
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.265", "0.735"]',
                    "volumeNum": 38_673.0,
                },
            ],
        },
    ]


class PolymarketSourceTest(unittest.TestCase):
    def test_groups_game_markets_and_extracts_favorite_minus_one_point_five(self):
        events = parse_polymarket_events(polymarket_payload())

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertAlmostEqual(event.home_probability, 0.235 / 0.995)
        self.assertAlmostEqual(event.draw_probability, 0.255 / 0.995)
        self.assertAlmostEqual(event.away_probability, 0.505 / 0.995)
        self.assertEqual(event.favorite_spread.team, "Chelsea FC")
        self.assertEqual(event.favorite_spread.line, -1.5)
        self.assertAlmostEqual(event.favorite_spread.probability, 0.265)
        self.assertTrue(event.signal_eligible)

    def test_enrichment_exposes_prediction_market_snapshot(self):
        event = parse_polymarket_events(polymarket_payload())[0]
        matches = [{"home_team": "Fulham", "away_team": "Chelsea", "sources": []}]

        enriched = _enrich_with_polymarket(matches, [event])[0]

        self.assertEqual(enriched["polymarket"]["favorite_side"], "away")
        self.assertEqual(enriched["polymarket"]["favorite_spread"]["line"], -1.5)
        self.assertTrue(enriched["polymarket"]["spread_signal_eligible"])
        self.assertIn("Polymarket", enriched["sources"])

    def test_liquid_low_cover_signal_strengthens_deeper_lottery_mismatch(self):
        event = parse_polymarket_events(polymarket_payload())[0]
        match = {
            "home_team": "Fulham FC",
            "away_team": "Chelsea FC",
            "european_odds": {"home": 4.3, "draw": 3.8, "away": 1.9},
            "asian_handicap": {
                "provider": "Pinnacle",
                "handicap": 0.5,
                "home_odds": 1.95,
                "away_odds": 1.95,
            },
            "chinese_lottery": {
                "handicap": 1,
                "handicap_odds": {"home": 1.8, "draw": 3.5, "away": 3.5},
            },
            "football_data_snapshot": {"match_id": 1},
            "fundamental_context": {
                "home": {"played_games": 10, "points": 20, "goal_difference": 7, "form": ["W", "W", "D"]},
                "away": {"played_games": 10, "points": 12, "goal_difference": -2, "form": ["L", "D", "W"]},
            },
            "sources": [],
        }
        match = _enrich_with_polymarket([match], [event])[0]

        analyzed = analyze_slate_match(match)

        self.assertTrue(analyzed["mismatch"]["matched"])
        self.assertIn("Polymarket", analyzed["mismatch"]["reason"])
        self.assertEqual(analyzed["prediction"]["basis"], "fresh_multi_market_snapshot")
        self.assertGreaterEqual(analyzed["prediction"]["confidence"], 65)

    def test_low_volume_market_is_display_only(self):
        event = parse_polymarket_events(polymarket_payload(volume=5_000))[0]
        enriched = _enrich_with_polymarket(
            [{"home_team": "Fulham", "away_team": "Chelsea", "sources": []}],
            [event],
        )[0]

        self.assertFalse(enriched["polymarket"]["signal_eligible"])


    def test_liquid_polymarket_conflict_rejects_sporttery_mismatch(self):
        match = {
            "home_team": "Fulham FC",
            "away_team": "Chelsea FC",
            "european_odds": {"home": 4.3, "draw": 3.8, "away": 1.9},
            "asian_handicap": {
                "provider": "Pinnacle",
                "handicap": 0.5,
                "home_odds": 1.95,
                "away_odds": 1.95,
            },
            "chinese_lottery": {
                "handicap": 1,
                "handicap_odds": {"home": 1.8, "draw": 3.5, "away": 3.5},
            },
            "football_data_snapshot": {"match_id": 1},
            "fundamental_context": {
                "home": {"played_games": 10, "points": 20, "goal_difference": 7, "form": ["W", "W", "D"]},
                "away": {"played_games": 10, "points": 12, "goal_difference": -2, "form": ["L", "D", "W"]},
            },
            "polymarket": {
                "home": 0.15,
                "draw": 0.20,
                "away": 0.65,
                "favorite_side": "away",
                "signal_eligible": True,
                "spread_signal_eligible": True,
                "favorite_spread": {
                    "team": "Chelsea FC",
                    "line": -1.5,
                    "probability": 0.58,
                },
            },
        }

        analyzed = analyze_slate_match(match)

        self.assertFalse(analyzed["mismatch"]["matched"])
        self.assertEqual(analyzed["mismatch"]["polymarket_validation"], "conflict")
        self.assertEqual(analyzed["prediction"]["market"], "亚盘 Pinnacle")
        self.assertIn("降级为观察", analyzed["recommendation"]["mismatch"])


if __name__ == "__main__":
    unittest.main()
