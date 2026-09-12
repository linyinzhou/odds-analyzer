from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from odds_analyzer.dashboard_payload import merge_dashboard_payload
from odds_analyzer.learning import (calibrate_predictions, evaluate_archive, freeze_predictions, record_result,
    selected_snapshots, training_performance, unit_profit, market_probability, merge_learning_archives)
from odds_analyzer.models import MatchScore
from odds_analyzer.prediction_settlement import settle_saved_prediction
from odds_analyzer.jobs.review_results import review_checker_results
from odds_analyzer.sources.football_data import parse_football_data_fixtures


def match(index=1, line=-0.5, market="asian_handicap", selections=None):
    day = datetime(2026, 7, 1) + timedelta(days=index - 1)
    return {
        "id": f"match-{index}", "batch_date": day.date().isoformat(),
        "home_team": f"Home {index}", "away_team": f"Away {index}",
        "kickoff_time": f"{day.date()} 22:00", "competition": "英超",
        "football_data_snapshot": {"match_id": index},
        "prediction": {"market": "saved market", "market_type": market, "pick": "saved pick",
                       "selection_keys": selections or ["home"], "home_handicap": line, "confidence": 60},
        "asian_handicap": {"handicap": line, "home_odds": 1.9, "away_odds": 2.1},
        "chinese_lottery": {"handicap": line, "handicap_odds": {"home": 4.0, "draw": 3.0, "away": 2.0},
                            "standard": {"home": 4.0, "draw": 3.0, "away": 2.0}},
        "european_odds": {"home": 2, "draw": 3, "away": 4},
    }


def forecast(payload, item, hour="18:00:00", *, at=None):
    at = at or f"{item['batch_date']}T{hour}+08:00"
    calibrated, _ = calibrate_predictions(payload, [item], at)
    freeze_predictions(payload, calibrated, at)
    return payload["prediction_archive"][-1]


def result(payload, snapshot, home=1, away=0, *, at=None):
    day = datetime.fromisoformat(snapshot["batch_date"]) + timedelta(days=1)
    record_result(payload, snapshot, home, away, at or f"{day.date()}T08:00:00+08:00")


class FrozenLearningTest(unittest.TestCase):
    def test_refresh_preserves_first_prediction_and_never_mutates_input(self):
        payload = {}
        first = forecast(payload, match())
        saved = deepcopy(first)
        second_match = match()
        second_match["prediction"]["selection_keys"] = ["away"]
        forecast(payload, second_match, "20:00:00")
        second_match["prediction"]["confidence"] = 99
        self.assertEqual(payload["prediction_archive"][0], saved)
        self.assertEqual(selected_snapshots(payload), [saved])
        self.assertEqual(evaluate_archive(payload)["duplicate_versions_excluded"], 1)
        # Review follows frozen home selection even after the displayed pick flips.
        result(payload, saved)
        self.assertTrue(evaluate_archive(payload)["rows"][0]["hit"])

    def test_post_kickoff_unknown_time_and_known_results_are_excluded(self):
        payload = {}
        forecast(payload, match(), "22:00:00")
        item = match(2); item["kickoff_time"] = "待确认"
        forecast(payload, item)
        item = match(3); item["review"] = {"reviewed": True}
        forecast(payload, item)
        self.assertEqual(selected_snapshots(payload), [])
        self.assertEqual(set(evaluate_archive(payload)["exclusions"]),
                         {"recorded_after_kickoff", "unknown_kickoff", "result_already_present"})

    def test_no_bet_does_not_prevent_later_first_valid_prediction(self):
        payload = {}
        item = match(); item["prediction"]["market_type"] = "none"
        forecast(payload, item)
        forecast(payload, match(), "20:00:00")
        self.assertEqual(len(selected_snapshots(payload)), 1)

    def test_same_fixture_daily_and_adhoc_count_once(self):
        payload = {}
        forecast(payload, match())
        item = match(); item.update(id="adhoc-different", batch_date="2026-07-02", adhoc=True)
        forecast(payload, item, at="2026-07-01T19:00:00+08:00")
        self.assertEqual(len(selected_snapshots(payload)), 1)

    def test_backdated_query_cannot_become_a_prematch_import(self):
        item = match(); item["generated_at"] = "2026-07-01T12:00:00+08:00"
        payload = {}
        freeze_predictions(payload, [item], "2026-07-02T08:00:00+08:00")
        self.assertFalse(payload["prediction_archive"][0]["eligible"])

    def test_timezone_and_missing_timezone(self):
        payload = {}
        item = match(); item["kickoff_time"] = "2026-07-01T14:00:00Z"
        forecast(payload, item, at="2026-07-01T13:59:00Z")
        self.assertEqual(len(selected_snapshots(payload)), 1)
        with self.assertRaises(ValueError):
            freeze_predictions(payload, [item], "2026-07-01T13:00:00")

    def test_result_timestamp_not_batch_date_controls_training(self):
        payload = {}
        snapshot = forecast(payload, match())
        result(payload, snapshot, at="2026-07-05T08:00:00+08:00")
        for cutoff in ("2026-07-02T18:00:00+08:00", "2026-07-05T08:00:00+08:00"):
            self.assertEqual(training_performance(payload, cutoff)["training_records"], [])
        self.assertEqual(len(training_performance(payload, "2026-07-05T08:00:01+08:00")["training_records"]), 1)

    def test_repeated_review_preserves_first_known_time_and_correction_appends(self):
        payload = {}; snapshot = forecast(payload, match())
        result(payload, snapshot)
        result(payload, snapshot, at="2026-07-03T08:00:00+08:00")
        self.assertEqual(len(payload["result_archive"]), 1)
        result(payload, snapshot, home=0, away=1, at="2026-07-04T08:00:00+08:00")
        self.assertEqual(len(payload["result_archive"]), 2)
        before = training_performance(payload, "2026-07-03T12:00:00+08:00")
        after = training_performance(payload, "2026-07-04T12:00:00+08:00")
        self.assertEqual(before["strategies"]["market:asian_handicap"]["hits"], 1)
        self.assertEqual(after["strategies"]["market:asian_handicap"]["hits"], 0)

    def test_future_results_do_not_change_saved_forecast_or_replay(self):
        payload = {}
        for index in range(1, 21):
            snapshot = forecast(payload, match(index))
            result(payload, snapshot)
        target = forecast(payload, match(21))
        self.assertEqual(target["match"]["prediction"]["confidence"], 65)
        frozen = deepcopy(target)
        result(payload, target, home=0, away=1)
        row = evaluate_archive(payload)["rows"][-1]
        self.assertEqual(row["replayed_confidence"], 65)
        self.assertEqual(row["training_sample"], 20)
        self.assertEqual(target, frozen)
        self.assertEqual(row["base"], 0.60)
        self.assertEqual(row["calibrated"], 0.65)
        report = evaluate_archive(payload)
        self.assertGreater(report["overall"]["brier_delta"], 0)
        self.assertGreaterEqual(len(report["weekly_walk_forward"]), 3)

    def test_result_arriving_between_calculation_and_freeze_does_not_change_replay(self):
        payload = {}
        for index in range(1, 21):
            snapshot = forecast(payload, match(index))
            if index < 20:
                result(payload, snapshot)
        target = match(21)
        calibrated, _ = calibrate_predictions(payload, [target], "2026-07-21T18:00:00+08:00")
        self.assertEqual(calibrated[0]["prediction"]["confidence"], 60)
        freeze_predictions(payload, calibrated, "2026-07-21T18:00:02+08:00")
        result(payload, snapshot, at="2026-07-21T18:00:01+08:00")
        result(payload, selected_snapshots(payload)[-1])
        row = evaluate_archive(payload)["rows"][-1]
        self.assertEqual(row["replayed_confidence"], 60)
        self.assertEqual(row["training_sample"], 19)

    def test_legacy_mutable_history_never_trains(self):
        payload = {"checker_history": [{**match(i), "review": {"reviewed": True, "hit": True}} for i in range(1, 25)]}
        self.assertEqual(training_performance(payload, "2026-08-01T08:00:00+08:00")["training_records"], [])
        self.assertEqual(evaluate_archive(payload)["overall"]["settled"], 0)

    def test_market_scores_use_identical_paired_subset(self):
        payload = {}
        half = forecast(payload, match(1, line=-0.5)); result(payload, half)
        quarter = forecast(payload, match(2, line=-0.25)); result(payload, quarter, home=0, away=0)
        report = evaluate_archive(payload)["overall"]
        self.assertEqual(report["base"]["n"], 2)
        for scores in report["market_paired"].values():
            self.assertEqual(scores["n"], 1)
        self.assertAlmostEqual(market_probability(match()), 0.525)
        self.assertIsNone(market_probability(match(line=0)))
        self.assertIsNone(market_probability(match(line=-0.25)))

    def test_missing_quote_excludes_roi_but_not_forecast_score(self):
        payload = {}; item = match(); item["asian_handicap"] = None
        snapshot = forecast(payload, item); result(payload, snapshot)
        summary = evaluate_archive(payload)["overall"]
        self.assertEqual(summary["base"]["n"], 1)
        self.assertEqual(summary["roi"]["priced_n"], 0)
        self.assertEqual(summary["roi"]["missing_prices"], 1)
        self.assertIsNone(summary["roi"]["return_per_unit"])

    def test_push_is_counted_for_roi_not_binary_scoring_or_training(self):
        payload = {}; snapshot = forecast(payload, match(line=0)); result(payload, snapshot, home=0, away=0)
        summary = evaluate_archive(payload)["overall"]
        self.assertEqual(summary["outcomes"], {"push": 1})
        self.assertEqual(summary["base"]["n"], 0)
        self.assertEqual(summary["roi"]["return_per_unit"], 0)
        self.assertEqual(training_performance(payload, "2026-07-03T08:00:00+08:00")["training_records"], [])

    def test_brier_and_logloss_known_values(self):
        payload = {}; snapshot = forecast(payload, match()); result(payload, snapshot)
        summary = evaluate_archive(payload)["overall"]
        self.assertAlmostEqual(summary["base"]["brier"], .16)
        self.assertAlmostEqual(summary["base"]["log_loss"], -math.log(.6), places=6)

    def test_asian_five_outcomes_and_decimal_returns(self):
        cases = [(-.5, 1, 0, "win", .9), (-.75, 1, 0, "half_win", .45),
                 (0, 0, 0, "push", 0), (-.25, 0, 0, "half_loss", -.5), (-.5, 0, 0, "loss", -1)]
        for line, home, away, outcome, profit in cases:
            with self.subTest(line=line):
                item = match(line=line)
                decision = settle_saved_prediction(item, MatchScore(home, away))
                self.assertEqual(decision["outcome"], outcome)
                self.assertAlmostEqual(unit_profit(item, decision), profit)
        item = match(line=-.75, selections=["away"])
        decision = settle_saved_prediction(item, MatchScore(1, 0))
        self.assertEqual(decision["outcome"], "half_loss")

    def test_lottery_pair_uses_total_one_unit_and_matching_line(self):
        item = match(line=-1, market="sporttery_handicap", selections=["home", "draw"])
        decision = settle_saved_prediction(item, MatchScore(1, 0))
        self.assertTrue(decision["hit"])
        self.assertEqual(unit_profit(item, decision), .5)  # half a unit at 3.0, total stake 1
        item["chinese_lottery"]["handicap"] = -2
        self.assertIsNone(unit_profit(item, decision))

    def test_invalid_handicaps_are_not_silently_rounded(self):
        for market, line in (("sporttery_handicap", -.5), ("asian_handicap", -.3), ("asian_handicap", float("nan"))):
            self.assertIsNone(settle_saved_prediction(match(line=line, market=market), MatchScore(1, 0)))

    def test_merge_preserves_ledgers_even_when_ui_prefers_other_payload(self):
        payload = {}; snapshot = forecast(payload, match()); result(payload, snapshot)
        merged = merge_learning_archives({"slate": {"date": "2030-01-01"}}, payload)
        self.assertEqual(merged["prediction_archive"], payload["prediction_archive"])
        self.assertEqual(merged["result_archive"], payload["result_archive"])
        self.assertEqual(merged["slate"]["date"], "2030-01-01")
        self.assertEqual(len(merge_learning_archives(merged, payload)["prediction_archive"]), 1)

    def test_tampered_archive_fails_closed(self):
        payload = {}; forecast(payload, match())
        payload["prediction_archive"][0]["match"]["prediction"]["confidence"] = 99
        with self.assertRaises(ValueError):
            evaluate_archive(payload)

    def test_checker_rerun_cannot_remove_archive(self):
        payload = {}; snapshot = forecast(payload, match())
        saved = deepcopy(snapshot)
        with patch("odds_analyzer.learning.now_iso", return_value="2026-07-01T20:00:00+08:00"):
            merged = merge_dashboard_payload(payload, {"slate": {"date": "2026-07-01"}, "current_matches": [], "replace_history_batch": True})
        self.assertEqual(merged["prediction_archive"], [saved])

    def test_review_settles_archive_without_checker_row(self):
        payload = {}; snapshot = forecast(payload, match())
        fixtures = parse_football_data_fixtures({"matches": [{
            "id": 1, "utcDate": "2026-07-01T14:00:00Z", "status": "FINISHED",
            "homeTeam": {"name": "Home 1"}, "awayTeam": {"name": "Away 1"},
            "score": {"duration": "REGULAR", "fullTime": {"home": 1, "away": 0}},
        }]}, "PL")
        reviewed, counts = review_checker_results(payload, "2026-07-01", fixtures, "2026-07-02T08:00:00+08:00")
        self.assertEqual(counts["reviewed"], 0)
        self.assertEqual(reviewed["learning_evaluation"]["overall"]["settled"], 1)
        self.assertEqual(reviewed["strategy_performance"]["strategies"]["market:asian_handicap"]["sample_size"], 1)

    def test_extra_time_uses_regular_time_and_missing_regular_time_stays_unknown(self):
        item = {"id": 1, "utcDate": "2026-07-01T14:00:00Z", "status": "FINISHED",
                "homeTeam": {"name": "Home"}, "awayTeam": {"name": "Away"},
                "score": {"duration": "PENALTY_SHOOTOUT", "fullTime": {"home": 7, "away": 6},
                          "regularTime": {"home": 1, "away": 1}}}
        fixture = parse_football_data_fixtures({"matches": [item]}, "CL")[0]
        self.assertEqual((fixture.home_score, fixture.away_score), (1, 1))
        item["score"].pop("regularTime")
        fixture = parse_football_data_fixtures({"matches": [item]}, "CL")[0]
        self.assertIsNone(fixture.home_score)
        self.assertIsNone(fixture.away_score)

    def test_ad_hoc_and_postponed_fixture_is_resolved_by_id(self):
        from odds_analyzer.jobs.review_results import review_results
        payload = {}; item = match(); item["adhoc"] = True
        forecast(payload, item)
        fixture = parse_football_data_fixtures({"matches": [{
            "id": 1, "utcDate": "2026-07-03T14:00:00Z", "status": "FINISHED",
            "homeTeam": {"name": "Home 1"}, "awayTeam": {"name": "Away 1"},
            "score": {"fullTime": {"home": 1, "away": 0}},
        }]}, "PL")[0]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "payload.json"
            target.write_text(json.dumps(payload), encoding="utf-8")
            with patch("odds_analyzer.jobs.review_results.fetch_evening_fixtures", return_value=()), \
                 patch("odds_analyzer.jobs.review_results.fetch_fixture_by_id", return_value=fixture) as fetch, \
                 patch("odds_analyzer.jobs.review_results.refresh_next_matchday", side_effect=lambda p, key: (p, {"status": "success", "successful": 0, "failed": 0})):
                reviewed = review_results(target, "2026-07-01", "test-key")
            fetch.assert_called_once_with("test-key", 1)
            self.assertEqual(reviewed["learning_evaluation"]["overall"]["settled"], 1)

    def test_cli_is_read_only_and_rejects_input_as_output(self):
        root = Path(__file__).resolve().parents[1]
        payload = {}; snapshot = forecast(payload, match()); result(payload, snapshot)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "payload.json"
            output = Path(directory) / "report.json"
            markdown = Path(directory) / "report.md"
            target.write_text(json.dumps(payload), encoding="utf-8")
            original = target.read_bytes()
            import os
            env = {**os.environ, "PYTHONPATH": str(root / "src")}
            command = [sys.executable, "-m", "odds_analyzer.jobs.evaluate_predictions", "--payload", str(target)]
            completed = subprocess.run([*command, "--output", str(output), "--markdown", str(markdown)], env=env, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(output.read_text())["overall"]["settled"], 1)
            self.assertIn("Weekly walk-forward", markdown.read_text(encoding="utf-8"))
            rejected = subprocess.run([*command, "--output", str(target)], env=env, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(target.read_bytes(), original)

    def test_awarded_and_unfinished_results_do_not_enter_archive(self):
        payload = {}; snapshot = forecast(payload, match())
        for status in ("AWARDED", "IN_PLAY", "POSTPONED"):
            record_result(payload, snapshot, 1, 0, "2026-07-02T08:00:00+08:00", status=status)
        self.assertEqual(payload.get("result_archive", []), [])


if __name__ == "__main__":
    unittest.main()
