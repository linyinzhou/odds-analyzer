import unittest
from datetime import date, datetime, timedelta, timezone as fixed_timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds_analyzer import (
    AsianHandicapLine,
    AsianHandicapOdds,
    ChineseLotteryLine,
    ChineseLotteryOdds,
    HandicapMismatchCheck,
    MatchRequest,
    MatchReport,
    MatchSlateWindow,
    MatchScore,
    Selection,
    ThreeWayOdds,
    build_match_search_plan,
    build_today_slate_window,
    check_lottery_asian_mismatch,
    compare_handicap_markets,
    render_match_report,
    merge_dashboard_payload,
    settle_asian_handicap,
    settle_chinese_lottery,
)
from odds_analyzer.jobs.refresh_evening_slate import build_evening_slate_batch
from odds_analyzer.sources import (
    DataSourcePurpose,
    ReliabilityTier,
    get_data_source_candidates,
    get_sources_by_purpose,
    parse_official_sporttery,
)

class HandicapSettlementTest(unittest.TestCase):
    def test_chinese_lottery_draw_when_home_gives_one_and_wins_by_one(self):
        score = MatchScore(home_goals=2, away_goals=1)
        line = ChineseLotteryLine(home_handicap=-1)

        self.assertEqual(settle_chinese_lottery(score, line), Selection.DRAW)

    def test_asian_home_minus_half_wins_when_home_wins_by_one(self):
        score = MatchScore(home_goals=2, away_goals=1)
        line = AsianHandicapLine(home_handicap=-0.5)

        self.assertEqual(settle_asian_handicap(score, line, Selection.HOME), 1.0)

    def test_asian_home_minus_one_pushes_when_home_wins_by_one(self):
        score = MatchScore(home_goals=2, away_goals=1)
        line = AsianHandicapLine(home_handicap=-1.0)

        self.assertEqual(settle_asian_handicap(score, line, Selection.HOME), 0.0)

    def test_asian_home_minus_quarter_half_wins_when_home_draws(self):
        score = MatchScore(home_goals=1, away_goals=1)
        line = AsianHandicapLine(home_handicap=-0.25)

        self.assertEqual(settle_asian_handicap(score, line, Selection.AWAY), 0.5)

class HandicapAnalysisTest(unittest.TestCase):
    def test_lottery_draw_signal_for_half_ball_vs_lottery_minus_one(self):
        signal = compare_handicap_markets(
            asian_line=AsianHandicapLine(home_handicap=-0.5),
            lottery_line=ChineseLotteryLine(home_handicap=-1),
            estimated_home_margin=1.0,
        )

        self.assertEqual(signal.selection, Selection.DRAW)
        self.assertGreaterEqual(signal.confidence, 0.6)

    def test_mismatch_check_flags_lottery_deeper_with_draw_away_pair(self):
        check = check_lottery_asian_mismatch(
            asian_line=AsianHandicapLine(home_handicap=-0.5),
            lottery_line=ChineseLotteryLine(home_handicap=-1),
            max_supported_home_margin=1.0,
        )

        self.assertIsInstance(check, HandicapMismatchCheck)
        self.assertEqual(check.status, "lottery_deeper_small_win")
        self.assertEqual(check.preferred_selections, (Selection.DRAW, Selection.AWAY))

    def test_mismatch_check_flags_lottery_shallower(self):
        check = check_lottery_asian_mismatch(
            asian_line=AsianHandicapLine(home_handicap=-1.25),
            lottery_line=ChineseLotteryLine(home_handicap=-1),
            max_supported_home_margin=2.0,
        )

        self.assertEqual(check.status, "lottery_shallower_favorite_supported")
        self.assertEqual(check.preferred_selections, (Selection.HOME, Selection.DRAW))

    def test_mismatch_check_flags_zero_lottery_when_asian_half_ball_supports_favorite(self):
        check = check_lottery_asian_mismatch(
            asian_line=AsianHandicapLine(home_handicap=-0.5),
            lottery_line=ChineseLotteryLine(home_handicap=0),
            max_supported_home_margin=0.5,
        )

        self.assertEqual(check.status, "lottery_shallower_favorite_supported")
        self.assertEqual(check.preferred_selections, (Selection.HOME, Selection.DRAW))

class SearchPlanTest(unittest.TestCase):
    def test_build_match_search_plan_includes_core_market_queries(self):
        match = MatchRequest(
            home_team="Inter Milan",
            away_team="Juventus",
            match_date="2026-09-20",
            competition="Serie A",
        )

        plan = build_match_search_plan(match)
        topics = {item.topic for item in plan}
        queries = " ".join(item.query for item in plan)

        self.assertIn("match_context", topics)
        self.assertIn("asian_handicap", topics)
        self.assertIn("china_lottery", topics)
        self.assertIn("Inter Milan", queries)
        self.assertIn("Juventus", queries)

class MatchSlateWindowTest(unittest.TestCase):
    def test_build_today_slate_window_covers_afternoon_to_next_early_morning(self):
        window = build_today_slate_window(date(2026, 8, 8))
        try:
            tz = ZoneInfo("Asia/Shanghai")
        except ZoneInfoNotFoundError:
            tz = fixed_timezone(timedelta(hours=8), name="Asia/Shanghai")

        self.assertIsInstance(window, MatchSlateWindow)
        self.assertTrue(window.contains(datetime(2026, 8, 8, 15, 0, tzinfo=tz)))
        self.assertTrue(window.contains(datetime(2026, 8, 9, 2, 45, tzinfo=tz)))
        self.assertFalse(window.contains(datetime(2026, 8, 8, 10, 0, tzinfo=tz)))
        self.assertFalse(window.contains(datetime(2026, 8, 9, 6, 0, tzinfo=tz)))

class DataSourceRegistryTest(unittest.TestCase):
    def test_registry_has_core_sources_for_three_market_comparison(self):
        sources = get_data_source_candidates()
        keys = {source.key for source in sources}

        self.assertIn("sporttery", keys)
        self.assertIn("hkjc", keys)
        self.assertIn("the_odds_api", keys)
        self.assertIn("five_hundred", keys)

    def test_sources_can_be_filtered_by_purpose(self):
        asian_sources = get_sources_by_purpose(DataSourcePurpose.ASIAN_HANDICAP)
        keys = {source.key for source in asian_sources}

        self.assertIn("hkjc", keys)
        self.assertIn("the_odds_api", keys)
        self.assertTrue(any(source.tier == ReliabilityTier.MARKET for source in asian_sources))

class MatchReportTest(unittest.TestCase):
    def test_render_match_report_includes_markets_and_recommendation(self):
        report = MatchReport(
            match=MatchRequest("NEC Nijmegen", "Telstar", "2026-08-08", "Eredivisie"),
            kickoff_time="2026-08-08 22:30 Asia/Shanghai",
            venue="Goffertstadion",
            weather="Cloudy",
            standings=("NEC stronger baseline.",),
            form=("Telstar weaker recent profile.",),
            team_news=("Lineups pending.",),
            tactical_notes=("NEC likely needs sustained pressure to clear the handicap.",),
            head_to_head=("H2H pending source validation.",),
            fundamentals=("NEC has a stronger baseline than Telstar.",),
            european_odds=ThreeWayOdds(home=1.42, draw=4.80, away=6.80),
            asian_handicap=AsianHandicapOdds(
                handicap=-1.25,
                home_odds=1.92,
                away_odds=1.98,
                provider="HKJC",
            ),
            chinese_lottery=ChineseLotteryOdds(
                standard=ThreeWayOdds(home=1.40, draw=4.60, away=6.50),
                handicap=-1,
                handicap_odds=ThreeWayOdds(home=2.15, draw=3.55, away=2.65),
            ),
            signal=None,
            recommendation="If the Asian line remains -1.25 while lottery stays -1, prioritize handicap home.",
            risks=("Confirm lottery odds before publishing the final pick.",),
            data_sources=("HKJC candidate", "Chinese lottery pending"),
        )

        markdown = render_match_report(report)

        self.assertIn("# NEC Nijmegen vs Telstar", markdown)
        self.assertIn("## Match", markdown)
        self.assertIn("## Fundamentals", markdown)
        self.assertIn("## Odds", markdown)
        self.assertIn("## Verdict", markdown)
        self.assertIn("Ranking: NEC stronger baseline.", markdown)
        self.assertIn("Team news: Lineups pending.", markdown)
        self.assertIn("Asian handicap: HKJC -1.25", markdown)
        self.assertIn("HHAD -1", markdown)
        self.assertIn("prioritize handicap home", markdown)
        self.assertIn("HKJC candidate", markdown)

class DashboardPrototypeTest(unittest.TestCase):
    def test_dashboard_sample_payload_has_required_fields(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "daily_matches.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))

        self.assertIn("slate", payload)
        self.assertGreaterEqual(len(payload["current_matches"]), 1)
        self.assertIn("mismatch_history", payload)
        self.assertIn("checker_history", payload)

        first = payload["current_matches"][0]
        for key in ("id", "kickoff_time", "competition", "home_team", "away_team", "status", "recommendation", "prediction"):
            self.assertIn(key, first)

        for key in ("market", "pick", "confidence"):
            self.assertIn(key, first["prediction"])

        self.assertIn(first["status"], {"mismatch", "pending", "watch"})

    def test_run_status_payload_has_required_fields(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "run_status.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8-sig"))

        for key in ("status", "run_type", "run_id", "commit", "branch", "actor", "updated_at"):
            self.assertIn(key, payload)

class EveningSlateRefreshJobTest(unittest.TestCase):
    def test_build_evening_slate_for_aug_22_contains_window_matches_only(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "daily_matches.json"
        existing = json.loads(payload_path.read_text(encoding="utf-8"))

        batch = build_evening_slate_batch(existing, "2026-08-22")
        ids = {match["id"] for match in batch["current_matches"]}

        self.assertEqual(batch["slate"]["date"], "2026-08-22")
        self.assertIn("2026-08-22-hull-man-united", ids)
        self.assertIn("2026-08-22-athletic-club-sevilla-fc", ids)
        self.assertIn("2026-08-23-inter-milan-monza", ids)
        self.assertIn("2026-08-22-lens-auxerre", ids)
        self.assertNotIn("2026-08-22-arsenal-coventry", ids)
        self.assertNotIn("2026-08-23-brighton-aston-villa", ids)

    def test_placeholder_matches_do_not_enter_checker_or_mismatch(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "daily_matches.json"
        existing = json.loads(payload_path.read_text(encoding="utf-8"))

        batch = build_evening_slate_batch(existing, "2026-08-22")
        athletic = next(
            match
            for match in batch["current_matches"]
            if match["id"] == "2026-08-22-athletic-club-sevilla-fc"
        )

        self.assertIsNone(athletic["european_odds"])
        self.assertIsNone(athletic["asian_handicap"])
        self.assertIsNone(athletic["chinese_lottery"])
        self.assertEqual(athletic["prediction"]["market"], "无推荐")
        self.assertFalse(athletic["mismatch"]["matched"])
        self.assertNotIn(athletic["id"], {match["id"] for match in batch["checker_history"]})
        self.assertNotIn(athletic["id"], {match["id"] for match in batch["mismatch_history"]})
class SportterySourceTest(unittest.TestCase):
    def test_parse_official_sporttery_supports_hhad_only_match(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "sporttery_official_sample.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))

        matches = parse_official_sporttery(payload, "2026-08-21")
        match = matches[0]
        hhad = match.market("hhad")

        self.assertEqual(len(matches), 1)
        self.assertEqual(match.match_no, "周五010")
        self.assertEqual(match.home_team, "阿森纳")
        self.assertEqual(match.away_team, "考文垂")
        self.assertEqual(match.kickoff_at, "2026-08-22T03:00:00")
        self.assertIsNone(match.market("had"))
        self.assertIsNotNone(hhad)
        self.assertEqual(match.handicap, -2.0)
        self.assertEqual([outcome.odds for outcome in hhad.outcomes], [2.32, 3.8, 2.3])

class DashboardPayloadMergeTest(unittest.TestCase):
    def test_current_matches_are_replaced_and_histories_are_upserted(self):
        existing = {
            "slate": {"date": "2026-08-22", "window": "old"},
            "current_matches": [sample_match("old-current", confidence=50)],
            "mismatch_history": [sample_match("same-match", confidence=60, batch_date="2026-08-22")],
            "checker_history": [sample_match("same-match", confidence=60, batch_date="2026-08-22")],
            "next_matchday": {"competitions": []},
        }
        fresh_same_match = sample_match("same-match", confidence=72)
        batch = {
            "slate": {"date": "2026-08-22", "window": "18:00-06:00"},
            "current_matches": [sample_match("new-current", confidence=55)],
            "mismatch_history": [fresh_same_match],
            "checker_history": [fresh_same_match],
            "next_matchday": {"competitions": [{"name": "英超", "fixtures": []}]},
        }

        merged = merge_dashboard_payload(existing, batch)

        self.assertEqual([item["id"] for item in merged["current_matches"]], ["new-current"])
        self.assertEqual(len(merged["mismatch_history"]), 1)
        self.assertEqual(len(merged["checker_history"]), 1)
        self.assertEqual(merged["mismatch_history"][0]["prediction"]["confidence"], 72)
        self.assertEqual(merged["checker_history"][0]["prediction"]["confidence"], 72)
        self.assertEqual(merged["checker_history"][0]["batch_date"], "2026-08-22")

    def test_replace_history_batch_removes_stale_items_for_that_batch(self):
        existing = {
            "slate": {"date": "2026-08-22"},
            "current_matches": [],
            "mismatch_history": [sample_match("old-same-batch", confidence=60, batch_date="2026-08-22")],
            "checker_history": [
                sample_match("old-same-batch", confidence=60, batch_date="2026-08-22"),
                sample_match("older-batch", confidence=55, batch_date="2026-08-21"),
            ],
        }
        batch = {
            "slate": {"date": "2026-08-22"},
            "current_matches": [],
            "mismatch_history": [],
            "checker_history": [sample_match("fresh", confidence=70)],
            "replace_history_batch": True,
        }

        merged = merge_dashboard_payload(existing, batch)

        self.assertEqual([item["id"] for item in merged["mismatch_history"]], [])
        self.assertEqual(
            [item["id"] for item in merged["checker_history"]],
            ["fresh", "older-batch"],
        )
    def test_same_match_in_different_batch_is_preserved(self):
        existing = {
            "slate": {"date": "2026-08-23"},
            "current_matches": [],
            "mismatch_history": [sample_match("same-match", confidence=60, batch_date="2026-08-22")],
            "checker_history": [],
        }
        batch = {
            "slate": {"date": "2026-08-23"},
            "current_matches": [],
            "mismatch_history": [sample_match("same-match", confidence=70)],
            "checker_history": [],
        }

        merged = merge_dashboard_payload(existing, batch)

        self.assertEqual(len(merged["mismatch_history"]), 2)
        self.assertEqual([item["batch_date"] for item in merged["mismatch_history"]], ["2026-08-23", "2026-08-22"])

def sample_match(match_id, confidence, batch_date=None):
    item = {
        "id": match_id,
        "kickoff_time": "08-22 22:00",
        "competition": "英超",
        "home_team": "主队",
        "away_team": "客队",
        "status": "watch",
        "recommendation": {"fundamental": "test", "mismatch": "test"},
        "prediction": {"market": "竞彩", "pick": "胜", "confidence": confidence},
    }
    if batch_date:
        item["batch_date"] = batch_date
    return item

if __name__ == "__main__":
    unittest.main()

