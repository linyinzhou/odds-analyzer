import unittest
from datetime import date, timedelta

from odds_analyzer.models import Selection
from odds_analyzer.poisson_baseline import (
    expected_asian_return,
    expected_sporttery_return,
    fit_from_standings,
    fit_goals,
    score_probabilities,
    shadow_match,
)


class PoissonBaselineTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = []
        start = date(2025, 8, 1)
        teams = range(1, 11)
        for i in range(150):
            home = i % 10 + 1
            away = (i * 3 + 4) % 10 + 1
            if away == home:
                away = away % 10 + 1
            self.fixtures.append({
                "competition_code": "PL", "utc_date": (start + timedelta(days=i)).isoformat() + "T12:00:00Z",
                "home_team_id": home, "away_team_id": away,
                "home_score": (i + home) % 4, "away_score": (i + away) % 3,
                "status": "FINISHED",
            })

    def test_future_result_cannot_enter_training(self):
        cutoff = "2025-12-01T12:00:00Z"
        fitted = fit_goals(self.fixtures, "PL", cutoff, 1, 2)
        self.assertIsNotNone(fitted)
        extra = dict(self.fixtures[0], utc_date="2025-12-01T12:00:00Z", home_score=50)
        self.assertEqual(fitted, fit_goals(self.fixtures + [extra], "PL", cutoff, 1, 2))
        self.assertIsNone(fit_goals(self.fixtures[:10], "PL", cutoff, 1, 2))

    def test_quarter_line_expected_return_and_push(self):
        # Home +0.25: draw half win; home win full win; loss full loss.
        matrix = {(1, 0): .25, (0, 0): .50, (0, 1): .25}
        result = expected_asian_return(matrix, .25, Selection.HOME, 2.0)
        self.assertAlmostEqual(result["expected_profit_per_unit"], .25)
        self.assertAlmostEqual(result["half_win"], .5)
        self.assertAlmostEqual(sum(result[k] for k in
            ("full_win", "half_win", "push", "half_loss", "full_loss")), 1)
        result = expected_asian_return(matrix, 0, Selection.HOME, 2.0)
        self.assertAlmostEqual(result["push"], .5)
        self.assertAlmostEqual(result["expected_profit_per_unit"], 0)

    def test_sporttery_and_probability_matrix(self):
        matrix = score_probabilities(1.3, 1.1)
        self.assertAlmostEqual(sum(matrix.values()), 1, places=10)
        toy = {(1, 0): .4, (0, 0): .6}
        self.assertAlmostEqual(expected_sporttery_return(toy, -1, Selection.DRAW, 3), .2)

    def test_shadow_does_not_modify_prediction(self):
        match = {
            "football_data_snapshot": {"competition_code": "PL", "utc_date": "2025-12-01T12:00:00Z"},
            "fundamental_context": {"home": {"team_id": 1}, "away": {"team_id": 2}},
            "asian_handicap": {"handicap": -.25, "home_odds": 1.9, "away_odds": 1.9},
            "prediction": {"decision": "watch", "betting_eligible": False},
        }
        result = shadow_match(match, self.fixtures)
        self.assertEqual(result["status"], "shadow")
        self.assertEqual(match["prediction"], {"decision": "watch", "betting_eligible": False})

    def test_existing_season_aggregates_work_without_api_key(self):
        context = {
            "home": {"played_games": 5, "goals_for": 9, "goals_against": 6, "team_id": 1},
            "away": {"played_games": 5, "goals_for": 14, "goals_against": 3, "team_id": 2},
        }
        fitted = fit_from_standings(context)
        self.assertAlmostEqual(fitted["expected_home_goals"], 1.2)
        self.assertAlmostEqual(fitted["expected_away_goals"], 2.0)
        match = {
            "football_data_snapshot": {"competition_code": "SA", "utc_date": "2026-10-11T10:30:00Z"},
            "fundamental_context": context,
            "asian_handicap": {"handicap": -.25, "home_odds": 1.9, "away_odds": 1.9},
            "prediction": {"decision": "watch", "betting_eligible": False},
        }
        result = shadow_match(match, [])
        self.assertEqual(result["status"], "shadow_aggregate")
        self.assertEqual(match["prediction"]["decision"], "watch")
        context["home"]["played_games"] = 2
        self.assertIsNone(fit_from_standings(context))


if __name__ == "__main__":
    unittest.main()
