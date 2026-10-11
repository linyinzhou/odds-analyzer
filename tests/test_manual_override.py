from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer.jobs.refresh_evening_slate import refresh_evening_slate


class ManualOverrideTest(unittest.TestCase):
    def test_manual_report_marks_its_slate_and_scheduled_rerun_keeps_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily_matches.json"
            path.write_text(json.dumps({"slate": {"date": "2026-10-10"}, "current_matches": []}), encoding="utf-8")
            with (
                patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}, clear=True),
                patch("odds_analyzer.jobs.refresh_evening_slate.fetch_official_sporttery_matches", return_value=[]),
                patch("odds_analyzer.jobs.refresh_evening_slate.fetch_evening_polymarket_events", return_value=[]),
                patch(
                    "odds_analyzer.jobs.refresh_evening_slate.build_evening_slate_batch",
                    return_value={"slate": {"date": "2026-10-10"}, "current_matches": [], "mismatch_history": [], "checker_history": []},
                ),
            ):
                manual = refresh_evening_slate(path, "2026-10-10")

            self.assertEqual(manual["manual_override"]["slate_date"], "2026-10-10")
            self.assertEqual(manual["manual_override"]["source"], "evening-report")
            before = path.read_bytes()

            with (
                patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True),
                patch("odds_analyzer.jobs.refresh_evening_slate.fetch_official_sporttery_matches") as sporttery,
            ):
                scheduled = refresh_evening_slate(path, "2026-10-10")

            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(scheduled["manual_override"], manual["manual_override"])
            sporttery.assert_not_called()

    def test_next_slate_can_refresh_after_manual_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily_matches.json"
            path.write_text(
                json.dumps({
                    "slate": {"date": "2026-10-10"},
                    "current_matches": [],
                    "manual_override": {"slate_date": "2026-10-10", "source": "fallback"},
                }),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}, clear=True),
                patch("odds_analyzer.jobs.refresh_evening_slate.fetch_official_sporttery_matches", return_value=[]),
                patch("odds_analyzer.jobs.refresh_evening_slate.fetch_evening_polymarket_events", return_value=[]),
                patch(
                    "odds_analyzer.jobs.refresh_evening_slate.build_evening_slate_batch",
                    return_value={"slate": {"date": "2026-10-11"}, "current_matches": [], "mismatch_history": [], "checker_history": []},
                ) as build,
            ):
                scheduled = refresh_evening_slate(path, "2026-10-11")

            build.assert_called_once()
            self.assertEqual(scheduled["slate"]["date"], "2026-10-11")
            self.assertEqual(scheduled["manual_override"]["slate_date"], "2026-10-10")


if __name__ == "__main__":
    unittest.main()
