import unittest
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from odds_analyzer.learning import timestamp, merge_learning_archives
from odds_analyzer.season_model import (
    append_record, known_results, predict, update_predictions, review_predictions,
    first_forecasts, features, import_checker, ingest_fixtures,
)
from odds_analyzer.sources.football_data import FootballDataFixture


class SeasonModelTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"slate": {"date": "2026-10-13"}}
        for i in range(36):
            home, away = [(1,2),(3,4),(2,3),(4,1),(1,3),(2,4)][i % 6]
            kickoff = datetime(2026,8,1,tzinfo=timezone.utc)+timedelta(days=i)
            append_record(self.payload, "season_results", {
                "fixture_key": f"football-data:{i+100}", "competition_code": "PL", "season": 2026,
                "kickoff": kickoff.isoformat(), "observed_at": (kickoff+timedelta(hours=3)).isoformat(),
                "home_team_id": home, "away_team_id": away,
                "home_score": (3 if home==1 else 1), "away_score": (2 if away==1 else 0),
                "rankings": {"home": home, "away": away},
                "rank_recorded_at": (kickoff-timedelta(hours=2)).isoformat(),
                "asian_handicap": {"handicap": -.5, "home_odds": 1.9, "away_odds": 1.95},
                "market_recorded_at": (kickoff-timedelta(hours=2)).isoformat(), "source": "fixture",
            }, "observation_id")
        self.match = {"id": "target", "home_team": "One", "away_team": "Two", "competition": "英超",
            "kickoff_time": "2026-10-13 20:00", "football_data_snapshot": {
                "match_id": 999, "competition_code": "PL", "utc_date": "2026-10-13T12:00:00Z"},
            "fundamental_context": {"home": {"team_id":1,"position":1}, "away":{"team_id":2,"position":4}},
            "asian_handicap": {"handicap":-.25,"home_odds":1.95,"away_odds":1.95},
            "prediction": {"decision":"watch", "betting_eligible":False}}
        self.now = "2026-10-13T08:00:00Z"
        self.payload["current_matches"] = [deepcopy(self.match)]

    def test_feature_model_produces_normalized_forecast_and_uses_all_factors(self):
        result = predict(self.payload, self.match, self.now)
        self.assertEqual(result["status"], "research")
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1)
        self.assertGreater(result["expected_home_goals"], result["expected_away_goals"])
        self.assertEqual(result["feature_coverage"]["ranking_training_matches"], 36)
        self.assertEqual(result["form_features"]["home"]["market_count"], 5)
        self.assertNotEqual(result["feature_coefficients"]["ranking"], 0)
        x = features(1,2,True,{"recent":.5,"market":.2},1,10)
        self.assertIn("defence:2", x)
        self.assertIn("venue:1:home", x)
        self.assertGreater(x["ranking"], 0)

    def test_future_observations_and_other_season_do_not_change_prediction(self):
        before = predict(self.payload, self.match, self.now)
        for change in ({"observed_at":"2026-10-14T00:00:00Z"}, {"season":2025}):
            row = deepcopy(self.payload["season_results"][0])
            row.pop("observation_id")
            row.update(change)
            row.update(fixture_key=str(change), home_score=20)
            append_record(self.payload,"season_results",row,"observation_id")
        self.assertEqual(before, predict(self.payload,self.match,self.now))

    def test_corrections_respect_first_known_time_and_deduplicate(self):
        row = deepcopy(self.payload["season_results"][0])
        row.pop("observation_id")
        row.update(home_score=0,observed_at="2026-10-14T00:00:00Z")
        append_record(self.payload,"season_results",row,"observation_id")
        self.assertEqual(len(known_results(self.payload,timestamp(self.now))),36)
        corrected = {r["fixture_key"]:r for r in known_results(self.payload,timestamp("2026-10-15T00:00:00Z"))}
        self.assertEqual(corrected[row["fixture_key"]]["home_score"],0)

    def test_freeze_first_forecast_and_settle_original_quarter_line(self):
        update_predictions(self.payload,self.now)
        first = deepcopy(first_forecasts(self.payload)[0])
        update_predictions(self.payload,"2026-10-13T08:01:00Z")
        self.payload["current_matches"][0]["asian_handicap"]["handicap"] = -4
        update_predictions(self.payload,"2026-10-13T09:00:00Z")
        self.assertEqual(first_forecasts(self.payload)[0], first)
        fixture = FootballDataFixture(999,"PL","Premier League","2026-10-13T12:00:00Z","2026-10-13 20:00",1,"One",2,"Two",8,None,"FINISHED",home_score=0,away_score=0)
        ingest_fixtures(self.payload,[fixture],"2026-10-13T15:00:00Z")
        review_predictions(self.payload,"2026-10-13T15:00:00Z")
        review = self.payload["model_reviews"][0]
        selection = first["analysis"]["selection"]
        expected = -.5 if selection["side"]=="home" else .5*(selection["odds"]-1)
        self.assertAlmostEqual(review["unit_profit"],expected)
        review_predictions(self.payload,"2026-10-14T00:00:00Z")
        self.assertEqual(len(self.payload["model_reviews"]),1)
        self.assertEqual(self.payload["model_evaluation"]["reviewed"],1)
        self.assertEqual(self.payload["current_matches"][0]["prediction"],self.match["prediction"])

    def test_no_retrospective_forecast_or_thin_sample(self):
        update_predictions(self.payload,"2026-10-13T13:00:00Z")
        self.assertFalse(self.payload.get("model_forecasts"))
        self.assertEqual(predict({},self.match,self.now)["status"],"unavailable")

    def test_archive_merge_preserves_forecasts_and_training(self):
        update_predictions(self.payload,self.now)
        merged = merge_learning_archives({},self.payload)
        self.assertEqual(len(merged["season_results"]),36)
        self.assertEqual(first_forecasts(merged),first_forecasts(self.payload))
        merged["season_results"][0]["home_score"] = 100
        with self.assertRaises(ValueError):
            known_results(merged,timestamp(self.now))

    def test_legacy_import_requires_score_ids_and_observed_time(self):
        match = deepcopy(self.match)
        match["review"] = {"reviewed":True,"final_score":"2-1","reviewed_at":"2026-10-13T15:00:00Z"}
        payload = {"checker_history":[match,deepcopy(match)]}
        self.assertEqual(import_checker(payload)["imported"],1)
        self.assertIsNone(payload["season_results"][0]["asian_handicap"])
        self.assertFalse(payload["season_results"][0]["rankings"])
        self.assertEqual(import_checker(payload)["imported"],0)
        payload["checker_history"][0]["review"]["reviewed_at"] = "2026-10-14T02:00:00Z"
        self.assertEqual(import_checker(payload)["imported"],0)

    def test_morning_review_ingests_unselected_games_and_settles_model(self):
        from odds_analyzer.jobs.review_results import review_checker_results
        update_predictions(self.payload,self.now)
        target = FootballDataFixture(999,"PL","Premier League","2026-10-13T12:00:00Z","2026-10-13 20:00",1,"One",2,"Two",8,None,"FINISHED",home_score=2,away_score=1)
        unselected = FootballDataFixture(1000,"PL","Premier League","2026-10-13T12:00:00Z","2026-10-13 20:00",3,"Three",4,"Four",8,None,"FINISHED",home_score=1,away_score=1)
        reviewed, _ = review_checker_results(self.payload,"2026-10-13",(target,unselected),"2026-10-14T00:00:00Z")
        self.assertEqual(reviewed["model_evaluation"]["reviewed"],1)
        self.assertEqual(len(known_results(reviewed,timestamp("2026-10-14T01:00:00Z"))),38)
        repeated, _ = review_checker_results(reviewed,"2026-10-13",(target,unselected),"2026-10-15T00:00:00Z")
        self.assertEqual(repeated["season_results"], reviewed["season_results"])

    def test_scheduled_review_collects_yesterday_without_recommendations(self):
        from odds_analyzer.jobs.review_results import review_results, BEIJING
        yesterday = (datetime.now(BEIJING).date()-timedelta(days=1)).isoformat()
        with TemporaryDirectory() as directory:
            path = Path(directory)/"payload.json"
            path.write_text(json.dumps({"checker_history":[{"batch_date":"2026-08-01"}]}),encoding="utf-8")
            with patch("odds_analyzer.jobs.review_results.fetch_evening_fixtures",return_value=()) as fetch, patch(
                "odds_analyzer.jobs.review_results.refresh_next_matchday",
                side_effect=lambda p,k:(p,{"status":"skipped","successful":0,"failed":0})):
                review_results(path,"","key")
            self.assertIn(yesterday,[call.args[1] for call in fetch.call_args_list])


if __name__ == "__main__":
    unittest.main()
