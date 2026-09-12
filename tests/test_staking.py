from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from odds_analyzer.staking import build_staking_plan
from odds_analyzer.slate_analysis import analyze_slate_match
from odds_analyzer.jobs.refresh_evening_slate import _checker_candidates, _attach_bilingual_reports
from odds_analyzer.learning import valid_prediction, unit_profit
from odds_analyzer.models import MatchScore
from odds_analyzer.prediction_settlement import settle_saved_prediction
from test_handicap_analysis import dynamic_analysis_match


def lottery(draw, away, single=None):
    return {"handicap": -1, "handicap_odds": {"home": 4.5, "draw": draw, "away": away}, "single_handicap": single}


class StakingPlanTest(unittest.TestCase):
    def test_user_example_is_impossible_not_fixed_by_multiples(self):
        plan = build_staking_plan(lottery(2.5, 1.4), ["draw", "away"])
        self.assertEqual(plan["status"], "impossible")
        self.assertEqual(plan["allocations"], [])
        rows = {row["selection"]: row for row in plan["equal_stake_scenarios"]}
        self.assertEqual(rows["draw"]["net_profit"], 1)
        self.assertEqual(rows["away"]["return"], 2.8)
        self.assertEqual(rows["away"]["net_profit"], -1.2)
        self.assertEqual(rows["home"]["net_profit"], -4)

    def test_break_even_is_not_profit(self):
        self.assertEqual(build_staking_plan(lottery(2, 2), ["draw", "away"])["status"], "impossible")

    def test_minimum_integer_stake_with_conditional_positive_returns(self):
        plan = build_staking_plan(lottery(2.5, 1.8), ["draw", "away"])
        self.assertEqual(plan["status"], "feasible")
        self.assertEqual(plan["total_stake"], 14)
        self.assertEqual([row["units"] for row in plan["allocations"]], [3, 4])
        self.assertEqual([row["stake"] for row in plan["allocations"]], [6, 8])
        self.assertEqual(plan["minimum_covered_profit"], .4)
        self.assertEqual(plan["uncovered_loss"], 14)
        self.assertEqual(plan["purchase_status"], "confirm_single")

    def test_existing_example_needs_two_units_on_lower_odds(self):
        plan = build_staking_plan(lottery(3.55, 1.6, True), ["draw", "away"])
        self.assertEqual(plan["total_stake"], 6)
        self.assertEqual([row["units"] for row in plan["allocations"]], [1, 2])
        rows = {row["selection"]: row for row in plan["scenarios"]}
        self.assertEqual(rows["draw"]["net_profit"], 1.1)
        self.assertEqual(rows["away"]["net_profit"], .4)
        self.assertEqual(rows["home"]["net_profit"], -6)
        self.assertEqual(plan["purchase_status"], "ready")

    def test_budget_is_not_silently_increased(self):
        self.assertEqual(build_staking_plan(lottery(2.5, 1.8), ["draw", "away"], 12)["status"], "over_cap")
        self.assertEqual(build_staking_plan(lottery(2.01, 2), ["draw", "away"])["status"], "over_cap")

    def test_cent_rounding_does_not_claim_fractional_cent_profit(self):
        self.assertEqual(build_staking_plan(lottery(2.0001, 2.0001), ["draw", "away"])["status"], "over_cap")

    def test_single_unavailable_is_not_a_purchase_suggestion(self):
        plan = build_staking_plan(lottery(3.55, 1.6, False), ["draw", "away"])
        self.assertEqual(plan["status"], "feasible")
        self.assertEqual(plan["purchase_status"], "parlay_reference")
        self.assertEqual([row["units"] for row in plan["allocations"]], [1, 2])

    def test_genoa_ratio_and_non_single_learning_exclusion(self):
        item = dynamic_analysis_match(True)
        item["chinese_lottery"] = lottery(3.85, 1.59, False)
        analyzed = analyze_slate_match(item)
        plan = analyzed["prediction"]["staking_plan"]
        self.assertEqual(plan["total_stake"], 6)
        self.assertEqual([row["units"] for row in plan["allocations"]], [1, 2])
        self.assertEqual([row["net_profit"] for row in plan["scenarios"]], [-6, 1.7, .36])
        self.assertEqual(len(analyzed["staking_references"]), 3)
        self.assertFalse(valid_prediction(analyzed))
        self.assertEqual(_checker_candidates([analyzed], "2026-09-12"), [])

    def test_display_refresh_preserves_forecasts_and_archives_after_kickoff(self):
        from odds_analyzer.jobs.refresh_staking_references import refresh_staking_references
        match = analyze_slate_match(dynamic_analysis_match(True))
        match["id"] = "saved"
        match["kickoff_time"] = "2020-01-01 20:00"
        match["chinese_lottery"] = lottery(3.85, 1.59, False)
        payload = {"slate": {"date": "2020-01-01"}, "current_matches": [match],
                   "checker_history": [{"id": "unchanged"}], "prediction_archive": [{"snapshot_id": "unchanged"}],
                   "result_archive": [{"result_id": "unchanged"}]}
        before = deepcopy(payload)
        updated = refresh_staking_references(payload)
        self.assertEqual(payload, before)
        for key in ("checker_history", "prediction_archive", "result_archive"):
            self.assertEqual(updated[key], before[key])
        fresh = updated["current_matches"][0]
        for key in ("selection_keys", "confidence", "betting_eligible"):
            self.assertEqual(fresh["prediction"].get(key), match["prediction"].get(key))
        self.assertEqual(fresh["chinese_lottery"], match["chinese_lottery"])
        self.assertEqual(len(fresh["staking_references"]), 3)
        self.assertFalse(updated["last_staking_refresh"]["forecasts_regenerated"])

    def test_missing_invalid_and_duplicate_selections(self):
        for price in (None, 0, 1, -1, float("nan"), float("inf"), True, "bad"):
            self.assertEqual(build_staking_plan(lottery(price, 1.6), ["draw", "away"])["status"], "missing_data")
        for keys in ([], ["draw"], ["draw", "draw"], ["home", "draw", "away"], ["draw", "other"]):
            self.assertEqual(build_staking_plan(lottery(3.55, 1.6), keys)["status"], "missing_data")
        self.assertEqual(build_staking_plan(None, ["draw", "away"])["status"], "missing_data")

    def test_selection_order_does_not_change_plan_and_input_is_untouched(self):
        quotes = lottery(3.55, 1.6)
        before = deepcopy(quotes)
        self.assertEqual(build_staking_plan(quotes, ["draw", "away"]), build_staking_plan(quotes, ["away", "draw"]))
        self.assertEqual(quotes, before)

    def test_search_matches_independent_integer_cent_enumeration(self):
        for left in (140, 180, 200, 250, 355):
            for right in (140, 180, 200, 250, 355):
                feasible = [(a+b, min(2*a*left - 200*(a+b), 2*b*right - 200*(a+b)))
                            for a in range(1, 20) for b in range(1, 20)
                            if a+b <= 20 and 2*a*left > 200*(a+b) and 2*b*right > 200*(a+b)]
                plan = build_staking_plan(lottery(left/100, right/100), ["draw", "away"], 40)
                with self.subTest(left=left, right=right):
                    if feasible:
                        smallest = min(row[0] for row in feasible)
                        best_floor = max(row[1] for row in feasible if row[0] == smallest)
                        self.assertEqual(plan["total_stake"], smallest*2)
                        self.assertEqual(plan["minimum_covered_profit"], best_floor/100)
                    else:
                        self.assertNotEqual(plan["status"], "feasible")

    def test_impossible_pattern_remains_visible_but_not_a_betting_candidate(self):
        item = dynamic_analysis_match(True)
        item["chinese_lottery"] = lottery(2.5, 1.4)
        analyzed = analyze_slate_match(item)
        self.assertTrue(analyzed["mismatch"]["matched"])
        self.assertFalse(analyzed["prediction"]["betting_eligible"])
        self.assertEqual(_checker_candidates([analyzed], "2026-08-22"), [])
        self.assertFalse(valid_prediction(analyzed))
        report = _attach_bilingual_reports([analyzed])[0]
        self.assertIn("不建议双选", report["report_zh"])
        self.assertIn("Skip this pair", report["report_en"])

    def test_replay_uses_frozen_stake_ratio_not_equal_split(self):
        analyzed = analyze_slate_match(dynamic_analysis_match(True))
        self.assertTrue(analyzed["prediction"]["betting_eligible"])
        self.assertTrue(valid_prediction(analyzed))
        self.assertEqual(len(_checker_candidates([analyzed], "2026-08-22")), 1)
        # 0-0 with home -1 settles as away; 4 yuan at 1.6 returns 6.4 on a 6-yuan pair.
        decision = settle_saved_prediction(analyzed, MatchScore(0, 0))
        self.assertAlmostEqual(unit_profit(analyzed, decision), .4 / 6)
        # Home wins by two: uncovered result loses the entire combination.
        decision = settle_saved_prediction(analyzed, MatchScore(2, 0))
        self.assertEqual(unit_profit(analyzed, decision), -1)

    def test_non_mismatch_prediction_has_no_staking_plan(self):
        analyzed = analyze_slate_match(dynamic_analysis_match(False))
        self.assertNotIn("staking_plan", analyzed["prediction"])


if __name__ == "__main__":
    unittest.main()
