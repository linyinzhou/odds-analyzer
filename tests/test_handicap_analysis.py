import unittest
from datetime import date, datetime, timedelta, timezone as fixed_timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from unittest.mock import patch
from urllib.error import HTTPError
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
from odds_analyzer.jobs.refresh_evening_slate import (
    _checker_candidates,
    _build_next_matchday,
    _enrich_with_odds_api,
    _normalize_team,
    build_evening_slate_batch,
)
from odds_analyzer.jobs.review_results import (
    refresh_next_matchday,
    review_checker_results,
    review_results,
    settle_saved_prediction,
)
from odds_analyzer.slate_analysis import analyze_slate_match
from odds_analyzer.sources.football_data import _source_error
from odds_analyzer.sources import (
    DataSourcePurpose,
    fetch_evening_football_data,
    fetch_evening_fixtures,
    fetch_upcoming_fixtures,
    parse_football_data_standings,
    parse_football_data_forms,
    FootballDataFixture,
    parse_football_data_fixtures,
    FootballDataSnapshot,
    OddsApiEvent,
    SportteryMarket,
    SportteryMatch,
    SportteryOutcome,
    ReliabilityTier,
    get_data_source_candidates,
    get_sources_by_purpose,
    parse_odds_api_events,
    parse_official_sporttery,
)


class FootballDataSourceErrorTest(unittest.TestCase):
    def test_http_error_includes_safe_api_message(self):
        error = HTTPError(
            url="https://api.football-data.org/v4/competitions/PL/matches",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"message":"Your API token is invalid.","errorCode":400}'),
        )

        self.assertEqual(
            _source_error(error),
            "HTTP 400 Bad Request: Your API token is invalid.",
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

class DynamicSlateAnalysisTest(unittest.TestCase):
    def test_complete_three_market_snapshot_generates_mismatch_prediction(self):
        match = dynamic_analysis_match(include_lottery=True)

        analyzed = analyze_slate_match(match)

        self.assertTrue(analyzed["mismatch"]["matched"])
        self.assertEqual(analyzed["mismatch"]["status"], "lottery_deeper_small_win")
        self.assertEqual(analyzed["prediction"]["market"], "竞彩让球 -1")
        self.assertEqual(analyzed["prediction"]["pick"], "让平 + 让负")
        self.assertEqual(analyzed["prediction"]["basis"], "fresh_three_market_snapshot")
        self.assertGreaterEqual(analyzed["prediction"]["confidence"], 60)

    def test_european_asian_snapshot_generates_exact_asian_recommendation(self):
        match = dynamic_analysis_match(include_lottery=False)

        analyzed = analyze_slate_match(match)

        self.assertFalse(analyzed["mismatch"]["matched"])
        self.assertEqual(analyzed["prediction"]["market"], "亚盘 Pinnacle")
        self.assertEqual(analyzed["prediction"]["pick"], "主队 -0.25")
        self.assertEqual(analyzed["prediction"]["basis"], "fresh_european_asian_snapshot")
        self.assertIn("本次竞彩未取得", analyzed["market_read"])

    def test_deeper_line_with_favorite_aligned_fundamentals_is_not_mismatch(self):
        match = dynamic_analysis_match(include_lottery=True)
        match["fundamental_context"]["home"]["played_games"] = 2
        match["fundamental_context"]["away"]["played_games"] = 2
        match["fundamental_context"]["home"]["form"] = ["L", "D"]
        match["fundamental_context"]["away"]["form"] = ["W", "W"]
        match["european_odds"] = {"home": 3.30, "draw": 3.35, "away": 2.22}
        match["asian_handicap"]["handicap"] = 0.25
        match["chinese_lottery"]["handicap"] = 1

        analyzed = analyze_slate_match(match)

        self.assertFalse(analyzed["mismatch"]["matched"])
        self.assertIn("基本面与盘口热门方方向一致", analyzed["mismatch"]["reason"])

    def test_limited_sample_keeps_fundamental_direction_and_marks_candidate(self):
        match = dynamic_analysis_match(include_lottery=True)
        match["fundamental_context"]["home"].update(
            {"played_games": 1, "points": 0, "goal_difference": -3, "form": []}
        )
        match["fundamental_context"]["away"].update(
            {"played_games": 1, "points": 1, "goal_difference": 0, "form": []}
        )

        analyzed = analyze_slate_match(match)

        self.assertTrue(analyzed["mismatch"]["matched"])
        self.assertTrue(analyzed["mismatch"]["limited_sample"])
        self.assertEqual(analyzed["signal_label"], "错盘候选")
        self.assertEqual(analyzed["prediction"]["confidence"], 58)
        self.assertIn("偏向客队", analyzed["recommendation"]["fundamental"])
        self.assertIn("样本不足3场", analyzed["recommendation"]["fundamental"])

    def test_lottery_deeper_mismatch_is_supported_by_underdog_fundamentals(self):
        match = dynamic_analysis_match(include_lottery=True)
        match["asian_handicap"]["handicap"] = -0.5
        match["fundamental_context"]["home"]["points"] = 0
        match["fundamental_context"]["home"]["goal_difference"] = -5
        match["fundamental_context"]["away"]["points"] = 9
        match["fundamental_context"]["away"]["goal_difference"] = 0

        analyzed = analyze_slate_match(match)

        self.assertTrue(analyzed["mismatch"]["matched"])
        self.assertEqual(analyzed["prediction"]["pick"], "让平 + 让负")
        self.assertFalse(analyzed["mismatch"]["limited_sample"])
        self.assertIn("基本面偏受让方", analyzed["mismatch"]["reason"])

    def test_away_favorite_mismatch_reverses_sporttery_selections(self):
        match = dynamic_analysis_match(include_lottery=True)
        match["european_odds"] = {"home": 3.80, "draw": 3.30, "away": 2.00}
        match["asian_handicap"] = {
            "provider": "Pinnacle",
            "handicap": 0.25,
            "home_odds": 1.95,
            "away_odds": 1.95,
        }
        match["chinese_lottery"]["handicap"] = 1
        match["fundamental_context"]["home"]["points"] = 21
        match["fundamental_context"]["home"]["goal_difference"] = 7
        match["fundamental_context"]["away"]["points"] = 11
        match["fundamental_context"]["away"]["goal_difference"] = -5

        analyzed = analyze_slate_match(match)

        self.assertTrue(analyzed["mismatch"]["matched"])
        self.assertEqual(analyzed["prediction"]["market"], "竞彩让球 +1")
        self.assertEqual(analyzed["prediction"]["pick"], "让平 + 让胜")

class ResultReviewTest(unittest.TestCase):
    def test_sporttery_handicap_combination_is_settled_from_saved_market(self):
        match = analyze_slate_match(dynamic_analysis_match(include_lottery=True))

        decision = settle_saved_prediction(match, MatchScore(home_goals=1, away_goals=0))

        self.assertTrue(decision["hit"])
        self.assertFalse(decision["void"])
        self.assertEqual(decision["settlement"], "draw")

    def test_asian_push_is_void_not_a_miss(self):
        match = analyze_slate_match(dynamic_analysis_match(include_lottery=False))
        match["prediction"]["home_handicap"] = -1.0
        match["prediction"]["pick"] = "主队 -1"

        decision = settle_saved_prediction(match, MatchScore(home_goals=1, away_goals=0))

        self.assertIsNone(decision["hit"])
        self.assertTrue(decision["void"])
        self.assertEqual(decision["outcome"], "push")

    def test_legacy_sporttery_standard_pick_is_supported(self):
        match = {"prediction": {"market": "竞彩胜平负", "pick": "客胜"}}

        decision = settle_saved_prediction(match, MatchScore(home_goals=0, away_goals=2))

        self.assertTrue(decision["hit"])
        self.assertEqual(decision["settlement"], "away")

    def test_review_updates_only_target_batch(self):
        target = analyze_slate_match(dynamic_analysis_match(include_lottery=True))
        target["batch_date"] = "2026-08-22"
        target["football_data_snapshot"] = {"match_id": 1001}
        older = sample_match("older", 55, batch_date="2026-08-21")
        fixture_payload = {
            "competition": {"code": "PL", "name": "Premier League"},
            "matches": [
                {
                    "id": 1001,
                    "utcDate": "2026-08-22T14:00:00Z",
                    "status": "FINISHED",
                    "homeTeam": {"id": 1, "name": "主队"},
                    "awayTeam": {"id": 2, "name": "客队"},
                    "score": {"fullTime": {"home": 1, "away": 0}},
                }
            ],
        }
        fixtures = parse_football_data_fixtures(fixture_payload, "PL")

        reviewed, counts = review_checker_results(
            {"checker_history": [target, older]},
            "2026-08-22",
            fixtures,
            "2026-08-23T08:00:00+08:00",
        )

        self.assertEqual(counts["reviewed"], 1)
        self.assertTrue(reviewed["checker_history"][0]["review"]["hit"])
        self.assertEqual(reviewed["checker_history"][0]["review"]["final_score"], "1-0")
        self.assertNotIn("review", reviewed["checker_history"][1])

    def test_morning_review_refreshes_all_schedule_competitions_independently(self):
        query_time = datetime(
            2026,
            8,
            29,
            8,
            tzinfo=fixed_timezone(timedelta(hours=8)),
        )

        def fetch_by_competition(api_key, start_date, days=14, competition_codes=(), timeout=20):
            code = competition_codes[0]
            if code != "PD":
                return ()
            return (
                FootballDataFixture(
                    match_id=2001,
                    competition_code="PD",
                    competition_name="PD",
                    utc_date="2026-09-05T14:00:00Z",
                    kickoff_time="2026-09-05 22:00",
                    home_team_id=None,
                    home_team="Home",
                    away_team_id=None,
                    away_team="Away",
                    matchday=4,
                    stage="REGULAR_SEASON",
                    status="TIMED",
                ),
            )

        with patch(
            "odds_analyzer.jobs.review_results.fetch_upcoming_fixtures",
            side_effect=fetch_by_competition,
        ) as fetch:
            updated, counts = refresh_next_matchday(
                {"current_matches": [], "next_matchday": {"generated_at": "old"}},
                "api-key",
                query_time,
            )

        self.assertEqual(fetch.call_count, 6)
        self.assertEqual(counts["status"], "success")
        self.assertEqual(updated["next_matchday"]["generated_at"], "2026-08-29T08:00:00+08:00")
        by_name = {
            competition["name"]: competition
            for competition in updated["next_matchday"]["competitions"]
        }
        self.assertEqual(set(by_name), {"英超", "西甲", "意甲", "德甲", "法甲", "欧冠"})
        self.assertEqual(by_name["西甲"]["fixtures"][0]["home_team"], "Home")
        self.assertEqual(by_name["意甲"]["fixtures"], [])

    def test_morning_schedule_partial_failure_keeps_other_competitions(self):
        query_time = datetime(
            2026,
            8,
            29,
            8,
            tzinfo=fixed_timezone(timedelta(hours=8)),
        )

        def partial_fetch(api_key, start_date, days=14, competition_codes=(), timeout=20):
            if competition_codes == ("SA",):
                raise RuntimeError("unavailable")
            return ()

        with patch(
            "odds_analyzer.jobs.review_results.fetch_upcoming_fixtures",
            side_effect=partial_fetch,
        ):
            updated, counts = refresh_next_matchday({}, "api-key", query_time)

        self.assertEqual(counts["status"], "partial")
        self.assertEqual(counts["successful"], 5)
        self.assertEqual(updated["next_matchday"]["refresh_errors"], {"意甲": "RuntimeError"})
        serie_a = next(
            item
            for item in updated["next_matchday"]["competitions"]
            if item["name"] == "意甲"
        )
        self.assertIn("查询失败", serie_a["status"])

    def test_morning_schedule_total_failure_preserves_last_generated_data(self):
        query_time = datetime(
            2026,
            8,
            29,
            8,
            tzinfo=fixed_timezone(timedelta(hours=8)),
        )
        existing = {
            "next_matchday": {
                "generated_at": "2026-08-28T18:00:00+08:00",
                "competitions": [{"name": "英超", "fixtures": []}],
            }
        }

        with patch(
            "odds_analyzer.jobs.review_results.fetch_upcoming_fixtures",
            side_effect=RuntimeError("unavailable"),
        ):
            updated, counts = refresh_next_matchday(existing, "api-key", query_time)

        self.assertEqual(counts["status"], "unavailable")
        self.assertEqual(updated["next_matchday"]["generated_at"], "2026-08-28T18:00:00+08:00")
        self.assertEqual(updated["next_matchday"]["last_attempt_at"], "2026-08-29T08:00:00+08:00")

    def test_schedule_refresh_still_runs_when_result_fixture_fetch_fails(self):
        schedule_counts = {"status": "success", "successful": 6, "failed": 0}
        with TemporaryDirectory() as directory:
            payload_path = Path(directory) / "payload.json"
            payload_path.write_text('{"checker_history": []}', encoding="utf-8")
            with (
                patch(
                    "odds_analyzer.jobs.review_results.fetch_evening_fixtures",
                    side_effect=RuntimeError("results unavailable"),
                ),
                patch(
                    "odds_analyzer.jobs.review_results.refresh_next_matchday",
                    return_value=({"checker_history": [], "next_matchday": {}}, schedule_counts),
                ) as refresh,
            ):
                updated = review_results(payload_path, "2026-08-28", "api-key")

        refresh.assert_called_once()
        self.assertEqual(updated["next_matchday"], {})


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

class CheckerCandidateTest(unittest.TestCase):
    def test_small_batch_keeps_only_top_three(self):
        matches = [sample_match(f"match-{index}", confidence) for index, confidence in enumerate((51, 55, 53, 52))]

        selected = _checker_candidates(matches, "2026-08-22")

        self.assertEqual([item["prediction"]["confidence"] for item in selected], [55, 53, 52])

    def test_large_batch_is_capped_at_eight(self):
        matches = [sample_match(f"match-{index}", 50 + index) for index in range(10)]

        selected = _checker_candidates(matches, "2026-08-22")

        self.assertEqual(len(selected), 8)
        self.assertEqual(selected[0]["prediction"]["confidence"], 59)


class WorkflowConfigurationTest(unittest.TestCase):
    def test_evening_workflow_runs_daily_at_beijing_16(self):
        workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "manual-report.yml"
        workflow = workflow_path.read_text(encoding="utf-8")

        self.assertIn('cron: "0 8 * * *"', workflow)
        self.assertIn("github.event.schedule == '0 8 * * *'", workflow)
        self.assertIn('cron: "0 0 * * *"', workflow)
        self.assertIn("odds_analyzer.jobs.review_results", workflow)


class EveningSlateRefreshJobTest(unittest.TestCase):
    def test_build_evening_slate_for_aug_22_contains_window_matches_only(self):
        batch = build_evening_slate_batch({}, "2026-08-22")
        ids = {match["id"] for match in batch["current_matches"]}

        self.assertEqual(batch["slate"]["date"], "2026-08-22")
        self.assertIn("2026-08-22-athletic-club-sevilla-fc", ids)
        self.assertIn("2026-08-23-inter-milan-monza", ids)
        self.assertIn("2026-08-22-lens-auxerre", ids)
        self.assertNotIn("2026-08-22-arsenal-coventry", ids)
        self.assertNotIn("2026-08-23-brighton-aston-villa", ids)

    def test_sporttery_enrichment_updates_lottery_without_prediction(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "daily_matches.json"
        existing = json.loads(payload_path.read_text(encoding="utf-8"))
        sporttery_match = SportteryMatch(
            match_id="fixture-016",
            match_no="周六016",
            business_date="2026-08-22",
            league="西甲",
            home_team="毕尔巴鄂",
            away_team="塞维利亚",
            kickoff_at="2026-08-22T23:00:00",
            markets=(
                SportteryMarket(
                    code="hhad",
                    label="让球胜平负",
                    line=-1.0,
                    outcomes=(
                        SportteryOutcome("home", "主胜", 2.10, "flat"),
                        SportteryOutcome("draw", "平", 3.55, "flat"),
                        SportteryOutcome("away", "客胜", 2.70, "flat"),
                    ),
                    updated_at="2026-08-22 12:00:00",
                ),
            ),
        )

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            sporttery_matches=[sporttery_match],
            sporttery_source="Sporttery official",
        )
        athletic = next(
            match
            for match in batch["current_matches"]
            if match["id"] == "2026-08-22-athletic-club-sevilla-fc"
        )

        self.assertEqual(batch["slate"]["sporttery_source"], "Sporttery official")
        self.assertEqual(athletic["chinese_lottery"]["handicap"], -1)
        self.assertEqual(athletic["chinese_lottery"]["handicap_odds"]["home"], 2.10)
        self.assertEqual(athletic["sporttery_snapshot"]["match_no"], "周六016")
        self.assertEqual(athletic["signal_label"], "数据不足")
        self.assertEqual(athletic["prediction"]["market"], "无推荐")

    def test_odds_api_enrichment_fills_missing_european_and_asian_odds(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "daily_matches.json"
        existing = json.loads(payload_path.read_text(encoding="utf-8"))
        odds_event = OddsApiEvent(
            event_id="event-1",
            sport_key="soccer_spain_la_liga",
            commence_time="2026-08-22T15:00:00Z",
            home_team="Athletic Club",
            away_team="Sevilla FC",
            bookmaker="Pinnacle",
            bookmaker_key="pinnacle",
            updated_at="2026-08-22T10:00:00Z",
            european_odds=ThreeWayOdds(home=1.95, draw=3.40, away=3.80),
            asian_handicap=AsianHandicapOdds(
                handicap=-0.5,
                home_odds=1.91,
                away_odds=1.99,
                provider="Pinnacle",
            ),
        )

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            odds_api_events=[odds_event],
            odds_api_source="The Odds API",
        )
        athletic = next(
            match
            for match in batch["current_matches"]
            if match["id"] == "2026-08-22-athletic-club-sevilla-fc"
        )

        self.assertEqual(batch["slate"]["odds_api_source"], "The Odds API")
        self.assertEqual(athletic["european_odds"]["home"], 1.95)
        self.assertEqual(athletic["asian_handicap"]["handicap"], -0.5)
        self.assertEqual(athletic["odds_api_snapshot"]["bookmaker_key"], "pinnacle")
        self.assertEqual(athletic["signal_label"], "数据不足")
        self.assertEqual(athletic["prediction"]["market"], "无推荐")

    def test_odds_api_team_fallback_tolerates_name_and_minute_differences(self):
        event = OddsApiEvent(
            event_id="event-current",
            sport_key="soccer_epl",
            commence_time="2026-08-23T11:35:00Z",
            home_team="Brighton and Hove Albion",
            away_team="Aston Villa",
            bookmaker="Pinnacle",
            bookmaker_key="pinnacle",
            updated_at="2026-08-23T10:00:00Z",
            european_odds=ThreeWayOdds(home=2.30, draw=3.40, away=3.10),
            asian_handicap=None,
        )
        matches = [{
            "competition": "英超 第 1 轮",
            "kickoff_time": "2026-08-23 19:30",
            "home_team": "Brighton & Hove Albion FC",
            "away_team": "Aston Villa FC",
            "sources": [],
        }]

        enriched = _enrich_with_odds_api(matches, [event])

        self.assertEqual(enriched[0]["european_odds"]["home"], 2.30)
        self.assertEqual(enriched[0]["odds_api_snapshot"]["event_id"], "event-current")

    def test_official_team_names_share_keys_with_curated_slate_names(self):
        pairs = (
            ("Hull City", "Hull City AFC"),
            ("Manchester United", "Manchester United FC"),
            ("Espanyol", "RCD Espanyol de Barcelona"),
            ("Inter Milan", "FC Internazionale Milano"),
            ("Como", "Como 1907"),
            ("Lens", "RC Lens"),
            ("Le Mans", "Le Mans FC"),
            ("Brest", "Stade Brestois 29"),
            ("Troyes", "ES Troyes AC"),
            ("Brighton and Hove Albion", "Brighton & Hove Albion FC"),
            ("Manchester City", "Manchester City FC"),
            ("Atletico Madrid", "Club Atl\u00e9tico de Madrid"),
            ("Lecce", "US Lecce"),
            ("Sassuolo", "US Sassuolo Calcio"),
            ("Frosinone", "Frosinone Calcio"),
            ("Barcelona", "FC Barcelona"),
            ("Levante UD", "莱万特"),
            ("Tottenham Hotspur FC", "热刺"),
            ("Newcastle United FC", "纽卡斯尔"),
            ("AC Monza", "蒙扎"),
            ("Udinese Calcio", "乌迪内斯"),
            ("ACF Fiorentina", "佛罗伦萨"),
            ("Frosinone Calcio", "弗洛西诺"),
            ("US Sassuolo Calcio", "萨索洛"),
            ("Torino FC", "都灵"),
            ("Real Sociedad de Fútbol", "皇家社会"),
            ("RCD Espanyol de Barcelona", "西班牙人"),
            ("Juventus FC", "尤文图斯"),
            ("Sevilla FC", "塞维利亚"),
            ("Club Atlético de Madrid", "马竞"),
        )

        for curated_name, official_name in pairs:
            with self.subTest(official_name=official_name):
                self.assertEqual(_normalize_team(curated_name), _normalize_team(official_name))
    def test_same_match_from_all_sources_is_merged_and_latest_odds_replace_seed(self):
        payload_path = Path(__file__).resolve().parents[1] / "dashboard" / "data" / "daily_matches.json"
        existing = json.loads(payload_path.read_text(encoding="utf-8"))
        fixture_payload = {
            "competition": {"code": "PL", "name": "Premier League"},
            "matches": [
                {
                    "id": 1001,
                    "utcDate": "2026-08-22T14:00:00Z",
                    "status": "TIMED",
                    "matchday": 1,
                    "stage": "REGULAR_SEASON",
                    "venue": "Hill Dickinson Stadium",
                    "homeTeam": {"id": 62, "name": "Everton FC"},
                    "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
                }
            ],
        }
        football_data_snapshot = FootballDataSnapshot(
            fixtures=parse_football_data_fixtures(fixture_payload, "PL"),
            standings={},
            forms={},
        )
        odds_event = OddsApiEvent(
            event_id="event-everton",
            sport_key="soccer_epl",
            commence_time="2026-08-22T14:00:00Z",
            home_team="Everton",
            away_team="Crystal Palace",
            bookmaker="Pinnacle",
            bookmaker_key="pinnacle",
            updated_at="2026-08-22T11:00:00Z",
            european_odds=ThreeWayOdds(home=1.88, draw=3.55, away=4.20),
            asian_handicap=AsianHandicapOdds(
                handicap=-0.5,
                home_odds=1.94,
                away_odds=1.96,
                provider="Pinnacle",
            ),
        )
        sporttery_match = SportteryMatch(
            match_id="sporttery-everton",
            match_no="周六010",
            business_date="2026-08-22",
            league="英超",
            home_team="埃弗顿",
            away_team="水晶宫",
            kickoff_at="2026-08-22T22:00:00",
            markets=(
                SportteryMarket(
                    code="hhad",
                    label="让球胜平负",
                    line=-1.0,
                    outcomes=(
                        SportteryOutcome("home", "主胜", 4.50, "flat"),
                        SportteryOutcome("draw", "平", 3.55, "flat"),
                        SportteryOutcome("away", "客胜", 1.60, "flat"),
                    ),
                    updated_at="2026-08-22 17:30:00",
                ),
            ),
        )

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            sporttery_matches=[sporttery_match],
            sporttery_source="Sporttery official",
            odds_api_events=[odds_event],
            odds_api_source="The Odds API",
            football_data_snapshot=football_data_snapshot,
            football_data_source="football-data.org",
        )
        matches = [
            match
            for match in batch["current_matches"]
            if match["id"] == "2026-08-22-everton-crystal-palace"
            or match["home_team"] == "Everton FC"
        ]

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["home_team"], "Everton FC")
        self.assertEqual(match["football_data_snapshot"]["match_id"], 1001)
        self.assertEqual(match["odds_api_snapshot"]["event_id"], "event-everton")
        self.assertEqual(match["sporttery_snapshot"]["match_id"], "sporttery-everton")
        self.assertEqual(match["european_odds"]["home"], 1.88)
        self.assertEqual(match["asian_handicap"]["handicap"], -0.5)
        self.assertEqual(match["chinese_lottery"]["handicap"], -1)

    def test_refresh_preserves_completed_market_snapshots_when_sources_are_unavailable(self):
        existing = {
            "slate": {"date": "2026-08-22"},
            "current_matches": [
                {
                    "id": "2026-08-22-everton-crystal-palace",
                    "kickoff_time": "2026-08-22 22:00",
                    "competition": "英超 R1",
                    "home_team": "埃弗顿",
                    "away_team": "水晶宫",
                    "european_odds": {"home": 2.12, "draw": 3.3, "away": 3.25},
                    "asian_handicap": {
                        "provider": "Pinnacle",
                        "handicap": -0.25,
                        "home_odds": 1.9,
                        "away_odds": 1.95,
                    },
                    "chinese_lottery": {
                        "handicap": -1,
                        "handicap_odds": {"home": 4.5, "draw": 3.55, "away": 1.6},
                    },
                }
            ],
        }

        batch = build_evening_slate_batch(existing, "2026-08-22")
        everton = next(
            match
            for match in batch["current_matches"]
            if match["id"] == "2026-08-22-everton-crystal-palace"
        )

        self.assertIsNotNone(everton["european_odds"])
        self.assertIsNotNone(everton["asian_handicap"])
        self.assertIsNotNone(everton["chinese_lottery"])
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
        self.assertEqual(athletic["prediction"]["market"], "无推荐")
        self.assertFalse(athletic["mismatch"]["matched"])
        self.assertNotIn(athletic["id"], {match["id"] for match in batch["checker_history"]})
        self.assertNotIn(athletic["id"], {match["id"] for match in batch["mismatch_history"]})

class FootballDataSourceTest(unittest.TestCase):
    def test_dynamic_next_matchday_uses_earliest_actual_round_and_excludes_qualifiers(self):
        def fixture(match_id, code, utc_date, home, away, matchday, stage="REGULAR_SEASON"):
            return FootballDataFixture(
                match_id=match_id,
                competition_code=code,
                competition_name=code,
                utc_date=utc_date,
                kickoff_time=utc_date,
                home_team_id=None,
                home_team=home,
                away_team_id=None,
                away_team=away,
                matchday=matchday,
                stage=stage,
                status="TIMED",
            )

        upcoming = (
            fixture(1, "PD", "2026-08-29T14:00:00Z", "Round Two Home", "Round Two Away", 2),
            fixture(2, "PD", "2026-09-01T14:00:00Z", "Late Round One", "Visitor", 1),
            fixture(3, "SA", "2026-08-30T18:00:00Z", "Serie A Home", "Serie A Away", 2),
            fixture(4, "CL", "2026-08-28T19:00:00Z", "Qualifier", "Opponent", 0, "QUALIFICATION"),
            fixture(5, "CL", "2026-09-02T19:00:00Z", "League Stage", "Opponent", 1, "LEAGUE_STAGE"),
        )
        result = _build_next_matchday(
            upcoming,
            current_matches=[],
            query_time=datetime(2026, 8, 26, 18, tzinfo=fixed_timezone(timedelta(hours=8))),
            fallback={},
        )
        by_name = {item["name"]: item for item in result["competitions"]}

        self.assertEqual(set(by_name), {"英超", "西甲", "意甲", "德甲", "法甲", "欧冠"})
        self.assertEqual(by_name["西甲"]["matchday"], "2026/27 第 2 轮")
        self.assertEqual(by_name["西甲"]["fixtures"][0]["home_team"], "Round Two Home")
        self.assertEqual(by_name["欧冠"]["fixtures"][0]["home_team"], "League Stage")
        self.assertEqual(by_name["英超"]["fixtures"], [])

    def test_parse_football_data_fixtures_standings_and_forms(self):
        fixture_payload = {
            "competition": {"code": "PL", "name": "Premier League"},
            "matches": [
                {
                    "id": 1001,
                    "utcDate": "2026-08-22T14:00:00Z",
                    "status": "TIMED",
                    "matchday": 1,
                    "stage": "REGULAR_SEASON",
                    "venue": "Goodison Park",
                    "homeTeam": {"id": 62, "name": "Everton FC"},
                    "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
                }
            ],
        }
        standing_payload = {
            "standings": [
                {
                    "type": "TOTAL",
                    "table": [
                        {
                            "position": 8,
                            "team": {"id": 62, "name": "Everton FC"},
                            "playedGames": 10,
                            "won": 4,
                            "draw": 3,
                            "lost": 3,
                            "goalsFor": 14,
                            "goalsAgainst": 12,
                            "goalDifference": 2,
                            "points": 15,
                        }
                    ],
                }
            ]
        }
        finished_matches = [
            {
                "utcDate": "2026-08-15T14:00:00Z",
                "status": "FINISHED",
                "homeTeam": {"id": 62},
                "awayTeam": {"id": 354},
                "score": {"fullTime": {"home": 2, "away": 1}},
            },
            {
                "utcDate": "2026-08-10T14:00:00Z",
                "status": "FINISHED",
                "homeTeam": {"id": 99},
                "awayTeam": {"id": 62},
                "score": {"fullTime": {"home": 0, "away": 0}},
            },
        ]

        fixtures = parse_football_data_fixtures(fixture_payload, "PL")
        standings = parse_football_data_standings(standing_payload)
        forms = parse_football_data_forms(finished_matches)

        self.assertEqual(fixtures[0].kickoff_time, "2026-08-22 22:00")
        self.assertEqual(fixtures[0].venue, "Goodison Park")
        self.assertEqual(standings[62].position, 8)
        self.assertEqual(forms[62].results, ("W", "D"))

    def test_result_fixture_fetch_uses_one_request_and_parses_final_score(self):
        payload = {
            "matches": [
                {
                    "id": 1001,
                    "competition": {"code": "PL", "name": "Premier League"},
                    "utcDate": "2026-08-22T14:00:00Z",
                    "status": "FINISHED",
                    "homeTeam": {"id": 62, "name": "Everton FC"},
                    "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
                    "score": {"fullTime": {"home": 2, "away": 1}},
                }
            ]
        }

        with patch(
            "odds_analyzer.sources.football_data._get_json",
            return_value=payload,
        ) as get_json:
            fixtures = fetch_evening_fixtures("test-key", "2026-08-22")

        self.assertEqual(get_json.call_count, 1)
        self.assertEqual(fixtures[0].home_score, 2)
        self.assertEqual(fixtures[0].away_score, 1)
        self.assertEqual(fixtures[0].status, "FINISHED")
    def test_fetch_uses_one_fixture_request_and_only_active_standings(self):
        fixture_payload = {
            "matches": [
                {
                    "id": 1001,
                    "competition": {"code": "PL", "name": "Premier League"},
                    "utcDate": "2026-08-22T14:00:00Z",
                    "status": "TIMED",
                    "matchday": 1,
                    "stage": "REGULAR_SEASON",
                    "homeTeam": {"id": 62, "name": "Everton FC"},
                    "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
                }
            ]
        }
        standing_payload = {
            "standings": [
                {
                    "type": "TOTAL",
                    "table": [
                        {
                            "position": 8,
                            "team": {"id": 62, "name": "Everton FC"},
                            "playedGames": 10,
                            "won": 4,
                            "draw": 3,
                            "lost": 3,
                            "goalsFor": 14,
                            "goalsAgainst": 12,
                            "goalDifference": 2,
                            "points": 15,
                            "form": "W,D,L,W,W",
                        }
                    ],
                }
            ]
        }

        def fake_get_json(path, api_key, query, timeout):
            self.assertEqual(api_key, "test-key")
            if path == "/matches":
                self.assertEqual(
                    query,
                    {
                        "dateFrom": "2026-08-22",
                        "dateTo": "2026-08-23",
                        "competitions": "PL,PD,SA,BL1,FL1,CL",
                    },
                )
                return fixture_payload
            if path == "/competitions/PL/standings":
                return standing_payload
            self.fail(f"Unexpected football-data request: {path}")

        with patch(
            "odds_analyzer.sources.football_data._get_json",
            side_effect=fake_get_json,
        ) as get_json:
            snapshot = fetch_evening_football_data(
                "test-key",
                "2026-08-22",
                competition_codes=("PL", "PD", "SA", "BL1", "FL1", "CL"),
            )

        self.assertEqual(get_json.call_count, 2)
        self.assertEqual(len(snapshot.fixtures), 1)
        self.assertEqual(snapshot.standings[62].position, 8)
        self.assertEqual(snapshot.forms[62].results, ("W", "D", "L", "W", "W"))
        self.assertEqual(snapshot.errors, ())

    def test_football_data_snapshot_enriches_evening_batch_without_prediction(self):
        existing = {"current_matches": [], "next_matchday": {"competitions": []}}
        fixture_payload = {
            "competition": {"code": "PL", "name": "Premier League"},
            "matches": [
                {
                    "id": 1001,
                    "utcDate": "2026-08-22T14:00:00Z",
                    "status": "TIMED",
                    "matchday": 1,
                    "stage": "REGULAR_SEASON",
                    "venue": "Goodison Park",
                    "homeTeam": {"id": 62, "name": "Everton FC"},
                    "awayTeam": {"id": 354, "name": "Crystal Palace FC"},
                }
            ],
        }
        standing_payload = {
            "standings": [
                {
                    "type": "TOTAL",
                    "table": [
                        {
                            "position": 8,
                            "team": {"id": 62, "name": "Everton FC"},
                            "playedGames": 10,
                            "won": 4,
                            "draw": 3,
                            "lost": 3,
                            "goalsFor": 14,
                            "goalsAgainst": 12,
                            "goalDifference": 2,
                            "points": 15,
                        },
                        {
                            "position": 11,
                            "team": {"id": 354, "name": "Crystal Palace FC"},
                            "playedGames": 10,
                            "won": 3,
                            "draw": 4,
                            "lost": 3,
                            "goalsFor": 11,
                            "goalsAgainst": 11,
                            "goalDifference": 0,
                            "points": 13,
                        },
                    ],
                }
            ]
        }
        snapshot = FootballDataSnapshot(
            fixtures=parse_football_data_fixtures(fixture_payload, "PL"),
            standings=parse_football_data_standings(standing_payload),
            forms=parse_football_data_forms([]),
        )

        batch = build_evening_slate_batch(
            existing,
            "2026-08-22",
            football_data_snapshot=snapshot,
            football_data_source="football-data.org",
        )
        match = next(item for item in batch["current_matches"] if item["home_team"] == "Everton FC")

        self.assertEqual(batch["slate"]["football_data_source"], "football-data.org")
        self.assertEqual(match["venue"], "Goodison Park")
        self.assertIn("排名第 8", match["fundamentals"][0]["home"])
        self.assertEqual(match["prediction"]["market"], "无推荐")

class OddsApiSourceTest(unittest.TestCase):
    def test_parse_odds_api_events_extracts_h2h_and_spread(self):
        payload = [
            {
                "id": "event-1",
                "sport_key": "soccer_spain_la_liga",
                "commence_time": "2026-08-22T15:00:00Z",
                "home_team": "Athletic Club",
                "away_team": "Sevilla FC",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "last_update": "2026-08-22T10:00:00Z",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Athletic Club", "price": 1.95},
                                    {"name": "Draw", "price": 3.40},
                                    {"name": "Sevilla FC", "price": 3.80},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Athletic Club", "price": 1.91, "point": -0.5},
                                    {"name": "Sevilla FC", "price": 1.99, "point": 0.5},
                                ],
                            },
                        ],
                    }
                ],
            }
        ]

        events = parse_odds_api_events(payload, "soccer_spain_la_liga")
        event = events[0]

        self.assertEqual(event.home_team, "Athletic Club")
        self.assertEqual(event.european_odds.home, 1.95)
        self.assertEqual(event.european_odds.draw, 3.40)
        self.assertEqual(event.european_odds.away, 3.80)
        self.assertEqual(event.asian_handicap.handicap, -0.5)
        self.assertEqual(event.asian_handicap.home_odds, 1.91)
        self.assertEqual(event.asian_handicap.away_odds, 1.99)
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

def dynamic_analysis_match(include_lottery):
    lottery = None
    if include_lottery:
        lottery = {
            "standard": {"home": 2.10, "draw": 3.30, "away": 3.50},
            "handicap": -1,
            "handicap_odds": {"home": 4.50, "draw": 3.55, "away": 1.60},
            "source": "Sporttery official",
        }
    return {
        "id": "dynamic-home-away",
        "kickoff_time": "2026-08-22 22:00",
        "competition": "英超 第 1 轮",
        "home_team": "主队",
        "away_team": "客队",
        "football_data_snapshot": {"match_id": 1, "source": "football-data.org"},
        "fundamental_context": {
            "home": {
                "played_games": 10,
                "points": 13,
                "goal_difference": -2,
                "form": ["L", "D", "L"],
            },
            "away": {
                "played_games": 10,
                "points": 20,
                "goal_difference": 6,
                "form": ["W", "D", "W"],
            },
        },
        "european_odds": {"home": 2.10, "draw": 3.30, "away": 3.50},
        "asian_handicap": {
            "provider": "Pinnacle",
            "handicap": -0.25,
            "home_odds": 1.90,
            "away_odds": 2.00,
        },
        "chinese_lottery": lottery,
        "sources": ["football-data.org", "The Odds API"],
    }

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
