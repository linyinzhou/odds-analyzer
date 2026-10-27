import copy
import unittest
from test_handicap_analysis import dynamic_analysis_match
from odds_analyzer.slate_analysis import analyze_slate_match, _asian_margin_requirement
from odds_analyzer.calibration import apply_confidence_calibration
from odds_analyzer.learning import valid_prediction
from odds_analyzer.jobs.refresh_evening_slate import _checker_candidates


class ObservationPolicyTests(unittest.TestCase):
    def test_market_only_direction_cannot_become_recommendation(self):
        source = dynamic_analysis_match(False)
        original = copy.deepcopy(source)
        result = analyze_slate_match(source)
        self.assertEqual(source, original)
        self.assertEqual(result["prediction"]["decision"], "watch")
        self.assertFalse(valid_prediction(result))
        self.assertEqual(_checker_candidates([result], "2026-10-11"), [])
        calibrated = apply_confidence_calibration(result, {"strategies": {
            "market:asian_handicap": {"active": True, "adjustment": 5}}})
        self.assertEqual(calibrated["prediction"], result["prediction"])

    def test_quarter_lines_and_received_handicap_settlement(self):
        for line, expected in [(-.25, "0 half loss"), (-.75, "+1 half win"),
                               (.25, "0 half win"), (.75, "-1 half loss"),
                               (-2, "+2 push"), (-2.5, "+3 win")]:
            with self.subTest(line=line):
                self.assertIn(expected, _asian_margin_requirement(line)[1])

    def test_missing_context_is_explained(self):
        source = dynamic_analysis_match(False)
        source["fundamental_context"] = {}
        result = analyze_slate_match(source)
        self.assertEqual(result["prediction"]["confidence"], 0)
        self.assertEqual(result["prediction"]["selection_keys"], [])
        self.assertTrue(result["recommendation"]["fundamental"])

    def test_nonfinite_and_invalid_lines_are_not_predictions(self):
        for line in [float("nan"), float("inf"), .3]:
            source = dynamic_analysis_match(False)
            source["asian_handicap"]["handicap"] = line
            result = analyze_slate_match(source)
            self.assertEqual(result["prediction"]["market_type"], "none")

if __name__ == "__main__":
    unittest.main()
