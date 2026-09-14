from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from odds_analyzer.jobs.refresh_evening_slate import _enrich_with_football_data, build_evening_slate_batch
from odds_analyzer.sources.football_data import FootballDataFixture, FootballDataStanding, FootballDataForm, FootballDataSnapshot
from odds_analyzer.slate_analysis import analyze_slate_matches


class VerifiedFormRefreshTest(unittest.TestCase):
    def setUp(self):
        self.match = json.loads((Path(__file__).parent / "fixtures/levante_verified_form.json").read_text(encoding="utf-8"))
        self.fixture = FootballDataFixture(564675, "PD", "La Liga", "2026-09-13T14:15:00Z", "2026-09-13 22:15", 88, "Levante UD", 81, "FC Barcelona", 5, None, "TIMED")
        standings = {}
        for side in ("home", "away"):
            team = dict(self.match["fundamental_context"][side])
            team.pop("form")
            team["team_name"] = self.match[f"{side}_team"]
            standings[team["team_id"]] = FootballDataStanding(**team)
        self.snapshot = FootballDataSnapshot((self.fixture,), standings, {})

    def refresh(self, match=None, snapshot=None):
        return _enrich_with_football_data([match or self.match], snapshot or self.snapshot)[0]

    def test_same_slate_refresh_keeps_verified_forms_and_mismatch(self):
        original = deepcopy(self.match)
        batch = build_evening_slate_batch(
            {"slate": {"date": "2026-09-13"}, "current_matches": [self.match]},
            "2026-09-13", football_data_snapshot=self.snapshot,
        )
        match = next(m for m in batch["current_matches"] if m["id"] == self.match["id"])
        self.assertTrue(match["mismatch"]["matched"])
        self.assertEqual(match["prediction"]["market"], "竞彩让球 +2")
        self.assertEqual(set(match["prediction"]["selection_keys"]), {"away", "draw"})
        for side in ("home", "away"):
            self.assertEqual(match["fundamental_context"][side]["form"], original["fundamental_context"][side]["form"])
            self.assertIn("沿用同场赛前已核验记录", match["fundamentals"][0][side])
            self.assertIn("form_provenance", match["fundamental_context"][side])
        self.assertEqual(self.match, original)
        self.assertTrue(analyze_slate_matches([self.refresh(match)])[0]["mismatch"]["matched"])

    def test_fresh_forms_take_precedence(self):
        snapshot = replace(self.snapshot, forms={88: FootballDataForm(88, ("W", "W", "W"))})
        match = self.refresh(snapshot=snapshot)
        self.assertEqual(match["fundamental_context"]["home"]["form"], ["W"] * 3)
        self.assertNotIn("form_provenance", match["fundamental_context"]["home"])

    def test_changed_stats_do_not_reuse_old_form(self):
        standings = dict(self.snapshot.standings)
        standings[88] = replace(standings[88], played_games=5)
        match = self.refresh(snapshot=replace(self.snapshot, standings=standings))
        self.assertEqual(match["fundamental_context"]["home"]["form"], [])
        self.assertFalse(analyze_slate_matches([match])[0]["mismatch"]["matched"])

    def test_missing_stale_post_kickoff_or_untraceable_evidence_is_rejected(self):
        for timestamp in (None, "bad", "2026-09-12T16:00:00+08:00", "2026-09-13T22:16:00+08:00", "2026-09-13T16:00:00"):
            with self.subTest(timestamp=timestamp):
                match = deepcopy(self.match)
                match["fallback_research"]["fundamentals"]["queried_at"] = timestamp
                self.assertEqual(self.refresh(match)["fundamental_context"]["home"]["form"], [])
        match = deepcopy(self.match)
        match["fallback_research"]["fundamentals"]["sources"] = []
        self.assertEqual(self.refresh(match)["fundamental_context"]["home"]["form"], [])

    def test_different_fixture_does_not_reuse_form(self):
        match = deepcopy(self.match)
        match["football_data_snapshot"]["match_id"] = 999
        self.assertEqual(self.refresh(match)["fundamental_context"]["home"]["form"], [])

    def test_missing_form_message_does_not_claim_four_games_are_less_than_three(self):
        match = deepcopy(self.match)
        match.pop("fallback_research")
        analyzed = analyze_slate_matches([self.refresh(match)])[0]
        self.assertIn("近期战绩记录不足3条", analyzed["recommendation"]["fundamental"])
        self.assertNotIn("当前赛季样本不足3场", analyzed["recommendation"]["fundamental"])


if __name__ == "__main__":
    unittest.main()
