from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.calibration import (
    MINIMUM_SAMPLE,
    apply_confidence_calibration,
    build_strategy_performance,
)


def reviewed_match(index: int, hit: bool, confidence: int = 60, reviewed: bool = True) -> dict:
    return {
        "id": f"match-{index}",
        "batch_date": f"2026-07-{index + 1:02d}",
        "mismatch": {"matched": True, "status": "lottery_deeper_small_win"},
        "prediction": {
            "market": "竞彩让球 -1",
            "market_type": "sporttery_handicap",
            "confidence": confidence,
        },
        "review": {"reviewed": reviewed, "hit": hit, "void": False},
    }


class StrategyCalibrationTest(unittest.TestCase):
    def test_small_sample_is_recorded_but_does_not_adjust_confidence(self):
        history = [reviewed_match(index, True) for index in range(MINIMUM_SAMPLE - 1)]
        performance = build_strategy_performance(history, "2026-08-25T08:20:00+08:00")
        strategy = performance["strategies"]["mismatch:lottery_deeper_small_win"]

        self.assertEqual(strategy["sample_size"], MINIMUM_SAMPLE - 1)
        self.assertFalse(strategy["active"])
        self.assertEqual(strategy["adjustment"], 0)

        calibrated = apply_confidence_calibration(history[0], performance)
        self.assertEqual(calibrated["prediction"]["confidence"], 60)
        self.assertEqual(calibrated["prediction"]["calibration"]["status"], "collecting")

    def test_minimum_sample_enables_bounded_adjustment(self):
        history = [reviewed_match(index, True) for index in range(MINIMUM_SAMPLE)]
        performance = build_strategy_performance(history, "2026-08-25T08:20:00+08:00")
        strategy = performance["strategies"]["mismatch:lottery_deeper_small_win"]

        self.assertTrue(strategy["active"])
        self.assertEqual(strategy["adjustment"], 5)

        calibrated = apply_confidence_calibration(history[0], performance)
        self.assertEqual(calibrated["prediction"]["base_confidence"], 60)
        self.assertEqual(calibrated["prediction"]["confidence"], 65)
        self.assertEqual(calibrated["prediction"]["calibration"]["adjustment"], 5)

    def test_current_batch_review_is_excluded_from_walk_forward_training(self):
        history = [reviewed_match(index, True) for index in range(5)]
        same_batch = reviewed_match(10, True)
        same_batch["batch_date"] = "2026-08-25"
        history.append(same_batch)

        performance = build_strategy_performance(
            history, "2026-08-25T18:00:00+08:00", before_batch="2026-08-25"
        )
        strategy = performance["strategies"]["mismatch:lottery_deeper_small_win"]

        self.assertEqual(strategy["sample_size"], 5)
        self.assertEqual(performance["trained_through_batch"], "2026-07-05")

    def test_unreviewed_future_rows_do_not_enter_training_sample(self):
        history = [reviewed_match(index, index % 2 == 0) for index in range(5)]
        history.append(reviewed_match(20, True, reviewed=False))

        performance = build_strategy_performance(history, "2026-08-25T08:20:00+08:00")
        strategy = performance["strategies"]["mismatch:lottery_deeper_small_win"]

        self.assertEqual(strategy["sample_size"], 5)
        self.assertEqual(performance["trained_through_batch"], "2026-07-05")


if __name__ == "__main__":
    unittest.main()
